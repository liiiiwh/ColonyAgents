'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AxiosError } from 'axios';
import {
  ChevronRight,
  Download,
  FileUp,
  Folder,
  HardDrive,
  Home,
  Image as ImageIcon,
  RefreshCw,
  Trash2,
  Users as UsersIcon,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { useConfirm, useToast } from '@/components/providers/ConfirmProvider';
import { missionsAdminApi } from '@/lib/api/missionsAdmin';
import { storageApi } from '@/lib/api/storage';
import type { MissionPublic } from '@/types/mission';
import type { StorageObject } from '@/types/storage';

/** Backend S3 key conventions (see SPEC §6 / session_service._workspace_key):
 *  - colony/workspace/{mission_id}/{user_id}/{session_id}/{branch_id}/{node}/{artifact_id}.{ext}
 *  - aux-image/{hash}-{rand}.png   <- invoke_aux_model scratch images
 *  - users/{user_id}/{yyyymm}/{uuid}-{filename}   <- user-uploaded attachments
 */
const QUICK_LINKS: { labelKey: string; prefix: string; hintKey: string }[] = [
  { labelKey: 'storage.quickAll', prefix: '', hintKey: 'storage.quickAllHint' },
  { labelKey: 'storage.quickWorkspace', prefix: 'colony/workspace/', hintKey: 'storage.quickWorkspaceHint' },
  { labelKey: 'storage.quickAux', prefix: 'aux-image/', hintKey: 'storage.quickAuxHint' },
  { labelKey: 'storage.quickUploads', prefix: 'users/', hintKey: 'storage.quickUploadsHint' },
];

export default function StoragePage() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const [items, setItems] = useState<StorageObject[]>([]);
  const [prefix, setPrefix] = useState('');
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // mission 过滤（ADR-018 mission-only：workspace 按 mission 分目录，无 session 维度）
  const [projects, setProjects] = useState<MissionPublic[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');

  /** 默认 prefix：`colony/workspace/`，方便用户从根 workspace 起浏览。
   *  也可以选 mission 快速跳到该 mission 子目录；选 session 再细化。
   */
  useEffect(() => {
    if (!prefix) {
      // 首屏默认显示 workspace 根（避免 list 全部）
      setPrefix('colony/workspace/');
    }
    missionsAdminApi.list().then(setProjects).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // prefix 变 → 拉数据
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefix]);

  // ADR-018 mission-only · 选 mission → 跳到该 mission workspace prefix（S3 key 已无 session 段）
  useEffect(() => {
    if (!selectedProjectId) return;
    setPrefix(`colony/workspace/${selectedProjectId}/`);
  }, [selectedProjectId]);

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      setItems(await storageApi.list(prefix));
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('storage.loadFailed'));
    } finally {
      setLoading(false);
    }
  }

  async function handleUpload(file: File) {
    setUploading(true);
    try {
      await storageApi.upload(file);
      await refresh();
    } catch (e) {
      toast(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('storage.uploadFailed'), 'error');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  async function handleDelete(o: StorageObject) {
    if (!(await confirm({ message: t('storage.confirmDelete', { key: o.key }), danger: true }))) return;
    await storageApi.delete(o.key);
    await refresh();
  }

  async function handleDownload(o: StorageObject) {
    const { url } = await storageApi.presignedUrl(o.key);
    window.open(url, '_blank');
  }

  /** 当前 prefix 拆成面包屑（按 / 拆分） */
  const breadcrumbs = useMemo(() => {
    const parts = prefix.split('/').filter(Boolean);
    const out: { label: string; prefix: string }[] = [{ label: t('storage.breadcrumbRoot'), prefix: '' }];
    for (let i = 0; i < parts.length; i++) {
      out.push({
        label: parts[i],
        prefix: parts.slice(0, i + 1).join('/') + '/',
      });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefix]);

  /** 按当前 prefix 下一层目录分组（让用户看到子文件夹），以及当前层级的文件 */
  const grouped = useMemo(() => {
    const folders = new Map<string, number>(); // 子文件夹名 → 子文件个数
    const files: StorageObject[] = [];
    const base = prefix; // e.g. "colony/workspace/mission-id/"
    for (const item of items) {
      if (!item.key.startsWith(base)) continue;
      const rel = item.key.slice(base.length);
      const slashIdx = rel.indexOf('/');
      if (slashIdx >= 0) {
        const folder = rel.slice(0, slashIdx);
        folders.set(folder, (folders.get(folder) || 0) + 1);
      } else if (rel.length > 0) {
        files.push(item);
      }
    }
    return {
      folders: Array.from(folders.entries()).map(([name, count]) => ({ name, count })).sort((a, b) => a.name.localeCompare(b.name)),
      files: files.sort((a, b) => a.key.localeCompare(b.key)),
    };
  }, [items, prefix]);

  return (
    <div className="mx-auto max-w-6xl px-8 py-10">
      <header className="flex items-center justify-between border-b border-border pb-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">{t('storage.title')}</h1>
          <p className="mt-1 text-sm text-muted-foreground/70">{t('storage.subtitle')}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
            {t('storage.refresh')}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
          />
          <Button onClick={() => fileInputRef.current?.click()} disabled={uploading}>
            <FileUp className="mr-1.5 h-3.5 w-3.5" />
            {uploading ? t('storage.uploading') : t('storage.upload')}
          </Button>
        </div>
      </header>

      {/* 快捷前缀 */}
      <section className="mt-4 flex flex-wrap items-center gap-2">
        {QUICK_LINKS.map((q) => (
          <Button
            key={q.labelKey}
            size="sm"
            variant={prefix === q.prefix ? 'default' : 'outline'}
            onClick={() => {
              setSelectedProjectId('');
              setPrefix(q.prefix);
            }}
            title={t(q.hintKey)}
          >
            <QuickIcon prefix={q.prefix} className="mr-1 h-3.5 w-3.5" />
            {t(q.labelKey)}
          </Button>
        ))}
      </section>

      {/* mission / session 二级筛选 */}
      <section className="mt-4 flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label>{t('storage.filterByMission')}</Label>
          <Select
            value={selectedProjectId}
            onChange={(e) => setSelectedProjectId(e.target.value)}
            className="w-64"
          >
            <option value="">{t('storage.allMissions')}</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.slug})
              </option>
            ))}
          </Select>
        </div>
        <div className="flex-1 space-y-1">
          <Label>{t('storage.prefixLabel')}</Label>
          <Input
            value={prefix}
            onChange={(e) => setPrefix(e.target.value)}
            placeholder="colony/workspace/"
          />
        </div>
      </section>

      {/* 面包屑 */}
      <section className="mt-4 flex flex-wrap items-center gap-1 rounded-md bg-background px-3 py-2 text-xs">
        <Home className="h-3.5 w-3.5 text-muted-foreground/70" />
        {breadcrumbs.map((bc, i) => (
          <span key={bc.prefix} className="flex items-center gap-1">
            {i > 0 && <ChevronRight className="h-3 w-3 text-muted-foreground/70" />}
            <button
              type="button"
              onClick={() => setPrefix(bc.prefix)}
              className="font-mono text-muted-foreground hover:text-primary"
            >
              {bc.label}
            </button>
          </span>
        ))}
        <span className="ml-auto text-muted-foreground/70">{t('storage.itemCount', { count: items.length })}</span>
      </section>

      {err && <p className="mt-4 rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}
      {items.length > 0 && (items[0] as { __truncated__?: boolean }).__truncated__ && (
        <p className="mt-2 rounded bg-warning/10 border border-warning/40 px-3 py-2 text-xs text-warning">
          {t('storage.truncatedWarning')}
        </p>
      )}

      <section className="mt-4 overflow-hidden rounded-lg border border-border bg-card">
        {loading ? (
          <p className="p-8 text-center text-sm text-muted-foreground/70">{t('common.loading')}</p>
        ) : items.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground/70">{t('storage.emptyPrefix')}</p>
        ) : (
          <div>
            {grouped.folders.length > 0 && (
              <div className="border-b border-border bg-background">
                <div className="px-4 py-2 text-[11px] uppercase tracking-wide text-muted-foreground/70">
                  {t('storage.subdirsCount', { count: grouped.folders.length })}
                </div>
                <ul className="divide-y divide-border">
                  {grouped.folders.map((f) => {
                    const childPrefix = prefix + f.name + '/';
                    return (
                      <li key={f.name}>
                        <button
                          type="button"
                          onClick={() => setPrefix(childPrefix)}
                          className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-accent/50"
                        >
                          <Folder className="h-3.5 w-3.5 text-primary" />
                          <span className="font-mono text-foreground">{f.name}/</span>
                          <span className="ml-auto text-xs text-muted-foreground/70">
                            {t('storage.fileCount', { count: f.count })}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
            {grouped.files.length > 0 && (
              <div>
                <div className="border-b border-border bg-background px-4 py-2 text-[11px] uppercase tracking-wide text-muted-foreground/70">
                  {t('storage.currentLevelFiles', { count: grouped.files.length })}
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground/70">
                      <th className="px-4 py-2 font-medium">{t('storage.colKey')}</th>
                      <th className="px-4 py-2 font-medium">{t('storage.colSize')}</th>
                      <th className="px-4 py-2 font-medium">{t('storage.colModified')}</th>
                      <th className="px-4 py-2 font-medium"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {grouped.files.map((o) => {
                      const rel = o.key.slice(prefix.length);
                      return (
                        <tr key={o.key} className="border-b border-border last:border-b-0 hover:bg-accent/50">
                          <td className="px-4 py-2.5 font-mono text-xs text-foreground" title={o.key}>{rel}</td>
                          <td className="px-4 py-2.5 text-muted-foreground">{formatSize(o.size)}</td>
                          <td className="px-4 py-2.5 text-xs text-muted-foreground/70">
                            {new Date(o.last_modified).toLocaleString()}
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Button size="sm" variant="ghost" onClick={() => handleDownload(o)}>
                                <Download className="h-3.5 w-3.5" />
                              </Button>
                              <Button size="sm" variant="ghost" onClick={() => handleDelete(o)}>
                                <Trash2 className="h-3.5 w-3.5 text-destructive" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function QuickIcon({ prefix, className }: { prefix: string; className?: string }) {
  if (prefix === '') return <HardDrive className={className} />;
  if (prefix.includes('workspace')) return <Folder className={className} />;
  if (prefix.includes('aux-image')) return <ImageIcon className={className} />;
  if (prefix.includes('users')) return <UsersIcon className={className} />;
  return <Folder className={className} />;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}
