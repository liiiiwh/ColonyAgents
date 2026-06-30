import { api } from '@/lib/api';
import type {
  MCPServerCreateInput,
  MCPServerPublic,
  MCPTestResponse,
  SkillCreateInput,
  SkillPublic,
  SkillUpdateInput,
} from '@/types/skill';

export const skillsApi = {
  list: () => api.get<SkillPublic[]>('/api/skills').then((r) => r.data),
  get: (id: string) => api.get<SkillPublic>(`/api/skills/${id}`).then((r) => r.data),
  create: (body: SkillCreateInput) =>
    api.post<SkillPublic>('/api/skills', body).then((r) => r.data),
  update: (id: string, body: SkillUpdateInput) =>
    api.put<SkillPublic>(`/api/skills/${id}`, body).then((r) => r.data),
  delete: (id: string) => api.delete(`/api/skills/${id}`),
};

export const mcpServersApi = {
  list: () => api.get<MCPServerPublic[]>('/api/mcp-servers').then((r) => r.data),
  get: (id: string) => api.get<MCPServerPublic>(`/api/mcp-servers/${id}`).then((r) => r.data),
  create: (body: MCPServerCreateInput) =>
    api.post<MCPServerPublic>('/api/mcp-servers', body).then((r) => r.data),
  update: (id: string, body: Partial<MCPServerCreateInput>) =>
    api.put<MCPServerPublic>(`/api/mcp-servers/${id}`, body).then((r) => r.data),
  delete: (id: string) => api.delete(`/api/mcp-servers/${id}`),
  test: (id: string) =>
    api.post<MCPTestResponse>(`/api/mcp-servers/${id}/test`).then((r) => r.data),
};
