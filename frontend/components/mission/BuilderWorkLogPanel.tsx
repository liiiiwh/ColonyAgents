'use client';

/**
 * ADR-009 G5 · Builder per-session 工作记录面板。
 *
 * 显示 build_super/build_worker/install_skill/resume 等 mutation 审计行：
 * 建/升了什么、影响了哪些 super、结果（ok/blocked/failed）。可按当前 session 过滤。
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ClipboardList, AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';
import { superConversationApi, type BuilderWorkLogItem } from '@/lib/api/superConversation';

const RESULT_ICON: Record<string, React.ReactNode> = {
  ok: <CheckCircle2 className="w-3 h-3 text-success" />,
  blocked: <AlertTriangle className="w-3 h-3 text-warning" />,
  failed: <XCircle className="w-3 h-3 text-destructive" />,
};

export function BuilderWorkLogPanel({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const [items, setItems] = useState<BuilderWorkLogItem[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    superConversationApi
      .workLog(slug)
      .then((r) => {
        if (alive) {
          setItems(r.items || []);
          setLoaded(true);
        }
      })
      .catch(() => alive && setLoaded(true));
    return () => {
      alive = false;
    };
  }, [slug]);

  if (!loaded || items.length === 0) return null; // 仅在有记录时显示（对非 Builder super 自然为空）

  return (
    <div className="border-t border-border p-3">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground mb-2">
        <ClipboardList className="w-3.5 h-3.5" />
        {t('missionCards.workLogTitle', { count: items.length })}
      </div>
      <div className="space-y-1.5 max-h-72 overflow-y-auto">
        {items.map((it) => (
          <div key={it.id} className="rounded border border-border bg-card px-2 py-1.5 text-[11px] text-foreground">
            <div className="flex items-center gap-1.5">
              {RESULT_ICON[it.result] ?? null}
              <span className="font-medium">{it.action}</span>
              <span className="text-muted-foreground">
                {it.target_type}:{it.target_id}
              </span>
              <span className="ml-auto text-[10px] text-muted-foreground/70">
                {it.created_at?.slice(5, 16)?.replace('T', ' ')}
              </span>
            </div>
            {it.summary && (
              <div className="mt-0.5 text-muted-foreground break-words">{it.summary.slice(0, 240)}</div>
            )}
            {it.affected_supers.length > 0 && (
              <div className="mt-0.5 text-warning">
                {t('missionCards.workLogAffected', { supers: it.affected_supers.join('、') })}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
