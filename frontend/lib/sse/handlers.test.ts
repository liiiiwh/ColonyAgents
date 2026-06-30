import type { Dispatch, SetStateAction } from 'react';
import { describe, it, expect } from 'vitest';
import { dispatchSSEEvent, type SSEStateHooks } from './handlers';
import type { ApprovalCardData } from '@/components/chat/ApprovalCard';

/** 收集 setApprovals 结果的假 state（其余 hook no-op）。 */
function makeState() {
  let approvals: ApprovalCardData[] = [];
  const setApprovals: Dispatch<SetStateAction<ApprovalCardData[]>> = (fn) => {
    approvals = typeof fn === 'function' ? fn(approvals) : fn;
  };
  const s: SSEStateHooks = {
    setStreamState: () => {},
    setApprovals,
    setMessages: () => {},
    setRedirects: () => {},
    setLiveCalls: () => {},
    handleActivityEvent: () => {},
  };
  return { s, get approvals() { return approvals; } };
}

describe('SSE init · 审批卡读时合并', () => {
  it('已决审批刷新后保留 resolution/status/thread_key（不再幽灵复活成可点）', () => {
    const h = makeState();
    dispatchSSEEvent({
      type: 'init',
      pending_approvals: [{
        request_id: 'r1', title: 't', message: 'm', options: ['同意', '拒绝'],
        created_at: '2026-01-01T00:00:00Z', thread_key: 'main', status: 'decided',
        resolution: { option: '同意', decided_by: 'admin', via: 'inline' },
      }],
    }, h.s);
    expect(h.approvals).toHaveLength(1);
    const card = h.approvals[0];
    expect(card.status).toBe('decided');
    expect(card.resolution?.option).toBe('同意');
    expect(card.thread_key).toBe('main');
  });

  it('pending 审批正常透传（无 resolution）', () => {
    const h = makeState();
    dispatchSSEEvent({
      type: 'init',
      pending_approvals: [{
        request_id: 'r2', title: 't2', message: 'm2', options: ['A', 'B'],
        created_at: '2026-01-01T00:00:00Z', thread_key: 'worker:abc:def', status: 'pending',
      }],
    }, h.s);
    expect(h.approvals[0].status).toBe('pending');
    expect(h.approvals[0].resolution).toBeUndefined();
    expect(h.approvals[0].thread_key).toBe('worker:abc:def');
  });
});
