'use client';

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { providersApi } from '@/lib/api/providers';
import type { LLMModelPublic } from '@/types/provider';
import { Badge } from '@/components/ui/badge';

interface Props {
  providerId: string;
  refreshToken: number;
}

const TYPE_COLOR: Record<string, 'default' | 'secondary' | 'success' | 'warning' | 'outline'> = {
  chat: 'default',
  embedding: 'success',
  completion: 'secondary',
};

export function ModelsTable({ providerId, refreshToken }: Props) {
  const { t } = useTranslation();
  const [models, setModels] = useState<LLMModelPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    providersApi
      .listModels(providerId)
      .then((m) => {
        setModels(m);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : t('providerDialog.modelsLoadFailed')))
      .finally(() => setLoading(false));
  }, [providerId, refreshToken]);

  async function toggleEnabled(m: LLMModelPublic) {
    const updated = await providersApi.updateModel(providerId, m.id, {
      is_enabled: !m.is_enabled,
    });
    setModels((prev) => prev.map((x) => (x.id === m.id ? updated : x)));
  }

  if (loading)
    return <p className="py-6 text-center text-sm text-muted-foreground/70">{t('common.loading')}</p>;
  if (error) return <p className="py-6 text-center text-sm text-destructive">{error}</p>;
  if (models.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground/70">
        {t('providerDialog.modelsEmpty')}
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground/70">
            <th className="px-3 py-2 font-medium">{t('providerDialog.colModelId')}</th>
            <th className="px-3 py-2 font-medium">{t('providerDialog.colName')}</th>
            <th className="px-3 py-2 font-medium">{t('providerDialog.colType')}</th>
            <th className="px-3 py-2 font-medium">{t('providerDialog.colContext')}</th>
            <th className="px-3 py-2 font-medium">{t('providerDialog.colCapabilities')}</th>
            <th className="px-3 py-2 font-medium">{t('providerDialog.colEnabled')}</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr
              key={m.id}
              className="border-b border-border last:border-b-0 hover:bg-accent/50"
            >
              <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{m.model_id}</td>
              <td className="px-3 py-2 text-foreground">{m.display_name}</td>
              <td className="px-3 py-2">
                <Badge variant={TYPE_COLOR[m.model_type] ?? 'secondary'}>{m.model_type}</Badge>
              </td>
              <td className="px-3 py-2 text-muted-foreground/70">
                {m.context_window > 0 ? m.context_window.toLocaleString() : '—'}
              </td>
              <td className="px-3 py-2 text-xs text-muted-foreground/70">
                {[
                  m.supports_vision && 'Vision',
                  m.supports_function_calling && 'Tools',
                ]
                  .filter(Boolean)
                  .join(' · ') || '—'}
              </td>
              <td className="px-3 py-2">
                <input
                  type="checkbox"
                  checked={m.is_enabled}
                  onChange={() => toggleEnabled(m)}
                  className="cursor-pointer"
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
