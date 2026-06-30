# Demo recording shot-list

Storyboards for the README demo table. Record each as a short clip (or GIF) in **English** first (default UI), then switch the top-right toggle to 中 and record the Chinese pass. Suggested asset paths in `docs/media/`.

> Note: these must be recorded by a human (screen capture). The app flows below are all verified working; this is just the shot order.

## 1 · 60-second overview  → `docs/media/overview-en.mp4`
1. Land on **/login** (dark, hexagon-C logo, EN/中 + theme toggles top-right).
2. Sign in (`admin`). Land on **Overview** — "How Colony works" 4 steps.
3. Hover the Builder quick-start card → click into the Builder.
4. (Optional) flip theme to light, then back to dark, to show the design system.

## 2 · Onboarding: provider → first assistant  → `docs/media/onboarding-en.mp4`
1. Fresh install (is_install=0). Overview shows the **Getting-started banner**: "Configure your LLM provider".
2. Go to **LLM providers** → add a provider → **Sync models**.
3. Back on the dashboard banner → **pick default supervisor + worker models** → "Initialize & go to Builder".
4. Auto-init runs → lands in the **Builder** chat. Type one sentence ("run my Xiaohongshu account") → Builder starts designing.

## 3 · A mission running autonomously  → `docs/media/mission-en.mp4`
1. Open a Super's **mission workbench** (`/mission/<slug>`): 3-column — sessions / chat stream / live panel.
2. Show the **schedule** tab (cron/interval) and the **live worker calls** panel during a tick.
3. Show an **approval card** appearing inline; approve it. Show the **Manual / Full-auto** toggle.

## 4 · Self-optimization (ATA loop)  → `docs/media/selfopt-en.mp4`
1. Open the Builder's system **"平台 Worker 健康自检 / Worker health self-check"** session (non-deletable).
2. Show a worker's **observe page** (`/worker/<id>`): success rate, per-action, top errors.
3. Show the work-log / a protocol auto-iteration entry (Super flags issue → Builder fixes → resume).

---

After recording, drop the files in `docs/media/` and replace the `_add link_` placeholders in `README.md` / `README_zh.md`.
