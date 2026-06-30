'use client';

/**
 * v5 · /super/[slug] 内嵌 schedule editor（list + add + edit + delete + fire）
 *
 * 复用 schedulesApi（admin/projects/[id] 早已有这套）；这里把 UI 搬到 super 工作台。
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Calendar, Play, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { schedulesApi } from '@/lib/api/schedules';
import { errMessage } from '@/lib/errors';
import { useConfirm } from '@/components/providers/ConfirmProvider';
import type { ScheduleCreateInput, SchedulePublic, ScheduleKind } from '@/types/schedule';

const PRESETS: Array<{ labelKey: string; expr: string }> = [
  { labelKey: 'superPanel.schedulePresetEvery3min', expr: '*/3 * * * *' },
  { labelKey: 'superPanel.schedulePresetHourly', expr: '0 * * * *' },
  { labelKey: 'superPanel.schedulePresetDaily9', expr: '0 9 * * *' },
  { labelKey: 'superPanel.schedulePresetMon9', expr: '0 9 * * 1' },
];

export function ScheduleEditor({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [list, setList] = useState<SchedulePublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState<ScheduleCreateInput>({
    name: '',
    kind: 'cron',
    expr: '*/30 * * * *',
    enabled: true,
  });

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      setList(await schedulesApi.list(projectId));
    } catch (e) {
      setErr(errMessage(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function create() {
    if (!form.name || !form.expr) return;
    try {
      await schedulesApi.create(projectId, form);
      setForm({ name: '', kind: 'cron', expr: '*/30 * * * *', enabled: true });
      setShowAdd(false);
      await refresh();
    } catch (e) {
      setErr(errMessage(e));
    }
  }
  async function toggle(s: SchedulePublic) {
    await schedulesApi.update(projectId, s.id, { enabled: !s.enabled });
    await refresh();
  }
  async function fire(s: SchedulePublic) {
    await schedulesApi.fire(projectId, s.id);
    setTimeout(refresh, 600);
  }
  async function del(s: SchedulePublic) {
    if (!(await confirm({ message: t('superPanel.scheduleDeleteConfirm', { name: s.name }), danger: true }))) return;
    await schedulesApi.delete(projectId, s.id);
    await refresh();
  }

  return (
    <div className="border border-border rounded p-2 text-xs bg-card space-y-2">
      <div className="flex items-center gap-2">
        <Calendar className="w-3.5 h-3.5" />
        <span className="font-semibold text-foreground">{t('superPanel.scheduleTitle', { count: list.length })}</span>
        <Button size="sm" variant="ghost" onClick={() => void refresh()} className="h-6 px-1.5">
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="ml-auto h-6 px-1.5"
          onClick={() => setShowAdd((v) => !v)}
        >
          <Plus className="w-3 h-3 mr-1" /> {t('superPanel.scheduleNew')}
        </Button>
      </div>

      {err && <div className="text-destructive bg-destructive/10 p-1 rounded">{err}</div>}

      {showAdd && (
        <div className="border border-border rounded p-2 bg-muted space-y-1.5">
          <Input
            placeholder={t('superPanel.scheduleNamePlaceholder')}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="h-7 text-xs"
          />
          <div className="flex gap-1">
            <Select
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value as ScheduleKind })}
              className="w-20 h-7 text-xs"
            >
              <option value="cron">cron</option>
              <option value="interval">interval(s)</option>
              <option value="event">event</option>
            </Select>
            <Input
              placeholder={form.kind === 'cron' ? '*/30 * * * *' : form.kind === 'interval' ? '300' : 'event_name'}
              value={form.expr}
              onChange={(e) => setForm({ ...form, expr: e.target.value })}
              className="flex-1 h-7 text-xs font-mono"
            />
            <Button size="sm" onClick={() => void create()} className="h-7 px-2">
              {t('superPanel.scheduleAdd')}
            </Button>
          </div>
          {form.kind === 'cron' && (
            <div className="flex flex-wrap gap-1">
              {PRESETS.map((p) => (
                <button
                  key={p.labelKey}
                  onClick={() => setForm({ ...form, expr: p.expr })}
                  className="text-[10px] bg-card border border-border text-foreground px-1.5 py-0.5 rounded hover:bg-accent/50"
                >
                  {t(p.labelKey)}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {list.length === 0 ? (
        <div className="text-muted-foreground/70 italic text-center py-2">{t('superPanel.scheduleEmpty')}</div>
      ) : (
        <table className="w-full">
          <thead className="text-muted-foreground">
            <tr>
              <th className="text-left py-1 font-normal">{t('superPanel.scheduleColName')}</th>
              <th className="text-left py-1 font-normal">{t('superPanel.scheduleColKind')}</th>
              <th className="text-left py-1 font-normal">{t('superPanel.scheduleColExpr')}</th>
              <th className="text-left py-1 font-normal">{t('superPanel.scheduleColNext')}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {list.map((s) => (
              <tr key={s.id} className="border-t border-border text-foreground">
                <td className="py-1">{s.name}</td>
                <td className="py-1">{s.kind}</td>
                <td className="py-1 font-mono">{s.expr}</td>
                <td className="py-1">
                  {s.next_fire_at ? new Date(s.next_fire_at).toLocaleString().slice(5, 19) : '-'}
                </td>
                <td className="py-1 text-right">
                  <button
                    onClick={() => void toggle(s)}
                    title={s.enabled ? t('superPanel.scheduleToggleDisable') : t('superPanel.scheduleToggleEnable')}
                    className="px-1"
                  >
                    {s.enabled ? '✅' : '⭕'}
                  </button>
                  <button onClick={() => void fire(s)} title={t('superPanel.scheduleFire')} className="px-1">
                    <Play className="w-3 h-3 inline" />
                  </button>
                  <button onClick={() => void del(s)} title={t('common.delete')} className="px-1 text-destructive">
                    <Trash2 className="w-3 h-3 inline" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
