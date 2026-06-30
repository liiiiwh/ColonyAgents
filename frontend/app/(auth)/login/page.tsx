'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { AxiosError } from 'axios';
import { useTranslation } from 'react-i18next';
import { RefreshCw, Coins, Zap, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { LogoMark } from '@/components/brand/Logo';
import { useAuthStore } from '@/stores/authStore';

export default function LoginPage() {
  const router = useRouter();
  const { t } = useTranslation();
  const login = useAuthStore((s) => s.login);
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(username, password);
      const params = new URLSearchParams(window.location.search);
      const next = params.get('next');
      if (next && next.startsWith('/')) {
        router.push(next);
      } else {
        const { useAuthStore } = await import('@/stores/authStore');
        const user = useAuthStore.getState().user;
        router.push(user?.role === 'admin' ? '/admin' : '/orchestrator');
      }
    } catch (err) {
      const msg =
        err instanceof AxiosError
          ? (err.response?.data?.detail ?? err.message)
          : err instanceof Error
            ? err.message
            : t('login.failed');
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  const features = [
    { icon: RefreshCw, label: t('features.selfLoop') },
    { icon: Coins, label: t('features.lowCost') },
    { icon: Zap, label: t('features.highThroughput') },
  ];

  return (
    <div className="relative min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-[380px]">
        <div className="flex flex-col items-center text-center mb-7">
          <LogoMark size={46} className="mb-4" />
          <h1 className="text-[25px] font-medium text-foreground tracking-tight">Colony</h1>
          <p className="text-[13.5px] text-muted-foreground mt-2 leading-relaxed max-w-[320px]">
            {t('brand.tagline')}
          </p>
        </div>

        <div className="bg-card border border-border rounded-xl p-6">
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="username">{t('login.username')}</Label>
              <Input
                id="username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder={t('login.usernamePlaceholder')}
                disabled={loading}
                required
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="password">{t('login.password')}</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t('login.passwordPlaceholder')}
                disabled={loading}
                required
              />
            </div>

            {error && <div className="text-[12.5px] text-destructive">{error}</div>}

            <Button type="submit" size="lg" disabled={loading} className="mt-1 gap-2">
              {loading ? t('login.signingIn') : t('login.signIn')}
              {!loading && <ArrowRight className="h-4 w-4" />}
            </Button>
          </form>

          <div className="mt-5 pt-4 border-t border-border">
            <p className="text-[12px] text-muted-foreground leading-relaxed">
              {t('login.needAccount')}
            </p>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-3 gap-2">
          {features.map(({ icon: Icon, label }) => (
            <div
              key={label}
              className="flex flex-col items-center gap-1.5 rounded-lg border border-border bg-card px-2 py-3"
            >
              <Icon className="h-[18px] w-[18px] text-primary" />
              <span className="text-[11px] font-medium text-secondary-foreground">{label}</span>
            </div>
          ))}
        </div>

        <p className="text-center text-[11.5px] text-muted-foreground/70 mt-6">
          {t('brand.footer')}
        </p>
      </div>
    </div>
  );
}
