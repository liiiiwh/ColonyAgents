'use client';

/**
 * /admin 概览页：用户视角的「Colony 怎么工作」+ 快速入口。
 * 不暴露内部实现细节（守卫编号 / daemon 内部名等）。
 */
import Link from 'next/link';
import { useTranslation } from 'react-i18next';
import { Bot, Code2, Lightbulb, Plug, Puzzle, Settings, ArrowRight } from 'lucide-react';

const STEPS = ['step1', 'step2', 'step3', 'step4'] as const;

const QUICK_LINKS = [
  { href: '/super/builder', label: 'Builder', icon: Lightbulb, descKey: 'overview.qlBuilder', primary: true },
  { href: '/admin/agents', label: 'Agents', icon: Bot, descKey: 'overview.qlAgents' },
  { href: '/admin/skills', label: 'Skills', icon: Puzzle, descKey: 'overview.qlSkills' },
  { href: '/admin/mcp-servers', label: 'MCP servers', icon: Code2, descKey: 'overview.qlMcp' },
  { href: '/admin/providers', label: 'LLM providers', icon: Plug, descKey: 'overview.qlProviders' },
  { href: '/admin/system-settings', label: 'System settings', icon: Settings, descKey: 'overview.qlSettings' },
];

export default function AdminDashboard() {
  const { t } = useTranslation();
  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <header className="pb-6">
        <h1 className="text-2xl font-medium tracking-tight text-foreground">{t('overview.title')}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t('overview.subtitle')}</p>
      </header>

      {/* How it works */}
      <section className="mb-7 rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 text-sm font-medium text-foreground">{t('overview.howTitle')}</h2>
        <ol className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <li key={s} className="relative rounded-lg border border-border bg-background p-4">
              <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-primary/15 text-xs font-medium text-primary">
                {i + 1}
              </span>
              <div className="mt-2.5 text-[13.5px] font-medium text-foreground">
                {t(`overview.${s}Title`)}
              </div>
              <div className="mt-1 text-xs leading-relaxed text-muted-foreground">
                {t(`overview.${s}Desc`)}
              </div>
            </li>
          ))}
        </ol>
      </section>

      <h2 className="mb-3 text-sm font-medium text-foreground">{t('overview.quickStart')}</h2>
      <section className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {QUICK_LINKS.map(({ href, label, icon: Icon, descKey, primary }) => (
          <Link
            key={href}
            href={href}
            className={`group flex items-start gap-3 rounded-xl border p-4 transition-colors ${
              primary
                ? 'border-primary/30 bg-primary/5 hover:border-primary/60'
                : 'border-border bg-card hover:border-primary/40'
            }`}
          >
            <Icon className={`mt-0.5 h-5 w-5 ${primary ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground'}`} />
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-1 text-sm font-medium text-foreground">
                {label}
                <ArrowRight className="h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-60" />
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">{t(descKey)}</p>
            </div>
          </Link>
        ))}
      </section>
    </div>
  );
}
