'use client';

/**
 * 审核渠道管理页（当前仅微信）：
 * - 列已绑定的账号；扫码登录新账号；改 reviewers / 启停
 * - mission 关联（每个 worker mission 选用哪个账号 + mission 专属审批人）放在 mission 编辑页
 * - 顶部标注：其它渠道后续接入
 */

import { useEffect, useState } from 'react';
import { CheckCircle2, Plus, QrCode, Trash2, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useConfirm } from '@/components/providers/ConfirmProvider';
import {
  clawbotApi,
  type ClawbotAccountPublic,
  type OutboxItemPublic,
} from '@/lib/api/approvals';
import { extractErrorMessage } from '@/lib/utils';

export default function ClawbotPage() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [accounts, setAccounts] = useState<ClawbotAccountPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [loginOpen, setLoginOpen] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      setAccounts(await clawbotApi.listAccounts());
    } catch (e) {
      setErr(extractErrorMessage(e, t('approvals.loadFailed')));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void refresh();
  }, []);

  async function handleDelete(acc: ClawbotAccountPublic) {
    if (!(await confirm({ message: t('approvals.deleteConfirm', { name: acc.name }), danger: true }))) return;
    await clawbotApi.deleteAccount(acc.id);
    await refresh();
  }

  async function handleToggle(acc: ClawbotAccountPublic) {
    await clawbotApi.updateAccount(acc.id, { is_enabled: !acc.is_enabled });
    await refresh();
  }

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <header className="flex items-center justify-between border-b border-border pb-5">
        <div>
          <h1 className="text-2xl font-medium tracking-tight text-foreground">
            {t('approvals.title')}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">{t('approvals.subtitle')}</p>
        </div>
        <Button onClick={() => setLoginOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          {t('approvals.addAccount')}
        </Button>
      </header>

      {/* 渠道页签：当前仅微信，其它后续接入 */}
      <div className="mt-5 flex items-center gap-2">
        <span className="rounded-lg bg-accent px-3 py-1.5 text-[13px] font-medium text-foreground">
          {t('approvals.wechat')}
        </span>
        <span className="rounded-lg border border-dashed border-border px-3 py-1.5 text-[12.5px] text-muted-foreground">
          {t('approvals.comingSoon')}
        </span>
      </div>

      {err && (
        <p className="mt-4 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>
      )}

      <section className="mt-6">
        {loading ? (
          <p className="p-10 text-center text-sm text-muted-foreground">{t('common.loading')}</p>
        ) : accounts.length === 0 ? (
          <p className="p-10 text-center text-sm text-muted-foreground">{t('approvals.empty')}</p>
        ) : (
          <div className="space-y-3">
            {accounts.map((a) => (
              <AccountCard
                key={a.id}
                acc={a}
                onDelete={() => handleDelete(a)}
                onToggle={() => handleToggle(a)}
                onUpdated={refresh}
              />
            ))}
          </div>
        )}
      </section>

      <LoginDialog
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onDone={() => {
          setLoginOpen(false);
          void refresh();
        }}
      />
    </div>
  );
}

function AccountCard({
  acc,
  onDelete,
  onToggle,
  onUpdated,
}: {
  acc: ClawbotAccountPublic;
  onDelete: () => void;
  onToggle: () => void;
  onUpdated: () => void;
}) {
  const { t } = useTranslation();
  const [editingReviewers, setEditingReviewers] = useState(false);
  const [reviewersText, setReviewersText] = useState(acc.reviewers.join('\n'));
  const [outbox, setOutbox] = useState<OutboxItemPublic[]>([]);
  const [showOutbox, setShowOutbox] = useState(false);
  useEffect(() => {
    clawbotApi
      .listOutbox(acc.id)
      .then(setOutbox)
      .catch(() => setOutbox([]));
  }, [acc.id]);

  async function saveReviewers() {
    const list = reviewersText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
    await clawbotApi.updateAccount(acc.id, { reviewers: list });
    setEditingReviewers(false);
    onUpdated();
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-3">
        <Badge variant={acc.is_enabled ? 'success' : 'secondary'}>
          {acc.is_enabled ? t('approvals.enabled') : t('approvals.disabled')}
        </Badge>
        <h3 className="text-base font-medium text-foreground">{acc.name}</h3>
        {acc.description && (
          <span className="text-xs text-muted-foreground">— {acc.description}</span>
        )}
        <span className="ml-auto font-mono text-[11px] text-muted-foreground/70">
          {acc.ilink_bot_id.slice(0, 12)}…
        </span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground md:grid-cols-4">
        <div>
          <span className="text-muted-foreground/70">{t('approvals.scannedBy')}：</span>
          <span className="font-mono">{acc.ilink_user_id ?? '—'}</span>
        </div>
        <div>
          <span className="text-muted-foreground/70">{t('approvals.baseUrl')}：</span>
          <span className="font-mono">{acc.base_url}</span>
        </div>
        <div>
          <span className="text-muted-foreground/70">{t('approvals.lastHeartbeat')}：</span>
          <span className="font-mono">
            {acc.last_polled_at ? new Date(acc.last_polled_at).toLocaleString() : '—'}
          </span>
        </div>
        <div>
          <span className="text-muted-foreground/70">{t('approvals.lastError')}：</span>
          <span className={acc.last_error ? 'font-mono text-destructive' : 'text-muted-foreground/70'}>
            {acc.last_error ?? '—'}
          </span>
        </div>
      </div>

      <div className="mt-3">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">
            {t('approvals.reviewers')}（{acc.reviewers.length}）：
          </span>
          {!editingReviewers && (
            <Button size="sm" variant="ghost" onClick={() => setEditingReviewers(true)}>
              {t('common.edit')}
            </Button>
          )}
        </div>
        {editingReviewers ? (
          <div className="mt-2 space-y-2">
            <Textarea
              value={reviewersText}
              onChange={(e) => setReviewersText(e.target.value)}
              placeholder={t('approvals.reviewersPlaceholder')}
              rows={4}
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={saveReviewers}>
                {t('common.save')}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setReviewersText(acc.reviewers.join('\n'));
                  setEditingReviewers(false);
                }}
              >
                {t('common.cancel')}
              </Button>
            </div>
          </div>
        ) : (
          <ul className="mt-1 list-disc pl-5 text-xs text-foreground/80">
            {acc.reviewers.length === 0 ? (
              <li className="list-none text-muted-foreground/70">{t('approvals.noReviewers')}</li>
            ) : (
              acc.reviewers.map((r) => (
                <li key={r} className="font-mono">
                  {r}
                </li>
              ))
            )}
          </ul>
        )}
      </div>

      {outbox.length > 0 && (
        <div className="mt-3 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2">
          <div className="flex items-center gap-2 text-xs">
            <span className="font-medium text-warning">
              {t('approvals.backlog', { count: outbox.length })}
            </span>
            <span className="text-muted-foreground">{t('approvals.backlogHint')}</span>
            <button
              type="button"
              className="ml-auto text-[11px] text-warning underline"
              onClick={() => setShowOutbox((v) => !v)}
            >
              {showOutbox ? t('approvals.collapse') : t('approvals.expand')}
            </button>
          </div>
          {showOutbox && (
            <ul className="mt-2 space-y-2">
              {outbox.map((o) => (
                <li key={o.id} className="rounded-lg border border-border bg-card p-2 text-[11px]">
                  <div className="flex gap-2">
                    <Badge variant={o.kind === 'approval_resend' ? 'warning' : 'secondary'}>
                      {o.kind === 'approval_resend'
                        ? t('approvals.approvalResend')
                        : t('approvals.notification')}
                    </Badge>
                    <span className="font-mono">{o.target_wechat_id}</span>
                    <span className="ml-auto text-muted-foreground">
                      {t('approvals.attempts', { count: o.attempt_count })} ·{' '}
                      {new Date(o.created_at).toLocaleString()}
                    </span>
                  </div>
                  <pre className="mt-1 whitespace-pre-wrap text-foreground/80">
                    {o.content.slice(0, 300)}
                    {o.content.length > 300 && '…'}
                  </pre>
                  {o.last_error && (
                    <p className="mt-1 text-destructive">
                      {t('approvals.lastError')}: {o.last_error.slice(0, 200)}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="mt-3 flex gap-2">
        <Button size="sm" variant="outline" onClick={onToggle}>
          {acc.is_enabled ? (
            <>
              <XCircle className="mr-2 h-3.5 w-3.5" />
              {t('approvals.disable')}
            </>
          ) : (
            <>
              <CheckCircle2 className="mr-2 h-3.5 w-3.5" />
              {t('approvals.enable')}
            </>
          )}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDelete}>
          <Trash2 className="mr-2 h-3.5 w-3.5 text-destructive" />
          {t('common.delete')}
        </Button>
      </div>
    </div>
  );
}

function LoginDialog({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [reviewersText, setReviewersText] = useState('');
  const [qrSession, setQrSession] = useState('');
  const [qrImgUrl, setQrImgUrl] = useState('');
  const [qrInlineImgUrl, setQrInlineImgUrl] = useState('');
  const [phase, setPhase] = useState<'idle' | 'waiting-scan' | 'confirming' | 'done' | 'error'>(
    'idle',
  );
  const [err, setErr] = useState<string | null>(null);

  async function handleStart() {
    if (!name.trim()) {
      setErr(t('approvals.nameRequired'));
      return;
    }
    setErr(null);
    try {
      const { qrcode_session, qrcode_img_url, qrcode_inline_img_url } =
        await clawbotApi.startLogin();
      setQrSession(qrcode_session);
      setQrImgUrl(qrcode_img_url);
      setQrInlineImgUrl(qrcode_inline_img_url || '');
      setPhase('waiting-scan');
    } catch (e) {
      setErr(extractErrorMessage(e, t('approvals.qrFailedErr')));
      setPhase('error');
    }
  }

  async function handleConfirm() {
    setPhase('confirming');
    setErr(null);
    const reviewers = reviewersText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      await clawbotApi.confirmLogin({
        name: name.trim(),
        description: description.trim(),
        reviewers,
        qrcode_session: qrSession,
        max_poll_seconds: 240,
      });
      setPhase('done');
      onDone();
    } catch (e) {
      setErr(extractErrorMessage(e, t('approvals.confirmFailed')));
      setPhase('error');
    }
  }

  function reset() {
    setName('');
    setDescription('');
    setReviewersText('');
    setQrSession('');
    setQrImgUrl('');
    setQrInlineImgUrl('');
    setPhase('idle');
    setErr(null);
    onClose();
  }

  if (!open) return null;
  return (
    <Dialog open={open} onClose={reset} title={t('approvals.dialogTitle')}>
      <div className="space-y-4 p-1">
        {phase === 'idle' && (
          <>
            <div className="space-y-2">
              <Label>{t('approvals.accountName')}</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="ops-bot-A" />
            </div>
            <div className="space-y-2">
              <Label>{t('approvals.note')}</Label>
              <Input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={t('approvals.notePlaceholder')}
              />
            </div>
            <Button onClick={handleStart} disabled={!name.trim()}>
              <QrCode className="mr-2 h-3.5 w-3.5" />
              {t('approvals.pullQr')}
            </Button>
          </>
        )}
        {phase === 'waiting-scan' && (
          <>
            <p className="text-xs text-muted-foreground">{t('approvals.scanHint')}</p>
            <div className="flex flex-col items-center gap-2 rounded-lg border border-border bg-card p-4">
              {qrInlineImgUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={qrInlineImgUrl}
                  alt="WeChat login QR"
                  className="h-[280px] w-[280px]"
                />
              ) : (
                <p className="text-xs text-muted-foreground">{t('approvals.qrFailed')}</p>
              )}
              <a
                href={qrImgUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="break-all text-center font-mono text-[10.5px] text-primary hover:underline"
              >
                {qrImgUrl}
              </a>
            </div>
            <div className="space-y-2">
              <Label>{t('approvals.reviewersOptional')}</Label>
              <Textarea
                rows={3}
                value={reviewersText}
                onChange={(e) => setReviewersText(e.target.value)}
                placeholder="user-1@im.wechat&#10;user-2@im.wechat"
              />
            </div>
            <Button onClick={handleConfirm}>{t('approvals.scanned')}</Button>
          </>
        )}
        {phase === 'confirming' && (
          <p className="text-sm text-foreground">{t('approvals.confirming')}</p>
        )}
        {phase === 'done' && <p className="text-sm text-success">{t('approvals.bound')}</p>}
        {err && (
          <p className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>
        )}
        <div className="flex justify-end">
          <Button variant="ghost" onClick={reset}>
            {t('common.close')}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
