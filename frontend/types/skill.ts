export type SkillType = 'instruction' | 'tool_builtin';
export type MCPServerType = 'stdio' | 'http';

export interface SkillPublic {
  id: string;
  name: string;
  slug: string;
  description: string;
  description_en: string | null;
  version: string;
  skill_type: SkillType;
  content_md: string;
  builtin_ref: string | null;
  config_schema: Record<string, unknown>;
  is_enabled: boolean;
  is_builtin: boolean;
  created_at: string;
  updated_at: string;
}

export interface SkillCreateInput {
  name: string;
  slug: string;
  description?: string;
  description_en?: string | null;
  version?: string;
  skill_type: SkillType;
  content_md?: string;
  builtin_ref?: string | null;
  is_enabled?: boolean;
}

export interface SkillUpdateInput {
  name?: string;
  description?: string;
  description_en?: string | null;
  version?: string;
  content_md?: string;
  is_enabled?: boolean;
}

export interface MCPServerPublic {
  id: string;
  name: string;
  description: string;
  server_type: MCPServerType;
  command: string[] | null;
  env_vars: Record<string, string> | null;
  url: string | null;
  headers: Record<string, string> | null;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface MCPServerCreateInput {
  name: string;
  description?: string;
  server_type: MCPServerType;
  command?: string[] | null;
  env_vars?: Record<string, string> | null;
  url?: string | null;
  headers?: Record<string, string> | null;
  is_enabled?: boolean;
}

export interface MCPToolInfo {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface MCPTestResponse {
  reachable: boolean;
  error: string | null;
  tools: MCPToolInfo[];
}
