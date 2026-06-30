'use client';

/** v4 · /orchestrator 已废弃 → redirect 到 /super/builder
 *  Builder = 第一个 super agent；用户跟 Builder 对话 = 进 super 工作台
 */
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslation } from 'react-i18next';

export default function OrchestratorRedirect() {
  const router = useRouter();
  const { t } = useTranslation();
  useEffect(() => {
    router.replace('/super/builder');
  }, [router]);
  return (
    <div className="flex h-screen items-center justify-center bg-background text-sm text-muted-foreground">
      {t('orchestrator.redirecting')}
    </div>
  );
}
