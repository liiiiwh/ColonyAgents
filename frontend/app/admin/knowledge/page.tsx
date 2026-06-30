'use client';

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AxiosError } from 'axios';
import { Database, FileText, Plus, Search, Trash2, Upload } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useConfirm, useToast } from '@/components/providers/ConfirmProvider';
import { knowledgeApi } from '@/lib/api/storage';
import { providersApi } from '@/lib/api/providers';
import type { LLMModelPublic, ProviderPublic } from '@/types/provider';
import type { DocumentPublic, KnowledgeBasePublic, SearchHit } from '@/types/storage';

export default function KnowledgePage() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const [kbs, setKbs] = useState<KnowledgeBasePublic[]>([]);
  const [selected, setSelected] = useState<KnowledgeBasePublic | null>(null);
  const [docs, setDocs] = useState<DocumentPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [newKbOpen, setNewKbOpen] = useState(false);
  const [indexOpen, setIndexOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchHits, setSearchHits] = useState<SearchHit[]>([]);
  const [searching, setSearching] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const list = await knowledgeApi.list();
      setKbs(list);
      if (selected && !list.find((k) => k.id === selected.id)) {
        setSelected(null);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('knowledge.loadFailed'));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) {
      setDocs([]);
      return;
    }
    knowledgeApi.listDocs(selected.id).then(setDocs);
  }, [selected]);

  async function handleDeleteKb(kb: KnowledgeBasePublic) {
    if (!(await confirm({ message: t('knowledge.confirmDeleteKb', { name: kb.name }), danger: true }))) return;
    await knowledgeApi.delete(kb.id);
    await refresh();
  }

  async function handleDeleteDoc(doc: DocumentPublic) {
    if (!selected) return;
    if (!(await confirm({ message: t('knowledge.confirmDeleteDoc', { name: doc.filename }), danger: true }))) return;
    await knowledgeApi.deleteDoc(selected.id, doc.id);
    setDocs(await knowledgeApi.listDocs(selected.id));
  }

  async function handleSearch() {
    if (!selected || !searchQuery.trim()) return;
    setSearching(true);
    try {
      const hits = await knowledgeApi.search(selected.id, searchQuery);
      setSearchHits(hits);
    } catch (e) {
      toast(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('knowledge.searchFailed'), 'error');
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-8 py-10">
      <header className="flex items-center justify-between border-b border-border pb-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">{t('knowledge.title')}</h1>
          <p className="mt-1 text-sm text-muted-foreground/70">{t('knowledge.subtitle')}</p>
        </div>
        <Button onClick={() => setNewKbOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          {t('knowledge.newKb')}
        </Button>
      </header>

      {err && <p className="mt-4 rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}

      <section className="mt-6 grid grid-cols-[280px_1fr] gap-4">
        <aside className="rounded-lg border border-border bg-card">
          <div className="border-b border-border px-3 py-2.5 text-xs font-medium uppercase tracking-wide text-muted-foreground/70">
            {t('knowledge.countTotal', { count: kbs.length })}
          </div>
          {loading ? (
            <p className="p-6 text-center text-sm text-muted-foreground/70">{t('common.loading')}</p>
          ) : kbs.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground/70">{t('knowledge.emptyKbs')}</p>
          ) : (
            <ul>
              {kbs.map((kb) => (
                <li key={kb.id}>
                  <button
                    onClick={() => setSelected(kb)}
                    className={`flex w-full items-start gap-2 px-3 py-2.5 text-left text-sm transition-colors ${
                      selected?.id === kb.id ? 'bg-muted' : 'hover:bg-accent/50'
                    }`}
                  >
                    <Database className="mt-0.5 h-4 w-4 text-muted-foreground/70" />
                    <div className="flex-1">
                      <p className="font-medium text-foreground">{kb.name}</p>
                      <p className="mt-0.5 font-mono text-xs text-muted-foreground/70">{kb.collection_name}</p>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <div className="rounded-lg border border-border bg-card">
          {!selected ? (
            <p className="p-10 text-center text-sm text-muted-foreground/70">{t('knowledge.selectKb')}</p>
          ) : (
            <div>
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <div>
                  <h2 className="text-sm font-semibold text-foreground">{selected.name}</h2>
                  <p className="mt-0.5 text-xs text-muted-foreground/70">{selected.description || '—'}</p>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => setIndexOpen(true)}>
                    <Upload className="mr-1.5 h-3.5 w-3.5" />
                    {t('knowledge.indexDoc')}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => handleDeleteKb(selected)}>
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />
                  </Button>
                </div>
              </div>

              {/* document list */}
              <section className="p-4">
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground/70">{t('knowledge.documents')}</h3>
                {docs.length === 0 ? (
                  <p className="text-xs text-muted-foreground/70">{t('knowledge.emptyDocs')}</p>
                ) : (
                  <ul className="space-y-1">
                    {docs.map((d) => (
                      <li key={d.id} className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-xs">
                        <div className="flex items-center gap-2">
                          <FileText className="h-3.5 w-3.5 text-muted-foreground/70" />
                          <span className="font-medium text-foreground">{d.filename}</span>
                          <Badge variant="secondary">{t('knowledge.chunkCount', { count: d.chunk_count })}</Badge>
                          <Badge
                            variant={d.status === 'indexed' ? 'success' : d.status === 'failed' ? 'destructive' : 'warning'}
                          >
                            {d.status}
                          </Badge>
                        </div>
                        <Button size="sm" variant="ghost" onClick={() => handleDeleteDoc(d)}>
                          <Trash2 className="h-3 w-3 text-destructive" />
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* search test */}
              <section className="border-t border-border p-4">
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground/70">{t('knowledge.searchTest')}</h3>
                <div className="flex gap-2">
                  <Input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t('knowledge.searchPlaceholder')}
                    onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                  />
                  <Button onClick={handleSearch} disabled={searching || !searchQuery.trim()}>
                    <Search className="mr-1.5 h-3.5 w-3.5" />
                    {searching ? t('knowledge.searching') : t('knowledge.search')}
                  </Button>
                </div>
                {searchHits.length > 0 && (
                  <ul className="mt-3 space-y-2">
                    {searchHits.map((h, i) => (
                      <li key={i} className="rounded-md border border-border p-3 text-xs">
                        <div className="mb-1 flex items-center gap-2 text-muted-foreground/70">
                          <Badge variant="secondary">#{i + 1}</Badge>
                          <span className="font-mono">score = {h.score.toFixed(4)}</span>
                        </div>
                        <p className="whitespace-pre-wrap text-foreground">
                          {h.content.slice(0, 300)}
                          {h.content.length > 300 ? '…' : ''}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          )}
        </div>
      </section>

      <NewKbDialog open={newKbOpen} onClose={() => setNewKbOpen(false)} onSaved={refresh} />
      {selected && (
        <IndexDocDialog
          open={indexOpen}
          onClose={() => setIndexOpen(false)}
          kbId={selected.id}
          onSaved={async () => {
            setDocs(await knowledgeApi.listDocs(selected.id));
          }}
        />
      )}
    </div>
  );
}

function NewKbDialog({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [collectionName, setCollectionName] = useState('');
  const [desc, setDesc] = useState('');
  const [providers, setProviders] = useState<ProviderPublic[]>([]);
  const [providerId, setProviderId] = useState('');
  const [embeddingModels, setEmbeddingModels] = useState<LLMModelPublic[]>([]);
  const [embeddingModelId, setEmbeddingModelId] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setErr(null);
    setName('');
    setCollectionName('');
    setDesc('');
    providersApi.list().then((ps) => {
      const enabled = ps.filter((p) => p.is_enabled);
      setProviders(enabled);
      setProviderId(enabled[0]?.id ?? '');
    });
  }, [open]);

  useEffect(() => {
    if (!providerId) {
      setEmbeddingModels([]);
      setEmbeddingModelId('');
      return;
    }
    providersApi.listModels(providerId).then((ms) => {
      const embed = ms.filter((m) => m.model_type === 'embedding' && m.is_enabled);
      setEmbeddingModels(embed);
      setEmbeddingModelId(embed[0]?.id ?? '');
    });
  }, [providerId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setSubmitting(true);
    try {
      await knowledgeApi.create({
        name,
        collection_name: collectionName,
        description: desc,
        embedding_model_id: embeddingModelId,
      });
      await onSaved();
      onClose();
    } catch (e) {
      setErr(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('knowledge.createFailed'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t('knowledge.newKb')}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label>{t('knowledge.fieldName')}</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div className="space-y-2">
          <Label>{t('knowledge.fieldCollection')}</Label>
          <Input
            value={collectionName}
            onChange={(e) => setCollectionName(e.target.value)}
            pattern="^[a-z0-9][a-z0-9_]*$"
            placeholder="toy_materials"
            required
          />
        </div>
        <div className="space-y-2">
          <Label>{t('knowledge.fieldDescription')}</Label>
          <Input value={desc} onChange={(e) => setDesc(e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>{t('knowledge.fieldProvider')}</Label>
            <Select value={providerId} onChange={(e) => setProviderId(e.target.value)} required>
              <option value="">{t('knowledge.optionSelect')}</option>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-2">
            <Label>{t('knowledge.fieldEmbeddingModel')}</Label>
            <Select
              value={embeddingModelId}
              onChange={(e) => setEmbeddingModelId(e.target.value)}
              disabled={!providerId}
              required
            >
              {embeddingModels.length === 0 && <option value="">{t('knowledge.optionNone')}</option>}
              {embeddingModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.display_name}
                </option>
              ))}
            </Select>
          </div>
        </div>

        {err && <p className="rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={submitting || !embeddingModelId}>
            {submitting ? t('knowledge.creating') : t('common.create')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function IndexDocDialog({
  open,
  onClose,
  kbId,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  kbId: string;
  onSaved: () => Promise<void> | void;
}) {
  const { t } = useTranslation();
  const [filename, setFilename] = useState('');
  const [content, setContent] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setFilename('');
    setContent('');
    setErr(null);
  }, [open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setSubmitting(true);
    try {
      await knowledgeApi.index(kbId, filename, content);
      await onSaved();
      onClose();
    } catch (e) {
      setErr(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('knowledge.indexFailed'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t('knowledge.indexDocTitle')} className="max-w-2xl">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label>{t('knowledge.fieldFilename')}</Label>
          <Input value={filename} onChange={(e) => setFilename(e.target.value)} required />
        </div>
        <div className="space-y-2">
          <Label>{t('knowledge.fieldContent')}</Label>
          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={10}
            required
          />
        </div>

        {err && <p className="rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={submitting}>
            {submitting ? t('knowledge.indexing') : t('knowledge.indexAction')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
