import { api } from '@/lib/api';

// ADR-019 D3 · 一键导入外部 worker（agency-agents）。
// version = 源仓库：en=英文原仓库，zh=社区中文 fork。
export type ImportVersion = 'en' | 'zh';

export type ImportCatalogItem = {
  division: string;
  name: string;
  slug: string;
  path: string;
};

export type ImportWorkerSpec = {
  name: string;
  slug: string;
  capability: string;
  category: string;
  soul_md: string;
  protocol_md: string;
  description: string;
  extra_config: Record<string, unknown>;
};

export const agentImportApi = {
  catalog: (version: ImportVersion) =>
    api
      .get<{ version: string; repo: string; count: number; items: ImportCatalogItem[] }>(
        '/api/agent-import/catalog',
        { params: { version } },
      )
      .then((r) => r.data),
  preview: (version: ImportVersion, path: string) =>
    api
      .post<{ spec: ImportWorkerSpec }>('/api/agent-import/preview', { version, path })
      .then((r) => r.data),
  import: (version: ImportVersion, path: string) =>
    api
      .post<{ ok: boolean; agent_id: string; updated: boolean; capability: string; name: string }>(
        '/api/agent-import',
        { version, path },
      )
      .then((r) => r.data),
};
