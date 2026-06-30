// 用 playwright 截取真实页面帧 → docs/media/frames/，供 ffmpeg 合成演示。
// 用法：node scripts/capture-demo.mjs  （需后端 9022 + 前端 3022 在跑）
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.DEMO_BASE || 'http://localhost:3022';
const USER = process.env.ADMIN_USER || 'admin';
const PASS = process.env.ADMIN_PASS || 'admin123';
const OUT = new URL('../../docs/media/frames/', import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });

// 演示「发了什么内容 → 得到什么结果」：真实工作台,不录 login/404。
const SHOTS = [
  { name: 'overview', path: '/admin' },
  { name: 'builder', path: '/mission/builder' },          // 描述目标 → Builder 设计出 super
  { name: 'douyin', path: '/mission/douyin-foodie' },     // 建好的 super + 其运营方案
  { name: 'seo', path: '/mission/seo-blog-auto' },        // 另一个领域的运营结果
  { name: 'workers', path: '/admin/agents?tab=worker' },  // 共享 worker + 成功率
];

const run = async () => {
  // 拿 token
  const res = await fetch(`${BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: USER, password: PASS }),
  });
  const { access_token, refresh_token } = await res.json();

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  // 预置 auth 到 localStorage（React 读取前）
  await ctx.addInitScript(
    ([a, r]) => {
      localStorage.setItem('colony-auth', JSON.stringify({ state: { accessToken: a, refreshToken: r }, version: 0 }));
    },
    [access_token, refresh_token],
  );
  const page = await ctx.newPage();

  let i = 1;
  for (const s of SHOTS) {
    await page.goto(`${BASE}${s.path}`, { waitUntil: 'networkidle' }).catch(() => {});
    await page.waitForTimeout(1500);
    const idx = String(i).padStart(3, '0');
    await page.screenshot({ path: `${OUT}${idx}-${s.name}.png` });
    console.log(`captured ${idx}-${s.name}`);
    i++;
  }
  await browser.close();
  console.log('DONE', OUT);
};
run().catch((e) => {
  console.error(e);
  process.exit(1);
});
