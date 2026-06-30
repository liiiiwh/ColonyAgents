'use client';

/**
 * v5 · Memory viewer + editor (feature-flagged) + revisions diff/revert
 *
 * 默认 viewer + clear；admin 打开 memory_edit_enabled 后才能编辑/revert。
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Eraser, History, Lock, RefreshCw, Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { errMessage } from '@/lib/errors';
import { useConfirm } from '@/components/providers/ConfirmProvider';
import { cleanThreadKey } from '@/lib/chat/threadLabel';

type MemView = {
  mission_id: string;
  super_agent_id: string;
  project_memory: {
    id: string;
    agent_node_name: string;
    memory_md: string;
    fingerprint_count: number;
    updated_at: string | null;
  } | null;
  branch_memories: Array<{
    id: string;
    thread_key: string;
    agent_node_name: string;
    memory_md: string;
    compressed_message_count: number;
    last_compressed_at: string | null;
  }>;
};

type Revision = {
  id: string;
  memory_id: string;
  memory_md: string;
  memory_md_preview: string;
  memory_md_size: number;
  edited_by: string | null;
  edited_at: string | null;
  reason: string | null;
  is_clear_op: boolean;
};

export function MemoryTab({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [view, setView] = useState<MemView | null>(null);
  const [revs, setRevs] = useState<Revision[]>([]);
  const [loading, setLoading] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [draft, setDraft] = useState('');
  const [reason, setReason] = useState('');
  const [showRev, setShowRev] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      const v = await api.get<MemView>(`/api/super/${slug}/memory`).then((r) => r.data);
      setView(v);
      setDraft(v.project_memory?.memory_md || '');
      const r = await api
        .get<Revision[]>(`/api/super/${slug}/memory/revisions`)
        .then((r) => r.data);
      setRevs(r);
    } catch (e) {
      setErr(errMessage(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  async function clearMemory() {
    if (!(await confirm({ message: t('superPanel.memoryClearConfirm'), danger: true }))) return;
    try {
      const r = reason.trim() || t('superPanel.memoryClearDefaultReason');
      await api.post(`/api/super/${slug}/memory/clear`, { reason: r });
      setToast(t('superPanel.memoryClearedToast'));
      setTimeout(() => setToast(null), 3000);
      setReason('');
      await refresh();
    } catch (e) {
      setErr(errMessage(e));
    }
  }

  async function saveDraft() {
    if (!reason.trim()) {
      setErr(t('superPanel.memoryReasonRequired'));
      return;
    }
    try {
      await api.patch(`/api/super/${slug}/memory`, {
        memory_md: draft,
        reason: reason.trim(),
      });
      setToast(t('superPanel.memorySavedToast'));
      setTimeout(() => setToast(null), 3000);
      setEditMode(false);
      setReason('');
      await refresh();
    } catch (e) {
      setErr(errMessage(e));
    }
  }

  async function revertTo(rev: Revision) {
    if (!(await confirm({ message: t('superPanel.memoryRevertConfirm', { time: rev.edited_at?.slice(0, 19) || '?' }), danger: true }))) return;
    try {
      await api.post(`/api/super/${slug}/memory/revisions/${rev.id}/revert`);
      setToast(t('superPanel.memoryRevertedToast'));
      setTimeout(() => setToast(null), 3000);
      await refresh();
    } catch (e) {
      setErr(errMessage(e));
    }
  }

  return (
    <div className="p-3 space-y-3 text-sm">
      <header className="flex items-center gap-2">
        <h2 className="font-semibold text-foreground">{t('superPanel.memoryTitle', { slug })}</h2>
        <Button size="sm" variant="ghost" onClick={() => void refresh()} disabled={loading}>
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </Button>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setShowRev((v) => !v)}>
            <History className="w-3.5 h-3.5 mr-1" /> {t('superPanel.memoryRevisions')} ({revs.length})
          </Button>
          <Button size="sm" variant="outline" onClick={() => setEditMode((v) => !v)}>
            <Save className="w-3.5 h-3.5 mr-1" /> {editMode ? t('superPanel.memoryCancelEdit') : t('common.edit')}
          </Button>
          <Button size="sm" variant="destructive" onClick={() => void clearMemory()}>
            <Eraser className="w-3.5 h-3.5 mr-1" /> {t('superPanel.memoryClear')}
          </Button>
        </div>
      </header>

      {toast && (
        <div className="text-xs bg-success/10 text-success p-2 rounded border border-success/40">
          {toast}
        </div>
      )}
      {err && (
        <div className="text-xs bg-destructive/10 text-destructive p-2 rounded border border-destructive/40 flex items-start gap-2">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5" />
          <div>{err}</div>
        </div>
      )}

      {/* Project memory (super long-term memory) */}
      <section className="border border-border rounded p-2 bg-card">
        <div className="text-xs text-muted-foreground mb-1">
          {t('superPanel.memoryProjectLabel')}
          {view?.project_memory?.updated_at && (
            <span className="ml-2">{t('superPanel.memoryUpdated', { time: view.project_memory.updated_at.slice(0, 19) })}</span>
          )}
        </div>
        {!view?.project_memory ? (
          <div className="text-xs text-muted-foreground/70 italic p-2">{t('superPanel.memoryNoLongTerm')}</div>
        ) : editMode ? (
          <div className="space-y-2">
            <textarea
              className="w-full h-64 p-2 font-mono text-xs border border-border rounded bg-background text-foreground"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <input
              className="w-full p-1.5 text-xs border border-border rounded bg-background text-foreground"
              placeholder={t('superPanel.memoryReasonPlaceholder')}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <div className="flex gap-2 justify-end">
              <Button size="sm" onClick={() => void saveDraft()}>
                <Save className="w-3.5 h-3.5 mr-1" /> {t('superPanel.memorySaveNewVersion')}
              </Button>
            </div>
            <p className="text-[10px] text-warning flex items-center gap-1">
              <Lock className="w-3 h-3" /> {t('superPanel.memoryEditFlagHint')}
            </p>
          </div>
        ) : (
          <pre className="whitespace-pre-wrap break-words text-xs font-mono p-2 bg-muted text-foreground rounded max-h-[60vh] overflow-auto">
            {view.project_memory.memory_md || t('superPanel.memoryEmptyValue')}
          </pre>
        )}
      </section>

      {/* Revisions */}
      {showRev && (
        <section className="border border-border rounded p-2 bg-card">
          <div className="text-xs font-semibold mb-2 text-foreground">{t('superPanel.memoryRevisionsRecent', { count: revs.length })}</div>
          {revs.length === 0 ? (
            <div className="text-xs text-muted-foreground/70 italic">{t('superPanel.memoryNoRevisions')}</div>
          ) : (
            <div className="space-y-1.5 max-h-96 overflow-auto">
              {revs.map((r) => (
                <div key={r.id} className="border border-border rounded p-1.5 text-xs">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className={r.is_clear_op ? 'text-destructive' : ''}>
                      {r.is_clear_op ? t('superPanel.memoryOpClear') : t('superPanel.memoryOpEdit')}
                    </span>
                    <span className="text-muted-foreground">{r.edited_at?.slice(0, 19)}</span>
                    <span className="text-muted-foreground truncate flex-1">
                      {t('superPanel.memoryReasonLabel', { reason: r.reason || t('superPanel.memoryReasonNone') })}
                    </span>
                    <span className="text-[10px] text-muted-foreground/70">{r.memory_md_size}B</span>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-6 px-1.5"
                      onClick={() => void revertTo(r)}
                    >
                      {t('superPanel.memoryRevert')}
                    </Button>
                  </div>
                  <pre className="whitespace-pre-wrap break-words text-[10px] font-mono text-muted-foreground bg-muted p-1 rounded max-h-20 overflow-auto">
                    {r.memory_md_preview}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Branch memories (thread compressed summaries) */}
      <section className="border border-border rounded p-2 bg-card">
        <div className="text-xs font-semibold mb-2 text-foreground">
          {t('superPanel.memoryBranchLabel', { count: view?.branch_memories.length || 0 })}
        </div>
        {(view?.branch_memories || []).length === 0 ? (
          <div className="text-xs text-muted-foreground/70 italic">{t('superPanel.memoryNoBranchSummaries')}</div>
        ) : (
          <div className="space-y-1 max-h-72 overflow-auto">
            {view!.branch_memories.map((b) => (
              <details key={b.id} className="border border-border rounded p-1.5 text-xs">
                <summary className="cursor-pointer text-foreground">
                  <span className="font-mono">{cleanThreadKey(b.thread_key)}</span>
                  <span className="text-muted-foreground ml-2">
                    {t('superPanel.memoryMsgsCount', { count: b.compressed_message_count })}
                  </span>
                  {b.last_compressed_at && (
                    <span className="text-muted-foreground ml-2">{b.last_compressed_at.slice(0, 19)}</span>
                  )}
                </summary>
                <pre className="whitespace-pre-wrap break-words font-mono text-[10px] mt-1 p-1 bg-muted rounded max-h-40 overflow-auto">
                  {b.memory_md}
                </pre>
              </details>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
