/**
 * 极简 Dialog（无动画、仅用于表单弹窗）。
 * 后续引入 shadcn CLI 可替换为 Radix 版本。
 */
'use client';

import { useEffect, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  className?: string;
  /** false = 强制门（onboarding gate）：无关闭按钮、点遮罩/Esc 不关。默认 true。 */
  dismissable?: boolean;
}

export function Dialog({ open, onClose, title, children, className, dismissable = true }: DialogProps) {
  useEffect(() => {
    if (!open || !dismissable) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose, dismissable]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={dismissable ? onClose : undefined}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={cn(
          // max-h-[90vh] + flex 列 + 子区域 overflow-y-auto，避免内容过高时弹出视口（拿不到底部按钮）
          'relative flex max-h-[90vh] w-full max-w-md flex-col rounded-[12px] border border-border bg-card shadow-lg',
          className,
        )}
      >
        {title && (
          <div className="flex shrink-0 items-center justify-between border-b border-border/60 px-6 py-4">
            <h2 className="text-lg font-semibold text-foreground">{title}</h2>
            {dismissable && (
              <button
                type="button"
                onClick={onClose}
                className="rounded-[6px] p-1 text-muted-foreground transition-colors hover:bg-accent"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {children}
        </div>
      </div>
    </div>
  );
}
