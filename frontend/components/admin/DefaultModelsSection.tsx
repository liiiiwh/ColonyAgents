'use client';

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Save, Cpu, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { systemSettingsApi, type DefaultModelEntry } from '@/lib/api/systemSettings';
import { providersApi } from '@/lib/api/providers';
import type { LLMModelPublic } from '@/types/provider';
import { errMessage } from '@/lib/errors';

/** 续接① · 默认模型（supervisor/agent/embedding）查看 + 编辑。
 *
 * 为什么独立成段：默认模型可能来自 .env（env-install 不回写 system_settings），普通
 * system_settings 列表读不到。此处用 GET /default-models 解析出有效值（含来源），并以
 * provider/model_id 形式展示（绝不裸 uuid）；保存复用 POST /default-models 的 partial 编辑。
 */

type ModelOpt = { id: string; label: string; type: 'chat' | 'embedding' };

const ROLE_KEY: Record<string, string> = {
  supervisor: 'roleSupervisor',
  agent: 'roleAgent',
  embedding: 'roleEmbedding',
};
const SOURCE_KEY: Record<string, string> = {
  env: 'sourceEnv',
  system_settings: 'sourceSystemSettings',
  unresolved: 'sourceUnresolved',
  none: 'sourceNone',
};

export function DefaultModelsSection() {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<DefaultModelEntry[]>([]);
  const [models, setModels] = useState<ModelOpt[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingRole, setSavingRole] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const refresh = async () => {
    setErr(null);
    try {
      const [defs, providers] = await Promise.all([
        systemSettingsApi.getDefaultModels(),
        providersApi.list().catch(() => []),
      ]);
      const opts: ModelOpt[] = [];
      for (const p of providers) {
        if (!p.is_enabled) continue;
        const ms: LLMModelPublic[] = await providersApi.listModels(p.id).catch(() => []);
        for (const m of ms) {
          if (!m.is_enabled) continue;
          if (m.model_type === 'chat' || m.model_type === 'embedding')
            opts.push({ id: m.id, label: `${p.name} / ${m.model_id}`, type: m.model_type });
        }
      }
      setEntries(defs);
      setModels(opts);
      const d: Record<string, string> = {};
      for (const e of defs) d[e.role] = e.model_id ?? '';
      setDrafts(d);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  useEffect(() => {
    void refresh();
  }, []);

  const onSave = async (role: string) => {
    setSavingRole(role);
    setErr(null);
    setToast(null);
    try {
      const id = drafts[role];
      await systemSettingsApi.setDefaultModels({ [`${role}_model_id`]: id || undefined });
      setToast(t('settings.saveSuccess', { key: `default_${role}_model_id` }));
      setTimeout(() => setToast(null), 4000);
      await refresh();
    } catch (e) {
      const msg = errMessage(e);
      setErr(t('settings.saveFailed', { key: `default_${role}_model_id`, msg }));
    } finally {
      setSavingRole(null);
    }
  };

  const embeddingUnset = entries.find((e) => e.role === 'embedding' && !e.model_id);

  return (
    <section className="mb-6 border border-border rounded-lg overflow-hidden">
      <div className="bg-muted px-4 py-2.5">
        <h2 className="text-sm font-semibold text-foreground flex items-center gap-1.5">
          <Cpu className="w-4 h-4" /> {t('settings.defaultModelsTitle')}
        </h2>
        <p className="text-[11px] text-muted-foreground mt-0.5">{t('settings.defaultModelsDesc')}</p>
      </div>

      {toast && (
        <div className="mx-3 mt-3 p-2 rounded bg-success/10 text-success text-xs border border-success/40">
          {toast}
        </div>
      )}
      {err && (
        <div className="mx-3 mt-3 p-2 rounded bg-destructive/10 text-destructive text-xs border border-destructive/40 flex items-start gap-2">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5" />
          <div>{err}</div>
        </div>
      )}
      {embeddingUnset && (
        <div className="mx-3 mt-3 p-2 rounded bg-warning/10 text-warning text-xs border border-warning/40 flex items-start gap-2">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5" />
          <div>{t('settings.embeddingUnsetWarn')}</div>
        </div>
      )}

      <div className="divide-y divide-border">
        {entries.map((e) => {
          const opts = models.filter((m) =>
            e.role === 'embedding' ? m.type === 'embedding' : m.type === 'chat',
          );
          const sourceLabel = t(`settings.${SOURCE_KEY[e.source] ?? 'sourceNone'}`);
          return (
            <div key={e.role} className="p-3 flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-foreground">{t(`settings.${ROLE_KEY[e.role]}`)}</div>
                <div className="text-[11px] text-muted-foreground truncate">
                  {e.label ?? '—'}{' '}
                  <span
                    className={
                      e.source === 'unresolved' || e.source === 'none'
                        ? 'text-warning'
                        : 'text-muted-foreground/70'
                    }
                  >
                    ({sourceLabel})
                  </span>
                </div>
              </div>
              <select
                className="w-64 rounded-lg border border-border bg-card px-2 py-1.5 text-sm font-mono"
                value={drafts[e.role] ?? ''}
                onChange={(ev) => setDrafts((d) => ({ ...d, [e.role]: ev.target.value }))}
              >
                {e.role === 'embedding' && <option value="">{t('onboarding.embeddingNone')}</option>}
                {opts.length === 0 && <option value="">{t('settings.defaultModelNoOption')}</option>}
                {opts.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                disabled={savingRole === e.role || (drafts[e.role] ?? '') === (e.model_id ?? '')}
                onClick={() => void onSave(e.role)}
              >
                <Save className="w-3.5 h-3.5 mr-1" />
                {savingRole === e.role ? t('settings.saving') : t('common.save')}
              </Button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
