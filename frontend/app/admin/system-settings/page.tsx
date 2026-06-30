'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Save, RefreshCw, Settings, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { systemSettingsApi, type SystemSetting } from '@/lib/api/systemSettings';
import { settingDescription } from '@/lib/settings/descriptions';
import { errMessage } from '@/lib/errors';
import { DefaultModelsSection } from '@/components/admin/DefaultModelsSection';

/** Platform-level system_settings management (admin only).
 *
 * Grouped by key prefix (compression / escalation / worker / invoke_worker / daemon / dev etc.)
 * so admins can quickly find the item to tune; includes limit hints.
 */

type Category = {
  key: string;
  titleKey: string;
  descriptionKey: string;
};

const CATEGORIES: Category[] = [
  { key: 'compression.', titleKey: 'settings.catCompressionTitle', descriptionKey: 'settings.catCompressionDesc' },
  { key: 'escalation.', titleKey: 'settings.catEscalationTitle', descriptionKey: 'settings.catEscalationDesc' },
  { key: 'worker.', titleKey: 'settings.catWorkerTitle', descriptionKey: 'settings.catWorkerDesc' },
  { key: 'invoke_worker.', titleKey: 'settings.catInvokeWorkerTitle', descriptionKey: 'settings.catInvokeWorkerDesc' },
  { key: 'return_result.', titleKey: 'settings.catReturnResultTitle', descriptionKey: 'settings.catReturnResultDesc' },
  { key: 'factory.', titleKey: 'settings.catFactoryTitle', descriptionKey: 'settings.catFactoryDesc' },
  { key: 'worker_invocation_log.', titleKey: 'settings.catWorkerLogTitle', descriptionKey: 'settings.catWorkerLogDesc' },
  { key: 'daemon.', titleKey: 'settings.catDaemonTitle', descriptionKey: 'settings.catDaemonDesc' },
  { key: 'mission.', titleKey: 'settings.catMissionTitle', descriptionKey: 'settings.catMissionDesc' },
  { key: 'dev.', titleKey: 'settings.catDevTitle', descriptionKey: 'settings.catDevDesc' },
];

const UNCATEGORIZED: Category = {
  key: '',
  titleKey: 'settings.catOtherTitle',
  descriptionKey: 'settings.catOtherDesc',
};

// 这三个默认模型 key 由专门的「默认模型」段（DefaultModelsSection）管理，
// 不在通用列表里重复显示（否则「其它」段会出现裸字符串冗余）。
const MANAGED_ELSEWHERE = new Set([
  'default_supervisor_model_id',
  'default_agent_model_id',
  'default_embedding_model_id',
]);

function categorize(rows: SystemSetting[]): Map<Category, SystemSetting[]> {
  const out = new Map<Category, SystemSetting[]>();
  CATEGORIES.forEach((c) => out.set(c, []));
  out.set(UNCATEGORIZED, []);
  for (const r of rows) {
    if (MANAGED_ELSEWHERE.has(r.key)) continue;
    const cat = CATEGORIES.find((c) => r.key.startsWith(c.key)) ?? UNCATEGORIZED;
    out.get(cat)!.push(r);
  }
  return out;
}

export default function SystemSettingsPage() {
  const { t, i18n } = useTranslation();
  const [rows, setRows] = useState<SystemSetting[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setErr(null);
    try {
      const data = await systemSettingsApi.list();
      setRows(data);
      const d: Record<string, string> = {};
      for (const r of data) d[r.key] = JSON.stringify(r.value);
      setDrafts(d);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void refresh();
  }, []);

  const grouped = useMemo(() => categorize(rows), [rows]);

  const onSave = async (key: string) => {
    setSavingKey(key);
    setErr(null);
    setToast(null);
    try {
      let parsed: unknown;
      const raw = (drafts[key] ?? '').trim();
      try {
        parsed = JSON.parse(raw);
      } catch {
        if (/^-?\d+(\.\d+)?$/.test(raw)) parsed = Number(raw);
        else if (raw === 'true' || raw === 'false') parsed = raw === 'true';
        else parsed = raw.replace(/^"|"$/g, '');
      }
      const updated = await systemSettingsApi.update(key, parsed);
      setRows((prev) => prev.map((r) => (r.key === key ? updated : r)));
      setToast(t('settings.saveSuccess', { key }));
      setTimeout(() => setToast(null), 4000);
    } catch (e) {
      const msg = errMessage(e);
      setErr(t('settings.saveFailed', { key, msg }));
    } finally {
      setSavingKey(null);
    }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <header className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Settings className="w-5 h-5" />
          <h1 className="text-xl font-semibold text-foreground">{t('settings.title')}</h1>
          <span className="text-xs text-muted-foreground">
            {t('settings.summary', { count: rows.length, categories: CATEGORIES.length })}
          </span>
        </div>
        <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> {t('common.refresh')}
        </Button>
      </header>

      <p className="text-xs text-muted-foreground mb-4">
        {t('settings.intro')}{' '}
        <strong>{t('settings.priorityOrder')}</strong>.
      </p>

      {toast && (
        <div className="mb-3 p-2 rounded bg-success/10 text-success text-sm border border-success/40">
          {toast}
        </div>
      )}
      {err && (
        <div className="mb-3 p-2 rounded bg-destructive/10 text-destructive text-sm border border-destructive/40 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 mt-0.5" />
          <div>{err}</div>
        </div>
      )}

      <DefaultModelsSection />

      {Array.from(grouped.entries()).map(([cat, items]) =>
        items.length === 0 ? null : (
          <section key={cat.key} className="mb-6 border border-border rounded-lg overflow-hidden">
            <div className="bg-muted px-4 py-2.5">
              <h2 className="text-sm font-semibold text-foreground">{t(cat.titleKey)}</h2>
              <p className="text-[11px] text-muted-foreground mt-0.5">{t(cat.descriptionKey)}</p>
            </div>
            <div className="divide-y divide-border">
              {items.map((r) => (
                <div key={r.key} className="p-3 flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-mono text-sm font-semibold truncate text-foreground">{r.key}</div>
                    {(settingDescription(r.key, i18n.language) ?? r.description) && (
                      <div className="text-xs text-muted-foreground truncate">
                        {settingDescription(r.key, i18n.language) ?? r.description}
                      </div>
                    )}
                    {r.updated_at && (
                      <div className="text-[10px] text-muted-foreground/70">
                        updated_at {r.updated_at}
                        {r.updated_by ? ` by ${r.updated_by.slice(0, 8)}…` : ''}
                      </div>
                    )}
                  </div>
                  {r.key.endsWith('_prompt') || (drafts[r.key] ?? '').includes('\\n') ? (
                    <textarea
                      className="w-80 min-h-[5rem] font-mono text-sm rounded-md border border-input bg-background px-3 py-2"
                      value={drafts[r.key] ?? ''}
                      onChange={(e) => setDrafts((d) => ({ ...d, [r.key]: e.target.value }))}
                      placeholder={t('settings.jsonValuePlaceholder')}
                    />
                  ) : (
                    <Input
                      className="w-56 font-mono text-sm"
                      value={drafts[r.key] ?? ''}
                      onChange={(e) => setDrafts((d) => ({ ...d, [r.key]: e.target.value }))}
                      placeholder={t('settings.jsonValuePlaceholder')}
                    />
                  )}
                  <Button size="sm" disabled={savingKey === r.key} onClick={() => void onSave(r.key)}>
                    <Save className="w-3.5 h-3.5 mr-1" />
                    {savingKey === r.key ? t('settings.saving') : t('common.save')}
                  </Button>
                </div>
              ))}
            </div>
          </section>
        )
      )}

      {rows.length === 0 && !loading && (
        <div className="p-6 text-center text-muted-foreground text-sm border border-border rounded">
          {t('settings.emptyHint')}
        </div>
      )}
    </div>
  );
}
