// Mission 工作台时间线装配（纯函数，从 page.tsx 内联 IIFE 抽出，可测）。
// 把 messages + approvals 归类成有序 Item：tick 折叠 / form 卡 / cta 卡 / 审批卡 / 散消息。
import type { MessageMeta } from '@/types/sse';

export type TimelineMessage = {
  id: string;
  role: string;
  content: string;
  meta?: MessageMeta | null;
  created_at: string | null;
};
export type TimelineApproval = { request_id: string; created_at?: string | null; [k: string]: unknown };

export type TimelineItem =
  | { kind: 'msg'; ts: string; data: TimelineMessage }
  | { kind: 'tick'; ts: string; turnId: string; data: TimelineMessage[] }
  | { kind: 'approval'; ts: string; data: TimelineApproval }
  | { kind: 'form'; ts: string; data: TimelineMessage }
  | { kind: 'cta'; ts: string; data: TimelineMessage };

export function assembleMissionTimeline(
  messages: TimelineMessage[],
  approvals: TimelineApproval[],
): TimelineItem[] {
  const tickBuckets: Record<string, TimelineMessage[]> = {};
  const tickFirstTs: Record<string, string> = {};
  const loose: TimelineMessage[] = [];
  const forms: TimelineMessage[] = [];
  const ctas: TimelineMessage[] = [];
  // Approval cards rebuilt from the persisted [审批请求] agent_log (meta.type=approval_request).
  // Without this they'd fold into the collapsed tick (role!=user + turn_id) and never surface —
  // the card would only ever come from live bus / init-frame state, so it vanished in poll mode,
  // on a missed event, or before reload. Reconstructing from the log makes the card robust.
  const rebuiltApprovals: TimelineApproval[] = [];
  // 持久化的 approval_response（meta.approval_response）→ request_id 的决议。
  // 重建审批卡时据此标记已决，刷新后不再幽灵复活成可点（即便不在 live approvals 集合里）。
  const responseByReq: Record<string, { option: string; decided_by?: string }> = {};
  for (const m of messages) {
    const resp = m.meta?.approval_response;
    if (resp?.request_id) {
      responseByReq[resp.request_id] = { option: resp.option, decided_by: resp.decided_by };
    }
  }

  for (const m of messages) {
    if (m.meta?.type === 'form_request' && m.meta?.request_id) {
      forms.push(m);
      continue;
    }
    if (m.meta?.type === 'approval_request' && m.meta?.request_id) {
      const resp = responseByReq[m.meta.request_id];
      rebuiltApprovals.push({
        request_id: m.meta.request_id,
        title: m.meta.title,
        message: m.meta.message,
        options: m.meta.options,
        created_at: m.created_at,
        // 有 response → 已决；无 response 又不在 live pending（重建卡都满足）→ closed（已撤/已处理）：
        // SSE init 总带全量 pending，重建卡不在 live 即非 pending，渲染为不可点，修孤儿可点。
        ...(resp
          ? { status: 'decided', resolution: { option: resp.option, decided_by: resp.decided_by, via: 'inline' } }
          : { status: 'closed' }),
      });
      continue;
    }
    if (m.meta?.type === 'super_activated' && m.meta?.project_slug) {
      ctas.push(m);
      continue;
    }
    const tid = m.role !== 'user' ? (m.meta?.turn_id as string | undefined) : undefined;
    if (tid) {
      if (!tickBuckets[tid]) {
        tickBuckets[tid] = [];
        tickFirstTs[tid] = m.created_at || '';
      }
      tickBuckets[tid].push(m);
    } else {
      loose.push(m);
    }
  }

  // Merge live/init-frame approvals (which track resolution status) with ones rebuilt from the
  // log; the state entry wins on conflict so a resolved card doesn't revert to pending.
  const seenApproval = new Set(approvals.map((a) => a.request_id));
  const mergedApprovals0 = [
    ...approvals,
    ...rebuiltApprovals.filter((a) => !seenApproval.has(a.request_id)),
  ];
  // 同一会话/线程内只允许「最新」的未决审批卡可点；老的未决卡被新卡取代 → 标 superseded（禁用）。
  // 防 builder 提案阶段重发多张审批卡时，用户误点已被取代的老卡。不 mutate 原对象（React state）。
  const _pending = mergedApprovals0
    .filter((a) => !a.resolution && a.status !== 'decided' && a.status !== 'closed')
    .sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
  const _supersededIds = new Set(_pending.slice(0, -1).map((a) => a.request_id));
  const mergedApprovals = mergedApprovals0.map((a) =>
    _supersededIds.has(a.request_id) ? { ...a, status: 'superseded' } : a,
  );

  const items: TimelineItem[] = [
    ...loose.map<TimelineItem>((m) => ({ kind: 'msg', ts: m.created_at || '', data: m })),
    ...forms.map<TimelineItem>((m) => ({ kind: 'form', ts: m.created_at || '', data: m })),
    ...ctas.map<TimelineItem>((m) => ({ kind: 'cta', ts: m.created_at || '', data: m })),
    ...Object.keys(tickBuckets).map<TimelineItem>((tid) => ({
      kind: 'tick',
      ts: tickFirstTs[tid],
      turnId: tid,
      data: tickBuckets[tid],
    })),
    ...mergedApprovals.map<TimelineItem>((a) => ({ kind: 'approval', ts: a.created_at || '', data: a })),
  ];
  items.sort((x, y) => x.ts.localeCompare(y.ts));
  return items;
}
