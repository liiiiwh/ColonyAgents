/**
 * ADR-008 P1 · foldTicks 纯逻辑单测（vitest）。
 * 修 V7.4 刷屏 regression：daemon 流式 agent_log 不再平铺，而是同 turn_id 折叠成一张 tick 卡。
 */
import { describe, it, expect } from 'vitest';
import { foldTicks, type LooseRow, type TickRow } from './ticks';
import type { MessageLike, TimelineItem } from './timeline';

function msg(partial: Partial<MessageLike>): MessageLike {
  return {
    id: 'm' + Math.random().toString(36).slice(2, 7),
    role: 'user',
    content: '',
    created_at: '2026-06-03T10:00:00Z',
    meta: {},
    ...partial,
  };
}

describe('foldTicks', () => {
  it('keeps a plain user message as a loose row', () => {
    const rows = foldTicks([msg({ role: 'user', content: '现在几点' })]);
    expect(rows).toHaveLength(1);
    expect(rows[0].kind).toBe('loose');
    expect((rows[0] as LooseRow).item.kind).toBe('user');
  });

  it('keeps an interactive assistant (no turn_id) loose', () => {
    const rows = foldTicks([
      msg({ role: 'assistant', content: '你好', created_at: '2026-06-03T10:00:01Z' }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].kind).toBe('loose');
    expect((rows[0] as LooseRow).item.kind).toBe('assistant');
  });

  it('folds same turn_id agent_log traces + reply into one tick row', () => {
    const turn = 'turn-1';
    const rows = foldTicks([
      msg({ role: 'user', content: '现在几点', created_at: '2026-06-03T10:00:00Z' }),
      msg({
        role: 'agent_log',
        content: '',
        created_at: '2026-06-03T10:00:01Z',
        meta: { turn_id: turn, source: 'daemon_tick', sequence: 0, raw: { type: 'tool-input-available', toolCallId: 'tc1', toolName: 'clock', input: {} } },
      }),
      msg({
        role: 'agent_log',
        content: '',
        created_at: '2026-06-03T10:00:02Z',
        meta: { turn_id: turn, source: 'daemon_tick', sequence: 1, raw: { type: 'tool-output-available', toolCallId: 'tc1', output: '10:00' } },
      }),
      msg({
        role: 'assistant',
        content: '现在是 10:00',
        created_at: '2026-06-03T10:00:03Z',
        meta: { turn_id: turn, source: 'daemon_tick_reply' },
      }),
    ]);
    // user(loose) + 1 tick
    expect(rows.map((r) => r.kind)).toEqual(['loose', 'tick']);
    const tick = rows[1] as TickRow;
    expect(tick.turnId).toBe(turn);
    expect(tick.stepCount).toBe(1); // 1 merged tool card
    expect(tick.steps[0].kind).toBe('tool');
    const reply = tick.reply as Extract<TimelineItem, { kind: 'assistant' }>;
    expect(reply.kind).toBe('assistant');
    expect(reply.content).toBe('现在是 10:00');
  });

  it('orders ticks by their first message and keeps loose rows interleaved', () => {
    const rows = foldTicks([
      msg({ role: 'user', content: 'A', created_at: '2026-06-03T10:00:00Z' }),
      msg({ role: 'agent_log', content: '', created_at: '2026-06-03T10:00:01Z', meta: { turn_id: 't1', raw: { type: 'thinking-segment' } } }),
      msg({ role: 'assistant', content: 'r1', created_at: '2026-06-03T10:00:02Z', meta: { turn_id: 't1', source: 'daemon_tick_reply' } }),
      msg({ role: 'user', content: 'B', created_at: '2026-06-03T10:00:03Z' }),
      msg({ role: 'assistant', content: 'r2', created_at: '2026-06-03T10:00:04Z', meta: { turn_id: 't2', source: 'daemon_tick_reply' } }),
    ]);
    expect(rows.map((r) => r.kind)).toEqual(['loose', 'tick', 'loose', 'tick']);
    expect((rows[1] as TickRow).turnId).toBe('t1');
    expect((rows[3] as TickRow).turnId).toBe('t2');
  });

  it('a tick with no reply yet (running) still groups its steps', () => {
    const rows = foldTicks([
      msg({ role: 'agent_log', content: '', created_at: '2026-06-03T10:00:01Z', meta: { turn_id: 't9', raw: { type: 'tool-input-available', toolCallId: 'x', toolName: 'web', input: {} } } }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].kind).toBe('tick');
    expect((rows[0] as TickRow).reply).toBeNull();
    expect((rows[0] as TickRow).stepCount).toBe(1);
  });
});
