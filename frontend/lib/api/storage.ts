import { api } from '@/lib/api';
import type {
  DocumentPublic,
  KnowledgeBasePublic,
  SearchHit,
  StorageObject,
} from '@/types/storage';

export const storageApi = {
  list: (prefix?: string) =>
    api
      .get<StorageObject[]>('/api/storage/files', { params: prefix ? { prefix } : undefined })
      .then((r) => r.data),
  upload: (file: File, key?: string) => {
    const form = new FormData();
    form.append('file', file);
    return api
      .post('/api/storage/upload', form, {
        params: key ? { key } : undefined,
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data);
  },
  /** 普通用户上传聊天附件（后端决定 key 前缀），返回预签名 URL */
  userUpload: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api
      .post<{
        key: string;
        size: number;
        content_type: string;
        url: string;
        expires_in: number;
      }>('/api/storage/user-upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data);
  },
  delete: (key: string) =>
    api.delete('/api/storage/files', { params: { key } }),
  presignedUrl: (key: string) =>
    api.get<{ url: string; expires_in: number }>('/api/storage/url', { params: { key } }).then((r) => r.data),
};

export const knowledgeApi = {
  list: () => api.get<KnowledgeBasePublic[]>('/api/knowledge').then((r) => r.data),
  create: (body: {
    name: string;
    collection_name: string;
    description?: string;
    embedding_model_id: string;
  }) => api.post<KnowledgeBasePublic>('/api/knowledge', body).then((r) => r.data),
  delete: (id: string) => api.delete(`/api/knowledge/${id}`),

  listDocs: (id: string) =>
    api.get<DocumentPublic[]>(`/api/knowledge/${id}/documents`).then((r) => r.data),
  index: (id: string, filename: string, content: string) =>
    api
      .post<DocumentPublic>(`/api/knowledge/${id}/documents`, { filename, content })
      .then((r) => r.data),
  deleteDoc: (id: string, docId: string) =>
    api.delete(`/api/knowledge/${id}/documents/${docId}`),

  search: (id: string, query: string, topK = 5) =>
    api
      .post<{ hits: SearchHit[] }>(`/api/knowledge/${id}/search`, {
        query,
        top_k: topK,
      })
      .then((r) => r.data.hits),
};
