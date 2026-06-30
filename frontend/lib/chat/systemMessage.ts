/** 判断一条 role=user 的消息是「系统/自动产生」还是「真人发送」，并给出来源子类。
 *
 * 真人消息唯一入口是 super 对话框（写 meta.source='user_chat'）；其余所有 role=user 的
 * 消息都是系统用 user 角色喂给 LLM 的（派单 / 健康自检 / 降级信号 / 升级 / 审批回复）。
 * 前端据此加标识，区别于真人消息——无需数据库回填（基于现有 meta 实时判断，历史全覆盖）。
 */
import type { MessageMeta } from '@/types/sse';

export type SystemMsgKind =
  | 'dispatch' // [super dispatch] super 派单给 worker
  | 'health' // 平台 worker 健康自检
  | 'issue' // worker 自动降级信号
  | 'escalation' // super 向 builder 升级请求
  | 'approval' // 审批回复（用户决定的系统回执）
  | 'system'; // 其它系统产生

/** role=user 且非真人 → 返回系统来源子类；真人或非 user → null。 */
export function systemUserKind(
  role: string,
  meta: MessageMeta | null | undefined,
): SystemMsgKind | null {
  if (role !== 'user') return null;
  if (meta?.source === 'user_chat') return null; // 真人在对话框发的
  const t = meta?.type;
  if (t === 'super_dispatch') return 'dispatch';
  if (t === 'worker_health_report') return 'health';
  if (t === 'worker_issue_report') return 'issue';
  if (t === 'project_escalation') return 'escalation';
  if (meta?.approval_response) return 'approval';
  return 'system';
}
