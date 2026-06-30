'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import { Activity, BarChart3, Code2, History, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  observeV3Api,
  type WorkerArtifact,
  type WorkerDetail,
  type WorkerInvocation,
  type WorkerOverride,
  type WorkerStats,
} from '@/lib/api/observeV3';

/** Worker cross-mission aggregated observation page.
 *  Dashboard: invocations / success rate / avg latency / token usage / active missions.
 *  Tabs: invocation list / artifacts / config & versions / performance & failure analysis.
 */
export default function WorkerObservePage() {
  const { t } = useTranslation();
  const params = useParams<{ id: string }>();
  const workerId = params.id;
  const [detail, setDetail] = useState<WorkerDetail | null>(null);
  const [stats, setStats] = useState<WorkerStats | null>(null);
  const [invocations, setInvocations] = useState<WorkerInvocation[]>([]);
  const [overrides, setOverrides] = useState<WorkerOverride[]>([]);
  const [artifacts, setArtifacts] = useState<WorkerArtifact[]>([]);
  const [tab, setTab] = useState<'list' | 'artifacts' | 'config' | 'perf'>('list');
  const [window, setWindow] = useState<'1d' | '7d' | '30d' | 'all'>('7d');
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const [d, s, inv, ov, art] = await Promise.all([
        observeV3Api.workerDetail(workerId),
        observeV3Api.workerStats(workerId, window).catch(() => null),
        observeV3Api.workerInvocations(workerId, { page: 1 }),
        observeV3Api.workerOverrides(workerId).catch(() => []),
        observeV3Api.workerArtifacts(workerId, { page: 1 }).catch(() => ({ items: [] as WorkerArtifact[] })),
      ]);
      setDetail(d);
      setStats(s);
      setInvocations(inv.items);
      setOverrides(ov);
      setArtifacts((art as { items: WorkerArtifact[] }).items || []);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workerId, window]);

  const ov = stats?.overall || {};
  const total = (ov.total as number) || 0;
  const ok = (ov.ok as number) || 0;
  const successRate = total > 0 ? ((ok / total) * 100).toFixed(1) : '-';

  const tabLabels: Record<typeof tab, string> = {
    list: t('worker.tabList'),
    artifacts: t('worker.tabArtifacts'),
    config: t('worker.tabConfig'),
    perf: t('worker.tabPerf'),
  };

  return (
    <div className="p-6 space-y-4 max-w-6xl mx-auto text-foreground">
      <header className="flex items-center gap-3">
        <h1 className="font-semibold text-lg">
          Worker · {detail?.name || workerId}{' '}
          {detail?.capability && (
            <code className="text-xs bg-muted px-2 py-0.5 rounded ml-2">{detail.capability}</code>
          )}
        </h1>
        <div className="ml-auto flex gap-2 items-center">
          <label className="text-xs text-muted-foreground">{t('worker.windowLabel')}</label>
          <select
            value={window}
            onChange={(e) => setWindow(e.target.value as '1d' | '7d' | '30d' | 'all')}
            className="border border-border bg-card rounded text-sm px-2 py-1"
          >
            <option value="1d">1d</option>
            <option value="7d">7d</option>
            <option value="30d">30d</option>
            <option value="all">all</option>
          </select>
          <Button size="sm" variant="ghost" onClick={() => void refresh()} disabled={loading}>
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </header>

      {/* Dashboard cards */}
      <section className="grid grid-cols-4 gap-3">
        <Card label={t('worker.cardTotalInvocations')} value={total} icon={<Activity className="w-4 h-4" />} />
        <Card label={t('worker.cardSuccessRate')} value={`${successRate}%`} icon={<BarChart3 className="w-4 h-4" />} />
        <Card
          label={t('worker.cardAvgLatency')}
          value={ov.avg_ms ? `${Math.round(ov.avg_ms as number)} ms` : '-'}
          subtitle={`p95: ${ov.p95_ms ? Math.round(ov.p95_ms as number) + 'ms' : '-'}`}
          icon={<BarChart3 className="w-4 h-4" />}
        />
        <Card
          label={t('worker.cardTokenUsage')}
          value={ov.tokens != null ? Number(ov.tokens).toLocaleString() : '-'}
          subtitle={t('worker.cardTokenAvgPer', { value: ov.avg_tokens != null ? Math.round(Number(ov.avg_tokens)) : '-' })}
          icon={<Code2 className="w-4 h-4" />}
        />
        <Card
          label={t('worker.cardActiveSupers')}
          value={(ov.active_supers as number) || 0}
          icon={<Activity className="w-4 h-4" />}
        />
        <Card
          label={t('worker.cardNeedClarification')}
          value={(ov.need_clar as number) || 0}
          subtitle={t('worker.cardNeedClarificationHint')}
          icon={<History className="w-4 h-4" />}
        />
        <Card
          label={t('worker.cardFailures')}
          value={(ov.failed as number) || 0}
          icon={<History className="w-4 h-4" />}
        />
        <Card
          label={t('worker.cardArtifacts')}
          value={t('worker.cardArtifactsCount', { count: (ov.artifacts as number) || 0 })}
          subtitle={ov.artifact_bytes ? `${Math.round((ov.artifact_bytes as number) / 1024)} KB` : '-'}
          icon={<Activity className="w-4 h-4" />}
        />
      </section>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-border">
        {(['list', 'artifacts', 'config', 'perf'] as const).map((tk) => (
          <button
            key={tk}
            onClick={() => setTab(tk)}
            className={`px-3 py-2 text-sm ${tab === tk ? 'border-b-2 border-primary font-semibold text-foreground' : 'text-muted-foreground'}`}
          >
            {tabLabels[tk]}
          </button>
        ))}
      </div>

      {tab === 'list' && (
        <table className="text-sm border border-border w-full">
          <thead className="bg-muted">
            <tr>
              <th className="text-left p-2">{t('worker.colStartedAt')}</th>
              <th className="text-left p-2">{t('worker.colSuper')}</th>
              <th className="text-left p-2">{t('worker.colAction')}</th>
              <th className="text-left p-2">{t('worker.colStatus')}</th>
              <th className="text-left p-2">{t('worker.colDuration')}</th>
              <th className="text-left p-2">{t('worker.colTokens')}</th>
              <th className="text-left p-2">{t('worker.colArtifacts')}</th>
            </tr>
          </thead>
          <tbody>
            {invocations.map((r) => (
              <tr key={r.id} className="border-t border-border">
                <td className="p-2 text-xs">{r.started_at?.replace('T', ' ').slice(0, 19)}</td>
                <td className="p-2 font-mono text-xs">{r.super_agent_id.slice(0, 8)}…</td>
                <td className="p-2">{r.action}</td>
                <td className="p-2">
                  <span
                    className={`text-xs px-1.5 py-0.5 rounded ${
                      r.status === 'completed' ? 'bg-success/10 text-success' :
                      r.status === 'failed' ? 'bg-destructive/10 text-destructive' :
                      r.status === 'needs_clarification' ? 'bg-warning/10 text-warning' :
                      'bg-muted text-muted-foreground'
                    }`}
                  >{r.status}</span>
                </td>
                <td className="p-2 text-xs">{r.duration_ms ? `${r.duration_ms}ms` : '-'}</td>
                <td className="p-2 text-xs">{((r.tokens_in || 0) + (r.tokens_out || 0)) || '-'}</td>
                <td className="p-2 text-xs">{r.artifact_count || 0}</td>
              </tr>
            ))}
            {invocations.length === 0 && (
              <tr><td colSpan={7} className="text-center text-muted-foreground p-6">{t('worker.emptyInvocations')}</td></tr>
            )}
          </tbody>
        </table>
      )}

      {tab === 'artifacts' && (
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">
            {t('worker.artifactsDescription')}
          </div>
          {artifacts.length === 0 ? (
            <div className="text-sm text-muted-foreground p-6 text-center">{t('worker.emptyArtifacts')}</div>
          ) : (
            <table className="text-sm border border-border w-full">
              <thead className="bg-muted">
                <tr>
                  <th className="text-left p-2">{t('worker.colTime')}</th>
                  <th className="text-left p-2">{t('worker.colSourceSuper')}</th>
                  <th className="text-left p-2">{t('worker.colAction')}</th>
                  <th className="text-left p-2">{t('worker.colType')}</th>
                  <th className="text-left p-2">{t('worker.colArtifact')}</th>
                </tr>
              </thead>
              <tbody>
                {artifacts.map((a) => (
                  <tr key={a.message_id} className="border-t border-border">
                    <td className="p-2 text-xs">{a.created_at?.replace('T', ' ').slice(0, 19)}</td>
                    <td className="p-2 text-xs">
                      {a.super_slug ? (
                        <a className="underline" href={`/super/${a.super_slug}`}>{a.super_name || a.super_slug}</a>
                      ) : '-'}
                    </td>
                    <td className="p-2">{a.action || '-'}</td>
                    <td className="p-2 text-xs">{a.media_type || '-'}</td>
                    <td className="p-2 text-xs">
                      {a.artifact_url ? (
                        <a className="underline text-primary" href={a.artifact_url} target="_blank" rel="noreferrer">
                          {t('worker.openArtifact')} ↗
                        </a>
                      ) : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === 'config' && (
        <div className="space-y-4">
          <section>
            <h3 className="font-semibold text-sm mb-1">{t('worker.capabilityContract')}</h3>
            <pre className="bg-muted p-3 rounded text-xs overflow-auto max-h-80">
{JSON.stringify(detail?.capability_contract || {}, null, 2)}
            </pre>
          </section>
          <section>
            <h3 className="font-semibold text-sm mb-1">{t('worker.perSuperOverrides', { count: overrides.length })}</h3>
            {overrides.length === 0 ? (
              <div className="text-xs text-muted-foreground">{t('worker.noOverrides')}</div>
            ) : (
              <table className="text-xs border border-border w-full">
                <thead className="bg-muted">
                  <tr><th className="text-left p-2">{t('worker.colSuperMission')}</th><th className="text-left p-2">{t('worker.colOverrideSummary')}</th></tr>
                </thead>
                <tbody>
                  {overrides.map((o) => (
                    <tr key={o.mission_id} className="border-t border-border">
                      <td className="p-2">
                        <a className="underline" href={`/super/${o.slug}`}>{o.name}</a>
                      </td>
                      <td className="p-2 font-mono">{JSON.stringify(o.override).slice(0, 200)}…</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      )}

      {tab === 'perf' && (
        <div className="space-y-4">
          {!stats && (
            <div className="text-sm text-muted-foreground p-6 text-center">{t('worker.statsUnavailable')}</div>
          )}
          <section>
            <h3 className="font-semibold text-sm mb-1">{t('worker.perAction')}</h3>
            <table className="text-xs border border-border w-full max-w-2xl">
              <thead className="bg-muted">
                <tr><th className="text-left p-2">{t('worker.colAction')}</th><th className="text-left p-2">{t('worker.colInvocations')}</th><th className="text-left p-2">{t('worker.colSuccess')}</th><th className="text-left p-2">{t('worker.colAvgMs')}</th></tr>
              </thead>
              <tbody>
                {(stats?.per_action ?? []).map((a) => (
                  <tr key={a.action} className="border-t border-border">
                    <td className="p-2">{a.action}</td><td className="p-2">{a.cnt}</td><td className="p-2">{a.ok}</td><td className="p-2">{a.avg_ms != null ? Number(a.avg_ms).toFixed(0) : '-'}</td>
                  </tr>
                ))}
                {(stats?.per_action ?? []).length === 0 && (
                  <tr><td colSpan={4} className="p-2 text-muted-foreground">{t('worker.emptyInvocations')}</td></tr>
                )}
              </tbody>
            </table>
          </section>
          <section>
            <h3 className="font-semibold text-sm mb-1">{t('worker.topErrors')}</h3>
            <ul className="text-xs space-y-1">
              {(stats?.top_errors ?? []).map((e, i) => (
                <li key={i}>×{e.cnt} · <code className="bg-muted px-1">{e.err}</code></li>
              ))}
              {(stats?.top_errors ?? []).length === 0 && (<li className="text-muted-foreground">{t('worker.noFailures')}</li>)}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}

function Card({ label, value, subtitle, icon }: { label: string; value: React.ReactNode; subtitle?: string; icon?: React.ReactNode }) {
  return (
    <div className="border border-border bg-card rounded p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        {icon}<span>{label}</span>
      </div>
      <div className="text-xl font-semibold mt-1 text-foreground">{value}</div>
      {subtitle && <div className="text-[10px] text-muted-foreground/70">{subtitle}</div>}
    </div>
  );
}
