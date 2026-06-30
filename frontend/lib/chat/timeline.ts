/**
 * R4-3 · Chat timeline 重建（纯逻辑，从 ChatArea.tsx 抽出，vitest 覆盖）。
 *
 * 服务端 messages → 前端 timeline 项。agent_log 消息 meta.raw 存完整 SSE 事件载荷，按类型重建：
 *   tool-input-available / tool-output-available → tool 卡（合并 toolCallId）
 *   data-subtask-start / data-subtask-end       → subtask 卡（按 worker 能力聚合）
 *   data-batch-start / data-batch-end           → batch 卡
 *   data-approval-request / meta.type=approval_request → approval 卡
 *   data-form-request                           → form 卡
 *   其它（chat-model-end / data-artifact / data-branch-*）→ 不回放
 */

/** 重建只需要这几个字段（比完整 MessagePublic 宽松，方便测试 + 解耦）。 */
export interface MessageLike {
  id: string;
  role: string;
  content: string;
  created_at: string;
  meta?: Record<string, unknown> | null;
}

export interface HistoryAttachment {
  type: 'image' | 'file' | 'text';
  name?: string | null;
  media_type?: string | null;
  content: string;
}

export interface ApprovalReplyMeta {
  requestId: string;
  title: string;
  option: string;
}

export type TimelineItem =
  | {
      kind: 'user';
      id: string;
      content: string;
      attachments?: HistoryAttachment[];
      approvalReply?: ApprovalReplyMeta;
    }
  | { kind: 'assistant'; id: string; content: string; streaming: boolean }
  | { kind: 'thinking'; id: string; content: string }
  | {
      kind: 'tool';
      id: string;
      name: string;
      input: unknown;
      output?: string;
      state: 'running' | 'done';
    }
  | {
      kind: 'subtask';
      id: string;
      batchId?: string;
      worker: string;
      task: string;
      summary?: string;
      ok?: boolean;
      state: 'running' | 'done';
    }
  | {
      kind: 'batch';
      id: string;
      total: number;
      subtasks: Record<string, {
        worker?: string;
        task?: string;
        summary?: string;
        ok?: boolean;
        state: 'running' | 'done';
      }>;
      state: 'running' | 'done';
      ok?: number;
      failed?: number;
    }
  | {
      kind: 'approval';
      id: string;
      title: string;
      message: string;
      options: string[];
    }
  | {
      kind: 'form';
      id: string;
      title: string;
      description: string;
      schema: Record<string, unknown>;
      prefilled: Record<string, unknown>;
      submitLabel: string;
      state: 'pending' | 'submitted';
    }
  | {
      kind: 'error';
      id: string;
      errorCode: string;
      userMessage: string;
      requestId?: string;
      attemptCount?: number;
      retryUserMessageId?: string;
      retryUserMessageContent?: string;
    };

/**
 * 识别并解析 `[approval_response ...]` 文本 payload。识别不到返回 null。
 * 格式须与 ChatArea.handleApprovalClick 的 ctxLines 构造保持一致。
 */
export function parseApprovalReply(
  raw: string,
): { meta: ApprovalReplyMeta; displayContent: string } | null {
  if (!raw.startsWith('[approval_response ')) return null;
  const headerMatch = raw.match(/^\[approval_response\s+request_id=([^\]]+)\]/);
  if (!headerMatch) return null;
  const requestId = headerMatch[1];
  const titleMatch = raw.match(/\n审批标题：(.+?)(?:\n|$)/);
  const optionMatch = raw.match(/\n用户选择：([\s\S]+?)$/);
  if (!titleMatch || !optionMatch) return null;
  return {
    meta: { requestId, title: titleMatch[1].trim(), option: optionMatch[1].trim() },
    displayContent: optionMatch[1].trim(),
  };
}

export function toTimeline(msgs: MessageLike[]): TimelineItem[] {
  // D6：严格按 created_at 升序 + meta.sequence 二级排序
  const sorted = [...msgs].sort((a, b) => {
    const ta = new Date(a.created_at).getTime();
    const tb = new Date(b.created_at).getTime();
    if (ta !== tb) return ta - tb;
    const sa = ((a.meta as { sequence?: number } | undefined)?.sequence ?? 0) || 0;
    const sb = ((b.meta as { sequence?: number } | undefined)?.sequence ?? 0) || 0;
    return sa - sb;
  });
  const items: TimelineItem[] = [];
  const toolIdx: Record<string, number> = {};
  const subtaskByKey: Record<string, number> = {};
  const batchIdx: Record<string, number> = {};
  let lastApprovalIdx = -1;
  let lastFormIdx = -1;

  for (const m of sorted) {
    const meta = (m.meta || {}) as Record<string, unknown>;

    if (m.role === 'user') {
      if (lastApprovalIdx >= 0) {
        lastApprovalIdx = -1;
      }
      if (lastFormIdx >= 0) {
        const prev = items[lastFormIdx];
        if (prev && prev.kind === 'form') {
          items[lastFormIdx] = { ...prev, state: 'submitted' };
        }
        lastFormIdx = -1;
      }
      const parsedApproval = parseApprovalReply(m.content);
      items.push({
        kind: 'user',
        id: m.id,
        content: parsedApproval ? parsedApproval.displayContent : m.content,
        approvalReply: parsedApproval?.meta,
        attachments: ((meta.attachments as HistoryAttachment[]) ?? []) as HistoryAttachment[],
      });
      continue;
    }

    if (m.role === 'assistant') {
      if ((meta as { type?: string }).type === 'error') {
        items.push({
          kind: 'error',
          id: m.id,
          errorCode: String((meta as { error_code?: unknown }).error_code ?? 'LLM_ERROR'),
          userMessage: String(
            (meta as { user_message?: unknown }).user_message ?? m.content ?? 'AI 服务出现意外错误',
          ),
          requestId: (meta as { request_id?: string }).request_id,
          attemptCount: (meta as { attempt_count?: number }).attempt_count,
          retryUserMessageId: (meta as { retry_user_message_id?: string }).retry_user_message_id,
          retryUserMessageContent: (meta as { retry_user_message_content?: string }).retry_user_message_content,
        });
        continue;
      }
      items.push({ kind: 'assistant', id: m.id, content: m.content, streaming: false });
      continue;
    }

    if (m.role !== 'agent_log') continue;

    const metaType = (meta as { type?: string }).type;
    if (metaType === 'approval_request') {
      const rid = String((meta as { request_id?: string }).request_id || m.id);
      const title = String((meta as { title?: string }).title || '');
      const message = String((meta as { message?: string }).message || m.content || '');
      const options = ((meta as { options?: unknown }).options as string[] | undefined) || [];
      lastApprovalIdx = items.length;
      items.push({
        kind: 'approval',
        id: rid,
        title,
        message,
        options: Array.isArray(options) ? options : [],
      });
      continue;
    }

    const raw = (meta.raw || {}) as Record<string, unknown>;
    const evtType = (meta.event_type as string) || (raw.type as string) || '';

    switch (evtType) {
      case 'tool-input-available': {
        const tid = String(raw.toolCallId || '');
        const tn = String(raw.toolName || 'tool');
        const input = raw.input;
        const idx = items.length;
        items.push({ kind: 'tool', id: tid || m.id, name: tn, input, state: 'running' });
        if (tid) toolIdx[tid] = idx;
        break;
      }
      case 'tool-output-available': {
        const tid = String(raw.toolCallId || '');
        const output = String(raw.output ?? '');
        const existing = toolIdx[tid];
        if (existing !== undefined) {
          const prev = items[existing] as Extract<TimelineItem, { kind: 'tool' }>;
          items[existing] = { ...prev, state: 'done', output };
        } else {
          items.push({
            kind: 'tool',
            id: tid || m.id,
            name: String(raw.toolName || 'tool'),
            input: {},
            state: 'done',
            output,
          });
        }
        break;
      }
      case 'data-batch-start': {
        const d = (raw.data || {}) as { batch_id: string; total: number };
        const idx = items.length;
        items.push({
          kind: 'batch',
          id: d.batch_id,
          total: d.total,
          subtasks: {},
          state: 'running',
        });
        batchIdx[d.batch_id] = idx;
        break;
      }
      case 'data-batch-end': {
        const d = (raw.data || {}) as { batch_id: string; ok: number; failed: number };
        const idx = batchIdx[d.batch_id];
        if (idx !== undefined) {
          const prev = items[idx] as Extract<TimelineItem, { kind: 'batch' }>;
          items[idx] = { ...prev, state: 'done', ok: d.ok, failed: d.failed };
        }
        break;
      }
      case 'data-subtask-start': {
        const d = (raw.data || {}) as { batch_id?: string; worker: string; task: string };
        // 子任务在批次内的标识键（worker capability 取向，回退到 worker 名）。
        const key = String((raw.data as { node?: string } | undefined)?.node ?? d.worker);
        if (d.batch_id) {
          const bIdx = batchIdx[d.batch_id];
          if (bIdx !== undefined) {
            const prev = items[bIdx] as Extract<TimelineItem, { kind: 'batch' }>;
            items[bIdx] = {
              ...prev,
              subtasks: {
                ...prev.subtasks,
                [key]: { worker: d.worker, task: d.task, state: 'running' },
              },
            };
          }
        } else {
          const idx = items.length;
          items.push({
            kind: 'subtask',
            id: `subtask-${m.id}`,
            worker: d.worker,
            task: d.task,
            state: 'running',
          });
          subtaskByKey[key] = idx;
        }
        break;
      }
      case 'data-subtask-end': {
        const d = (raw.data || {}) as { batch_id?: string; worker?: string; ok: boolean; summary?: string; error?: string };
        const key = String((raw.data as { node?: string } | undefined)?.node ?? d.worker ?? '');
        if (d.batch_id) {
          const bIdx = batchIdx[d.batch_id];
          if (bIdx !== undefined) {
            const prev = items[bIdx] as Extract<TimelineItem, { kind: 'batch' }>;
            const existing = prev.subtasks[key] ?? { state: 'done' as const };
            items[bIdx] = {
              ...prev,
              subtasks: {
                ...prev.subtasks,
                [key]: { ...existing, state: 'done', ok: d.ok, summary: d.summary || d.error },
              },
            };
          }
        } else {
          const idx = subtaskByKey[key];
          if (idx !== undefined) {
            const prev = items[idx] as Extract<TimelineItem, { kind: 'subtask' }>;
            items[idx] = { ...prev, state: 'done', ok: d.ok, summary: d.summary || d.error };
          }
        }
        break;
      }
      case 'data-approval-request': {
        const d = (raw.data || {}) as { request_id: string; title: string; message: string; options: string[] };
        lastApprovalIdx = items.length;
        items.push({ kind: 'approval', id: d.request_id, title: d.title, message: d.message, options: d.options });
        break;
      }
      case 'data-form-request': {
        const d = (raw.data || {}) as {
          request_id: string;
          title: string;
          description: string;
          schema: Record<string, unknown>;
          prefilled: Record<string, unknown>;
          submit_label: string;
        };
        lastFormIdx = items.length;
        items.push({
          kind: 'form',
          id: d.request_id,
          title: d.title,
          description: d.description,
          schema: d.schema,
          prefilled: d.prefilled,
          submitLabel: d.submit_label || '提交',
          state: 'pending',
        });
        break;
      }
      case 'thinking-segment':
        if (m.content.trim()) {
          items.push({ kind: 'thinking', id: m.id, content: m.content });
        }
        break;
      default:
        break;
    }
  }

  return items;
}
