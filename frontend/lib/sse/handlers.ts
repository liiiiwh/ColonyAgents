/**
 * R2-6 · /mission/[slug] SSE 事件 dispatch table。
 *
 * 之前 mission/[slug]/page.tsx 的 SSE onmessage 是一根 160-LOC if-else 链；
 * 每加一个 backend SSE event type 都要找对插入位置，没有单一 contract 表。
 *
 * 现在改成 typed Record<EventType, Handler>，TypeScript 编译期就能发现遗漏。
 * 新 backend SSE event type 加进 EventTypeMap → handlers map → 完。
 */
import type { ApprovalCardData } from '@/components/chat/ApprovalCard';
import type { RedirectSuggestionData } from '@/components/mission/RedirectSuggestionCard';
import type {
  ChatMessage,
  LiveCall,
  SSEEvent,
  SSEEventMap,
  SSEEventType,
  WorkerEventPayload,
} from '@/types/sse';

export type { SSEEventType } from '@/types/sse';

/** 给 handler 的状态钩子集合 — page 把它的 setState 全部传进来。 */
export interface SSEStateHooks {
  setStreamState: (s: {
    lifecycle_status?: string;
    is_running?: boolean;
    pending_count?: number;
  }) => void;
  setApprovals: React.Dispatch<React.SetStateAction<ApprovalCardData[]>>;
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  setRedirects: React.Dispatch<React.SetStateAction<RedirectSuggestionData[]>>;
  setLiveCalls: React.Dispatch<React.SetStateAction<LiveCall[]>>;
  handleActivityEvent: (evt: WorkerEventPayload) => void;
}

/** 每个 handler 拿到的载荷由其 event type 在 SSEEventMap 里精确给出。 */
type Handlers = {
  [K in SSEEventType]?: (data: SSEEventMap[K], s: SSEStateHooks) => void;
};

const handlers: Handlers = {
  init: (data, s) => {
    s.setStreamState({
      lifecycle_status: data.lifecycle_status,
      is_running: data.is_running,
      pending_count: data.pending_count,
    });
    const pending = data.pending_approvals;
    if (Array.isArray(pending)) {
      s.setApprovals((prev) => {
        const existing = new Set(prev.map((a) => a.request_id));
        const fresh: ApprovalCardData[] = pending
          .filter((pa) => !existing.has(pa.request_id))
          .map((pa) => ({
            request_id: pa.request_id,
            title: pa.title,
            message: pa.message,
            options: pa.options,
            created_at: pa.created_at,
            // ADR-024 #1/#3 · 透传真相源：status/resolution 让已决卡刷新后保持「已决定」不再可点；
            // thread_key 让审批按所属线程过滤渲染（worker 审批不串到主线）。
            thread_key: pa.thread_key,
            status: pa.status,
            resolution: pa.resolution,
          }));
        return fresh.length ? [...prev, ...fresh] : prev;
      });
    }
  },

  state: (data, s) => {
    s.setStreamState({
      lifecycle_status: data.lifecycle_status,
      is_running: data.is_running,
      pending_count: data.pending_count,
    });
  },

  // ADR-010 UI · daemon tick 逐字直播：把 token 累积进一个临时「直播气泡」（不落库）。
  // 真实持久消息到达时（下面 message handler）把它清掉，由正式消息接管。
  token: (data, s) => {
    const delta = data?.delta;
    if (!delta) return;
    s.setMessages((prev) => {
      const i = prev.findIndex((m) => m.id === 'stream-live');
      if (i >= 0) {
        const cp = [...prev];
        cp[i] = { ...cp[i], content: (cp[i].content || '') + delta };
        return cp;
      }
      return [
        ...prev,
        {
          id: 'stream-live',
          role: 'assistant',
          content: delta,
          meta: { _streaming: true },
          created_at: new Date().toISOString(),
        },
      ];
    });
  },

  message: (data, s) => {
    s.setMessages((prev) => {
      // 清掉直播占位气泡：正式持久消息（含折叠 tick 卡）将接管渲染
      const base = prev.filter((m) => m.id !== 'stream-live');
      if (base.some((m) => m.id === data.id)) return base;
      return [...base, data];
    });
  },

  heartbeat: () => {/* keep-alive */},

  activity_started: (data, s) => s.handleActivityEvent(data),
  activity_finished: (data, s) => s.handleActivityEvent(data),
  activity_intervened: (data, s) => s.handleActivityEvent(data),

  redirect_suggestion: (data, s) => {
    s.setRedirects((prev) => [
      ...prev,
      {
        reason: data.reason || '',
        candidates: data.candidates || [],
        original_message: data.original_message || '',
      },
    ]);
  },

  approval_request: (data, s) => {
    s.setApprovals((prev) => {
      if (prev.some((a) => a.request_id === data.request_id)) return prev;
      return [
        ...prev,
        {
          request_id: data.request_id,
          title: data.title,
          message: data.message,
          options: data.options,
          created_at: data.created_at || new Date().toISOString(),
        },
      ];
    });
  },

  approval_resolved: (data, s) => {
    s.setApprovals((prev) =>
      prev.map((a) =>
        a.request_id === data.request_id
          ? {
              ...a,
              resolution: {
                option: data.option,
                decided_by: data.decided_by ?? '',
                via: data.via ?? 'ui',
              },
            }
          : a,
      ),
    );
  },

  worker_resolve: (data, s) => handleWorkerEvent(data, s),
  worker_start: (data, s) => handleWorkerEvent(data, s),
  worker_llm_invoke: (data, s) => handleWorkerEvent(data, s),
  worker_done: (data, s) => handleWorkerEvent(data, s),

  lifecycle_changed: (data, s) => {
    // v6.M · LifecycleService 推的事件；同步 lifecycle 显示
    s.setStreamState({ lifecycle_status: data.to });
  },
};

function handleWorkerEvent(data: WorkerEventPayload, s: SSEStateHooks): void {
  const labelMap: Record<string, string> = {
    worker_resolve: '🔍 解析',
    worker_start: '⚡ 开始',
    worker_llm_invoke: '🧠 LLM',
    worker_done:
      data.status === 'completed' ? '✅ 完成' :
      data.status === 'cancelled' ? '🛑 取消' :
      data.status === 'timeout' ? '⏱️ 超时' :
      data.status === 'failed' ? '❌ 失败' : '⚠️ 结束',
  };
  const stage = labelMap[data.type];
  s.setLiveCalls((prev) => {
    const id = data.call_id;
    const existing = prev.find((c) => c.call_id === id);
    if (existing) {
      return prev.map((c) =>
        c.call_id === id
          ? {
              ...c,
              stage,
              done: data.type === 'worker_done',
              duration_ms: data.duration_ms || c.duration_ms,
              status: data.status || c.status,
              error_msg: data.error_msg || c.error_msg,
              artifact_url: data.artifact_url || c.artifact_url,
            }
          : c,
      );
    }
    return [
      ...prev,
      {
        call_id: id,
        capability: data.capability,
        action: data.action,
        worker_id: data.worker_id,
        stage,
        started_at: data.ts,
        done: false,
      },
    ].slice(-30);
  });
}

/**
 * onmessage 单一入口。未知 event type 静默忽略（前向兼容：backend 新事件不会让旧前端崩）。
 */
export function dispatchSSEEvent(data: SSEEvent, state: SSEStateHooks): void {
  const t = data?.type;
  if (!t) return;
  // dispatch 边界把宽松的原始事件交给按 type 精确缩窄的 handler。
  const h = handlers[t] as ((d: SSEEvent, s: SSEStateHooks) => void) | undefined;
  h?.(data, state);
}
