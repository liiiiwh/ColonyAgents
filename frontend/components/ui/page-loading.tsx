'use client';

import { HashLoader } from 'react-spinners';
import { cn } from '@/lib/utils';

interface PageLoadingProps {
  title?: string;
  description?: string;
  className?: string;
  fullscreen?: boolean;
}

export function PageLoading({
  title = '正在加载项目工作台',
  description = '正在同步 mission 配置、线程状态和工作区数据，请稍候。',
  className,
  fullscreen = true,
}: PageLoadingProps) {
  return (
    <div
      className={cn(
        'relative isolate overflow-hidden bg-background',
        fullscreen ? 'flex min-h-screen items-center justify-center px-6 py-10' : 'flex items-center justify-center p-8',
        className,
      )}
    >
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute left-1/2 top-[16%] h-52 w-52 -translate-x-1/2 rounded-full bg-primary/10 blur-3xl" />
        <div className="absolute bottom-[14%] left-[18%] h-40 w-40 rounded-full bg-secondary blur-3xl" />
        <div className="absolute right-[14%] top-[26%] h-36 w-36 rounded-full bg-primary/10 blur-3xl" />
      </div>

      <div className="relative w-full max-w-xl rounded-3xl border border-border/70 bg-card/88 px-8 py-10 shadow-sm backdrop-blur-sm">
        <div className="flex flex-col items-center text-center">
          <div className="flex h-20 w-20 items-center justify-center rounded-full border border-primary/15 bg-primary/5">
            <HashLoader color="hsl(var(--primary))" size={34} speedMultiplier={0.9} />
          </div>

          <div className="mt-6 space-y-2">
            <h1 className="text-lg font-semibold text-foreground">{title}</h1>
            <p className="mx-auto max-w-md text-sm leading-6 text-muted-foreground">{description}</p>
          </div>

          <div className="mt-7 flex items-center gap-2 text-xs text-muted-foreground">
            <span className="inline-block h-2 w-2 rounded-full bg-primary/70 animate-pulse" />
            <span>系统正在准备当前工作上下文</span>
          </div>
        </div>

        <div className="mt-8 grid gap-3 sm:grid-cols-3">
          <div className="rounded-2xl border border-border/60 bg-background/75 p-4">
            <div className="shimmer h-2.5 w-16 rounded-full" />
            <div className="mt-3 shimmer h-7 w-20 rounded-lg" />
            <div className="mt-3 shimmer h-2.5 w-full rounded-full" />
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/75 p-4">
            <div className="shimmer h-2.5 w-14 rounded-full" />
            <div className="mt-3 shimmer h-7 w-24 rounded-lg" />
            <div className="mt-3 shimmer h-2.5 w-4/5 rounded-full" />
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/75 p-4">
            <div className="shimmer h-2.5 w-12 rounded-full" />
            <div className="mt-3 shimmer h-7 w-16 rounded-lg" />
            <div className="mt-3 shimmer h-2.5 w-3/4 rounded-full" />
          </div>
        </div>
      </div>
    </div>
  );
}