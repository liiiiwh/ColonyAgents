'use client';

/**
 * v5 · Inline 审批卡片
 *
 * super 调 request_approval → 后端通过 event_bus 推 approval_request → 前端在 chat 流
 * 渲染本卡片；用户点按钮 → POST /api/pending-approvals/{id}/decide → bus 推 resolved
 * → 卡片自动 flip 成 "✅ 已通过 / ❌ 拒绝 / ⚙️ 改参数"
 */
import { useState } from 'react';
import { Check, X, AlertCircle, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { MarkdownViewer } from '@/components/ui/markdown-viewer';
import { api } from '@/lib/api';
import { errMessage } from '@/lib/errors';

export type ApprovalCardData = {
  request_id: string;
  title: string;
  message: string;
  options: string[];
  created_at?: string;  // v6 fix · 按 created_at 在消息流时间序混编渲染
  thread_key?: string;  // ADR-024 #3 · 审批所属线程（默认 main），前端按当前线程过滤渲染
  status?: string;      // ADR-024 #1 · pending / decided（读时合并真相源）
  resolution?: {
    option: string;
    decided_by: string;
    via: 'ui' | 'wechat' | 'auto' | 'chat' | 'inline';
  };
};

export function ApprovalCard({
  data,
  onResolved,
}: {
  data: ApprovalCardData;
  onResolved?: (option: string) => void;
}) {
  const { t } = useTranslation();
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // 已决/已关闭 → 不再可点（修刷新后幽灵复活成可点 + 孤儿审批卡可点）
  const resolved = !!data.resolution || data.status === 'decided' || data.status === 'closed';
  const closedNoResolution = !data.resolution && data.status === 'closed';
  // 被更新的方案取代：仍显示按钮但全部 disabled（防误点已被取代的老审批卡）
  const superseded = data.status === 'superseded';

  async function decide(option: string) {
    setSubmitting(option);
    setErr(null);
    try {
      await api.post(`/api/pending-approvals/${data.request_id}/decide`, {
        option,
        decided_by: 'inline-card',
      });
      onResolved?.(option);
    } catch (e) {
      setErr(errMessage(e));
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <div className="border-2 border-warning/40 bg-warning/10 rounded-lg p-3 my-2 max-w-3xl">
      <div className="flex items-start gap-2 mb-2">
        <AlertCircle className="w-4 h-4 text-warning mt-0.5" />
        <div className="flex-1">
          <div className="font-semibold text-sm text-foreground">
            {t('chat.approvalRequest')} · {data.title}
          </div>
          {data.message && (
            <MarkdownViewer
              content={data.message}
              className="text-xs text-muted-foreground mt-1"
            />
          )}
        </div>
      </div>

      {resolved ? (
        closedNoResolution ? (
          <div className="text-xs px-2 py-1.5 rounded bg-muted text-muted-foreground">
            ⏹️ {t('chat.approvalClosed')}
          </div>
        ) : (
          <div
            className={`text-xs px-2 py-1.5 rounded ${
              data.resolution?.via === 'wechat'
                ? 'bg-primary/10 text-primary'
                : 'bg-success/10 text-success'
            }`}
          >
            {(data.resolution?.option ?? data.options[0]) === data.options[0] ? '✅' : '❌'}{' '}
            {t('chat.approvalResolved', {
              option: data.resolution?.option ?? '已决定',
              via: data.resolution?.via ?? 'ui',
              decidedBy: data.resolution?.decided_by
                ? ` · ${data.resolution.decided_by}`
                : '',
            })}
          </div>
        )
      ) : (
        <div>
          {superseded && (
            <div className="text-[11px] text-muted-foreground mb-1.5">⏹️ {t('chat.approvalSuperseded')}</div>
          )}
          <div className="flex flex-wrap gap-2 mt-1">
            {data.options.map((opt) => (
              <Button
                key={opt}
                size="sm"
                variant={opt === data.options[0] ? 'default' : 'outline'}
                disabled={submitting !== null || superseded}
                onClick={() => decide(opt)}
              >
                {submitting === opt ? (
                  <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
                ) : opt === data.options[0] ? (
                  <Check className="w-3.5 h-3.5 mr-1" />
                ) : (
                  <X className="w-3.5 h-3.5 mr-1" />
                )}
                {opt}
              </Button>
            ))}
          </div>
        </div>
      )}

      {err && (
        <div className="mt-2 text-xs text-destructive bg-destructive/10 p-1.5 rounded">{err}</div>
      )}

      <div className="mt-1.5 text-[10px] text-muted-foreground/70">
        request_id: <code>{data.request_id.slice(0, 8)}…</code>
      </div>
    </div>
  );
}
