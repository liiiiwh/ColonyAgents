import { api } from '@/lib/api';

export type SystemSetting = {
  key: string;
  value: unknown;
  description: string | null;
  updated_at: string | null;
  updated_by: string | null;
};

export const systemSettingsApi = {
  list: () =>
    api.get<SystemSetting[]>('/api/admin/system-settings').then((r) => r.data),
  update: (key: string, value: unknown) =>
    api
      .patch<SystemSetting>(`/api/admin/system-settings/${encodeURIComponent(key)}`, {
        value,
      })
      .then((r) => r.data),
  // ADR-015 / ADR-019(修订) · 平台初始化向导（gate = 只认默认模型；语言不再阻塞）
  installStatus: () =>
    api
      .get<{ is_install: boolean; seed_language: 'en' | 'zh' }>(
        '/api/admin/system-settings/install-status',
      )
      .then((r) => r.data),
  // ADR-019(修订) · onboarding：选语言（播种系统 Agent 语言；前端另行 setLocale 设本人 UI 语言）
  setSeedLanguage: (language: 'en' | 'zh') =>
    api
      .post<{ ok: boolean; seed_language: string; reseeded: number }>(
        '/api/admin/system-settings/seed-language',
        { language },
      )
      .then((r) => r.data),
  runInstall: () =>
    api
      .post<{ ok: boolean; steps: Record<string, string>; is_install: boolean }>(
        '/api/admin/system-settings/install',
      )
      .then((r) => r.data),
  // ADR-016 · onboarding：UI 选默认模型 → 后端校验 + 存 + 自动 install。
  // 续接①：三个 role 均可选（设置页可只改其一）。
  setDefaultModels: (body: {
    supervisor_model_id?: string;
    agent_model_id?: string;
    embedding_model_id?: string;
  }) =>
    api
      .post<{ ok: boolean; is_install: boolean; auto_installed?: boolean }>(
        '/api/admin/system-settings/default-models',
        body,
      )
      .then((r) => r.data),
  // 续接① · 设置页读：三个默认模型的有效值 + 来源（system_settings>env），label 为 provider/model_id
  getDefaultModels: () =>
    api
      .get<DefaultModelEntry[]>('/api/admin/system-settings/default-models')
      .then((r) => r.data),
};

export type DefaultModelEntry = {
  role: 'supervisor' | 'agent' | 'embedding';
  spec: string | null;
  source: 'system_settings' | 'env' | 'unresolved' | 'none';
  model_id: string | null;
  label: string | null;
};
