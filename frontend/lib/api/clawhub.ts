import { api } from '@/lib/api';
import type {
  ClawhubInspectResp,
  ClawhubInstallReq,
  ClawhubInstallResp,
  ClawhubSearchResp,
  InstalledItem,
} from '@/types/clawhub';

export const clawhubApi = {
  search: (query: string, limit = 20) =>
    api
      .get<ClawhubSearchResp>('/api/admin/clawhub/search', {
        params: { query, limit },
      })
      .then((r) => r.data),
  inspect: (slug: string, version?: string) =>
    api
      .get<ClawhubInspectResp>('/api/admin/clawhub/inspect', {
        params: { slug, ...(version ? { version } : {}) },
      })
      .then((r) => r.data),
  install: (body: ClawhubInstallReq) =>
    api
      .post<ClawhubInstallResp>('/api/admin/clawhub/install', body)
      .then((r) => r.data),
  uninstall: (installId: string) =>
    api.delete(`/api/admin/clawhub/install/${installId}`),
  listInstalled: (projectId?: string) =>
    api
      .get<InstalledItem[]>('/api/admin/clawhub/installed', {
        params: projectId ? { mission_id: projectId } : undefined,
      })
      .then((r) => r.data),
};
