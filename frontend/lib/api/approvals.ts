import { api } from '@/lib/api';

export interface PendingApprovalPublic {
  id: string;
  mission_id: string;
  request_id: string;
  thread_key: string | null;
  agent_node_name: string | null;
  title: string;
  message: string;
  options: string[];
  status: 'pending' | 'decided' | 'expired' | 'cancelled';
  decided_option: string | null;
  decided_by: string | null;
  decided_at: string | null;
  clawbot_account_id: string | null;
  clawbot_user_ids: string[] | null;
  clawbot_sent_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClawbotAccountPublic {
  id: string;
  name: string;
  description: string;
  base_url: string;
  ilink_bot_id: string;
  ilink_user_id: string | null;
  reviewers: string[];
  is_enabled: boolean;
  last_polled_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface OutboxItemPublic {
  id: string;
  account_id: string;
  mission_id: string | null;
  target_wechat_id: string;
  kind: 'notification' | 'approval_resend';
  content: string;
  status: 'pending' | 'sent' | 'cancelled';
  attempt_count: number;
  last_error: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MissionApprovalChannelPublic {
  mission_id: string;
  clawbot_account_id: string | null;
  reviewer_wechat_ids: string[];
  enabled: boolean;
}

export const approvalsApi = {
  listForProject: (projectId: string, onlyPending = true) =>
    api
      .get<PendingApprovalPublic[]>(
        `/api/missions/${projectId}/pending-approvals`,
        { params: { only_pending: onlyPending } },
      )
      .then((r) => r.data),
  decide: (requestId: string, option: string, decidedBy = 'observe') =>
    api
      .post<PendingApprovalPublic>(`/api/pending-approvals/${requestId}/decide`, {
        option,
        decided_by: decidedBy,
      })
      .then((r) => r.data),
};

export const clawbotApi = {
  listAccounts: () =>
    api.get<ClawbotAccountPublic[]>('/api/clawbot-accounts').then((r) => r.data),
  listOutbox: (accountId: string) =>
    api
      .get<OutboxItemPublic[]>(`/api/clawbot-accounts/${accountId}/outbox`)
      .then((r) => r.data),
  startLogin: () =>
    api
      .post<{
        qrcode_session: string;
        qrcode_img_url: string;
        qrcode_inline_img_url: string;
      }>('/api/clawbot-accounts/login/start')
      .then((r) => r.data),
  confirmLogin: (body: {
    name: string;
    description?: string;
    reviewers?: string[];
    qrcode_session: string;
    max_poll_seconds?: number;
  }) =>
    api
      .post<ClawbotAccountPublic>('/api/clawbot-accounts/login/confirm', body)
      .then((r) => r.data),
  updateAccount: (
    id: string,
    body: {
      name?: string;
      description?: string;
      reviewers?: string[];
      is_enabled?: boolean;
    },
  ) =>
    api
      .put<ClawbotAccountPublic>(`/api/clawbot-accounts/${id}`, body)
      .then((r) => r.data),
  deleteAccount: (id: string) => api.delete(`/api/clawbot-accounts/${id}`),
  getProjectChannel: (projectId: string) =>
    api
      .get<MissionApprovalChannelPublic | null>(
        `/api/missions/${projectId}/approval-channel`,
      )
      .then((r) => r.data),
  upsertProjectChannel: (
    projectId: string,
    body: {
      clawbot_account_id?: string | null;
      reviewer_wechat_ids?: string[];
      enabled?: boolean;
    },
  ) =>
    api
      .put<MissionApprovalChannelPublic>(
        `/api/missions/${projectId}/approval-channel`,
        body,
      )
      .then((r) => r.data),
  deleteProjectChannel: (projectId: string) =>
    api.delete(`/api/missions/${projectId}/approval-channel`),
};
