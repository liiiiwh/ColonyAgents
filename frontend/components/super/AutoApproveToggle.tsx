'use client';

import { useEffect, useState } from 'react';
import { useTranslation, Trans } from 'react-i18next';
import { ShieldCheck, Zap, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { missionsAdminApi } from '@/lib/api/missionsAdmin';
import { cn } from '@/lib/utils';

/**
 * 「全自动·完全授权」开关（类似 Claude Code 的 auto 模式）。
 * - 关（默认）：super 的每个 request_approval 都等你人工授权——高危/不可逆动作（开处方·下单·删数据·
 *   外部不可逆发布）必须你点确认。
 * - 开：super 自动确认**所有**审批（含高危），完全自主运行。开启=你已授予完全授权、自负全责。
 *
 * 自包含：用 projectId 自己读/写 project.auto_approve，不依赖父组件透传。
 */
export function AutoApproveToggle({
  projectId,
  forcedAuto = false,
}: {
  projectId: string;
  /** System sessions (e.g. the worker-health self-check) always auto-approve regardless of
   *  the project setting — show a read-only "Auto approval" badge instead of the toggle. */
  forcedAuto?: boolean;
}) {
  const { t } = useTranslation();
  const [auto, setAuto] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    missionsAdminApi
      .get(projectId)
      .then((p) => alive && setAuto(Boolean(p.auto_approve)))
      .catch(() => alive && setAuto(false));
    return () => {
      alive = false;
    };
  }, [projectId]);

  const apply = async (next: boolean) => {
    setSaving(true);
    try {
      await missionsAdminApi.update(projectId, { auto_approve: next });
      setAuto(next);
    } catch {
      // 保持原状
    } finally {
      setSaving(false);
      setConfirmOpen(false);
    }
  };

  const onClick = () => {
    if (auto) void apply(false); // 关闭=安全，直接关
    else setConfirmOpen(true); // 开启=危险，先确认
  };

  // System auto-session (e.g. worker-health self-check): always auto, read-only badge.
  if (forcedAuto) {
    return (
      <Button
        size="sm"
        variant="ghost"
        disabled
        title={t('superPanel.autoApproveForcedTooltip')}
        className={cn('gap-1.5 rounded-full border px-3 border-warning/40 bg-warning/10 text-warning opacity-90')}
      >
        <Zap className="h-3.5 w-3.5" />
        {t('superPanel.autoApproveOn')}
      </Button>
    );
  }

  if (auto === null) return null;

  return (
    <>
      <Button
        size="sm"
        variant="ghost"
        disabled={saving}
        onClick={onClick}
        title={auto ? t('superPanel.autoApproveOnTooltip') : t('superPanel.autoApproveOffTooltip')}
        className={cn(
          'gap-1.5 rounded-full border px-3',
          auto
            ? 'border-warning/40 bg-warning/10 text-warning hover:bg-warning/20'
            : 'border-border/60 text-muted-foreground',
        )}
      >
        {saving ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : auto ? (
          <Zap className="h-3.5 w-3.5" />
        ) : (
          <ShieldCheck className="h-3.5 w-3.5" />
        )}
        {auto ? t('superPanel.autoApproveOn') : t('superPanel.autoApproveOff')}
      </Button>

      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)} title={t('superPanel.autoApproveConfirmTitle')}>
        <div className="space-y-3 text-sm text-muted-foreground">
          <p>
            <Trans
              i18nKey="superPanel.autoApproveConfirmBody1"
              components={{ strong1: <strong className="text-foreground" />, strong2: <strong className="text-warning" /> }}
            />
          </p>
          <p>
            <Trans
              i18nKey="superPanel.autoApproveConfirmBody2"
              components={{ strong1: <strong className="text-foreground" /> }}
            />
          </p>
          <div className="flex justify-end gap-2 pt-1">
            <Button size="sm" variant="outline" disabled={saving} onClick={() => setConfirmOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              size="sm"
              disabled={saving}
              onClick={() => void apply(true)}
              className="bg-warning text-background hover:bg-warning/90"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : t('superPanel.autoApproveConfirmCta')}
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}
