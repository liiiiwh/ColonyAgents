'use client';

import { useEffect, useState } from 'react';
import { AxiosError } from 'axios';
import { Plus, RefreshCw, Trash2, Pencil } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ProviderDialog } from '@/components/providers/ProviderDialog';
import { ModelsTable } from '@/components/providers/ModelsTable';
import { useConfirm, useToast } from '@/components/providers/ConfirmProvider';
import { providersApi } from '@/lib/api/providers';
import type { ProviderPublic, ProviderType } from '@/types/provider';

export default function ProvidersPage() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const [providers, setProviders] = useState<ProviderPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ProviderPublic | null>(null);
  const [selected, setSelected] = useState<ProviderPublic | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [modelsRefresh, setModelsRefresh] = useState(0);

  async function refresh() {
    setLoading(true);
    try {
      const list = await providersApi.list();
      setProviders(list);
      if (selected && !list.find((p) => p.id === selected.id)) {
        setSelected(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t('providers.loadFailed'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmit(body: {
    name: string;
    provider_type: ProviderType;
    api_key?: string;
    base_url?: string | null;
    is_enabled: boolean;
  }) {
    if (editing) {
      await providersApi.update(editing.id, body);
    } else {
      if (!body.api_key) throw new Error(t('providers.apiKeyRequired'));
      await providersApi.create({ ...body, api_key: body.api_key });
    }
    await refresh();
  }

  async function handleDelete(p: ProviderPublic) {
    if (!(await confirm({ message: t('providers.deleteConfirm', { name: p.name }), danger: true }))) return;
    try {
      await providersApi.delete(p.id);
      await refresh();
    } catch (e) {
      toast(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('providers.deleteFailed'), 'error');
    }
  }

  async function handleSync(p: ProviderPublic) {
    setSyncing(true);
    try {
      const resp = await providersApi.syncModels(p.id);
      toast(t('providers.syncSuccess', { count: resp.synced }), 'success');
      setModelsRefresh((x) => x + 1);
    } catch (e) {
      toast(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('providers.syncFailed'), 'error');
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-8 py-10">
      <header className="flex items-center justify-between border-b border-border pb-5">
        <div>
          <h1 className="text-2xl font-medium tracking-tight text-foreground">{t('providers.title')}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t('providers.subtitle')}</p>
        </div>
        <Button
          onClick={() => {
            setEditing(null);
            setDialogOpen(true);
          }}
        >
          <Plus className="mr-2 h-4 w-4" />
          {t('providers.newProvider')}
        </Button>
      </header>

      {error && (
        <p className="mt-4 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>
      )}

      {/* 平台支持的 provider 类型说明 */}
      <section className="mt-6 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 text-sm">
        <h2 className="font-medium text-foreground">{t('providers.supportedTitle')}</h2>
        <ul className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-muted-foreground sm:grid-cols-2">
          <li><b className="text-foreground/90">OpenAI</b> — {t('providers.supOpenai')}</li>
          <li><b className="text-foreground/90">Anthropic</b> — {t('providers.supAnthropic')}</li>
          <li><b className="text-foreground/90">Google Gemini / AI Studio</b> — {t('providers.supGemini')}</li>
          <li><b className="text-foreground/90">Azure OpenAI</b> — {t('providers.supAzure')}</li>
          <li><b className="text-foreground/90">DeepSeek</b> — {t('providers.supDeepseek')}</li>
          <li><b className="text-foreground/90">{t('providers.ollamaLabel')}</b> — {t('providers.supOllama')}</li>
          <li className="sm:col-span-2">
            <b className="text-foreground/90">{t('providers.customLabel')}</b> — {t('providers.supCustom')}
          </li>
        </ul>
        <p className="mt-2 text-xs text-muted-foreground/70">{t('providers.adr014Note')}</p>
      </section>

      <section className="mt-6 overflow-hidden rounded-xl border border-border bg-card">
        {loading ? (
          <p className="p-8 text-center text-sm text-muted-foreground">{t('common.loading')}</p>
        ) : providers.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground">{t('providers.empty')}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-2.5 font-medium">{t('providers.colName')}</th>
                <th className="px-4 py-2.5 font-medium">{t('providers.colType')}</th>
                <th className="px-4 py-2.5 font-medium">Base URL</th>
                <th className="px-4 py-2.5 font-medium">{t('providers.colStatus')}</th>
                <th className="px-4 py-2.5 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {providers.map((p) => (
                <tr
                  key={p.id}
                  className={`cursor-pointer border-b border-border last:border-b-0 hover:bg-accent/50 ${
                    selected?.id === p.id ? 'bg-accent/50' : ''
                  }`}
                  onClick={() => setSelected(p)}
                >
                  <td className="px-4 py-3 font-medium text-foreground">{p.name}</td>
                  <td className="px-4 py-3 text-muted-foreground">{p.provider_type}</td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground/70">
                    {p.base_url ?? '—'}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={p.is_enabled ? 'success' : 'secondary'}>
                      {p.is_enabled ? t('providers.enabled') : t('providers.disabled')}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSync(p);
                        }}
                        disabled={syncing}
                      >
                        <RefreshCw className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          setEditing(p);
                          setDialogOpen(true);
                        }}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(p);
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {selected && (
        <section className="mt-6 rounded-xl border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <div>
              <h2 className="text-sm font-medium text-foreground">
                {t('providers.modelsTitle', { name: selected.name })}
              </h2>
              <p className="mt-0.5 text-xs text-muted-foreground">{t('providers.modelsHint')}</p>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => handleSync(selected)}
              disabled={syncing}
            >
              <RefreshCw className="mr-2 h-3.5 w-3.5" />
              {syncing ? t('providers.syncing') : t('providers.syncModels')}
            </Button>
          </div>
          <ModelsTable providerId={selected.id} refreshToken={modelsRefresh} />
        </section>
      )}

      <ProviderDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        initial={editing}
        onSubmit={handleSubmit}
      />
    </div>
  );
}
