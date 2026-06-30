'use client';

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Cloud, Download, Lock, Pencil, Plus, Trash2 } from 'lucide-react';
import { AxiosError } from 'axios';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useConfirm, useToast } from '@/components/providers/ConfirmProvider';
import { skillsApi } from '@/lib/api/skills';
import { clawhubApi } from '@/lib/api/clawhub';
import { pickSkillDesc } from '@/lib/skills/desc';
import type { SkillPublic, SkillType } from '@/types/skill';
import type { ClawhubSearchHit, InstalledItem } from '@/types/clawhub';

const EMPTY: SkillPublic | null = null;

export default function SkillsPage() {
  const { t, i18n } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const [items, setItems] = useState<SkillPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<SkillPublic | null>(EMPTY);
  const [open, setOpen] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      setItems(await skillsApi.list());
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('skills.loadFailed'));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  async function handleDelete(s: SkillPublic) {
    if (s.is_builtin) return;
    if (!(await confirm({ message: t('skills.confirmDelete', { name: s.name }), danger: true }))) return;
    try {
      await skillsApi.delete(s.id);
      await refresh();
    } catch (e) {
      toast(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('skills.deleteFailed'), 'error');
    }
  }

  const builtinCount = items.filter((s) => s.is_builtin).length;
  const customCount = items.length - builtinCount;

  return (
    <div className="mx-auto max-w-6xl px-8 py-10">
      <header className="flex items-center justify-between border-b border-border pb-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">{t('skills.title')}</h1>
          <p className="mt-1 text-sm text-muted-foreground/70">
            {t('skills.countSummary', { builtin: builtinCount, custom: customCount })}
          </p>
        </div>
        <Button
          onClick={() => {
            setEditing(null);
            setOpen(true);
          }}
        >
          <Plus className="mr-2 h-4 w-4" />
          {t('skills.newSkill')}
        </Button>
      </header>

      {err && <p className="mt-4 rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}

      <ClawhubBrowser onInstalled={refresh} />

      <section className="mt-6 overflow-hidden rounded-lg border border-border bg-card">
        {loading ? (
          <p className="p-8 text-center text-sm text-muted-foreground/70">{t('common.loading')}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground/70">
                <th className="px-4 py-2.5 font-medium">{t('skills.colName')}</th>
                <th className="px-4 py-2.5 font-medium">{t('skills.colSlug')}</th>
                <th className="px-4 py-2.5 font-medium">{t('skills.colType')}</th>
                <th className="px-4 py-2.5 font-medium">{t('skills.colStatus')}</th>
                <th className="px-4 py-2.5 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.id} className="border-b border-border last:border-b-0 hover:bg-accent/50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 font-medium text-foreground">
                      {s.name}
                      {s.is_builtin && <Lock className="h-3.5 w-3.5 text-muted-foreground/70" />}
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground/70">{pickSkillDesc(s, i18n.language) || '—'}</p>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{s.slug}</td>
                  <td className="px-4 py-3">
                    <Badge variant={s.skill_type === 'instruction' ? 'secondary' : 'default'}>
                      {s.skill_type}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={s.is_enabled ? 'success' : 'secondary'}>
                      {s.is_enabled ? t('skills.statusEnabled') : t('skills.statusDisabled')}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
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
                      {!s.is_builtin && (
                        <Button size="sm" variant="ghost" onClick={() => handleDelete(s)}>
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <SkillDialog open={open} onClose={() => setOpen(false)} initial={editing} onSaved={refresh} />
    </div>
  );
}

interface DialogProps {
  open: boolean;
  onClose: () => void;
  initial: SkillPublic | null;
  onSaved: () => Promise<void> | void;
}

function SkillDialog({ open, onClose, initial, onSaved }: DialogProps) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [description, setDescription] = useState('');
  const [descriptionEn, setDescriptionEn] = useState('');
  const [skillType, setSkillType] = useState<SkillType>('instruction');
  const [contentMd, setContentMd] = useState('');
  const [builtinRef, setBuiltinRef] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setErr(null);
    if (initial) {
      setName(initial.name);
      setSlug(initial.slug);
      setDescription(initial.description);
      setDescriptionEn(initial.description_en ?? '');
      setSkillType(initial.skill_type);
      setContentMd(initial.content_md);
      setBuiltinRef(initial.builtin_ref ?? '');
      setEnabled(initial.is_enabled);
    } else {
      setName('');
      setSlug('');
      setDescription('');
      setDescriptionEn('');
      setSkillType('instruction');
      setContentMd('');
      setBuiltinRef('');
      setEnabled(true);
    }
  }, [open, initial]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setErr(null);
    try {
      if (initial) {
        // Builtin skills: only is_enabled + the (additive) English description are editable.
        if (initial.is_builtin) {
          await skillsApi.update(initial.id, {
            is_enabled: enabled,
            description_en: descriptionEn || null,
          });
        } else {
          await skillsApi.update(initial.id, {
            name,
            description,
            description_en: descriptionEn || null,
            content_md: contentMd,
            is_enabled: enabled,
          });
        }
      } else {
        await skillsApi.create({
          name,
          slug,
          description,
          description_en: descriptionEn || null,
          skill_type: skillType,
          content_md: contentMd,
          builtin_ref: skillType === 'tool_builtin' ? builtinRef : null,
          is_enabled: enabled,
        });
      }
      await onSaved();
      onClose();
    } catch (e) {
      setErr(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('skills.saveFailed'));
    } finally {
      setSubmitting(false);
    }
  }

  const readonlyFields = !!initial?.is_builtin;

  return (
    <Dialog open={open} onClose={onClose} title={initial ? t('skills.editSkill') : t('skills.newSkill')} className="max-w-2xl">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>{t('skills.fieldName')}</Label>
            <Input value={name} disabled={readonlyFields} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="space-y-2">
            <Label>{t('skills.colSlug')}</Label>
            <Input
              value={slug}
              disabled={!!initial}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="workspace_write"
              required
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label>{t('skills.fieldDescription')}</Label>
          <Input value={description} disabled={readonlyFields} onChange={(e) => setDescription(e.target.value)} />
        </div>

        <div className="space-y-2">
          <Label>{t('skills.fieldDescriptionEn')}</Label>
          <Input
            value={descriptionEn}
            onChange={(e) => setDescriptionEn(e.target.value)}
            placeholder={t('skills.fieldDescriptionEnPlaceholder')}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>{t('skills.fieldType')}</Label>
            <Select
              value={skillType}
              disabled={!!initial}
              onChange={(e) => setSkillType(e.target.value as SkillType)}
            >
              <option value="instruction">{t('skills.typeInstruction')}</option>
              <option value="tool_builtin">{t('skills.typeToolBuiltin')}</option>
            </Select>
          </div>
          {skillType === 'tool_builtin' && !initial && (
            <div className="space-y-2">
              <Label>{t('skills.fieldBuiltinRef')}</Label>
              <Input
                value={builtinRef}
                onChange={(e) => setBuiltinRef(e.target.value)}
                placeholder="workspace_read"
                required
              />
            </div>
          )}
        </div>

        {skillType === 'instruction' && (
          <div className="space-y-2">
            <Label>SKILL.md</Label>
            <Textarea
              value={contentMd}
              disabled={readonlyFields}
              onChange={(e) => setContentMd(e.target.value)}
              rows={10}
              placeholder={`---\nname: my-skill\n---\n\n${t('skills.skillMdPlaceholder')}`}
            />
          </div>
        )}

        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          {t('skills.enable')}
        </label>

        {err && <p className="rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={submitting}>
            {submitting ? t('skills.saving') : t('common.save')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

// ───────────────────────────── ClawhubBrowser ─────────────────────────────

function ClawhubBrowser({ onInstalled }: { onInstalled: () => Promise<void> | void }) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<ClawhubSearchHit[]>([]);
  const [installed, setInstalled] = useState<InstalledItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);
  const [installMsg, setInstallMsg] = useState<string | null>(null);
  const [installOk, setInstallOk] = useState(true);

  useEffect(() => {
    clawhubApi
      .listInstalled()
      .then(setInstalled)
      .catch((e) => console.warn('listInstalled failed', e));
  }, []);

  async function doSearch(e?: React.FormEvent) {
    e?.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setErr(null);
    setInstallMsg(null);
    try {
      const res = await clawhubApi.search(query.trim(), 20);
      // results 可能是 array 或 object 形态；只取 array
      const arr = Array.isArray(res.results) ? (res.results as ClawhubSearchHit[]) : [];
      setHits(arr);
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('skills.searchFailed'));
    } finally {
      setSearching(false);
    }
  }

  async function doInstall(hit: ClawhubSearchHit, forceHighRisk = false) {
    setInstalling(hit.slug);
    setInstallMsg(null);
    setErr(null);
    try {
      const res = await clawhubApi.install({ slug: hit.slug, force_high_risk: forceHighRisk });
      if (res.ok) {
        setInstallOk(true);
        setInstallMsg(
          t('skills.installSuccess', {
            slug: hit.slug,
            kind: res.runtime_kind,
            installId: res.install_id,
          }),
        );
        const fresh = await clawhubApi.listInstalled();
        setInstalled(fresh);
        await onInstalled();
      } else if (res.needs_approval) {
        if (await confirm({ message: t('skills.confirmHighRisk', { error: res.error }), danger: true })) {
          await doInstall(hit, true);
          return;
        } else {
          setInstallOk(false);
          setInstallMsg(t('skills.installCancelled'));
        }
      } else if (res.blocked) {
        setInstallOk(false);
        setInstallMsg(t('skills.installBlocked', { error: res.error }));
      } else {
        setInstallOk(false);
        setInstallMsg(t('skills.installFailedMsg', { error: res.error }));
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('skills.installFailed'));
    } finally {
      setInstalling(null);
    }
  }

  async function doUninstall(item: InstalledItem) {
    if (!(await confirm({ message: t('skills.confirmUninstall', { slug: item.slug, version: item.version }), danger: true }))) return;
    try {
      await clawhubApi.uninstall(item.install_id);
      const fresh = await clawhubApi.listInstalled();
      setInstalled(fresh);
      await onInstalled();
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('skills.uninstallFailed'));
    }
  }

  return (
    <section className="mt-6 rounded-lg border border-border bg-card p-5">
      <div className="flex items-center gap-2 border-b border-border pb-3">
        <Cloud className="h-4 w-4 text-muted-foreground/70" />
        <h2 className="text-sm font-semibold text-foreground">{t('skills.clawhubTitle')}</h2>
        <span className="text-xs text-muted-foreground/70">{t('skills.clawhubSubtitle')}</span>
      </div>

      <form onSubmit={doSearch} className="mt-3 flex gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('skills.searchPlaceholder')}
          className="flex-1"
        />
        <Button type="submit" disabled={searching || !query.trim()}>
          {searching ? t('skills.searching') : t('skills.search')}
        </Button>
      </form>

      {err && <p className="mt-3 rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}
      {installMsg && (
        <p className={`mt-3 rounded px-3 py-2 text-sm ${installOk ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning'}`}>
          {installMsg}
        </p>
      )}

      {hits.length > 0 && (
        <div className="mt-4 divide-y divide-border rounded-md border border-border">
          {hits.map((h) => (
            <div key={h.slug} className="flex items-start justify-between gap-3 px-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-foreground">{h.displayName ?? h.slug}</span>
                  <span className="font-mono text-[11px] text-muted-foreground/70">{h.slug}</span>
                  {h.latestVersion && (
                    <span className="font-mono text-[11px] text-muted-foreground/70">@{h.latestVersion}</span>
                  )}
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground/70 line-clamp-2">{h.summary ?? ''}</p>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={installing === h.slug}
                onClick={() => doInstall(h)}
              >
                <Download className="mr-1 h-3.5 w-3.5" />
                {installing === h.slug ? t('skills.installing') : t('skills.install')}
              </Button>
            </div>
          ))}
        </div>
      )}

      {installed.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-2 text-xs uppercase tracking-wide text-muted-foreground/70">{t('skills.installed')}</h3>
          <div className="divide-y divide-border rounded-md border border-border">
            {installed.map((it) => (
              <div key={it.install_id} className="flex items-center justify-between gap-3 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-foreground">{it.slug}</span>
                    <span className="font-mono text-[11px] text-muted-foreground/70">@{it.version}</span>
                    <Badge variant="secondary">{it.runtime_kind}</Badge>
                  </div>
                  {it.capability_tags.length > 0 && (
                    <p className="mt-1 text-[11px] text-warning">
                      {t('skills.capabilities', { tags: it.capability_tags.join(', ') })}
                    </p>
                  )}
                </div>
                <Button size="sm" variant="ghost" onClick={() => doUninstall(it)}>
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
