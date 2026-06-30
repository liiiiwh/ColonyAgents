'use client';
import { I18nextProvider } from 'react-i18next';
import { getI18n } from '@/lib/i18n';
import { ThemeProvider } from '@/lib/theme/ThemeProvider';
import { ConfirmProvider } from '@/components/providers/ConfirmProvider';

export function Providers({ children }: { children: React.ReactNode }) {
  const i18n = getI18n();
  return (
    <I18nextProvider i18n={i18n}>
      <ThemeProvider>
        <ConfirmProvider>{children}</ConfirmProvider>
      </ThemeProvider>
    </I18nextProvider>
  );
}
