'use client';

import { createContext, useCallback, useContext, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';

// 主题化 confirm/toast 取代原生 confirm()/alert()（与暗色设计一致 + i18n 按钮）。
export type ConfirmOptions = {
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
};
type ToastVariant = 'default' | 'success' | 'error';
type ToastItem = { id: number; message: string; variant: ToastVariant };

type ConfirmCtx = {
  confirm: (opts: ConfirmOptions | string) => Promise<boolean>;
  toast: (message: string, variant?: ToastVariant) => void;
};

const Ctx = createContext<ConfirmCtx>({ confirm: async () => true, toast: () => {} });

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const [pending, setPending] = useState<{ opts: ConfirmOptions; resolve: (v: boolean) => void } | null>(
    null,
  );
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const confirm = useCallback((o: ConfirmOptions | string) => {
    const opts = typeof o === 'string' ? { message: o } : o;
    return new Promise<boolean>((resolve) => setPending({ opts, resolve }));
  }, []);

  const toast = useCallback((message: string, variant: ToastVariant = 'default') => {
    const id = Date.now() + Math.random();
    setToasts((p) => [...p, { id, message, variant }]);
    setTimeout(() => setToasts((p) => p.filter((x) => x.id !== id)), 4000);
  }, []);

  const settle = (val: boolean) => {
    pending?.resolve(val);
    setPending(null);
  };

  return (
    <Ctx.Provider value={{ confirm, toast }}>
      {children}

      {pending && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4"
          onClick={() => settle(false)}
        >
          <div
            className="w-full max-w-sm rounded-xl border border-border bg-card p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            {pending.opts.title && (
              <h2 className="text-base font-medium text-foreground">{pending.opts.title}</h2>
            )}
            <p className="mt-1.5 whitespace-pre-wrap text-sm text-muted-foreground">
              {pending.opts.message}
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => settle(false)}>
                {pending.opts.cancelText ?? t('common.cancel')}
              </Button>
              <Button
                size="sm"
                className={pending.opts.danger ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90' : ''}
                onClick={() => settle(true)}
              >
                {pending.opts.confirmText ?? t('common.confirm')}
              </Button>
            </div>
          </div>
        </div>
      )}

      {toasts.length > 0 && (
        <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2">
          {toasts.map((tt) => (
            <div
              key={tt.id}
              className={`max-w-sm rounded-lg border px-3.5 py-2.5 text-sm shadow-lg ${
                tt.variant === 'error'
                  ? 'border-destructive/40 bg-destructive/10 text-destructive'
                  : tt.variant === 'success'
                    ? 'border-success/40 bg-success/10 text-success'
                    : 'border-border bg-card text-foreground'
              }`}
            >
              {tt.message}
            </div>
          ))}
        </div>
      )}
    </Ctx.Provider>
  );
}

export const useConfirm = () => useContext(Ctx).confirm;
export const useToast = () => useContext(Ctx).toast;
