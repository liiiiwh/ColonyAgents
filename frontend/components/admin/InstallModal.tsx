'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { AxiosError } from 'axios';
import { useTranslation } from 'react-i18next';
import { ArrowRight, Languages, Plug, Rocket } from 'lucide-react';
import { Dialog } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { systemSettingsApi } from '@/lib/api/systemSettings';
import { providersApi } from '@/lib/api/providers';
import { setLocale } from '@/lib/i18n';
import type { LLMModelPublic } from '@/types/provider';

/**
 * ADR-016 / ADR-019 · Onboarding modal — a MANDATORY gate while is_install=0:
 *  - step "language"  → pick platform language (en/zh). Sets the system agents' language
 *    (D2) + the default UI language. Required.
 *  - step "provider"  → no chat model yet → "add an LLM provider" (button → /admin/providers)
 *  - step "models"    → pick default supervisor/worker models → install (seeds the Builder +
 *    workers in the chosen language) → into the Builder.
 * The platform is "installed" only once BOTH a default model is resolvable AND a language is set
 * (ADR-019 gate), so the dialog is non-dismissable (no close button, backdrop/Esc don't close)
 * until that's true. Polls install-status + models every few seconds so each step pops the
 * moment its prerequisite is met. On /admin/providers it steps aside only for the provider step
 * (so the user can actually add a provider there).
 */
type ModelOpt = { id: string; label: string };
type Step = 'language' | 'provider' | 'models' | 'done';

export function InstallModal() {
  const router = useRouter();
  const pathname = usePathname();
  const { t } = useTranslation();
  const [needInstall, setNeedInstall] = useState(false);
  const [open, setOpen] = useState(false);
  // ADR-019(修订)：语言不再是 install gate，只是 onboarding 第一步（播种系统 Agent 语言 +
  // 设本人 UI 语言）。用本地 langChosen 记录用户本次是否已选（seed_language 默认 'en' 无法区分）。
  const [langChosen, setLangChosen] = useState(false);
  const [models, setModels] = useState<ModelOpt[]>([]);
  const [embModels, setEmbModels] = useState<ModelOpt[]>([]);
  const [sup, setSup] = useState('');
  const [agent, setAgent] = useState('');
  const [emb, setEmb] = useState('');
  const [busy, setBusy] = useState(false);
  const [langBusy, setLangBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const prevModelCount = useRef(0);
  const firstLoad = useRef(true);

  useEffect(() => {
    let cancelled = false;
    firstLoad.current = true;

    async function check() {
      try {
        const s = await systemSettingsApi.installStatus();
        if (cancelled) return;
        if (s.is_install) {
          setNeedInstall(false);
          setOpen(false);
          if (timer) clearInterval(timer);
          return;
        }
        setNeedInstall(true);
        const providers = await providersApi.list().catch(() => []);
        const all: ModelOpt[] = [];
        const embs: ModelOpt[] = [];
        for (const p of providers) {
          if (!p.is_enabled) continue;
          const ms: LLMModelPublic[] = await providersApi.listModels(p.id).catch(() => []);
          for (const m of ms) {
            if (!m.is_enabled) continue;
            if (m.model_type === 'chat') all.push({ id: m.id, label: `${p.name} / ${m.model_id}` });
            else if (m.model_type === 'embedding') embs.push({ id: m.id, label: `${p.name} / ${m.model_id}` });
          }
        }
        if (cancelled) return;
        setModels(all);
        setEmbModels(embs);
        setSup((cur) => cur || all[0]?.id || '');
        setAgent((cur) => cur || all[0]?.id || '');
        setEmb((cur) => cur || embs[0]?.id || '');
        // Pop on first load, or the moment models first appear (provider just configured).
        if (firstLoad.current || all.length > prevModelCount.current) setOpen(true);
        firstLoad.current = false;
        prevModelCount.current = all.length;
      } catch {
        if (!cancelled) setNeedInstall(false);
      }
    }

    const timer = setInterval(() => void check(), 3500);
    void check();
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [pathname]);

  const step: Step = done
    ? 'done'
    : !langChosen
      ? 'language'
      : models.length === 0
        ? 'provider'
        : 'models';

  if (!needInstall) return null;
  // On the providers page, step aside ONLY for the provider step (so the user can add a provider).
  if (step === 'provider' && pathname?.startsWith('/admin/providers')) return null;

  async function chooseLanguage(lang: 'en' | 'zh') {
    setLangBusy(true);
    setErr(null);
    try {
      await systemSettingsApi.setSeedLanguage(lang); // 播种系统 Agent 语言
      setLocale(lang); // 同步本人 UI 语言
      setLangChosen(true); // 进入下一步（语言非 gate）
      setOpen(true);
    } catch (e) {
      setErr(
        e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('onboarding.initFailed'),
      );
    } finally {
      setLangBusy(false);
    }
  }

  async function initialize() {
    setBusy(true);
    setErr(null);
    try {
      const r = await systemSettingsApi.setDefaultModels({
        supervisor_model_id: sup,
        agent_model_id: agent,
        embedding_model_id: emb || undefined,
      });
      if (r.is_install) {
        setDone(true);
        setTimeout(() => router.push('/super/builder'), 1200);
      }
    } catch (e) {
      setErr(
        e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('onboarding.initFailed'),
      );
    } finally {
      setBusy(false);
    }
  }

  function goProviders() {
    router.push('/admin/providers');
  }

  return (
    <Dialog open={open} onClose={() => {}} dismissable={false} title={t('onboarding.modalTitle')}>
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-sm font-medium text-foreground">
          <Rocket className="h-4 w-4 text-primary" />
          {t('onboarding.notInstalled')}
        </div>

        {step === 'done' ? (
          <div className="text-sm text-success">{t('onboarding.ready')}</div>
        ) : step === 'language' ? (
          <div className="space-y-3">
            <div>
              <div className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                <Languages className="h-4 w-4 text-primary" />
                {t('onboarding.langStepTitle')}
              </div>
              <div className="text-xs text-muted-foreground">{t('onboarding.langStepDesc')}</div>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                className="flex-1"
                disabled={langBusy}
                onClick={() => void chooseLanguage('en')}
              >
                {t('onboarding.langEnglish')}
              </Button>
              <Button className="flex-1" disabled={langBusy} onClick={() => void chooseLanguage('zh')}>
                {t('onboarding.langChinese')}
              </Button>
            </div>
          </div>
        ) : step === 'provider' ? (
          <div className="space-y-3">
            <div>
              <div className="text-sm font-medium text-foreground">{t('onboarding.step1Title')}</div>
              <div className="text-xs text-muted-foreground">{t('onboarding.step1Desc')}</div>
            </div>
            <Button className="gap-2" onClick={goProviders}>
              <Plug className="h-4 w-4" /> {t('onboarding.step1Cta')}
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <div className="text-sm font-medium text-foreground">{t('onboarding.step2Title')}</div>
              <div className="text-xs text-muted-foreground">{t('onboarding.step2Desc')}</div>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-muted-foreground">{t('onboarding.supervisorModel')}</label>
              <select
                value={sup}
                onChange={(e) => setSup(e.target.value)}
                className="rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-muted-foreground">{t('onboarding.agentModel')}</label>
              <select
                value={agent}
                onChange={(e) => setAgent(e.target.value)}
                className="rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-muted-foreground">{t('onboarding.embeddingModel')}</label>
              <select
                value={emb}
                onChange={(e) => setEmb(e.target.value)}
                className="rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
              >
                <option value="">{t('onboarding.embeddingNone')}</option>
                {embModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
              <div className="text-[11px] text-warning">{t('onboarding.embeddingHint')}</div>
            </div>
            <Button className="gap-2" onClick={initialize} disabled={busy || !sup || !agent}>
              {busy ? t('onboarding.initializing') : t('onboarding.initAndContinue')}
              {!busy && <ArrowRight className="h-4 w-4" />}
            </Button>
          </div>
        )}

        {err && <div className="text-xs text-destructive">{err}</div>}
      </div>
    </Dialog>
  );
}
