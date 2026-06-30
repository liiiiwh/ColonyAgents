export type ProviderType =
  | 'openai'
  | 'anthropic'
  | 'azure'
  | 'ollama'
  | 'deepseek'
  | 'gemini'
  | 'custom';
export type LLMModelType = 'chat' | 'image' | 'video' | 'embedding' | 'completion';

export interface ProviderPublic {
  id: string;
  name: string;
  provider_type: ProviderType;
  base_url: string | null;
  extra_config: Record<string, unknown>;
  is_enabled: boolean;
  has_api_key: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProviderCreateInput {
  name: string;
  provider_type: ProviderType;
  api_key: string;
  base_url?: string | null;
  extra_config?: Record<string, unknown>;
  is_enabled?: boolean;
}

export interface ProviderUpdateInput {
  name?: string;
  provider_type?: ProviderType;
  api_key?: string;
  base_url?: string | null;
  extra_config?: Record<string, unknown>;
  is_enabled?: boolean;
}

export interface LLMModelPublic {
  id: string;
  provider_id: string;
  model_id: string;
  display_name: string;
  model_type: LLMModelType;
  context_window: number;
  supports_vision: boolean;
  supports_function_calling: boolean;
  is_enabled: boolean;
}

export interface SyncModelsResponse {
  synced: number;
  models: LLMModelPublic[];
}
