/**
 * R4-3 · toTimeline + parseApprovalReply 从 ChatArea.tsx 抽到 lib/chat/timeline.ts。
 * 这是前端第一个单测（vitest）。锁纯逻辑：消息序列 → timeline 项重建。
 */
import { describe, it, expect } from 'vitest';
import { toTimeline, parseApprovalReply } from './timeline';
import type { MessageLike, TimelineItem } from './timeline';

type ItemOf<K extends TimelineItem['kind']> = Extract<TimelineItem, { kind: K }>;

function msg(partial: Partial<MessageLike>): MessageLike {
  return {
    id: 'm' + Math.random().toString(36).slice(2, 7),
    role: 'user',
    content: '',
    created_at: '2026-05-29T10:00:00Z',
    meta: {},
    ...partial,
  };
}

describe('parseApprovalReply', () => {
  it('returns null for plain text', () => {
    expect(parseApprovalReply('你好')).toBeNull();
  });

  it('parses approval_response payload', () => {
    const raw = '[approval_response request_id=abc123]\n审批标题：发布确认\n用户选择：通过';
    const out = parseApprovalReply(raw);
    expect(out).not.toBeNull();
    expect(out!.meta.requestId).toBe('abc123');
    expect(out!.meta.title).toBe('发布确认');
    expect(out!.meta.option).toBe('通过');
    expect(out!.displayContent).toBe('通过');
  });

  it('returns null when missing title/option', () => {
    expect(parseApprovalReply('[approval_response request_id=x]\n仅头部')).toBeNull();
  });
});

describe('toTimeline', () => {
  it('renders user + assistant in created_at order', () => {
    const items = toTimeline([
      msg({ role: 'assistant', content: '回复', created_at: '2026-05-29T10:00:02Z' }),
      msg({ role: 'user', content: '问题', created_at: '2026-05-29T10:00:01Z' }),
    ]);
    expect(items.map((i) => i.kind)).toEqual(['user', 'assistant']);
    expect((items[0] as ItemOf<'user'>).content).toBe('问题');
  });

  it('uses meta.sequence as tiebreaker for same timestamp', () => {
    const t = '2026-05-29T10:00:00Z';
    const items = toTimeline([
      msg({ role: 'user', content: 'B', created_at: t, meta: { sequence: 2 } }),
      msg({ role: 'user', content: 'A', created_at: t, meta: { sequence: 1 } }),
    ]);
    expect((items[0] as ItemOf<'user'>).content).toBe('A');
    expect((items[1] as ItemOf<'user'>).content).toBe('B');
  });

  it('turns assistant meta.type=error into an error card', () => {
    const items = toTimeline([
      msg({ role: 'assistant', content: '炸了', meta: { type: 'error', error_code: 'BAD_GATEWAY', user_message: '上游 502' } }),
    ]);
    expect(items[0].kind).toBe('error');
    expect((items[0] as ItemOf<'error'>).errorCode).toBe('BAD_GATEWAY');
    expect((items[0] as ItemOf<'error'>).userMessage).toBe('上游 502');
  });

  it('rebuilds approval card from agent_log meta.type=approval_request', () => {
    const items = toTimeline([
      msg({
        role: 'agent_log',
        content: '已发卡',
        meta: { type: 'approval_request', request_id: 'r1', title: '发布', message: '确认发布?', options: ['通过', '驳回'] },
      }),
    ]);
    expect(items[0].kind).toBe('approval');
    expect((items[0] as ItemOf<'approval'>).options).toEqual(['通过', '驳回']);
  });

  it('rebuilds tool card from input + output events (merged by toolCallId)', () => {
    const items = toTimeline([
      msg({ role: 'agent_log', content: '', meta: { raw: { type: 'tool-input-available', toolCallId: 'tc1', toolName: 'search', input: { q: 'x' } } } }),
      msg({ role: 'agent_log', content: '', created_at: '2026-05-29T10:00:01Z', meta: { raw: { type: 'tool-output-available', toolCallId: 'tc1', output: 'found' } } }),
    ]);
    expect(items).toHaveLength(1);
    expect(items[0].kind).toBe('tool');
    expect((items[0] as ItemOf<'tool'>).state).toBe('done');
    expect((items[0] as ItemOf<'tool'>).output).toBe('found');
  });
});
