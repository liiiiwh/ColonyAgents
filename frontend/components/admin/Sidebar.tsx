'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Bot,
  Boxes,
  CheckCheck,
  Database,
  Home,
  LogOut,
  Plug,
  Puzzle,
  Server,
  Settings,
  Users,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { useAuthStore } from '@/stores/authStore';
import { LogoMark } from '@/components/brand/Logo';

type Item = { href: string; key: string; icon: React.ComponentType<{ className?: string }> };
type Section = { titleKey?: string; items: Item[] };

const SECTIONS: Section[] = [
  { items: [{ href: '/admin', key: 'overview', icon: Home }] },
  {
    titleKey: 'nav.sectionBuild',
    items: [
      { href: '/admin/agents', key: 'agents', icon: Bot },
      { href: '/admin/skills', key: 'skills', icon: Puzzle },
      { href: '/admin/mcp-servers', key: 'mcp', icon: Server },
      { href: '/admin/providers', key: 'providers', icon: Plug },
    ],
  },
  {
    titleKey: 'nav.sectionKnowledge',
    items: [
      { href: '/admin/knowledge', key: 'knowledge', icon: Database },
      { href: '/admin/storage', key: 'storage', icon: Boxes },
    ],
  },
  {
    titleKey: 'nav.sectionPlatform',
    items: [
      { href: '/admin/clawbot', key: 'approvals', icon: CheckCheck },
      { href: '/admin/users', key: 'users', icon: Users },
      { href: '/admin/system-settings', key: 'settings', icon: Settings },
    ],
  },
];

export function AdminSidebar() {
  const pathname = usePathname();
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  return (
    <aside className="flex h-screen w-60 shrink-0 flex-col border-r border-border bg-card">
      <div className="flex h-16 items-center gap-2.5 px-5">
        <LogoMark size={26} />
        <span className="text-[15px] font-medium tracking-tight text-foreground">Colony</span>
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-2 scrollbar-thin">
        {SECTIONS.map((section, i) => (
          <div key={i} className="space-y-0.5">
            {section.titleKey && (
              <div className="px-3 pb-1.5 text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground/70">
                {t(section.titleKey)}
              </div>
            )}
            {section.items.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'group relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors',
                    active
                      ? 'bg-accent text-foreground'
                      : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
                  )}
                >
                  {active && (
                    <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-primary" />
                  )}
                  <item.icon
                    className={cn('h-[18px] w-[18px]', active && 'text-primary')}
                  />
                  {t(`nav.${item.key}`)}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="border-t border-border p-3">
        <div className="mb-1 flex items-center gap-2.5 px-2 py-1.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/15 text-[12px] font-medium text-primary">
            {(user?.username ?? '?').slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] text-foreground">{user?.username ?? '—'}</div>
            <div className="text-[11px] text-muted-foreground">{user?.role ?? '—'}</div>
          </div>
        </div>
        <button
          onClick={logout}
          className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
        >
          <LogOut className="h-[18px] w-[18px]" />
          {t('nav.logout')}
        </button>
      </div>
    </aside>
  );
}
