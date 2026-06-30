'use client';

/**
 * Legacy redirect: `/p/[slug]` -> `/super/[slug]`.
 *
 * The old `/p/[slug]` was a user chat page; Colony now centers conversations on
 * the mission workbench, so old bookmarks / shared links redirect client-side
 * to the canonical `/super/[slug]` super page.
 */

import { useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useTranslation } from 'react-i18next';

export default function LegacyProjectChatRedirect() {
  const { t } = useTranslation();
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();
  useEffect(() => {
    router.replace(`/super/${slug}`);
  }, [slug, router]);
  return (
    <div className="flex h-screen items-center justify-center text-sm text-muted-foreground/70">
      {t('embed.redirecting')}
    </div>
  );
}
