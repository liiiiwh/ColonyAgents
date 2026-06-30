'use client';

/**
 * Q7-mismatch redirect card.
 *
 * A Super calls emit_redirect_suggestion → SSE pushes a redirect_suggestion
 * event → this card renders inline in the chat stream with the options:
 *   1) Jump to an existing Super → POST /api/missions { super_agent_id, name, goal_hint=original }
 *   2) Ask the Builder → navigate to /super/builder (the Builder mission workbench)
 *   3) Continue in this mission anyway → close the card, the Super keeps collecting context
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useRouter } from 'next/navigation';
import {
  AlertCircle,
  Bot,
  Loader2,
  PenLine,
  Sparkles,
} from 'lucide-react';
import { missionsApi } from '@/lib/api/missions';
import { errMessage } from '@/lib/errors';

export type RedirectCandidate = {
  super_id?: string;
  name: string;
  fit_hint?: string;
  description?: string;
};

export type RedirectSuggestionData = {
  reason: string;
  candidates: RedirectCandidate[];
  original_message: string;
};

export function RedirectSuggestionCard({
  data,
  onResolved,
}: {
  data: RedirectSuggestionData;
  onResolved?: (action: 'redirected' | 'continued' | 'cancelled') => void;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [resolved, setResolved] = useState<string | null>(null);

  async function jumpToSuper(c: RedirectCandidate) {
    if (!c.super_id) return;
    setBusy(c.name);
    setErr(null);
    try {
      const res = await missionsApi.create({
        super_agent_id: c.super_id,
        name: data.original_message.slice(0, 24) || t('missionCards.redirectDefaultName'),
        goal_hint: data.original_message,
      });
      if (res.ok && res.mission) {
        setResolved(t('missionCards.redirectJumpedTo', { name: c.name }));
        onResolved?.('redirected');
        router.push(`/mission/${res.mission.slug}`);
      } else {
        setErr(res.error || t('missionCards.redirectFailed'));
      }
    } catch (e) {
      setErr(errMessage(e));
    } finally {
      setBusy(null);
    }
  }

  function jumpToBuilder() {
    setResolved(t('missionCards.redirectGoBuilder'));
    onResolved?.('redirected');
    router.push(`/super/builder`);
  }

  function continueHere() {
    setResolved(t('missionCards.redirectContinue'));
    onResolved?.('continued');
  }

  if (resolved) {
    return (
      <div className="my-2 max-w-3xl border border-success/40 bg-success/10 rounded-lg p-3 text-xs text-success">
        ✓ {t('missionCards.redirectChose', { choice: resolved })}
      </div>
    );
  }

  return (
    <div className="my-2 max-w-3xl border-2 border-warning/40 bg-warning/10 rounded-lg p-3">
      <div className="flex items-start gap-2 mb-2">
        <AlertCircle className="w-4 h-4 text-warning mt-0.5" />
        <div className="flex-1">
          <div className="font-semibold text-sm text-foreground">
            ⚠️ {t('missionCards.redirectNotFit')}
          </div>
          <p className="text-xs text-muted-foreground mt-1">{data.reason}</p>
        </div>
      </div>

      {data.original_message && (
        <div className="text-[11px] text-muted-foreground bg-muted p-2 rounded my-2 italic">
          {t('missionCards.redirectYourMessage', { message: data.original_message })}
        </div>
      )}

      <p className="text-xs font-semibold mt-3 mb-1.5 text-foreground">
        {t('missionCards.redirectRecommended')}
      </p>

      <div className="space-y-1.5">
        {data.candidates.map((c, i) => (
          <button
            key={i}
            disabled={busy !== null || !c.super_id}
            onClick={() => void jumpToSuper(c)}
            className="w-full text-left bg-card border border-border hover:border-primary rounded p-2 transition disabled:opacity-50"
          >
            <div className="flex items-center gap-2">
              <Bot className="w-3.5 h-3.5 text-primary" />
              <span className="font-semibold text-xs text-foreground">{c.name}</span>
              {busy === c.name && <Loader2 className="w-3 h-3 animate-spin ml-auto" />}
              {busy !== c.name && (
                <span className="ml-auto text-[10px] text-primary">{t('missionCards.redirectJump')}</span>
              )}
            </div>
            {c.fit_hint && (
              <p className="text-[11px] text-muted-foreground mt-0.5">{c.fit_hint}</p>
            )}
          </button>
        ))}

        <button
          disabled={busy !== null}
          onClick={jumpToBuilder}
          className="w-full text-left bg-card border border-border hover:border-warning/60 rounded p-2 transition disabled:opacity-50"
        >
          <div className="flex items-center gap-2">
            <Sparkles className="w-3.5 h-3.5 text-warning" />
            <span className="font-semibold text-xs text-foreground">🏗️ {t('missionCards.redirectAskBuilder')}</span>
            <span className="ml-auto text-[10px] text-warning">{t('missionCards.redirectJump')}</span>
          </div>
          <p className="text-[11px] text-muted-foreground mt-0.5">{t('missionCards.redirectNoneFit')}</p>
        </button>

        <button
          disabled={busy !== null}
          onClick={continueHere}
          className="w-full text-left bg-card border border-border hover:border-accent rounded p-2 transition disabled:opacity-50"
        >
          <div className="flex items-center gap-2">
            <PenLine className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="font-semibold text-xs text-foreground">📝 {t('missionCards.redirectTryHere')}</span>
          </div>
        </button>
      </div>

      {err && (
        <div className="mt-2 text-xs text-destructive bg-destructive/10 p-1.5 rounded">{err}</div>
      )}
    </div>
  );
}
