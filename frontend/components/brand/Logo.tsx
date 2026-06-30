import { cn } from '@/lib/utils';

const VIOLET = '#6C5CE7';

// 六边形 C 品牌标记（紫罗兰）。全站统一：登录 / 侧边栏 / 加载页 / favicon。
export function LogoMark({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      role="img"
      aria-label="Colony"
    >
      <path
        d="M16 2.5 27.7 9.25 V22.75 L16 29.5 4.3 22.75 V9.25 Z"
        fill={VIOLET}
      />
      <text
        x="16"
        y="21.3"
        textAnchor="middle"
        fontSize="15"
        fontWeight="600"
        fill="#fff"
        fontFamily="-apple-system, system-ui, sans-serif"
      >
        C
      </text>
    </svg>
  );
}

export function Wordmark({
  size = 28,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <LogoMark size={size} />
      <span
        className="font-medium tracking-tight text-foreground"
        style={{ fontSize: size * 0.72 }}
      >
        Colony
      </span>
    </div>
  );
}
