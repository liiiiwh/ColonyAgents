'use client';

/**
 * ADR-008 P1 · 消息驱动的 tick 折叠卡（替代 V7.4 退役的 agent_activities 驱动 ChatTickCard）。
 *
 * 同 turn_id 的 daemon tick 消息（agent_log 追踪 + assistant 回复）折叠成一张卡：
 *   折叠态：只看 super 的回复 + 「⚙ N 步」摘要按钮
 *   展开态：复用 lib/chat/timeline.ts:toTimeline 重建的每步（tool / thinking / subtask / batch）
 *
 * 修 V7.4 regression：daemon 流式 agent_log 不再平铺刷屏。
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Cog, Loader2 } from 'lucide-react';
import { foldTicks } from '@/lib/chat/ticks';
import type { MessageLike, TimelineItem } from '@/lib/chat/timeline';

function StepView({ item }: { item: TimelineItem }) {
  const { t } = useTranslation();
  switch (item.kind) {
    case 'tool':
      return (
        <div className="rounded border border-border bg-muted/40 px-2 py-1">
          <div className="flex items-center gap-1 text-[11px] font-medium text-foreground">
            {item.state === 'running' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Cog className="w-3 h-3" />}
            <span>{item.name}</span>
          </div>
          {item.input != null && (
            <pre className="mt-0.5 whitespace-pre-wrap break-words text-[10px] text-muted-foreground">
              {JSON.stringify(item.input).slice(0, 400)}
            </pre>
          )}
          {item.output && (
            <pre className="mt-0.5 whitespace-pre-wrap break-words text-[10px] text-muted-foreground">
              → {item.output.slice(0, 600)}
            </pre>
          )}
        </div>
      );
    case 'thinking':
      return (
        <div className="rounded border border-dashed border-border px-2 py-1 text-[11px] italic text-muted-foreground">
          💭 {item.content.slice(0, 600)}
        </div>
      );
    case 'subtask':
      return (
        <div className="rounded border border-border bg-muted/40 px-2 py-1 text-[11px] text-foreground">
          🧩 {item.worker} · {item.task.slice(0, 120)}
          {item.summary && <span className="text-muted-foreground"> → {item.summary.slice(0, 200)}</span>}
        </div>
      );
    case 'batch':
      return (
        <div className="rounded border border-border bg-muted/40 px-2 py-1 text-[11px] text-foreground">
          📦{' '}
          {item.state === 'done'
            ? t('missionCards.parallelSubtasksDone', {
                total: item.total,
                ok: item.ok ?? 0,
                failed: item.failed ?? 0,
              })
            : t('missionCards.parallelSubtasksRunning', { total: item.total })}
        </div>
      );
    default:
      return null;
  }
}

export function MessageTickCard({ messages }: { messages: MessageLike[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const rows = foldTicks(messages);
  const tick = rows.find((r) => r.kind === 'tick');
  if (!tick || tick.kind !== 'tick') return null;
  const { steps, reply, stepCount } = tick;

  return (
    <div className="max-w-3xl rounded border border-border bg-card text-sm text-foreground">
      {/* 折叠态头：N 步 摘要 + 展开 */}
      <button
        className="flex w-full items-center gap-1.5 px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent/50"
        onClick={() => setOpen((v) => !v)}
        disabled={stepCount === 0}
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <Cog className="w-3 h-3" />
        <span>
          {reply
            ? t('missionCards.superRanRound', { count: stepCount })
            : t('missionCards.superRanRoundRunning', { count: stepCount })}
        </span>
      </button>

      {/* 展开态：每步明细 */}
      {open && stepCount > 0 && (
        <div className="space-y-1 border-t border-border px-2 py-1.5">
          {steps.map((s, i) => (
            <StepView key={`${tick.turnId}-${i}`} item={s} />
          ))}
        </div>
      )}

      {/* 回复（折叠态也可见） */}
      {reply && reply.kind === 'assistant' && (
        <div className="border-t border-border px-2 py-1.5">
          <pre className="whitespace-pre-wrap break-words text-xs">{(reply.content || '').slice(0, 4000)}</pre>
        </div>
      )}
    </div>
  );
}
