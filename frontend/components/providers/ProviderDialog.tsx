'use client';

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import type { ProviderPublic, ProviderType } from '@/types/provider';

interface Props {
  open: boolean;
  onClose: () => void;
  initial?: ProviderPublic | null;
  onSubmit: (body: {
    name: string;
    provider_type: ProviderType;
    api_key?: string;
    base_url?: string | null;
    is_enabled: boolean;
  }) => Promise<void>;
}

export function ProviderDialog({ open, onClose, initial, onSubmit }: Props) {
  const { t } = useTranslation();
  const PROVIDER_TYPES: { value: ProviderType; label: string }[] = [
    { value: 'openai', label: 'OpenAI' },
    { value: 'anthropic', label: 'Anthropic' },
    { value: 'azure', label: 'Azure OpenAI' },
    { value: 'ollama', label: t('providerDialog.typeOllama') },
    { value: 'deepseek', label: 'DeepSeek' },
    { value: 'gemini', label: 'Google Gemini / AI Studio' },
    { value: 'custom', label: t('providerDialog.typeCustom') },
  ];
  const [name, setName] = useState('');
  const [providerType, setProviderType] = useState<ProviderType>('openai');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    if (initial) {
      setName(initial.name);
      setProviderType(initial.provider_type);
      setApiKey('');
      setBaseUrl(initial.base_url ?? '');
      setEnabled(initial.is_enabled);
    } else {
      setName('');
      setProviderType('openai');
      setApiKey('');
      setBaseUrl('');
      setEnabled(true);
    }
  }, [open, initial]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const body: Parameters<typeof onSubmit>[0] = {
        name,
        provider_type: providerType,
        base_url: baseUrl || null,
        is_enabled: enabled,
      };
      if (apiKey.trim()) body.api_key = apiKey.trim();
      if (!initial && !body.api_key) {
        throw new Error(t('providerDialog.apiKeyRequired'));
      }
      await onSubmit(body);
      onClose();
    } catch (e) {
      const msg =
        e && typeof e === 'object' && 'message' in e
          ? String((e as Error).message)
          : t('providerDialog.saveFailed');
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={initial ? t('providerDialog.editTitle') : t('providerDialog.createTitle')}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="p-name">{t('providerDialog.name')}</Label>
          <Input
            id="p-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="openai-main"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="p-type">{t('providerDialog.type')}</Label>
          <Select
            id="p-type"
            value={providerType}
            onChange={(e) => setProviderType(e.target.value as ProviderType)}
          >
            {PROVIDER_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="p-key">
            API Key{' '}
            {initial && (
              <span className="text-xs text-muted-foreground/70">
                {t('providerDialog.apiKeyKeepHint')}
              </span>
            )}
          </Label>
          <Input
            id="p-key"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={initial ? '••••••••' : 'sk-...'}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="p-url">{t('providerDialog.baseUrl')}</Label>
          <Input
            id="p-url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.openai.com/v1"
          />
        </div>

        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          {t('providerDialog.enabled')}
        </label>

        {error && (
          <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={submitting}>
            {submitting ? t('providerDialog.saving') : t('common.save')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
