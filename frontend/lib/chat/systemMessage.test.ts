import { describe, it, expect } from 'vitest';
import { systemUserKind } from './systemMessage';

describe('systemUserKind', () => {
  it('真人消息(meta.source=user_chat) → null', () => {
    expect(systemUserKind('user', { source: 'user_chat' })).toBeNull();
  });
  it('非 user 角色 → null', () => {
    expect(systemUserKind('assistant', { type: 'super_dispatch' })).toBeNull();
    expect(systemUserKind('agent_log', {})).toBeNull();
  });
  it('super 派单 → dispatch', () => {
    expect(systemUserKind('user', { type: 'super_dispatch' })).toBe('dispatch');
  });
  it('健康自检 → health；降级信号 → issue；升级 → escalation', () => {
    expect(systemUserKind('user', { type: 'worker_health_report' })).toBe('health');
    expect(systemUserKind('user', { type: 'worker_issue_report' })).toBe('issue');
    expect(systemUserKind('user', { type: 'project_escalation' })).toBe('escalation');
  });
  it('审批回复(meta.approval_response) → approval', () => {
    expect(systemUserKind('user', { approval_response: { request_id: 'r', option: '确认' } })).toBe('approval');
  });
  it('空 meta 的 user 消息 → system（真人一定带 user_chat，故空 meta 也是系统）', () => {
    expect(systemUserKind('user', null)).toBe('system');
    expect(systemUserKind('user', {})).toBe('system');
  });
});
