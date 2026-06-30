import { api } from '@/lib/api';
import type { ThinkingLevel } from '@/types/agent';

export type SuperThread = {
  // ADR-018 mission-only：thread 标识 = thread_key（'main' / 'worker:*' / 'health' / 其他）
  thread_key: string;
  thread_kind: string | null;
  title: string | null;
  msg_count: number;
  last_msg_at: string | null;
  created_at: string | null;
  compressed_up_to_at: string | null;
};

export type SuperThreadsResp = {
  // 无 standing mission 的 super 入口（如 Builder）返回空壳：mission_id=null、threads=[]。
  mission_id: string | null;
  slug: string;
  name: string;
  super_name?: string | null;
  lifecycle_status: string | null;
  paused_reason: string | null;
  supervisor_agent_id: string;
  threads: SuperThread[];
};

export type SuperStats = {
  mission_id: string;
  window: string;
  by_status: Record<string, { cnt: number; avg_ms: number | null; tokens: number; artifacts: number }>;
  per_worker: Array<{ worker_agent_id: string; cnt: number; ok: number; avg_ms: number | null }>;
  top_errors: Array<{ err: string; cnt: number }>;
};

export type WorkerOverride = {
  mission_id: string;
  slug: string;
  name: string;
  override: Record<string, unknown>;
};

export type WorkerListItem = {
  id: string;
  name: string;
  capability: string | null;
  kind: string;
  contract_version: string | null;
  invocations_30d: number;
  ok_30d: number;
  is_system?: boolean;
};

export type WorkerDetail = {
  id: string;
  name: string;
  kind: string;
  capability: string | null;
  description: string;
  category: string;
  max_iterations: number;
  enable_thinking: boolean;
  thinking_level: ThinkingLevel;
  is_enabled: boolean;
  extra_config: Record<string, unknown>;
  capability_contract: Record<string, unknown> | null;
};

export type WorkerInvocation = {
  id: string;
  super_agent_id: string;
  super_mission_id: string | null;
  action: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  status: string;
  error_msg: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  artifact_count: number;
  artifact_total_bytes: number;
  needs_clarification_round: number;
};

export type WorkerStats = {
  worker_id: string;
  window: string;
  overall: Record<string, number | null>;
  per_action: Array<{ action: string; cnt: number; ok: number; avg_ms: number | null }>;
  top_errors: Array<{ err: string; cnt: number }>;
};

export const observeV3Api = {
  // R23 super
  superThreads: (slug: string) =>
    api.get<SuperThreadsResp>(`/api/super/${slug}/threads`).then((r) => r.data),
  superStats: (slug: string, window = '7d') =>
    api.get<SuperStats>(`/api/super/${slug}/stats?window=${window}`).then((r) => r.data),
  superArtifacts: (slug: string, page = 1, limit = 50) =>
    api
      .get<{ page: number; limit: number; items: unknown[] }>(
        `/api/super/${slug}/artifacts?page=${page}&limit=${limit}`
      )
      .then((r) => r.data),
  exportThread: (slug: string, threadKey: string, format: 'markdown' | 'json' = 'markdown') =>
    api
      .get(`/api/super/${slug}/threads/${encodeURIComponent(threadKey)}/export?format=${format}`)
      .then((r) => r.data),
  deleteThread: (slug: string, threadKey: string) =>
    api.delete(`/api/super/${slug}/threads/${encodeURIComponent(threadKey)}`).then((r) => r.data),
  // R26 worker
  listWorkers: () => api.get<WorkerListItem[]>('/api/workers').then((r) => r.data),
  workerDetail: (id: string) =>
    api.get<WorkerDetail>(`/api/workers/${id}`).then((r) => r.data),
  workerInvocations: (id: string, opts?: { page?: number; status?: string; super_id?: string }) =>
    api
      .get<{ page: number; limit: number; items: WorkerInvocation[] }>(`/api/workers/${id}/invocations`, {
        params: opts,
      })
      .then((r) => r.data),
  workerStats: (id: string, window = '7d') =>
    api.get<WorkerStats>(`/api/workers/${id}/stats?window=${window}`).then((r) => r.data),
  workerOverrides: (id: string) =>
    api.get<WorkerOverride[]>(`/api/workers/${id}/overrides`).then((r) => r.data),
  workerArtifacts: (id: string, opts?: { page?: number; media_type?: string }) =>
    api
      .get<{ page: number; limit: number; items: WorkerArtifact[] }>(`/api/workers/${id}/artifacts`, {
        params: { page: opts?.page ?? 1, media_type: opts?.media_type },
      })
      .then((r) => r.data),
};

export type WorkerArtifact = {
  message_id: string;
  created_at: string | null;
  artifact_url: string | null;
  media_type: string | null;
  action: string | null;
  artifact_meta: unknown;
  super_slug: string | null;
  super_name: string | null;
};
