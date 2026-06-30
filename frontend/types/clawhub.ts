/** M6: ClawHub 远程 Skill 类型。 */

export interface ClawhubSearchResp {
  ok: boolean;
  query: string;
  /** 后端透传 ClawHub `results` / `items` 字段；最小约定字段如下 */
  results: ClawhubSearchHit[];
}

export interface ClawhubSearchHit {
  slug: string;
  displayName?: string;
  summary?: string;
  owner?: { handle?: string; displayName?: string };
  latestVersion?: string;
  // 其它原始字段保留
  [key: string]: unknown;
}

export interface ClawhubInspectResp {
  ok: boolean;
  slug: string;
  version: string;
  blocked: boolean;
  high_risk_tags: string[];
  skill: Record<string, unknown>;
  security: Record<string, unknown>;
}

export interface ClawhubInstallReq {
  slug: string;
  version?: string;
  mission_id?: string;
  force_high_risk?: boolean;
}

export interface ClawhubInstallResp {
  ok: boolean;
  install_id?: string;
  local_skill_id?: string;
  runtime_kind?: string;
  install_dir?: string;
  entrypoint?: string;
  capability_tags?: string[];
  error?: string;
  needs_approval?: boolean;
  blocked?: boolean;
}

export interface InstalledItem {
  install_id: string;
  slug: string;
  version: string;
  runtime_kind: string;
  install_dir: string;
  capability_tags: string[];
  local_skill_id: string | null;
  installed_at: string;
}
