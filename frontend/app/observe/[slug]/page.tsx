'use client';

/**
 * v3：`/observe/[slug]` 已迁移到 `/super/[slug]`（R23 super 观察页）。
 * 老书签 / 外链自动跳转，保持兼容。
 *
 * v1 老观察页（含 MissionNode workspace tab / nodes 概念）已废弃；
 * v3 的 super 观察页是 3 栏布局：thread 树 + 完整对话 + worker 卡 + 交付物。
 */
import { useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useTranslation } from 'react-i18next';

export default function LegacyObserveRedirect() {
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();
  const { t } = useTranslation();
  useEffect(() => {
    router.replace(`/super/${slug}`);
  }, [slug, router]);
  return (
    <div className="flex h-screen items-center justify-center bg-background text-sm text-muted-foreground/70">
      {t('observe.redirecting')}
    </div>
  );
}
