'use client';

/** v4 · /admin/sessions 已废弃 → 合到 super 详情页内的对话 / 调用历史 */
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function SessionsRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/admin/agents?tab=super');
  }, [router]);
  return (
    <div className="flex h-screen items-center justify-center text-sm text-neutral-500">
      历史线程已合到 mission 工作台内，正在跳转…
    </div>
  );
}
