import { api } from '@/lib/api';
import type {
  LLMModelPublic,
  ProviderCreateInput,
  ProviderPublic,
  ProviderUpdateInput,
  SyncModelsResponse,
} from '@/types/provider';

export const providersApi = {
  list: () => api.get<ProviderPublic[]>('/api/providers').then((r) => r.data),
  get: (id: string) => api.get<ProviderPublic>(`/api/providers/${id}`).then((r) => r.data),
  create: (body: ProviderCreateInput) =>
    api.post<ProviderPublic>('/api/providers', body).then((r) => r.data),
  update: (id: string, body: ProviderUpdateInput) =>
    api.put<ProviderPublic>(`/api/providers/${id}`, body).then((r) => r.data),
  delete: (id: string) => api.delete(`/api/providers/${id}`),
  syncModels: (id: string) =>
    api.post<SyncModelsResponse>(`/api/providers/${id}/sync-models`).then((r) => r.data),
  listModels: (id: string) =>
    api.get<LLMModelPublic[]>(`/api/providers/${id}/models`).then((r) => r.data),
  updateModel: (providerId: string, modelId: string, body: Partial<LLMModelPublic>) =>
    api
      .patch<LLMModelPublic>(`/api/providers/${providerId}/models/${modelId}`, body)
      .then((r) => r.data),
};
