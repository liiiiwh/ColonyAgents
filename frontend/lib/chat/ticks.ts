/**
 * ADR-008 P1 · 消息折叠成 tick（纯逻辑，vitest 覆盖）。
 *
 * V7.4 退役 ActivityTree 后，daemon 流式产出的 agent_log 追踪消息在 mission 页平铺刷屏。
 * 这里把同 `meta.turn_id` 的 daemon tick 消息（agent_log 追踪 + assistant 回复）折叠成一张
 * 可展开的 tick 卡：默认只看回复 + 「N 步」摘要，展开看每步（复用 toTimeline 重建 tool/thinking 卡）。
 *
 * 规则：
 *   role==='user'               → loose（永远独立一行）
 *   meta.turn_id 存在            → 归入该 turn 的 tick 桶（agent_log 追踪 + assistant 回复）
 *   其它（无 turn_id 的 assistant / system 等）→ loose（交互路径，非 daemon tick）
 */
import { toTimeline } from './timeline';
import type { MessageLike, TimelineItem } from './timeline';

export interface TickRow {
  kind: 'tick';
  turnId: string;
  steps: TimelineItem[]; // tool/thinking/subtask/batch —— 折叠的明细
  reply: TimelineItem | null; // assistant 回复 —— 折叠态也可见的标题
  stepCount: number;
  startedAt: string;
}

export interface LooseRow {
  kind: 'loose';
  item: TimelineItem;
}

export type ChatRow = TickRow | LooseRow;

function tickBelongs(m: MessageLike): boolean {
  if (m.role === 'user') return false;
  const meta = (m.meta || {}) as { turn_id?: unknown };
  return typeof meta.turn_id === 'string' && meta.turn_id.length > 0;
}

export function foldTicks(msgs: MessageLike[]): ChatRow[] {
  // 按 created_at + sequence 升序（与 toTimeline 同序），保证 tick 出现位置稳定。
  const sorted = [...msgs].sort((a, b) => {
    const ta = new Date(a.created_at).getTime();
    const tb = new Date(b.created_at).getTime();
    if (ta !== tb) return ta - tb;
    const sa = ((a.meta as { sequence?: number } | undefined)?.sequence ?? 0) || 0;
    const sb = ((b.meta as { sequence?: number } | undefined)?.sequence ?? 0) || 0;
    return sa - sb;
  });

  const rows: ChatRow[] = [];
  const tickRowIndex: Record<string, number> = {};
  const tickMsgs: Record<string, MessageLike[]> = {};

  for (const m of sorted) {
    if (!tickBelongs(m)) {
      // loose：单条消息走 toTimeline 取其 timeline 项（可能为空，如纯 trace 的 system）
      const items = toTimeline([m]);
      for (const item of items) rows.push({ kind: 'loose', item });
      continue;
    }
    const turnId = String((m.meta as { turn_id?: unknown }).turn_id);
    if (tickRowIndex[turnId] === undefined) {
      tickRowIndex[turnId] = rows.length;
      tickMsgs[turnId] = [];
      rows.push({ kind: 'tick', turnId, steps: [], reply: null, stepCount: 0, startedAt: m.created_at });
    }
    tickMsgs[turnId].push(m);
  }

  // 二次填充每个 tick 桶：steps（agent_log 追踪）+ reply（assistant 回复）。
  for (const turnId of Object.keys(tickMsgs)) {
    const bucket = tickMsgs[turnId];
    const traceMsgs = bucket.filter((m) => m.role === 'agent_log');
    const replyMsg = bucket.filter((m) => m.role === 'assistant').slice(-1)[0] || null;
    const steps = toTimeline(traceMsgs);
    const reply = replyMsg ? toTimeline([replyMsg])[0] || null : null;
    const idx = tickRowIndex[turnId];
    rows[idx] = {
      kind: 'tick',
      turnId,
      steps,
      reply,
      stepCount: steps.length,
      startedAt: (rows[idx] as TickRow).startedAt,
    };
  }

  return rows;
}
