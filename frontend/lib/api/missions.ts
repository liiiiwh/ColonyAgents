import { api } from '@/lib/api';

export type MissionPublic = {
  id: string;
  slug: string;
  name: string;
  description: string;
  super_agent_id: string;
  super_slug: string | null;
  super_name: string | null;
  lifecycle_status: string;
  is_system?: boolean;
  goal_hint: string | null;
  goal_spec: Record<string, unknown> | null;
  created_at: string | null;
};

export type MissionCreateBody = {
  super_agent_id: string;
  name: string;
  goal_hint?: string;
};

export type MissionCreateResp = {
  ok: boolean;
  mission?: MissionPublic;
  error?: string;
};

export const missionsApi = {
  /** v6.A · list missions; 可选按 super 过滤 */
  list: (superAgentId?: string) =>
    api
      .get<MissionPublic[]>('/api/missions', {
        params: superAgentId ? { super_agent_id: superAgentId } : undefined,
      })
      .then((r) => r.data),
  /** v6.A · spawn mission of an existing super (用户点 + 新建 Mission) */
  create: (body: MissionCreateBody) =>
    api.post<MissionCreateResp>('/api/missions', body).then((r) => r.data),
  /** v6.A · mission 详情（工作台首屏） */
  get: (slug: string) =>
    api.get<MissionPublic>(`/api/missions/${slug}`).then((r) => r.data),
};
