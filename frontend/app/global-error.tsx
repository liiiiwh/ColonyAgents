'use client';

// 根级错误边界：替换 root layout（无 Providers，故不走 i18n，内联深色样式）。
export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#08080a',
          color: '#e7e7ea',
          fontFamily: '-apple-system, system-ui, sans-serif',
          textAlign: 'center',
          padding: '1rem',
        }}
      >
        <div style={{ fontSize: 22, fontWeight: 500 }}>Something went wrong</div>
        <p style={{ color: '#85858e', fontSize: 14, maxWidth: 360, marginTop: 8 }}>
          A critical error occurred. Try reloading.
        </p>
        <button
          onClick={reset}
          style={{
            marginTop: 20,
            background: '#6C5CE7',
            color: '#fff',
            border: 'none',
            borderRadius: 9,
            padding: '9px 18px',
            fontSize: 14,
            cursor: 'pointer',
          }}
        >
          Reload
        </button>
      </body>
    </html>
  );
}
