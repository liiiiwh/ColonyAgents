'use client';

import { useEffect, useMemo, useState } from 'react';
import { AxiosError } from 'axios';
import { useTranslation } from 'react-i18next';
import { Download, Loader2, Search } from 'lucide-react';
import { Dialog } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import {
  agentImportApi,
  type ImportCatalogItem,
  type ImportVersion,
  type ImportWorkerSpec,
} from '@/lib/api/agentImport';

/**
 * ADR-019 D3 · 一键导入 Worker。选版本（en/zh 源仓库）→ 浏览/搜索 agent →
 * 预览 persona→worker 映射 → 确认导入（按 capability 幂等 upsert）。
 */
export function ImportWorkerModal({
  open,
  onClose,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}) {
  const { t } = useTranslation();
  const [version, setVersion] = useState<ImportVersion>('en');
  const [items, setItems] = useState<ImportCatalogItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<ImportCatalogItem | null>(null);
  const [spec, setSpec] = useState<ImportWorkerSpec | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    setSelected(null);
    setSpec(null);
    agentImportApi
      .catalog(version)
      .then((r) => {
        if (!cancelled) setItems(r.items);
      })
      .catch((e) => {
        if (!cancelled)
          setErr(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('agentImport.failed'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, version, t]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (it) => it.name.toLowerCase().includes(q) || it.division.toLowerCase().includes(q),
    );
  }, [items, query]);

  async function select(it: ImportCatalogItem) {
    setSelected(it);
    setSpec(null);
    setErr(null);
    setOkMsg(null);
    setPreviewing(true);
    try {
      const r = await agentImportApi.preview(version, it.path);
      setSpec(r.spec);
    } catch (e) {
      setErr(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('agentImport.failed'));
    } finally {
      setPreviewing(false);
    }
  }

  async function doImport() {
    if (!selected) return;
    setImporting(true);
    setErr(null);
    try {
      const r = await agentImportApi.import(version, selected.path);
      setOkMsg(t('agentImport.imported', { name: r.name }));
      onImported();
    } catch (e) {
      setErr(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('agentImport.failed'));
    } finally {
      setImporting(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t('agentImport.title')} className="max-w-2xl">
      <div className="space-y-3">
        <p className="text-xs text-muted-foreground">{t('agentImport.note')}</p>

        {/* version + search */}
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground">{t('agentImport.version')}</label>
          <select
            value={version}
            onChange={(e) => setVersion(e.target.value as ImportVersion)}
            className="rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
          >
            <option value="en">{t('agentImport.versionEn')}</option>
            <option value="zh">{t('agentImport.versionZh')}</option>
          </select>
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('agentImport.search')}
              className="w-full rounded-lg border border-border bg-card py-1.5 pl-7 pr-2 text-sm"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {/* catalog list */}
          <div className="max-h-80 overflow-y-auto rounded-lg border border-border">
            {loading ? (
              <p className="p-4 text-center text-xs text-muted-foreground">{t('agentImport.loading')}</p>
            ) : filtered.length === 0 ? (
              <p className="p-4 text-center text-xs text-muted-foreground">{t('agentImport.empty')}</p>
            ) : (
              <ul className="divide-y divide-border/60">
                {filtered.map((it) => (
                  <li key={it.path}>
                    <button
                      type="button"
                      onClick={() => void select(it)}
                      className={`flex w-full flex-col items-start px-3 py-2 text-left hover:bg-accent/50 ${
                        selected?.path === it.path ? 'bg-accent' : ''
                      }`}
                    >
                      <span className="text-sm text-foreground">{it.name}</span>
                      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                        {it.division}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* preview */}
          <div className="max-h-80 overflow-y-auto rounded-lg border border-border p-3">
            {previewing ? (
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> …
              </p>
            ) : spec ? (
              <div className="space-y-2">
                <div className="text-sm font-medium text-foreground">{spec.name}</div>
                <div className="text-xs text-muted-foreground">
                  {t('agentImport.capability')}: <span className="font-mono">{spec.capability}</span>
                </div>
                <pre className="whitespace-pre-wrap break-words rounded bg-muted p-2 text-[11px] text-muted-foreground">
                  {spec.soul_md.slice(0, 600)}
                  {spec.soul_md.length > 600 ? '…' : ''}
                </pre>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">—</p>
            )}
          </div>
        </div>

        {err && <div className="text-xs text-destructive">{err}</div>}
        {okMsg && <div className="text-xs text-success">{okMsg}</div>}

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t('common.close')}
          </Button>
          <Button onClick={() => void doImport()} disabled={!spec || importing} className="gap-2">
            {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            {importing ? t('agentImport.importing') : t('agentImport.importBtn')}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
