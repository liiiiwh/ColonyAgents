'use client';

import Link from 'next/link';
import { useTranslation } from 'react-i18next';
import { LogoMark } from '@/components/brand/Logo';
import { Button } from '@/components/ui/button';

export default function NotFound() {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 text-center">
      <LogoMark size={40} className="mb-6" />
      <div className="text-[64px] font-medium leading-none tracking-tight text-primary/80">
        {t('errors.code404')}
      </div>
      <h1 className="mt-4 text-xl font-medium text-foreground">{t('errors.notFoundTitle')}</h1>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">{t('errors.notFoundDesc')}</p>
      <Link href="/" className="mt-6">
        <Button>{t('errors.goHome')}</Button>
      </Link>
    </div>
  );
}
