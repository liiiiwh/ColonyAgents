/** M2：Project Schedule */

export type ScheduleKind = 'cron' | 'interval' | 'event';

export interface SchedulePublic {
  id: string;
  mission_id: string;
  name: string;
  kind: ScheduleKind;
  expr: string;
  payload_template: Record<string, unknown>;
  enabled: boolean;
  last_fired_at: string | null;
  next_fire_at: string | null;
  last_error: string | null;
  fire_count: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface ScheduleCreateInput {
  name: string;
  kind: ScheduleKind;
  expr: string;
  payload_template?: Record<string, unknown>;
  enabled?: boolean;
}

export type ScheduleUpdateInput = Partial<
  Omit<ScheduleCreateInput, 'name' | 'kind' | 'expr'>
> & {
  name?: string;
  kind?: ScheduleKind;
  expr?: string;
};
