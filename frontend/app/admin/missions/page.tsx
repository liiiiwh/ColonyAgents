'use client';

/** v4 · /admin/projects 已合到 /admin/agents?tab=super */
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function ProjectsRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/admin/agents?tab=super');
  }, [router]);
  return (
    <div className="flex h-screen items-center justify-center text-sm text-neutral-500">
      v4：Projects 已合到 Super Agents tab，正在跳转…
    </div>
  );
}
