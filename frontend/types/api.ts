/**
 * 后端 API 响应类型定义。
 * 与 backend/app/schemas/*.py 保持同步。
 */

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: 'bearer';
}

export interface UserPublic {
  id: string;
  username: string;
  email: string;
  role: 'admin' | 'user';
  is_active: boolean;
  created_at: string;
}
