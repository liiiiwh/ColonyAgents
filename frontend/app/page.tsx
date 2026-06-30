'use client';

/**
 * 根路径分流（Colony）：
 * - 未登录 → /login
 * - admin → /admin（M4 后默认进 Builder Chat 入口的看板）
 * - 普通用户 → /orchestrator（直接进 Builder Chat）
 */
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Lock, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuthStore } from '@/stores/authStore';

export default function Home() {
  const router = useRouter();
  const [pageState, setPageState] = useState<'loading' | 'empty' | 'error'>('loading');
  const hydrated = useAuthStore((s) => s.hydrated);
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const loadCurrentUser = useAuthStore((s) => s.loadCurrentUser);

  useEffect(() => {
    if (!hydrated) {
      setPageState('loading');
      return;
    }
    if (!accessToken) {
      router.replace('/login');
      return;
    }
    if (!user) {
      setPageState('loading');
      loadCurrentUser().catch(() => router.replace('/login'));
      return;
    }
    if (user.role === 'admin') {
      router.replace('/admin');
      return;
    }
    router.replace('/orchestrator');
  }, [hydrated, accessToken, user, loadCurrentUser, router]);

  if (pageState === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        正在加载…
      </div>
    );
  }

  if (pageState === 'error') {
    return (
      <div className="flex min-h-screen items-center justify-center px-6 py-12">
        <div className="w-full max-w-lg rounded-2xl border border-red-100 bg-white p-8 text-center shadow-sm">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-50 text-red-500">
            <RefreshCw className="h-5 w-5" />
          </div>
          <h1 className="text-xl font-semibold text-neutral-900">项目加载失败</h1>
          <p className="mt-2 text-sm leading-6 text-neutral-600">
            当前无法获取可访问项目列表，请稍后刷新重试；如果问题持续存在，请联系管理员排查权限或服务状态。
          </p>
          <div className="mt-6 flex justify-center">
            <Button type="button" variant="outline" onClick={() => window.location.reload()}>
              刷新页面
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-12">
      <div className="w-full max-w-lg rounded-2xl border border-amber-100 bg-white p-8 text-center shadow-sm">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-amber-50 text-amber-600">
          <Lock className="h-5 w-5" />
        </div>
        <h1 className="text-xl font-semibold text-neutral-900">暂无可访问项目</h1>
        <p className="mt-2 text-sm leading-6 text-neutral-600">
          你当前还没有被分配任何项目权限，暂时无法进入工作台。请联系管理员为你分配项目访问权限后再试。
        </p>
        <div className="mt-6 flex justify-center">
          <Button type="button" variant="outline" onClick={() => window.location.reload()}>
            重新检查
          </Button>
        </div>
      </div>
    </div>
  );
}
