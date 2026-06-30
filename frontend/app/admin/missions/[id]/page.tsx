'use client';

/** v4 · /admin/projects/[id] 已合到 super 工作台 */
import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { missionsAdminApi } from '@/lib/api/missionsAdmin';

export default function MissionEditRedirect() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const [msg, setMsg] = useState('正在跳转…');
  useEffect(() => {
    missionsAdminApi
      .get(id)
      .then((p) => router.replace(`/super/${p.slug}`))
      .catch(() => {
        setMsg('项目不存在；返回 Agents 列表');
        setTimeout(() => router.replace('/admin/agents?tab=super'), 1500);
      });
  }, [id, router]);
  return (
    <div className="flex h-screen items-center justify-center text-sm text-neutral-500">
      v4：项目编辑页已合到 super 工作台 — {msg}
    </div>
  );
}
