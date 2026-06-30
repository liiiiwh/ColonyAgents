'use client';

/**
 * 兼容解析器：/mission/<slug>（单段）→ 重定向到 /mission/<super>/<mission>（嵌套）。
 *
 * 老书签、CTA「进入 super」、以及任何只有 mission slug 的链接都落到这里：
 *  - slug 是 mission → 查出它的 super_slug → replace 到 /mission/<super_slug>/<mission_slug>
 *  - 否则可能是 super slug → 跳 /super/<slug>（super 角色页，会再决定进哪个 mission）
 */
import { useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { missionsApi } from '@/lib/api/missions';

export default function MissionRedirectResolver() {
  const params = useParams<{ superSlug: string }>();
  const router = useRouter();
  const slug = decodeURIComponent(params.superSlug);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const m = await missionsApi.get(slug).catch(() => null);
      if (cancelled) return;
      if (m && m.super_slug) {
        router.replace(`/mission/${m.super_slug}/${m.slug}`);
      } else {
        router.replace(`/super/${slug}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slug, router]);

  return (
    <div className="h-screen flex items-center justify-center text-sm text-muted-foreground">
      <Loader2 className="w-4 h-4 mr-2 animate-spin" /> …
    </div>
  );
}
