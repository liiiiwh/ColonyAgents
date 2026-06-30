import type { Metadata } from 'next';
import './globals.css';
import { Providers } from '@/components/providers/Providers';
import { GlobalControls } from '@/components/layout/GlobalControls';

export const metadata: Metadata = {
  title: 'Colony · Open-source ATA platform',
  description: 'Autonomous task agents that run, learn, and fix themselves.',
};

// 上漆前应用主题/语言，避免 FOUC（默认深色=无 class；仅 light 需加 class）。
const noFlashScript = `(function(){try{
var t=localStorage.getItem('colony-theme');
if(t==='light')document.documentElement.classList.add('light');
var l=localStorage.getItem('colony-locale');
if(l==='zh')document.documentElement.lang='zh-CN';
}catch(e){}})();`;

/**
 * 字体：系统字体栈（tailwind.config 已配 fallback），不走 Google Fonts，避免 SSR 阻塞。
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: noFlashScript }} />
      </head>
      <body className="font-sans antialiased min-h-screen">
        <Providers>
          <GlobalControls />
          {children}
        </Providers>
      </body>
    </html>
  );
}
