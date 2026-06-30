'use client';

import { useEffect, useState } from 'react';
import { AxiosError } from 'axios';
import { CheckCircle2, Pencil, Plug, Plus, Trash2, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { splitArgs } from '@/lib/shell/splitArgs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useConfirm, useToast } from '@/components/providers/ConfirmProvider';
import { mcpServersApi } from '@/lib/api/skills';
import type { MCPServerPublic, MCPServerType, MCPToolInfo } from '@/types/skill';

export default function MCPServersPage() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const [items, setItems] = useState<MCPServerPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<MCPServerPublic | null>(null);
  const [open, setOpen] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; msg?: string; tools?: MCPToolInfo[] }>>({});

  async function refresh() {
    setLoading(true);
    try {
      setItems(await mcpServersApi.list());
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('mcp.loadFailed'));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  async function handleTest(s: MCPServerPublic) {
    setTestingId(s.id);
    try {
      const r = await mcpServersApi.test(s.id);
      setTestResults((prev) => ({
        ...prev,
        [s.id]: { ok: r.reachable, msg: r.error ?? undefined, tools: r.tools },
      }));
    } catch (e) {
      setTestResults((prev) => ({
        ...prev,
        [s.id]: { ok: false, msg: e instanceof Error ? e.message : t('mcp.connectFailed') },
      }));
    } finally {
      setTestingId(null);
    }
  }

  async function handleDelete(s: MCPServerPublic) {
    if (!(await confirm({ message: t('mcp.deleteConfirm', { name: s.name }), danger: true }))) return;
    try {
      await mcpServersApi.delete(s.id);
      await refresh();
    } catch (e) {
      toast(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('mcp.deleteFailed'), 'error');
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-8 py-10">
      <header className="flex items-center justify-between border-b border-border pb-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">{t('mcp.title')}</h1>
          <p className="mt-1 text-sm text-muted-foreground/70">{t('mcp.subtitle')}</p>
        </div>
        <Button
          onClick={() => {
            setEditing(null);
            setOpen(true);
          }}
        >
          <Plus className="mr-2 h-4 w-4" />
          {t('mcp.newServer')}
        </Button>
      </header>

      {err && <p className="mt-4 rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}

      <section className="mt-6 overflow-hidden rounded-lg border border-border bg-card">
        {loading ? (
          <p className="p-8 text-center text-sm text-muted-foreground/70">{t('common.loading')}</p>
        ) : items.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground/70">{t('mcp.empty')}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground/70">
                <th className="px-4 py-2.5 font-medium">{t('mcp.colName')}</th>
                <th className="px-4 py-2.5 font-medium">{t('mcp.colType')}</th>
                <th className="px-4 py-2.5 font-medium">{t('mcp.colTarget')}</th>
                <th className="px-4 py-2.5 font-medium">{t('mcp.colStatus')}</th>
                <th className="px-4 py-2.5 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => {
                const r = testResults[s.id];
                return (
                  <tr key={s.id} className="border-b border-border last:border-b-0 hover:bg-accent/50">
                    <td className="px-4 py-3">
                      <p className="font-medium text-foreground">{s.name}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground/70">{s.description || '—'}</p>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={s.server_type === 'http' ? 'default' : 'secondary'}>
                        {s.server_type}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                      {s.server_type === 'stdio' ? (s.command?.join(' ') ?? '—') : (s.url ?? '—')}
                    </td>
                    <td className="px-4 py-3">
                      {r ? (
                        r.ok ? (
                          <span className="inline-flex items-center gap-1 text-xs text-success">
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            {t('mcp.connectionOk')}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-xs text-destructive">
                            <XCircle className="h-3.5 w-3.5" />
                            {r.msg ?? t('mcp.connectionFailed')}
                          </span>
                        )
                      ) : (
                        <Badge variant={s.is_enabled ? 'success' : 'secondary'}>
                          {s.is_enabled ? t('mcp.enabled') : t('mcp.disabled')}
                        </Badge>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleTest(s)}
                          disabled={testingId === s.id}
                        >
                          <Plug className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => {
                            setEditing(s);
                            setOpen(true);
                          }}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => handleDelete(s)}>
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <MCPDialog open={open} onClose={() => setOpen(false)} initial={editing} onSaved={refresh} />
    </div>
  );
}

interface DialogProps {
  open: boolean;
  onClose: () => void;
  initial: MCPServerPublic | null;
  onSaved: () => Promise<void> | void;
}

function MCPDialog({ open, onClose, initial, onSaved }: DialogProps) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [serverType, setServerType] = useState<MCPServerType>('stdio');
  const [commandLine, setCommandLine] = useState('');
  const [url, setUrl] = useState('');
  const [envJson, setEnvJson] = useState('');
  const [headersJson, setHeadersJson] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setErr(null);
    if (initial) {
      setName(initial.name);
      setDesc(initial.description);
      setServerType(initial.server_type);
      setCommandLine(initial.command?.join(' ') ?? '');
      setUrl(initial.url ?? '');
      setEnvJson(initial.env_vars ? JSON.stringify(initial.env_vars, null, 2) : '');
      setHeadersJson(initial.headers ? JSON.stringify(initial.headers, null, 2) : '');
      setEnabled(initial.is_enabled);
    } else {
      setName('');
      setDesc('');
      setServerType('stdio');
      setCommandLine('');
      setUrl('');
      setEnvJson('');
      setHeadersJson('');
      setEnabled(true);
    }
  }, [open, initial]);

  function parseJson<T>(text: string, label: string): T | null {
    if (!text.trim()) return null;
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new Error(t('mcp.invalidJson', { label }));
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setErr(null);
    try {
      const body = {
        name,
        description: desc,
        server_type: serverType,
        command: serverType === 'stdio' ? splitArgs(commandLine) : null,
        url: serverType === 'http' ? url : null,
        env_vars: parseJson<Record<string, string>>(envJson, 'env_vars'),
        headers: parseJson<Record<string, string>>(headersJson, 'headers'),
        is_enabled: enabled,
      };
      if (initial) {
        await mcpServersApi.update(initial.id, body);
      } else {
        await mcpServersApi.create(body);
      }
      await onSaved();
      onClose();
    } catch (e) {
      setErr(
        e instanceof AxiosError
          ? (e.response?.data?.detail ?? e.message)
          : e instanceof Error
            ? e.message
            : t('mcp.saveFailed'),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={initial ? t('mcp.editServer') : t('mcp.newServer')}
      className="max-w-2xl"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>{t('mcp.colName')}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="space-y-2">
            <Label>{t('mcp.colType')}</Label>
            <Select value={serverType} onChange={(e) => setServerType(e.target.value as MCPServerType)}>
              <option value="stdio">{t('mcp.typeStdio')}</option>
              <option value="http">{t('mcp.typeHttp')}</option>
            </Select>
          </div>
        </div>

        <div className="space-y-2">
          <Label>{t('mcp.descriptionLabel')}</Label>
          <Input value={desc} onChange={(e) => setDesc(e.target.value)} />
        </div>

        {serverType === 'stdio' ? (
          <>
            <div className="space-y-2">
              <Label>{t('mcp.commandLabel')}</Label>
              <Input
                value={commandLine}
                onChange={(e) => setCommandLine(e.target.value)}
                placeholder="npx -y @modelcontextprotocol/server-filesystem /tmp"
                required
              />
            </div>
            <div className="space-y-2">
              <Label>{t('mcp.envVarsLabel')}</Label>
              <Textarea value={envJson} onChange={(e) => setEnvJson(e.target.value)} rows={3} />
            </div>
          </>
        ) : (
          <>
            <div className="space-y-2">
              <Label>{t('mcp.urlLabel')}</Label>
              <Input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://mcp.example.com/mcp"
                required
              />
            </div>
            <div className="space-y-2">
              <Label>{t('mcp.headersLabel')}</Label>
              <Textarea value={headersJson} onChange={(e) => setHeadersJson(e.target.value)} rows={3} />
            </div>
          </>
        )}

        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          {t('mcp.enabled')}
        </label>

        {err && <p className="rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={submitting}>
            {submitting ? t('mcp.saving') : t('common.save')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
