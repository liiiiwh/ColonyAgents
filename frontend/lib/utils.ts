import { AxiosError } from 'axios';
import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * D17：统一错误消息提取。后端可能返回 `detail` / `message` / `error` 不同字段；
 * 多 fallback 防显示 undefined。
 */
export function extractErrorMessage(e: unknown, fallback = '未知错误'): string {
  if (e instanceof AxiosError) {
    const data = e.response?.data as Record<string, unknown> | undefined;
    return (
      (data?.detail as string) ??
      (data?.message as string) ??
      (data?.error as string) ??
      e.message ??
      fallback
    );
  }
  if (e instanceof Error) {
    return e.message || fallback;
  }
  return String(e ?? fallback);
}

/**
 * 合并 Tailwind classNames，解决类名冲突（shadcn/ui 风格）。
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * 生成 UUID v4。
 * 优先使用 crypto.randomUUID()（需要 Secure Context / HTTPS），
 * 降级到手动拼接以兼容 HTTP 部署和旧版浏览器。
 */
export function randomUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  // RFC 4122 v4 fallback
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}
