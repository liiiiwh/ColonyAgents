'use client';

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const { t } = useTranslation();
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-destructive/15 text-destructive">
        <AlertTriangle className="h-6 w-6" />
      </div>
      <h1 className="mt-5 text-xl font-medium text-foreground">{t('errors.errorTitle')}</h1>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">{t('errors.errorDesc')}</p>
      {error?.message && (
        <pre className="mt-3 max-w-md overflow-auto rounded-lg border border-border bg-card px-3 py-2 text-left text-xs text-muted-foreground">
          {error.message}
        </pre>
      )}
      <div className="mt-6 flex gap-2">
        <Button onClick={reset}>{t('errors.tryAgain')}</Button>
        <Button variant="outline" onClick={() => (window.location.href = '/')}>
          {t('errors.goHome')}
        </Button>
      </div>
    </div>
  );
}
