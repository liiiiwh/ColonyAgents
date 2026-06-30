'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import { AxiosError } from 'axios';
import {
  ArrowLeft,
  CheckCircle2,
  Plus,
  Save,
  Sparkles,
  Trash2,
  XCircle,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { agentsApi } from '@/lib/api/agents';
import { providersApi } from '@/lib/api/providers';
import { skillsApi, mcpServersApi } from '@/lib/api/skills';
import type {
  AgentAuxModelBinding,
  AgentDetail,
  AgentTestResponse,
  AuxModelRole,
  ThinkingLevel,
} from '@/types/agent';
import type { LLMModelPublic, LLMModelType, ProviderPublic } from '@/types/provider';
import type { MCPServerPublic, SkillPublic } from '@/types/skill';
import { ProviderTypeModelPicker } from '@/components/admin/ProviderTypeModelPicker';
import { useConfirm, useToast } from '@/components/providers/ConfirmProvider';

export default function AgentEditPage() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [allSkills, setAllSkills] = useState<SkillPublic[]>([]);
  const [allMCPs, setAllMCPs] = useState<MCPServerPublic[]>([]);
  const [providers, setProviders] = useState<ProviderPublic[]>([]);
  // provider -> model list (lazy-loaded + cached)
  const [modelsByProvider, setModelsByProvider] = useState<Record<string, LLMModelPublic[]>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Local Skill / MCP selection (checkbox click only updates here; diffed + batch-committed on save)
  const [localSkillIds, setLocalSkillIds] = useState<Set<string>>(new Set());
  const [localMCPIds, setLocalMCPIds] = useState<Set<string>>(new Set());
  const [testInput, setTestInput] = useState('');
  const [testResult, setTestResult] = useState<AgentTestResponse | null>(null);
  const [testing, setTesting] = useState(false);

  const [addAuxOpen, setAddAuxOpen] = useState(false);

  async function loadModelsFor(providerId: string) {
    if (modelsByProvider[providerId]) return modelsByProvider[providerId];
    const list = await providersApi.listModels(providerId);
    setModelsByProvider((prev) => ({ ...prev, [providerId]: list }));
    return list;
  }

  async function refresh() {
    setLoading(true);
    try {
      const [a, ss, ms, ps] = await Promise.all([
        agentsApi.get(id),
        skillsApi.list(),
        mcpServersApi.list(),
        providersApi.list(),
      ]);
      setAgent(a);
      setAllSkills(ss);
      setAllMCPs(ms);
      setProviders(ps);
      setLocalSkillIds(new Set(a.skill_bindings.map((b) => b.skill_id)));
      setLocalMCPIds(new Set(a.mcp_bindings.map((b) => b.mcp_server_id)));
      // Preload models for **all enabled providers** — supports cross-provider mixing
      // (e.g. Claude via nebula and Gemini via e2e-gemini active at the same time).
      // The model picker flattens these into a single `provider_name/model_id` dropdown.
      const enabledProviders = ps.filter((p) => p.is_enabled);
      await Promise.all(enabledProviders.map((p) => loadModelsFor(p.id)));
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('agentDetail.loadFailed'));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function saveAll() {
    if (!agent) return;
    setSaving(true);
    try {
      await agentsApi.update(agent.id, {
        name: agent.name,
        description: agent.description,
        model_id: agent.model_id,
        soul_md: agent.soul_md,
        protocol_md: agent.protocol_md,
        domain_memory_md: agent.domain_memory_md,
        max_iterations: agent.max_iterations,
        temperature: agent.temperature,
        max_output_tokens: agent.max_output_tokens,
        is_enabled: agent.is_enabled,
        produces_deliverable: agent.produces_deliverable,
        thinking_level: agent.thinking_level,
        extra_config: agent.extra_config,
      });

      // diff Skill bindings
      const originalSkills = new Set(agent.skill_bindings.map((b) => b.skill_id));
      const toAddSkills = Array.from(localSkillIds).filter((id) => !originalSkills.has(id));
      const toRemoveSkills = Array.from(originalSkills).filter((id) => !localSkillIds.has(id));
      for (const sid of toAddSkills) await agentsApi.bindSkill(agent.id, sid);
      for (const sid of toRemoveSkills) await agentsApi.unbindSkill(agent.id, sid);

      // diff MCP bindings
      const originalMCPs = new Set(agent.mcp_bindings.map((b) => b.mcp_server_id));
      const toAddMCPs = Array.from(localMCPIds).filter((id) => !originalMCPs.has(id));
      const toRemoveMCPs = Array.from(originalMCPs).filter((id) => !localMCPIds.has(id));
      for (const mid of toAddMCPs) await agentsApi.bindMCP(agent.id, mid);
      for (const mid of toRemoveMCPs) await agentsApi.unbindMCP(agent.id, mid);

      await refresh();
    } catch (e) {
      toast(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('agentDetail.saveFailed'), 'error');
    } finally {
      setSaving(false);
    }
  }

  function toggleSkill(skillId: string) {
    setLocalSkillIds((prev) => {
      const next = new Set(prev);
      if (next.has(skillId)) next.delete(skillId);
      else next.add(skillId);
      return next;
    });
  }
  function toggleMCP(mcpId: string) {
    setLocalMCPIds((prev) => {
      const next = new Set(prev);
      if (next.has(mcpId)) next.delete(mcpId);
      else next.add(mcpId);
      return next;
    });
  }

  // Unsaved-changes hint
  const hasUnsavedBindingChanges = useMemo(() => {
    if (!agent) return false;
    const origSk = new Set(agent.skill_bindings.map((b) => b.skill_id));
    const origMc = new Set(agent.mcp_bindings.map((b) => b.mcp_server_id));
    const sameSk = origSk.size === localSkillIds.size &&
      Array.from(origSk).every((x) => localSkillIds.has(x));
    const sameMc = origMc.size === localMCPIds.size &&
      Array.from(origMc).every((x) => localMCPIds.has(x));
    return !sameSk || !sameMc;
  }, [agent, localSkillIds, localMCPIds]);

  async function removeAux(binding: AgentAuxModelBinding) {
    if (!agent) return;
    if (!(await confirm({ message: t('agentDetail.unbindAuxConfirm', { name: binding.alias || binding.role }), danger: true, confirmText: t('common.delete') }))) return;
    await agentsApi.unbindAuxModel(agent.id, binding.model_id);
    await refresh();
  }

  async function handleTest() {
    if (!agent || !testInput.trim()) return;
    setTesting(true);
    try {
      setTestResult(await agentsApi.test(agent.id, testInput));
    } catch (e) {
      setTestResult({
        ok: false,
        output: null,
        tools_loaded: 0,
        error: e instanceof Error ? e.message : t('agentDetail.testFailed'),
      });
    } finally {
      setTesting(false);
    }
  }

  const modelsOfMainProvider: LLMModelPublic[] = useMemo(
    () => (agent?.model?.provider_id ? modelsByProvider[agent.model.provider_id] ?? [] : []),
    [agent, modelsByProvider],
  );

  /** Switch provider: auto-select that provider's first enabled chat model */
  async function onChangeMainProvider(providerId: string) {
    if (!agent) return;
    const models = await loadModelsFor(providerId);
    const chat = models.find((m) => m.model_type === 'chat' && m.is_enabled);
    setAgent({
      ...agent,
      model_id: chat?.id ?? agent.model_id,
      model: chat
        ? {
            id: chat.id,
            provider_id: providerId,
            model_id: chat.model_id,
            display_name: chat.display_name,
            model_type: chat.model_type,
            context_window: chat.context_window,
            supports_vision: chat.supports_vision,
            supports_function_calling: chat.supports_function_calling,
          }
        : agent.model,
    });
  }

  function onChangeMainModel(modelId: string) {
    if (!agent) return;
    if (!modelId) {
      // "Use platform default" → NULL model_id (resolved at runtime). ADR-017.
      setAgent({ ...agent, model_id: null });
      return;
    }
    const found = modelsOfMainProvider.find((m) => m.id === modelId);
    setAgent({
      ...agent,
      model_id: modelId,
      model: found
        ? {
            id: found.id,
            provider_id: found.provider_id,
            model_id: found.model_id,
            display_name: found.display_name,
            model_type: found.model_type,
            context_window: found.context_window,
            supports_vision: found.supports_vision,
            supports_function_calling: found.supports_function_calling,
          }
        : agent.model,
    });
  }

  if (loading) {
    return <p className="p-10 text-center text-sm text-muted-foreground/70">{t('common.loading')}</p>;
  }
  if (!agent) {
    return <p className="p-10 text-center text-sm text-destructive">{err ?? t('agentDetail.notFound')}</p>;
  }

  const boundSkillIds = localSkillIds;
  const boundMCPIds = localMCPIds;

  const docSections: { key: 'soul_md' | 'protocol_md' | 'domain_memory_md'; label: string; hint: string }[] = [
    { key: 'soul_md', label: t('agentDetail.soulLabel'), hint: t('agentDetail.soulHint') },
    { key: 'protocol_md', label: t('agentDetail.protocolLabel'), hint: t('agentDetail.protocolHint') },
    { key: 'domain_memory_md', label: t('agentDetail.seedMemoryLabel'), hint: t('agentDetail.seedMemoryHint') },
  ];

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <header className="mb-6 flex items-center justify-between border-b border-border pb-4">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => router.push('/admin/agents')}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-xl font-semibold text-foreground">{agent.name}</h1>
            <p className="text-xs text-muted-foreground/70">ID: {agent.id}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {hasUnsavedBindingChanges && (
            <span className="rounded-full bg-warning/10 px-2 py-0.5 text-[11px] text-warning">
              {t('agentDetail.unsavedBindings')}
            </span>
          )}
          <Button onClick={saveAll} disabled={saving}>
            <Save className="mr-2 h-4 w-4" />
            {saving ? t('agentDetail.saving') : t('common.save')}
          </Button>
        </div>
      </header>

      {/* Basic info */}
      <section className="mb-6 grid grid-cols-2 gap-4 rounded-lg border border-border bg-card p-5">
        <div className="col-span-2 space-y-2">
          <Label>{t('agentDetail.nameLabel')}</Label>
          <Input value={agent.name} onChange={(e) => setAgent({ ...agent, name: e.target.value })} />
        </div>
        <div className="col-span-2 space-y-2">
          <Label>{t('agentDetail.descriptionLabel')}</Label>
          <Input
            value={agent.description}
            onChange={(e) => setAgent({ ...agent, description: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label>{t('agentDetail.temperatureLabel', { value: agent.temperature })}</Label>
          <input
            type="range"
            min={0}
            max={2}
            step={0.1}
            value={agent.temperature}
            onChange={(e) => setAgent({ ...agent, temperature: Number(e.target.value) })}
            className="w-full"
          />
        </div>
        <div className="space-y-2">
          <Label>{t('agentDetail.maxIterationsLabel')}</Label>
          <Input
            type="number"
            min={1}
            max={50}
            value={agent.max_iterations}
            onChange={(e) => setAgent({ ...agent, max_iterations: Number(e.target.value) })}
          />
        </div>
        <div className="space-y-2">
          <Label>{t('agentDetail.maxOutputTokensLabel')}</Label>
          <Input
            type="number"
            min={256}
            max={64000}
            step={500}
            value={agent.max_output_tokens ?? 30000}
            onChange={(e) =>
              setAgent({ ...agent, max_output_tokens: Number(e.target.value) || 30000 })
            }
          />
          <p className="text-[11px] leading-relaxed text-muted-foreground/70">
            {t('agentDetail.maxOutputTokensHint')}
          </p>
        </div>
        {/* Deliverable toggle */}
        <div className="col-span-2 space-y-2 rounded-md border border-warning/40 bg-warning/10 p-3">
          <label className="flex cursor-pointer items-start gap-2.5">
            <input
              type="checkbox"
              checked={agent.produces_deliverable}
              onChange={(e) =>
                setAgent({ ...agent, produces_deliverable: e.target.checked })
              }
              className="mt-0.5 h-4 w-4"
            />
            <div className="flex-1">
              <span className="text-sm font-medium text-warning">
                {t('agentDetail.producesDeliverableLabel')}
              </span>
              <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                {t('agentDetail.producesDeliverableChecked')}{' '}
                <code className="rounded bg-muted px-1">workspace_write</code>{' '}
                {t('agentDetail.producesDeliverableCheckedTail')}
                <br />
                {t('agentDetail.producesDeliverableUnchecked')}{' '}
                <code className="rounded bg-muted px-1">node.state</code>
                {t('agentDetail.producesDeliverableUncheckedTail')}
              </p>
            </div>
          </label>
        </div>
        {/* ADR-026 D4 · Mission 默认全自动开关（仅 super 显示；worker 不建 mission） */}
        {agent.kind === 'super' && (
          <div className="col-span-2 space-y-2 rounded-md border border-success/40 bg-success/10 p-3">
            <label className="flex cursor-pointer items-start gap-2.5">
              <input
                type="checkbox"
                checked={(agent.extra_config?.mission_default_auto_approve ?? true) !== false}
                onChange={(e) =>
                  setAgent({
                    ...agent,
                    extra_config: {
                      ...agent.extra_config,
                      mission_default_auto_approve: e.target.checked,
                    },
                  })
                }
                className="mt-0.5 h-4 w-4"
              />
              <div className="flex-1">
                <span className="text-sm font-medium text-success">
                  {t('agentDetail.missionAutoApproveDefaultLabel')}
                </span>
                <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                  {t('agentDetail.missionAutoApproveDefaultHint')}
                </p>
              </div>
            </label>
          </div>
        )}
        {/* Model thinking level */}
        <div className="col-span-2 space-y-2 rounded-md border border-primary/40 bg-primary/10 p-3">
          <label htmlFor="thinking-level" className="block text-sm font-medium text-primary">
            {t('agentDetail.thinkingLevelLabel')}
          </label>
          <select
            id="thinking-level"
            value={agent.thinking_level ?? 'off'}
            onChange={(e) =>
              setAgent({ ...agent, thinking_level: e.target.value as ThinkingLevel })
            }
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
          >
            <option value="off">{t('agentDetail.thinkingLevelOff')}</option>
            <option value="low">{t('agentDetail.thinkingLevelLow')}</option>
            <option value="medium">{t('agentDetail.thinkingLevelMedium')}</option>
            <option value="high">{t('agentDetail.thinkingLevelHigh')}</option>
          </select>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            {t('agentDetail.thinkingLevelHint')}
            <br />
            · <strong>Gemini</strong> →{' '}
            <code className="rounded bg-muted px-1">thinkingBudget</code> = 0 / 512 / 2048 / 8192
            <br />
            · <strong>{t('agentDetail.thinkingLevelClaude')}</strong> →{' '}
            <code className="rounded bg-muted px-1">budget_tokens</code> = off / 2000 / 8000 / 16000
            <br />
            · {t('agentDetail.thinkingLevelOthers')} →{' '}
            <code className="rounded bg-muted px-1">reasoning_effort</code> = low / low / medium / high
            <br />
            {t('agentDetail.thinkingLevelTail')}{' '}
            <code className="rounded bg-muted px-1">extra_config</code>.
          </p>
        </div>
      </section>

      {/* Main model */}
      <section className="mb-6 rounded-lg border border-border bg-card p-5">
        <h2 className="mb-3 text-sm font-semibold text-foreground">{t('agentDetail.mainModelTitle')}</h2>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>Provider</Label>
            <Select
              value={agent.model?.provider_id ?? ''}
              onChange={(e) => onChangeMainProvider(e.target.value)}
            >
              <option value="">{t('agentDetail.selectPlaceholder')}</option>
              {providers
                .filter((p) => p.is_enabled)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.provider_type})
                  </option>
                ))}
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Model</Label>
            <Select value={agent.model_id ?? ''} onChange={(e) => onChangeMainModel(e.target.value)}>
              <option value="">{t('agentDetail.usePlatformDefault')}</option>
              {modelsOfMainProvider
                .filter((m) => m.model_type === 'chat' && m.is_enabled)
                .map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.model_id}
                  </option>
                ))}
            </Select>
          </div>
        </div>
        {agent.model && (
          <p className="mt-2 text-xs text-muted-foreground/70">
            {agent.model_id == null && (
              <span className="text-primary">{t('agentDetail.usePlatformDefault')} · </span>
            )}
            {providers.find((p) => p.id === agent.model?.provider_id)?.name ?? '?'}/
            {agent.model.model_id} · ctx={agent.model.context_window}
            {agent.model.supports_vision && ' · vision'}
            {agent.model.supports_function_calling && ' · tools'}
          </p>
        )}
      </section>

      {/* Aux models */}
      <section className="mb-6 rounded-lg border border-border bg-card p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-foreground">{t('agentDetail.auxModelsTitle')}</h2>
          <Button size="sm" variant="outline" onClick={() => setAddAuxOpen(true)}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            {t('agentDetail.bindAuxModel')}
          </Button>
        </div>
        {agent.aux_model_bindings.length === 0 ? (
          <p className="text-xs text-muted-foreground/70">
            {t('agentDetail.auxEmptyLead')}
            <code className="mx-1 rounded bg-muted px-1">invoke_aux_model</code>
            {t('agentDetail.auxEmptyTail')}
          </p>
        ) : (
          <ul className="space-y-2">
            {agent.aux_model_bindings.map((b) => (
              <li
                key={b.model_id}
                className="flex items-center gap-3 rounded-md border border-border p-2.5 text-xs"
              >
                <Sparkles className="h-3.5 w-3.5 text-muted-foreground/70" />
                <Badge variant="secondary">{b.role}</Badge>
                <span className="font-mono text-muted-foreground">
                  {b.alias ? `@${b.alias}` : '—'}
                </span>
                <span className="text-muted-foreground/70">
                  model_id: <code>{b.model_id.slice(0, 8)}…</code>
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto"
                  onClick={() => removeAux(b)}
                >
                  <Trash2 className="h-3 w-3 text-destructive" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Three document editors */}
      {docSections.map(({ key, label, hint }) => (
        <section key={key} className="mb-6 rounded-lg border border-border bg-card p-5">
          <div className="mb-2 flex items-center justify-between">
            <Label className="block text-sm">{label}</Label>
            {key === 'protocol_md' && (
              <span className="text-[11px] text-muted-foreground/70">
                {t('agentDetail.protocolReference')}{' '}
                <a
                  className="text-primary underline-offset-2 hover:underline"
                  href="/docs/design/supervisor-protocol.md"
                  target="_blank"
                  rel="noreferrer"
                >
                  {t('agentDetail.protocolTemplateLink')}
                </a>
                {t('agentDetail.protocolReferenceTail')}
              </span>
            )}
          </div>
          <p className="mb-2 text-[11px] text-muted-foreground/70">{hint}</p>
          <Textarea
            rows={8}
            value={(agent as unknown as Record<string, string>)[key]}
            placeholder={
              key === 'protocol_md'
                ? t('agentDetail.protocolPlaceholder')
                : key === 'domain_memory_md'
                  ? t('agentDetail.seedMemoryPlaceholder')
                  : undefined
            }
            onChange={(e) =>
              setAgent({ ...agent, [key]: e.target.value } as unknown as AgentDetail)
            }
          />
        </section>
      ))}

      {/* Skill bindings */}
      <section className="mb-6 rounded-lg border border-border bg-card p-5">
        <h2 className="mb-3 text-sm font-semibold text-foreground">{t('agentDetail.skillsTitle')}</h2>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {allSkills.map((s) => {
            const bound = boundSkillIds.has(s.id);
            return (
              <label
                key={s.id}
                className="flex cursor-pointer items-start gap-2 rounded-md border border-border p-2.5 text-xs transition-colors hover:bg-accent/50"
              >
                <input type="checkbox" checked={bound} onChange={() => toggleSkill(s.id)} className="mt-0.5" />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-foreground">{s.name}</span>
                    <Badge variant={s.skill_type === 'instruction' ? 'secondary' : 'default'}>
                      {s.skill_type}
                    </Badge>
                  </div>
                  <p className="mt-0.5 font-mono text-muted-foreground/70">{s.slug}</p>
                </div>
              </label>
            );
          })}
        </div>
      </section>

      {/* MCP bindings */}
      <section className="mb-6 rounded-lg border border-border bg-card p-5">
        <h2 className="mb-3 text-sm font-semibold text-foreground">{t('agentDetail.mcpTitle')}</h2>
        {allMCPs.length === 0 ? (
          <p className="text-xs text-muted-foreground/70">{t('agentDetail.mcpEmpty')}</p>
        ) : (
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {allMCPs.map((m) => {
              const bound = boundMCPIds.has(m.id);
              return (
                <label
                  key={m.id}
                  className="flex cursor-pointer items-start gap-2 rounded-md border border-border p-2.5 text-xs transition-colors hover:bg-accent/50"
                >
                  <input type="checkbox" checked={bound} onChange={() => toggleMCP(m.id)} className="mt-0.5" />
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-foreground">{m.name}</span>
                      <Badge>{m.server_type}</Badge>
                    </div>
                    <p className="mt-0.5 text-muted-foreground/70">{m.description || '—'}</p>
                  </div>
                </label>
              );
            })}
          </div>
        )}
      </section>

      {/* Single-shot test */}
      <section className="mb-6 rounded-lg border border-border bg-card p-5">
        <h2 className="mb-1 text-sm font-semibold text-foreground">{t('agentDetail.testTitle')}</h2>
        <p className="mb-3 text-[11px] text-muted-foreground/70">
          {t('agentDetail.testHintLead')}{' '}
          <code className="rounded bg-muted px-1">system (soul+protocol+memory) + user input</code>
          {t('agentDetail.testHintTail')}
        </p>
        <div className="flex gap-2">
          <Input
            value={testInput}
            onChange={(e) => setTestInput(e.target.value)}
            placeholder={t('agentDetail.testInputPlaceholder')}
          />
          <Button onClick={handleTest} disabled={testing || !testInput.trim()}>
            {testing ? t('agentDetail.testRunning') : t('agentDetail.testButton')}
          </Button>
        </div>
        {testResult && (
          <div className="mt-3 space-y-2">
            <div className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-xs">
              {testResult.ok ? (
                <CheckCircle2 className="h-4 w-4 text-success" />
              ) : (
                <XCircle className="h-4 w-4 text-destructive" />
              )}
              <span className="font-medium">{testResult.ok ? t('agentDetail.testPass') : t('agentDetail.testFail')}</span>
              <span className="text-muted-foreground/70">
                {t('agentDetail.testToolsLoaded', { count: testResult.tools_loaded })}
              </span>
            </div>
            {testResult.output && (
              <div className="rounded-md border border-success/40 bg-success/10 p-3">
                <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-success">
                  {t('agentDetail.testModelReply')}
                </div>
                <pre className="whitespace-pre-wrap text-xs leading-relaxed text-foreground">
                  {testResult.output}
                </pre>
              </div>
            )}
            {testResult.error && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3">
                <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-destructive">
                  {t('agentDetail.testError')}
                </div>
                <pre className="whitespace-pre-wrap text-xs text-destructive">{testResult.error}</pre>
              </div>
            )}
          </div>
        )}
      </section>

      <AddAuxDialog
        open={addAuxOpen}
        onClose={() => setAddAuxOpen(false)}
        agentId={agent.id}
        providers={providers}
        modelsByProvider={modelsByProvider}
        loadModelsFor={loadModelsFor}
        onBound={refresh}
      />
    </div>
  );
}

function AddAuxDialog({
  open,
  onClose,
  agentId,
  providers,
  modelsByProvider,
  loadModelsFor,
  onBound,
}: {
  open: boolean;
  onClose: () => void;
  agentId: string;
  providers: ProviderPublic[];
  modelsByProvider: Record<string, LLMModelPublic[]>;
  loadModelsFor: (pid: string) => Promise<LLMModelPublic[]>;
  onBound: () => Promise<void>;
}) {
  const { t } = useTranslation();

  const AUX_ROLES: { value: AuxModelRole; label: string }[] = [
    { value: 'chat', label: t('agentDetail.roleChat') },
    { value: 'vision', label: t('agentDetail.roleVision') },
    { value: 'image', label: t('agentDetail.roleImage') },
    { value: 'video', label: t('agentDetail.roleVideo') },
    { value: 'embedding', label: t('agentDetail.roleEmbedding') },
    { value: 'rerank', label: t('agentDetail.roleRerank') },
    { value: 'tts', label: t('agentDetail.roleTts') },
    { value: 'stt', label: t('agentDetail.roleStt') },
    { value: 'custom', label: t('agentDetail.roleCustom') },
  ];

  const [providerId, setProviderId] = useState('');
  const [modelType, setModelType] = useState<LLMModelType | ''>('image');
  const [modelId, setModelId] = useState('');
  const [role, setRole] = useState<AuxModelRole>('image');
  const [alias, setAlias] = useState('');
  const [configText, setConfigText] = useState('{}');
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setProviderId('');
    setModelType('image');
    setModelId('');
    setRole('image');
    setAlias('');
    setConfigText('{}');
    setErr(null);
  }, [open]);

  // role changed: auto-sync modelType (when 1:1). role=image → type=image,
  // role=video → type=video, role=embedding → type=embedding, others keep current selection.
  useEffect(() => {
    if (role === 'image') setModelType('image');
    else if (role === 'video') setModelType('video');
    else if (role === 'embedding' || role === 'rerank') setModelType('embedding');
    else if (role === 'chat' || role === 'vision') setModelType('chat');
    // tts / stt / custom not forced
  }, [role]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setSubmitting(true);
    try {
      let config: Record<string, unknown> = {};
      if (configText.trim()) {
        try {
          config = JSON.parse(configText);
        } catch {
          throw new Error(t('agentDetail.configInvalidJson'));
        }
      }
      await agentsApi.bindAuxModel(agentId, modelId, {
        role,
        alias: alias || null,
        config,
      });
      await onBound();
      onClose();
    } catch (e) {
      setErr(
        e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : (e as Error).message,
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t('agentDetail.bindAuxModel')} className="max-w-lg">
      <form onSubmit={submit} className="space-y-3">
        <div className="space-y-2">
          <Label>Role</Label>
          <Select value={role} onChange={(e) => setRole(e.target.value as AuxModelRole)}>
            {AUX_ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </Select>
        </div>
        <ProviderTypeModelPicker
          providers={providers}
          modelsByProvider={modelsByProvider}
          loadModelsFor={loadModelsFor}
          providerId={providerId}
          modelType={modelType}
          modelId={modelId}
          onChangeProvider={setProviderId}
          onChangeType={setModelType}
          onChangeModel={setModelId}
          required
        />
        <div className="space-y-2">
          <Label>{t('agentDetail.aliasLabel')}</Label>
          <Input
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            placeholder={t('agentDetail.aliasPlaceholder')}
          />
        </div>
        <div className="space-y-2">
          <Label>{t('agentDetail.extraConfigLabel')}</Label>
          <Textarea
            rows={3}
            value={configText}
            onChange={(e) => setConfigText(e.target.value)}
            placeholder='{"size": "1024x1024"}'
          />
        </div>
        {err && <p className="rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={submitting || !modelId}>
            {submitting ? t('agentDetail.binding') : t('agentDetail.bind')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
