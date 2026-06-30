'use client';
import { usePathname } from 'next/navigation';
import { LanguageToggle } from '@/components/ui/LanguageToggle';
import { ThemeToggle } from '@/components/ui/ThemeToggle';

// 全局固定右上角：语言 + 主题切换。所有页面（含登录后）常驻。
export function GlobalControls() {
  const pathname = usePathname();
  // 工作台 /p/[slug] 嵌入式预览不挂（避免遮挡）。
  if (pathname?.startsWith('/p/')) return null;
  return (
    <div className="fixed top-4 right-4 z-40 flex items-center gap-2">
      <LanguageToggle />
      <ThemeToggle />
    </div>
  );
}
