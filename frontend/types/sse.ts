/**
 * Mission SSE 流的事件载荷类型。
 *
 * 后端把异构事件按 `type` 字段区分推下来；前端 lib/sse/handlers.ts 按 type dispatch。
 * 这里用一个 type→payload 的映射给每个 handler 精确类型，取代散落的 `any`。
 */

/**
 * agent_log 消息 meta —— 本质是动态 JSON，这里把前端实际读到的字段显式标出，
 * 末尾保留开放索引兜住未列出的键。
 */
export interface MessageMeta {
  source?: string;
  type?: string;
  request_id?: string;
  title?: string;
  message?: string;
  description?: string;
  options?: string[];
  schema?: Record<string, unknown>;
  prefilled?: Record<string, unknown>;
  submit_label?: string;
  turn_id?: string;
  project_slug?: string;
  approval_response?: { request_id?: string; option: string; decided_by?: string };
  artifact_url?: string;
  artifact_meta?: { label?: string };
  artifact_bytes?: number;
  action?: string;
  media_type?: string;
  attachments?: unknown[];
  _local?: boolean;
  _streaming?: boolean;
  [k: string]: unknown;
}

/** chat 消息（持久 + 直播占位气泡共用的宽松形状）。 */
export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  created_at: string | null;
  meta?: MessageMeta | null;
}

/** 右栏「最近 worker 调用」一行的实时状态（最近 30 条）。 */
export interface LiveCall {
  call_id: string;
  capability?: string;
  action?: string;
  worker_id?: string;
  stage: string;
  started_at?: number;
  done: boolean;
  duration_ms?: number;
  status?: string;
  error_msg?: string;
  artifact_url?: string;
}

/** init 帧里回放的 pending 审批（字段与 ApprovalCardData 子集对齐）。 */
export interface PendingApprovalPayload {
  request_id: string;
  title: string;
  message: string;
  options: string[];
  created_at?: string;
  thread_key?: string;
  status?: string;
  resolution?: ApprovalResolution;
}

/** 审批决议（与 ApprovalCardData.resolution 对齐的线上契约）。 */
export interface ApprovalResolution {
  option: string;
  decided_by: string;
  via: 'ui' | 'wechat' | 'auto' | 'chat' | 'inline';
}

/** redirect 建议候选（结构与 RedirectSuggestionCard 的同名类型一致，靠结构兼容互通）。 */
export interface RedirectCandidate {
  super_id?: string;
  name: string;
  fit_hint?: string;
  description?: string;
}

/** 后端 SSE 推送的所有 event type。新 event 加这里 + handlers 里 + 下面 map = 完。 */
export type SSEEventType =
  | 'init'
  | 'state'
  | 'message'
  | 'heartbeat'
  | 'token'
  | 'activity_started'
  | 'activity_finished'
  | 'activity_intervened'
  | 'redirect_suggestion'
  | 'worker_resolve'
  | 'worker_start'
  | 'worker_llm_invoke'
  | 'worker_done'
  | 'approval_request'
  | 'approval_resolved'
  | 'lifecycle_changed'
  | 'error'
  | 'done'
  | 'project_deleted';

interface LifecycleSnapshot {
  lifecycle_status?: string;
  is_running?: boolean;
  pending_count?: number;
}

/** 每个 event type 对应的载荷。索引用 `type` 字段在 dispatch 时缩窄。 */
export interface SSEEventMap {
  init: LifecycleSnapshot & { pending_approvals?: PendingApprovalPayload[] };
  state: LifecycleSnapshot;
  message: ChatMessage;
  heartbeat: Record<string, never>;
  token: { delta?: string };
  activity_started: WorkerEventPayload;
  activity_finished: WorkerEventPayload;
  activity_intervened: WorkerEventPayload;
  redirect_suggestion: {
    reason?: string;
    candidates?: RedirectCandidate[];
    original_message?: string;
  };
  worker_resolve: WorkerEventPayload;
  worker_start: WorkerEventPayload;
  worker_llm_invoke: WorkerEventPayload;
  worker_done: WorkerEventPayload;
  approval_request: {
    request_id: string;
    title: string;
    message: string;
    options: string[];
    created_at?: string;
  };
  approval_resolved: {
    request_id: string;
    option: string;
    decided_by?: string;
    via?: ApprovalResolution['via'];
  };
  lifecycle_changed: { to?: string };
  error: { message?: string };
  done: Record<string, never>;
  project_deleted: Record<string, never>;
}

/** worker_* / activity_* 事件载荷。 */
export interface WorkerEventPayload {
  type: string;
  call_id: string;
  capability?: string;
  action?: string;
  worker_id?: string;
  status?: string;
  duration_ms?: number;
  error_msg?: string;
  artifact_url?: string;
  ts?: number;
}

/** dispatch 入口拿到的原始事件：带 type 判别字段的任意载荷。 */
export type SSEEvent = { type?: SSEEventType } & Record<string, unknown>;
