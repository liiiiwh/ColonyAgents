/** 模型内置思考档位：off（默认，最省 token / 最快首 token）/ low / medium / high。 */
export type ThinkingLevel = 'off' | 'low' | 'medium' | 'high';

export interface AgentSkillBinding {
  skill_id: string;
  config: Record<string, unknown>;
  /** 后端在 AgentDetail 里展开的关联 skill（list 接口可能不带） */
  skill?: { slug?: string; name?: string } | null;
}

export interface AgentMCPBinding {
  mcp_server_id: string;
  tool_filter: string[] | null;
}

export type AuxModelRole =
  | 'chat'
  | 'vision'
  | 'image'
  | 'video'
  | 'embedding'
  | 'rerank'
  | 'tts'
  | 'stt'
  | 'custom';

/**
 * Agent / Skill 功能分类（与后端 AgentCategory / SkillCategory 同枚举）。
 * 管理后台按 category 分组渲染。
 */
export type AgentCategory =
  | 'builder'
  | 'installer'
  | 'tester'
  | 'worker.web'
  | 'worker.data'
  | 'worker.io'
  | 'worker.creative'
  | 'utility'
  | 'custom';

/** 分组渲染时使用的中文标签 + 排序顺序。 */
export const AGENT_CATEGORY_LABELS: Record<AgentCategory, string> = {
  builder: 'Builder（编排）',
  installer: 'Installer（技能安装）',
  tester: 'Tester（测试）',
  'worker.web': 'Worker · Web（抓取 / 网络）',
  'worker.data': 'Worker · Data（数据处理）',
  'worker.io': 'Worker · IO（文件 / 通知 / 邮件）',
  'worker.creative': 'Worker · Creative（生成）',
  utility: 'Utility（辅助）',
  custom: 'Custom（未分类）',
};

export const AGENT_CATEGORY_ORDER: AgentCategory[] = [
  'builder',
  'installer',
  'tester',
  'worker.web',
  'worker.data',
  'worker.io',
  'worker.creative',
  'utility',
  'custom',
];

export interface AgentAuxModelBinding {
  model_id: string;
  role: AuxModelRole;
  alias: string | null;
  config: Record<string, unknown>;
}

export interface AgentModelInfo {
  id: string;
  provider_id: string;
  model_id: string;
  display_name: string;
  model_type: 'chat' | 'image' | 'video' | 'embedding' | 'completion';
  context_window: number;
  supports_vision: boolean;
  supports_function_calling: boolean;
}

/** v4: Agent 角色——admin UI 按 kind 分 Super / Worker 两类 */
export type AgentKind = 'super' | 'worker' | 'builder' | 'installer' | 'tester' | 'utility' | null;

export interface AgentPublic {
  id: string;
  name: string;
  description: string;
  category: AgentCategory;
  /** v4 · super / worker / builder / installer / tester / utility（NULL = 未分类老 agent） */
  kind?: AgentKind;
  /** v4 · worker 的 capability slug（如 'xhs_ops'），super 留空 */
  capability?: string | null;
  /** super 的 URL slug（如 Builder Supervisor='builder'）；worker 通常为 null */
  slug?: string | null;
  /** ADR-017 · NULL = 用平台默认模型（运行时按 kind 解析） */
  model_id: string | null;
  soul_md: string;
  protocol_md: string;
  domain_memory_md: string;
  max_iterations: number;
  temperature: number;
  /** 单次 LLM 调用最大输出 token（LiteLLM max_tokens）。默认 5000；命中上限时 ResilientChatLiteLLM 会自动续写（仅纯文本，tool_call 被截会抛错） */
  max_output_tokens: number;
  extra_config: Record<string, unknown>;
  is_enabled: boolean;
  /** ADR-015 · 系统内置对象（不可删除，UI 隐藏删除按钮） */
  is_system?: boolean;
  /** 该 Agent 的 workspace_write 是否视作「交付物」（上 S3、覆盖写、前端显示） */
  produces_deliverable: boolean;
  /** 【旧字段，保留兼容】请改用 thinking_level */
  enable_thinking: boolean;
  /** 模型内置思考档位（off/low/medium/high，默认 off）；_build_llm 按主模型家族映射成各家具体参数 */
  thinking_level: ThinkingLevel;
  created_at: string;
  updated_at: string;
}

export interface AgentDetail extends AgentPublic {
  skill_bindings: AgentSkillBinding[];
  mcp_bindings: AgentMCPBinding[];
  aux_model_bindings: AgentAuxModelBinding[];
  model: AgentModelInfo | null;
}

export interface AgentCreateInput {
  name: string;
  description?: string;
  category?: AgentCategory;
  model_id?: string | null;
  soul_md?: string;
  protocol_md?: string;
  domain_memory_md?: string;
  max_iterations?: number;
  temperature?: number;
  max_output_tokens?: number;
  is_enabled?: boolean;
  produces_deliverable?: boolean;
  enable_thinking?: boolean;
  thinking_level?: ThinkingLevel;
  /** ADR-026 D4 · per-super 配置；含 mission_default_auto_approve 等 key */
  extra_config?: Record<string, unknown>;
}

export type AgentUpdateInput = Partial<AgentCreateInput>;

export interface AgentTestResponse {
  ok: boolean;
  output: string | null;
  tools_loaded: number;
  error: string | null;
}
