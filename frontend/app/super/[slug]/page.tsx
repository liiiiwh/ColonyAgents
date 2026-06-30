'use client';

/**
 * /super/[slug] 已退役（原「Super 角色模板」过渡页）→ 一律重定向进工作台。
 *
 * 角色定义（Soul / Skills / 共享记忆）改由 Agent 配置页 /admin/agents/[id] 承载；
 * 新建 Mission 由工作台空壳自动弹出。这里只做解析重定向，保留路由不破坏老书签/外链：
 *  - slug 是 mission  → /mission/<super_slug>/<mission_slug>
 *  - slug 是 super    → /mission/<super_slug>/<primary_mission 或 super_slug>
 *      （super 无 mission 时用 super-slug 当 missionSlug，后端 superThreads 返回空壳 +
 *       工作台自动弹「新建 Mission」——与 Agent 列表「进入工作台」同一约定）
 *  - 都不匹配         → 回 Agent 列表
 */
import { useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { agentsApi } from '@/lib/api/agents';
import { missionsApi } from '@/lib/api/missions';
import { useAuthStore } from '@/stores/authStore';

export default function SuperRedirect() {
  const params = useParams<{ slug: string }>();
  const router = useRouter();
  const slug = decodeURIComponent(params.slug);
  const hydrated = useAuthStore((s) => s.hydrated);
  const accessToken = useAuthStore((s) => s.accessToken);

  useEffect(() => {
    if (!hydrated || !accessToken) return;
    let cancelled = false;
    (async () => {
      // 1) slug 是 mission？→ 直接进该 mission 工作台
      const m = await missionsApi.get(slug).catch(() => null);
      if (cancelled) return;
      if (m && m.super_slug) {
        router.replace(`/mission/${m.super_slug}/${m.slug}`);
        return;
      }
      // 2) slug 是 super？→ 进其 primary mission（无则用 super-slug 走空壳 + 自动弹新建）
      const agents = await agentsApi.list().catch(() => []);
      if (cancelled) return;
      const sup = agents.find(
        (a) => a.kind === 'super' && (a.slug === slug || a.id === slug || a.name === slug),
      );
      if (sup) {
        const superSlug = sup.slug ?? sup.id;
        const ms = await missionsApi.list(sup.id).catch(() => []);
        if (cancelled) return;
        const missionSlug = ms[0]?.slug ?? superSlug;
        router.replace(`/mission/${superSlug}/${missionSlug}`);
        return;
      }
      // 3) 兜底
      router.replace('/admin/agents?tab=super');
    })();
    return () => {
      cancelled = true;
    };
  }, [hydrated, accessToken, slug, router]);

  return (
    <div className="flex h-screen items-center justify-center bg-background text-sm text-muted-foreground">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" /> …
    </div>
  );
}
