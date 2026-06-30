'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import { AdminSidebar } from '@/components/admin/Sidebar';
import { InstallModal } from '@/components/admin/InstallModal';
import { useAuthStore } from '@/stores/authStore';

/**
 * Admin 访问守卫：未登录或非 admin 自动跳回 /login。
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { t } = useTranslation();
  // 单字段 selector，避免返回新对象触发 zustand re-render 死循环
  const hydrated = useAuthStore((s) => s.hydrated);
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const loadCurrentUser = useAuthStore((s) => s.loadCurrentUser);

  useEffect(() => {
    if (!hydrated) return;
    if (!accessToken) {
      router.replace('/login');
      return;
    }
    if (!user) {
      loadCurrentUser().catch(() => router.replace('/login'));
      return;
    }
    // 非 admin 用户不能进后台管理页，引导到仅会话的 /projects landing
    if (user.role !== 'admin') {
      router.replace('/missions');
    }
  }, [hydrated, accessToken, user, loadCurrentUser, router]);

  // 未就绪 / 未登录 / 非 admin（重定向中）→ 都只显示 loading，绝不渲染后台内容或触发 admin API
  if (!hydrated || !accessToken || !user || user.role !== 'admin') {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        {t('common.loading')}
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-background">
      {/* 固定左侧：页面滚动时保持可见 */}
      <div className="sticky top-0 h-screen shrink-0">
        <AdminSidebar />
      </div>
      <main className="flex-1 overflow-x-hidden">
        {children}
      </main>
      <InstallModal />
    </div>
  );
}
