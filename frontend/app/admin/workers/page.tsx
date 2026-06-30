'use client';

/** v4 · /admin/workers 已合到 /admin/agents?tab=worker */
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function WorkersRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/admin/agents?tab=worker');
  }, [router]);
  return (
    <div className="flex h-screen items-center justify-center text-sm text-neutral-500">
      v4：Worker Catalog 已合到 Agents 页内，正在跳转…
    </div>
  );
}
