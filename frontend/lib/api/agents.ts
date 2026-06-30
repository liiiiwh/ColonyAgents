import { api } from '@/lib/api';
import type {
  AgentCreateInput,
  AgentDetail,
  AgentPublic,
  AgentTestResponse,
  AgentUpdateInput,
} from '@/types/agent';

export const agentsApi = {
  list: () => api.get<AgentPublic[]>('/api/agents').then((r) => r.data),
  get: (id: string) => api.get<AgentDetail>(`/api/agents/${id}`).then((r) => r.data),
  create: (body: AgentCreateInput) =>
    api.post<AgentDetail>('/api/agents', body).then((r) => r.data),
  update: (id: string, body: AgentUpdateInput) =>
    api.put<AgentDetail>(`/api/agents/${id}`, body).then((r) => r.data),
  /** 级联删 super 的影响预览：会删哪些 Mission / 独占 worker，哪些 worker 因被其他 super
   *  使用（或系统对象）会保留。confirm 弹窗据此给提示。 */
  cascadePreview: (id: string) =>
    api
      .get<{
        super_name: string;
        mission_count: number;
        missions: string[];
        workers_to_delete: string[];
        workers_to_keep: { name: string; reason: 'shared' | 'system' }[];
      }>(`/api/agents/${id}/cascade-preview`)
      .then((r) => r.data),

  /** cascade=true（仅 super）：连带删名下所有 Mission + 独占 worker + super 本体，
   *  返回 {deleted_super, deleted_missions[], deleted_agents[], skipped[]}（非 cascade 为 204 无体）。 */
  delete: (id: string, cascade = false) =>
    api
      .delete(`/api/agents/${id}`, cascade ? { params: { cascade: true } } : undefined)
      .then((r) => r.data),

  bindSkill: (agentId: string, skillId: string, config?: Record<string, unknown>) =>
    api
      .post(`/api/agents/${agentId}/skills/${skillId}`, config ?? {})
      .then((r) => r.data),
  unbindSkill: (agentId: string, skillId: string) =>
    api.delete(`/api/agents/${agentId}/skills/${skillId}`),
  bindMCP: (agentId: string, mcpId: string, toolFilter?: string[]) =>
    api
      .post(`/api/agents/${agentId}/mcp-servers/${mcpId}`, toolFilter ?? null)
      .then((r) => r.data),
  unbindMCP: (agentId: string, mcpId: string) =>
    api.delete(`/api/agents/${agentId}/mcp-servers/${mcpId}`),

  bindAuxModel: (
    agentId: string,
    modelId: string,
    body: { role: string; alias?: string | null; config?: Record<string, unknown> },
  ) =>
    api
      .post(`/api/agents/${agentId}/aux-models/${modelId}`, body)
      .then((r) => r.data),
  unbindAuxModel: (agentId: string, modelId: string) =>
    api.delete(`/api/agents/${agentId}/aux-models/${modelId}`),

  test: (id: string, input: string) =>
    api
      .post<AgentTestResponse>(`/api/agents/${id}/test`, { input })
      .then((r) => r.data),
};
