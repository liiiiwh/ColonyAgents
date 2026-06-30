import { api } from '@/lib/api';
import type { UserPublic } from '@/types/api';

export type UserRole = 'admin' | 'user';

export interface UserCreateInput {
  username: string;
  email: string;
  password: string;
  role: UserRole;
  is_active?: boolean;
}

export interface UserUpdateInput {
  email?: string;
  password?: string | null;
  role?: UserRole;
  is_active?: boolean;
}

export const usersApi = {
  list: (search?: string) =>
    api
      .get<UserPublic[]>('/api/users', {
        params: search ? { search } : {},
      })
      .then((r) => r.data),

  search: (query: string, limit = 10) =>
    api
      .get<UserPublic[]>('/api/users/search', {
        params: { q: query, limit },
      })
      .then((r) => r.data),

  create: (body: UserCreateInput) =>
    api.post<UserPublic>('/api/users', body).then((r) => r.data),
  update: (id: string, body: UserUpdateInput) =>
    api.put<UserPublic>(`/api/users/${id}`, body).then((r) => r.data),
  remove: (id: string) => api.delete(`/api/users/${id}`),
};
