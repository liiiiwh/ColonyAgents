'use client';
import { useTranslation } from 'react-i18next';
import { setLocale, currentLocale, type Locale } from '@/lib/i18n';
import { cn } from '@/lib/utils';

// EN / 中 段控切换，写 localStorage + 立即重渲染。
export function LanguageToggle({ className }: { className?: string }) {
  const { i18n } = useTranslation();
  const active = (i18n.language as Locale) || currentLocale();

  const pill = (lng: Locale, label: string) => (
    <button
      key={lng}
      type="button"
      onClick={() => setLocale(lng)}
      aria-pressed={active === lng}
      className={cn(
        'px-2.5 py-1 text-xs rounded-md transition-colors',
        active === lng
          ? 'bg-accent text-accent-foreground'
          : 'text-muted-foreground hover:text-foreground',
      )}
    >
      {label}
    </button>
  );

  return (
    <div
      className={cn(
        'inline-flex items-center gap-0.5 rounded-lg border border-border bg-card p-0.5',
        className,
      )}
      role="group"
      aria-label="Language"
    >
      {pill('en', 'EN')}
      {pill('zh', '中')}
    </div>
  );
}
