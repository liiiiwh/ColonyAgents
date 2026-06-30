'use client';

/**
 * v3：用户多 super 选择页。
 * Project 概念已退化为「super agent 的家」；这里列出该用户可访问的 super，
 * 点击进入 /super/[slug]（R23 观察页）。
 *
 * 老路由 `/projects` 兼容保留；如只有 1 个 super 自动跳转。
 */
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, Bot, RefreshCw } from 'lucide-react';
import { AxiosError } from 'axios';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { PageLoading } from '@/components/ui/page-loading';
import { missionsAdminApi } from '@/lib/api/missionsAdmin';
import { useAuthStore } from '@/stores/authStore';
import type { MissionPublic } from '@/types/mission';

export default function SupersLandingPage() {
  const router = useRouter();
  const { t } = useTranslation();
  const hydrated = useAuthStore((s) => s.hydrated);
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const loadCurrentUser = useAuthStore((s) => s.loadCurrentUser);
  const [supers, setSupers] = useState<MissionPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!hydrated) return;
    if (!accessToken) {
      router.replace('/login?next=/missions');
      return;
    }
    if (!user) {
      loadCurrentUser().catch(() => router.replace('/login'));
      return;
    }
    if (user.role === 'admin') {
      router.replace('/admin');
      return;
    }
    setLoading(true);
    setErr(null);
    missionsAdminApi
      .listActive()
      .then((items) => {
        if (items.length === 1) {
          router.replace(`/super/${items[0].slug}`);
          return;
        }
        setSupers(items);
      })
      .catch((e) => {
        setErr(e instanceof AxiosError ? (e.response?.data?.detail ?? e.message) : t('supersLanding.loadFailed'));
      })
      .finally(() => setLoading(false));
  }, [hydrated, accessToken, user, loadCurrentUser, router]);

  if (loading) {
    return <PageLoading title={t('supersLanding.loadingTitle')} description={t('supersLanding.loadingDesc')} />;
  }
  if (err) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6">
        <div className="rounded-2xl border border-destructive/30 bg-card p-6 text-center max-w-md">
          <RefreshCw className="mx-auto mb-3 h-6 w-6 text-destructive" />
          <h1 className="text-lg font-medium text-foreground">{t('supersLanding.loadFailedTitle')}</h1>
          <p className="text-sm text-muted-foreground mt-2">{err}</p>
          <Button className="mt-4" variant="outline" onClick={() => window.location.reload()}>
            {t('common.refresh')}
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-4xl mx-auto">
        <header className="text-center mb-8">
          <div className="mx-auto h-12 w-12 rounded-2xl bg-primary text-primary-foreground flex items-center justify-center mb-3">
            <Bot className="h-5 w-5" />
          </div>
          <h1 className="text-2xl font-medium text-foreground">{t('supersLanding.chooseTitle')}</h1>
          <p className="text-sm text-muted-foreground mt-2">
            {t('supersLanding.chooseHint')}{' '}
            <a href="/orchestrator" className="font-medium text-primary underline">
              {t('supersLanding.openBuilder')}
            </a>
          </p>
        </header>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {supers.map((s) => (
            <button
              key={s.id}
              onClick={() => router.push(`/super/${s.slug}`)}
              className="border border-border bg-card rounded-2xl p-5 text-left hover:border-primary/40 transition-colors"
            >
              <h2 className="font-medium text-foreground truncate">{s.name}</h2>
              <p className="text-xs text-muted-foreground mt-0.5">/super/{s.slug}</p>
              <p className="text-sm text-muted-foreground mt-3 line-clamp-2 min-h-[40px]">
                {s.description || t('supersLanding.cardDescFallback')}
              </p>
              <div className="mt-4 flex items-center justify-between text-sm text-foreground">
                <span>{t('supersLanding.enter')}</span>
                <ArrowRight className="h-4 w-4" />
              </div>
            </button>
          ))}
        </div>
        {supers.length === 0 && (
          <div className="text-center text-muted-foreground text-sm p-8">
            {t('supersLanding.empty')}{' '}
            <a className="text-primary underline" href="/orchestrator">
              {t('supersLanding.openBuilder')}
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
