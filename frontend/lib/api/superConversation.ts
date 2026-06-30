/** v4 · 用户跟 super 实时对话 API 客户端
 *  - POST /chat       发消息（自动 cancel + trigger）
 *  - POST /interrupt  强 cancel
 *  - EventSource /stream  SSE 拉 super 实时状态 + 新消息
 */
import { api } from '@/lib/api';

export type ChatAttachment = {
  kind: 'image' | 'file';
  name: string;
  url: string;
  mediaType?: string;
  size?: number;
};

export type SuperChatBody = {
  content: string;
  meta?: Record<string, unknown>;
  attachments?: ChatAttachment[];
  auto_start?: boolean;
};

export type SuperChatResp = {
  ok: boolean;
  message_id?: string;
  queue_size_after?: number;
  cancel_result?: Record<string, unknown>;
  triggered_tick?: boolean;
  v38_offloaded?: boolean;
  auto_started?: boolean;
  lifecycle_after?: string;
  warning?: string;
  error?: string;
};

export type SuperStreamEvent =
  | { type: 'init'; mission_id: string; slug: string; lifecycle_status: string; is_running: boolean; pending_count: number }
  | { type: 'state'; lifecycle_status: string; is_running: boolean; pending_count: number }
  | { type: 'message'; id: string; role: string; content: string; meta: Record<string, unknown>; created_at: string | null }
  | { type: 'error' }
  | { type: 'done' }
  | { type: 'project_deleted' };

export type MessageOpResp = {
  ok: boolean;
  deleted_messages: number;
  dropped_pending: number;
  cancelled_current_tick?: boolean;
  error?: string;
};

export const superConversationApi = {
  chat: (slug: string, body: SuperChatBody) =>
    api.post<SuperChatResp>(`/api/super/${slug}/chat`, body).then((r) => r.data),
  interrupt: (slug: string) =>
    api.post<{ ok: boolean; cancel_result?: Record<string, unknown> }>(`/api/super/${slug}/interrupt`).then((r) => r.data),
  /** EventSource 工厂：调用方 onmessage 处理 SuperStreamEvent；记得 close()。
   *  默认走同源（经 Next rewrites 代理到后端），与 axios 客户端一致；不再硬编码 dev 端口
   *  （修：生产未设 NEXT_PUBLIC_API_BASE_URL 时 SSE 连 localhost:9022 → mission 直播黑屏）。 */
  streamUrl: (slug: string, token: string) =>
    `${process.env.NEXT_PUBLIC_API_BASE_URL || ''}/api/super/${slug}/stream?token=${encodeURIComponent(token)}`,
  /** v4.3 · 删除主 thread 单条消息（hard delete + drop 对应 pending 队列） */
  deleteMessage: (slug: string, messageId: string) =>
    api
      .delete<MessageOpResp>(`/api/super/${slug}/messages/${messageId}`)
      .then((r) => r.data),
  /** v4.3 · rewind 到指定消息：删除其后的全部主 thread 消息 + 可选 cancel 当前 tick */
  rewindTo: (slug: string, messageId: string, cancelRunning = true) =>
    api
      .post<MessageOpResp>(`/api/super/${slug}/messages/${messageId}/rewind`, {
        cancel_running: cancelRunning,
      })
      .then((r) => r.data),
  /** ADR-009 G5 · Builder（或任意 super）每 mission 的结构化工作记录 */
  workLog: (slug: string) =>
    api
      .get<{ ok: boolean; items: BuilderWorkLogItem[] }>(`/api/super/${slug}/work-log`)
      .then((r) => r.data),
};

export type BuilderWorkLogItem = {
  id: string;
  session_id: string;
  action: string;
  target_type: string;
  target_id: string;
  affected_supers: string[];
  result: string;
  summary: string;
  created_at: string | null;
};
