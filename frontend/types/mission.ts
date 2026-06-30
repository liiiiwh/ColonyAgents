export type MissionStatus = 'draft' | 'active' | 'archived';

/** M1：Project 运行态（与 MissionStatus 正交） */
export type MissionRuntimeStatus =
  | 'stopped'
  | 'starting'
  | 'running'
  | 'stopping'
  | 'error';

export type MissionLifecycleAction =
  | 'start'
  | 'stop'
  | 'restart'
  | 'clear_memory'
  | 'run_once';

export interface MissionRuntimePublic {
  mission_id: string;
  status: MissionRuntimeStatus;
  started_at: string | null;
  stopped_at: string | null;
  last_heartbeat_at: string | null;
  last_error: string | null;
  current_step: string | null;
  run_count: number;
}

export interface MissionPublic {
  id: string;
  name: string;
  description: string;
  slug: string;
  status: MissionStatus;
  runtime_status: MissionRuntimeStatus;
  lifecycle_status?: string;
  is_system?: boolean;
  supervisor_agent_id: string;
  auto_approve: boolean;
  context_compression_threshold: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export type MissionDetail = MissionPublic;

export interface MissionCreateInput {
  name: string;
  description?: string;
  slug: string;
  supervisor_agent_id: string;
  auto_approve?: boolean;
  context_compression_threshold?: number;
}

export type MissionUpdateInput = Partial<Omit<MissionCreateInput, 'slug'>>;

export interface MissionActivationResponse {
  ok: boolean;
  status: MissionStatus;
  issues: string[];
}
