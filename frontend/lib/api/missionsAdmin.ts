import { api } from '@/lib/api';
import type {
  MissionActivationResponse,
  MissionCreateInput,
  MissionDetail,
  MissionLifecycleAction,
  MissionPublic,
  MissionRuntimePublic,
  MissionUpdateInput,
} from '@/types/mission';

export const missionsAdminApi = {
  list: () => api.get<MissionPublic[]>('/api/missions/all').then((r) => r.data),
  /** 任意登录用户可访问；只返回 active 项目。用于普通用户的 /projects landing */
  listActive: () => api.get<MissionPublic[]>('/api/missions/active').then((r) => r.data),
  get: (id: string) => api.get<MissionDetail>(`/api/missions/detail/${id}`).then((r) => r.data),
  create: (body: MissionCreateInput) =>
    api.post<MissionDetail>('/api/missions/full', body).then((r) => r.data),
  update: (id: string, body: MissionUpdateInput) =>
    api.put<MissionDetail>(`/api/missions/${id}`, body).then((r) => r.data),
  delete: (id: string, opts?: { cascadeAgents?: boolean }) =>
    api
      .delete<{
        deleted_project: string;
        cascade_agents: boolean;
        deleted_agents: string[];
        skipped_shared_or_failed: string[];
      }>(`/api/missions/${id}`, {
        params: opts?.cascadeAgents ? { cascade_agents: true } : undefined,
      })
      .then((r) => r.data),

  activate: (id: string) =>
    api
      .post<MissionActivationResponse>(`/api/missions/${id}/activate`)
      .then((r) => r.data),
  deactivate: (id: string) =>
    api
      .post<MissionActivationResponse>(`/api/missions/${id}/deactivate`)
      .then((r) => r.data),

  /** M1：触发生命周期动作（start / stop / restart）。返回最新 runtime。 */
  lifecycle: (id: string, action: MissionLifecycleAction) =>
    api
      .post<MissionRuntimePublic>(`/api/missions/${id}/lifecycle/${action}`)
      .then((r) => r.data),

  /** M1：拉取当前运行态明细（含 heartbeat / last_error / run_count）。 */
  runtime: (id: string) =>
    api.get<MissionRuntimePublic>(`/api/missions/${id}/runtime`).then((r) => r.data),
};
