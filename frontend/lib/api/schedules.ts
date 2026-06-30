import { api } from '@/lib/api';
import type {
  ScheduleCreateInput,
  SchedulePublic,
  ScheduleUpdateInput,
} from '@/types/schedule';

export const schedulesApi = {
  list: (projectId: string) =>
    api
      .get<SchedulePublic[]>(`/api/missions/${projectId}/schedules`)
      .then((r) => r.data),
  create: (projectId: string, body: ScheduleCreateInput) =>
    api
      .post<SchedulePublic>(`/api/missions/${projectId}/schedules`, body)
      .then((r) => r.data),
  update: (projectId: string, scheduleId: string, body: ScheduleUpdateInput) =>
    api
      .put<SchedulePublic>(
        `/api/missions/${projectId}/schedules/${scheduleId}`,
        body,
      )
      .then((r) => r.data),
  delete: (projectId: string, scheduleId: string) =>
    api.delete(`/api/missions/${projectId}/schedules/${scheduleId}`),
  /** 手动触发一次（不影响下次自动 fire） */
  fire: (projectId: string, scheduleId: string) =>
    api
      .post<SchedulePublic>(
        `/api/missions/${projectId}/schedules/${scheduleId}/fire`,
      )
      .then((r) => r.data),
  /** webhook：触发所有 enabled & kind='event' & expr=eventName 的 schedule */
  fireEvent: (
    projectId: string,
    eventName: string,
    payload: Record<string, unknown> = {},
  ) =>
    api
      .post<SchedulePublic[]>(`/api/missions/${projectId}/events/${eventName}`, {
        payload,
      })
      .then((r) => r.data),
};
