import { describe, it, expect } from 'vitest';
import { assembleMissionTimeline, type TimelineItem, type TimelineMessage } from './missionTimeline';

type ApprovalItem = Extract<TimelineItem, { kind: 'approval' }>;

const msg = (over: Partial<TimelineMessage>): TimelineMessage => ({
  id: 'x',
  role: 'assistant',
  content: '',
  created_at: '2026-01-01T00:00:00',
  ...over,
});

describe('assembleMissionTimeline', () => {
  it('folds non-user messages sharing a turn_id into one tick', () => {
    const items = assembleMissionTimeline(
      [
        msg({ id: 'a', meta: { turn_id: 't1' }, created_at: '2026-01-01T00:00:01' }),
        msg({ id: 'b', meta: { turn_id: 't1' }, created_at: '2026-01-01T00:00:02' }),
      ],
      [],
    );
    expect(items).toHaveLength(1);
    expect(items[0].kind).toBe('tick');
    if (items[0].kind === 'tick') expect(items[0].data).toHaveLength(2);
  });

  it('extracts form_request messages as form items (not folded)', () => {
    const items = assembleMissionTimeline(
      [msg({ id: 'f', meta: { type: 'form_request', request_id: 'r1', turn_id: 't1' } })],
      [],
    );
    expect(items).toHaveLength(1);
    expect(items[0].kind).toBe('form');
  });

  it('extracts super_activated as a cta item', () => {
    const items = assembleMissionTimeline(
      [msg({ id: 'c', meta: { type: 'super_activated', project_slug: 'x' } })],
      [],
    );
    expect(items[0].kind).toBe('cta');
  });

  it('keeps user messages and turn-less messages as loose msg items', () => {
    const items = assembleMissionTimeline(
      [
        msg({ id: 'u', role: 'user' }),
        msg({ id: 'n', meta: {} }),
      ],
      [],
    );
    expect(items.every((i) => i.kind === 'msg')).toBe(true);
    expect(items).toHaveLength(2);
  });

  it('rebuilds an approval card from a turn-bucketed agent_log meta.type=approval_request', () => {
    // The super logs [审批请求] as an agent_log with a turn_id; it must surface as an approval
    // CARD, not get folded (hidden) inside the collapsed tick. Regression: 审批卡不显示.
    const items = assembleMissionTimeline(
      [msg({ id: 'ar', role: 'agent_log', meta: { type: 'approval_request', request_id: 'r9', turn_id: 't1', title: '发布?', message: '确认发布', options: ['通过', '驳回'] } })],
      [],
    );
    const appr = items.find((i) => i.kind === 'approval') as ApprovalItem | undefined;
    expect(appr).toBeTruthy();
    expect(appr!.data.request_id).toBe('r9');
    expect(appr!.data.options).toEqual(['通过', '驳回']);
    expect(items.some((i) => i.kind === 'tick')).toBe(false);  // not folded into a tick
  });

  it('does not double-render an approval present in both messages and approvals state', () => {
    const items = assembleMissionTimeline(
      [msg({ id: 'ar', role: 'agent_log', meta: { type: 'approval_request', request_id: 'dup', title: 't', message: 'm', options: ['a'] } })],
      [{ request_id: 'dup', created_at: '2026-01-01T00:00:00', resolution: 'a' }],
    );
    expect(items.filter((i) => i.kind === 'approval')).toHaveLength(1);
  });

  it('includes approvals and sorts everything by timestamp', () => {
    const items = assembleMissionTimeline(
      [msg({ id: 'late', role: 'user', created_at: '2026-01-01T00:00:09' })],
      [{ request_id: 'ap', created_at: '2026-01-01T00:00:01' }],
    );
    expect(items[0].kind).toBe('approval');
    expect(items[1].kind).toBe('msg');
  });

  it('从持久化 approval_response 标记重建审批卡为已决（刷新后不再可点）', () => {
    const items = assembleMissionTimeline(
      [
        msg({ id: 'ar', role: 'agent_log', created_at: '2026-01-01T00:00:01',
              meta: { type: 'approval_request', request_id: 'r9', title: '确认方案？', options: ['确认', '取消'] } }),
        msg({ id: 'resp', role: 'user', created_at: '2026-01-01T00:00:02',
              content: '[approval_response request_id=r9] 用户选择：确认',
              meta: { approval_response: { request_id: 'r9', option: '确认', decided_by: 'admin' } } }),
      ],
      [],  // live approvals 为空 → 走 messages 重建路径
    );
    const ap = items.find((it) => it.kind === 'approval');
    expect(ap).toBeTruthy();
    if (ap && ap.kind === 'approval') {
      expect(ap.data.status).toBe('decided');
      expect((ap.data.resolution as { option?: string })?.option).toBe('确认');
    }
  });

  it('重建审批卡：无 approval_response 且不在 live → 标 closed（不可点，修孤儿可点）', () => {
    const items = assembleMissionTimeline(
      [
        msg({ id: 'ar', role: 'agent_log', created_at: '2026-01-01T00:00:01',
              meta: { type: 'approval_request', request_id: 'orphan', title: '确认构建？', options: ['确认', '取消'] } }),
      ],
      [],  // live approvals 为空（SSE 真相：它不 pending）
    );
    const ap = items.find((it) => it.kind === 'approval');
    expect(ap).toBeTruthy();
    if (ap && ap.kind === 'approval') {
      expect(ap.data.status).toBe('closed');  // 不再渲染成可点
    }
  });

  it('多张未决审批卡：只有最新一张可点，老的标 superseded（禁用）', () => {
    const items = assembleMissionTimeline(
      [],
      [
        { request_id: 'old', created_at: '2026-01-01T00:00:01' },   // 老提案
        { request_id: 'new', created_at: '2026-01-01T00:00:05' },   // 新提案
      ],
    );
    const cards = items.filter((it) => it.kind === 'approval');
    const byId = Object.fromEntries(cards.map((c) => {
      const d = (c as ApprovalItem).data;
      return [d.request_id, d];
    }));
    expect(byId['old'].status).toBe('superseded');  // 老的被取代 → 禁用
    expect(byId['new'].status).toBeUndefined();      // 最新的仍可点
  });

  it('已决审批卡不受 superseded 影响（只取代未决的）', () => {
    const items = assembleMissionTimeline(
      [],
      [
        { request_id: 'done', created_at: '2026-01-01T00:00:01', status: 'decided', resolution: { option: 'a' } },
        { request_id: 'pend', created_at: '2026-01-01T00:00:05' },
      ],
    );
    const byId = Object.fromEntries(items.filter((i) => i.kind === 'approval').map((c) => {
      const d = (c as ApprovalItem).data;
      return [d.request_id, d];
    }));
    expect(byId['done'].status).toBe('decided');     // 已决不动
    expect(byId['pend'].status).toBeUndefined();      // 唯一未决 → 可点
  });
});
