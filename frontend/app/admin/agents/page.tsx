'use client';

/**
 * /admin/agents — unified Agents entry
 *
 * Two tabs: Super Agents / Worker Agents (split by kind field)
 * - click a super row → /super/[slug] (live chat workbench)
 * - click a worker row → /worker/[id] (cross-super aggregate dashboard)
 *
 * Top buttons:
 * - Ask Builder to design  → /super/builder (navigate + inject bootstrap)
 * - + New (manual)         → fallback dialog (admin emergency / debug)
 */

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { AxiosError } from 'axios';
import { useTranslation } from 'react-i18next';
import { Bot, Download, Lightbulb, Pencil, Plus, RefreshCw, Trash2, Sparkles, Wrench } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { agentsApi } from '@/lib/api/agents';
import { missionsAdminApi } from '@/lib/api/missionsAdmin';
import { providersApi } from '@/lib/api/providers';
import { observeV3Api, type WorkerListItem } from '@/lib/api/observeV3';
import { useConfirm, useToast } from '@/components/providers/ConfirmProvider';
import { ImportWorkerModal } from '@/components/admin/ImportWorkerModal';
import type {
  AgentCategory,
  AgentCreateInput,
  AgentKind,
  AgentPublic,
} from '@/types/agent';
import { AGENT_CATEGORY_LABELS, AGENT_CATEGORY_ORDER } from '@/types/agent';
import type { MissionPublic } from '@/types/mission';
import type { LLMModelPublic, ProviderPublic } from '@/types/provider';

type TabKey = 'super' | 'worker';

export default function AgentsPage() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const router = useRouter();
  const search = useSearchParams();
  const initialTab = (search.get('tab') as TabKey) || 'super';
  const [tab, setTab] = useState<TabKey>(initialTab);
  const [agents, setAgents] = useState<AgentPublic[]>([]);
  const [workers, setWorkers] = useState<WorkerListItem[]>([]);
  const [projects, setProjects] = useState<MissionPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [openNew, setOpenNew] = useState(false);
  const [openImport, setOpenImport] = useState(false);

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      const [as, ws, ps] = await Promise.all([
        agentsApi.list(),
        observeV3Api.listWorkers().catch(() => [] as WorkerListItem[]),
        missionsAdminApi.list().catch(() => [] as MissionPublic[]),
      ]);
      setAgents(as);
      setWorkers(ws);
      setProjects(ps);
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('agents.loadFailed'));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleDelete(a: AgentPublic, missionCount = 0) {
    // 监管着运营实例的 super（含 kind=builder 的自动 supervisor）：强确认，确认后级联删
    // Mission + 独占 worker + super 本体（?cascade=true）。按 missionCount 判断，不依赖 kind。
    const cascade = missionCount > 0;
    let message: string;
    if (cascade) {
      // 先拉影响预览：会删的独占 worker + 因被其他 super 使用而保留的 worker，给用户明确提示。
      let delWorkers = 0;
      let keptShared: string[] = [];
      try {
        const preview = await agentsApi.cascadePreview(a.id);
        delWorkers = preview.workers_to_delete.length;
        keptShared = preview.workers_to_keep.filter((w) => w.reason === 'shared').map((w) => w.name);
      } catch {
        /* 预览失败不阻塞删除流程，confirm 退化为通用文案 */
      }
      message = t('agents.deleteSuperCascadeConfirm', { name: a.name, count: missionCount, delWorkers });
      if (keptShared.length > 0) {
        message += '\n' + t('agents.deleteSuperCascadeKeepHint', {
          count: keptShared.length,
          names: keptShared.join('、'),
        });
      }
    } else {
      message = t('agents.deleteConfirm', { name: a.name });
    }
    if (!(await confirm({ message, danger: true, confirmText: t('common.delete') }))) return;
    try {
      const resp = await agentsApi.delete(a.id, cascade);
      if (cascade) {
        const r = (resp ?? {}) as { deleted_missions?: string[]; deleted_agents?: string[] };
        toast(
          t('agents.deleteSuperCascadeDone', {
            missions: r.deleted_missions?.length ?? 0,
            agents: r.deleted_agents?.length ?? 0,
          }),
          'success',
        );
      }
      await refresh();
    } catch (e) {
      toast(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('agents.deleteFailed'), 'error');
    }
  }

  // super agents = kind='super' or supervisor of some mission
  // A super is a role TEMPLATE; 1 super → N missions. Collect ALL missions for
  // this super. 0 missions is a normal template state (not an "unbound" defect).
  const supers = useMemo(() => {
    const supSet = new Set(projects.map((p) => p.supervisor_agent_id).filter(Boolean));
    return agents
      .filter((a) => a.kind === 'super' || supSet.has(a.id))
      .map((a) => {
        const missions = projects.filter((p) => p.supervisor_agent_id === a.id);
        return {
          agent: a,
          missions,
          primary: missions[0],
        };
      });
  }, [agents, projects]);

  // workers = kind='worker' or non-empty capability (v3 catalog is already worker)
  const workerRows = useMemo(() => {
    // prefer the v3 observe API result (carries invocation stats)
    if (workers.length > 0) {
      return workers.map((w) => {
        const a = agents.find((x) => x.id === w.id);
        return { worker: w, agent: a };
      });
    }
    // fallback: agents table with kind='worker'
    return agents
      .filter((a) => a.kind === 'worker')
      .map((a) => ({
        worker: {
          id: a.id,
          name: a.name,
          capability: a.capability ?? null,
          kind: 'worker',
          contract_version: null,
          invocations_30d: 0,
          ok_30d: 0,
        } as WorkerListItem,
        agent: a,
      }));
  }, [workers, agents]);

  const askBuilder = () => {
    // inject bootstrap prompt (super page chat input can read it)
    try {
      sessionStorage.setItem(
        'super_bootstrap_prompt',
        t('agents.builderBootstrapPrompt'),
      );
    } catch {
      /* ignore */
    }
    router.push('/super/builder');
  };

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <header className="flex items-center justify-between border-b border-border pb-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">{t('agents.title')}</h1>
          <p className="mt-1 text-sm text-muted-foreground/70">
            {t('agents.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={askBuilder} className="bg-warning/10 text-warning hover:bg-warning/20">
            <Lightbulb className="mr-2 h-4 w-4" />
            {t('agents.askBuilder')}
          </Button>
          {/* ADR-019 D3 · agency-agents 一键导入入口暂时隐藏（后端 + ImportWorkerModal 保留可用，
              去掉 `false &&` 即恢复）。 */}
          {false && tab === 'worker' && (
            <Button variant="outline" onClick={() => setOpenImport(true)}>
              <Download className="mr-2 h-4 w-4" />
              {t('agentImport.cta')}
            </Button>
          )}
          <Button variant="outline" onClick={() => setOpenNew(true)}>
            <Plus className="mr-2 h-4 w-4" />
            {t('agents.newManual')}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => refresh()} disabled={loading} title={t('common.refresh')}>
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </header>

      {/* Tabs */}
      <div className="mt-5 flex gap-1 border-b border-border">
        <button
          onClick={() => setTab('super')}
          className={`px-4 py-2 text-sm font-medium ${
            tab === 'super'
              ? 'border-b-2 border-primary text-primary'
              : 'text-muted-foreground'
          }`}
        >
          <Sparkles className="inline w-3.5 h-3.5 mr-1" />
          {t('agents.tabSuper', { count: supers.length })}
        </button>
        <button
          onClick={() => setTab('worker')}
          className={`px-4 py-2 text-sm font-medium ${
            tab === 'worker'
              ? 'border-b-2 border-primary text-primary'
              : 'text-muted-foreground'
          }`}
        >
          <Wrench className="inline w-3.5 h-3.5 mr-1" />
          {t('agents.tabWorker', { count: workerRows.length })}
        </button>
      </div>

      {err && <p className="mt-4 rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}

      {/* Super tab */}
      {tab === 'super' && (
        <section className="mt-4 overflow-hidden rounded-lg border border-border bg-card">
          {loading ? (
            <p className="p-8 text-center text-sm text-muted-foreground">{t('common.loading')}</p>
          ) : supers.length === 0 ? (
            <p className="p-8 text-center text-sm text-muted-foreground">
              {t('agents.superEmpty')}
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-muted">
                <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-4 py-2">{t('agents.colRoleTemplate')}</th>
                  <th className="px-4 py-2">{t('agents.colMissions')}</th>
                  <th className="px-4 py-2">{t('agents.colConfig')}</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {supers.map(({ agent, missions, primary }) => (
                  <tr key={agent.id} className="border-t border-border hover:bg-accent/50">
                    <td className="px-4 py-3">
                      <Link
                        href={primary ? `/super/${primary.slug}` : `/admin/agents/${agent.id}`}
                        className="flex items-center gap-2 font-medium text-foreground hover:underline"
                      >
                        <Bot className="h-4 w-4 text-muted-foreground" />
                        {agent.name}
                        {agent.is_system && (
                          <Badge variant="secondary" className="text-[10px]">{t('agents.systemBadge')}</Badge>
                        )}
                      </Link>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {agent.description || '—'}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      {/* A super is a role template: 0 missions is normal (template awaiting derivation), not a defect */}
                      {missions.length === 0 ? (
                        <span className="text-xs text-muted-foreground/70">{t('agents.templateNoMissions')}</span>
                      ) : (
                        <div className="flex flex-col gap-1">
                          <span className="text-xs text-muted-foreground">
                            {t('agents.missionCount', { count: missions.length })}
                          </span>
                          <div className="flex flex-wrap gap-1">
                            {missions.slice(0, 6).map((m) => (
                              <Link key={m.id} href={`/super/${m.slug}`} title={m.name}>
                                <Badge
                                  variant={
                                    m.lifecycle_status === 'running'
                                      ? 'success'
                                      : m.lifecycle_status === 'paused_waiting_capability'
                                        ? 'warning'
                                        : 'secondary'
                                  }
                                  className="cursor-pointer"
                                >
                                  {m.name}
                                </Badge>
                              </Link>
                            ))}
                            {missions.length > 6 && (
                              <span className="text-xs text-muted-foreground/70">+{missions.length - 6}</span>
                            )}
                          </div>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      <Link
                        href={`/admin/agents/${agent.id}`}
                        className="text-primary hover:underline"
                      >
                        {t('agents.editConfig')}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                      {/* 进入工作台：直接进工作台（跳过 /super 角色页）。有 mission → 跳该 mission；
                          无 mission → missionSlug 用 super-slug，后端 superThreads 返回空壳 →
                          工作台空 mission 列表 + 自动弹「新建 Mission」。无 mission 的 super 也能进。 */}
                      <Link
                        href={`/mission/${agent.slug ?? agent.id}/${
                          (primary ?? missions[0])?.slug ?? agent.slug ?? agent.id
                        }`}
                      >
                        <Button size="sm" variant="outline">
                          {t('agents.enter')}
                        </Button>
                      </Link>
                      {/* ADR-015 · system objects cannot be deleted → hide delete button */}
                      {!agent.is_system && (
                        <Button size="sm" variant="ghost" onClick={() => handleDelete(agent, missions.length)} title={t('common.delete')}>
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
      )}

      {/* Worker tab */}
      {tab === 'worker' && (
        <section className="mt-4 overflow-hidden rounded-lg border border-border bg-card">
          {loading ? (
            <p className="p-8 text-center text-sm text-muted-foreground">{t('common.loading')}</p>
          ) : workerRows.length === 0 ? (
            <p className="p-8 text-center text-sm text-muted-foreground">{t('agents.workerEmpty')}</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-muted">
                <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-4 py-2">{t('agents.colCapability')}</th>
                  <th className="px-4 py-2">{t('agents.colName')}</th>
                  <th className="px-4 py-2">{t('agents.colVersion')}</th>
                  <th className="px-4 py-2">{t('agents.colInvocations30d')}</th>
                  <th className="px-4 py-2">{t('agents.colSuccessRate')}</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {workerRows.map(({ worker, agent }) => (
                  <tr key={worker.id} className="border-t border-border hover:bg-accent/50">
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{worker.capability || '—'}</td>
                    <td className="px-4 py-3">
                      <Link
                        href={`/worker/${worker.id}`}
                        className="flex items-center gap-2 font-medium text-foreground hover:underline"
                      >
                        <Wrench className="h-4 w-4 text-muted-foreground" />
                        {worker.name}
                        {worker.is_system && (
                          <Badge variant="secondary" className="text-[10px]">{t('agents.systemBadge')}</Badge>
                        )}
                      </Link>
                      {agent?.description && (
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {agent.description}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">{worker.contract_version || '-'}</td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">{worker.invocations_30d}</td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {worker.invocations_30d > 0
                        ? `${((worker.ok_30d / worker.invocations_30d) * 100).toFixed(0)}%`
                        : '-'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link href={`/worker/${worker.id}`}>
                        <Button size="sm" variant="ghost">
                          {t('agents.observe')}
                        </Button>
                      </Link>
                      {agent && (
                        <Link href={`/admin/agents/${agent.id}`}>
                          <Button size="sm" variant="ghost" title={t('common.edit')}>
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                        </Link>
                      )}
                      {/* ADR-015 · worker delete (system objects hide button; backend 409 if still in use) */}
                      {agent && !worker.is_system && !agent.is_system && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleDelete(agent)}
                          title={t('agents.deleteWorkerHint')}
                        >
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      <NewAgentDialog open={openNew} onClose={() => setOpenNew(false)} onSaved={refresh} />
      <ImportWorkerModal open={openImport} onClose={() => setOpenImport(false)} onImported={refresh} />
    </div>
  );
}

// ─────────────────────────── NewAgentDialog (fallback) ───────────────────────────
function NewAgentDialog({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
}) {
  const { t } = useTranslation();
  const [providers, setProviders] = useState<ProviderPublic[]>([]);
  const [models, setModels] = useState<LLMModelPublic[]>([]);
  const [providerId, setProviderId] = useState('');
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [kind, setKind] = useState<AgentKind>('worker');
  const [capability, setCapability] = useState('');
  const [category, setCategory] = useState<AgentCategory>('custom');
  const [modelId, setModelId] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setErr(null);
    setName('');
    setDesc('');
    setKind('worker');
    setCapability('');
    setCategory('custom');
    providersApi.list().then((ps) => setProviders(ps.filter((p) => p.is_enabled)));
  }, [open]);

  useEffect(() => {
    if (!providerId) {
      setModels([]);
      setModelId('');
      return;
    }
    providersApi.listModels(providerId).then((ms) => {
      const chat = ms.filter((m) => m.model_type === 'chat' && m.is_enabled);
      setModels(chat);
      setModelId(chat[0]?.id ?? '');
    });
  }, [providerId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setSubmitting(true);
    try {
      const body: AgentCreateInput & { kind?: string; capability?: string } = {
        name,
        description: desc,
        category,
        model_id: modelId,
      };
      if (kind) body.kind = kind;
      if (capability) body.capability = capability;
      await agentsApi.create(body);
      await onSaved();
      onClose();
    } catch (e) {
      setErr(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('agents.createFailed'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t('agents.newDialogTitle')}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="text-xs text-warning border border-warning/40 rounded p-2 bg-warning/10">
          {t('agents.newDialogHint')}
        </div>
        <div className="space-y-2">
          <Label>{t('agents.fieldName')}</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div className="space-y-2">
          <Label>{t('agents.fieldDescription')}</Label>
          <Input value={desc} onChange={(e) => setDesc(e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>{t('agents.fieldKind')}</Label>
            <Select value={kind || 'worker'} onChange={(e) => setKind(e.target.value as AgentKind)}>
              <option value="super">{t('agents.kindSuper')}</option>
              <option value="worker">{t('agents.kindWorker')}</option>
              <option value="utility">{t('agents.kindUtility')}</option>
            </Select>
          </div>
          {kind === 'worker' && (
            <div className="space-y-2">
              <Label>{t('agents.fieldCapabilitySlug')}</Label>
              <Input
                value={capability}
                onChange={(e) => setCapability(e.target.value)}
                placeholder={t('agents.capabilityPlaceholder')}
                required
              />
            </div>
          )}
        </div>
        <div className="space-y-2">
          <Label>{t('agents.fieldCategory')}</Label>
          <Select value={category} onChange={(e) => setCategory(e.target.value as AgentCategory)}>
            {AGENT_CATEGORY_ORDER.map((c) => (
              <option key={c} value={c}>
                {AGENT_CATEGORY_LABELS[c]}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-2">
          <Label>{t('agents.fieldProvider')}</Label>
          <Select value={providerId} onChange={(e) => setProviderId(e.target.value)} required>
            <option value="">{t('agents.selectPlaceholder')}</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.provider_type})
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-2">
          <Label>{t('agents.fieldModelChat')}</Label>
          <Select
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            disabled={!providerId}
            required
          >
            {models.length === 0 && <option value="">{t('agents.selectProviderFirst')}</option>}
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.model_id}
              </option>
            ))}
          </Select>
        </div>
        {err && <p className="rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={submitting || !modelId || !name}>
            {submitting ? t('agents.creating') : t('agents.createAndEdit')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
