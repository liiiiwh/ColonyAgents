'use client';

/** v4 · /admin/memories 已废弃 → 合到 super 详情页右栏 */
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function MemoriesRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/admin/agents?tab=super');
  }, [router]);
  return (
    <div className="flex h-screen items-center justify-center text-sm text-neutral-500">
      线程记忆已合到 mission 工作台内，正在跳转…
    </div>
  );
}
