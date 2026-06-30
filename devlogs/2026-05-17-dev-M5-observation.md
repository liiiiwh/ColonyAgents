---
date: 2026-05-17
role: dev
task: M5 — 项目运行观察页 (/observe/[slug])
related_task_id: M5
files_changed:
  - backend/app/schemas/project.py            # ProjectLifecycleAction + 'run_once'
  - backend/app/api/projects.py               # /lifecycle/run_once 接 daemon.run_once
  - frontend/types/project.ts                 # ProjectLifecycleAction + 'run_once'
  - frontend/app/observe/[slug]/page.tsx      # 新建：5s 轮询 runtime + 最近消息 + 5 按钮
  - frontend/app/p/[slug]/page.tsx            # 重写为 client redirect → /observe/[slug]（旧版备份为 page.tsx.bak.M5）
status: done

## 验证

- ✅ pytest 全套 116 passed
- ✅ frontend tsc 0 错
- ✅ `/observe/builder` HTTP 200
- ✅ `/p/builder` HTTP 200（client redirect 到 /observe/builder）
- ✅ `/api/projects/{id}/lifecycle/run_once` → run_count + 1, status=running

## 已知遗留

- M5 仍是轮询模式（5s）；M7 接入 daemon 真实事件后会切到 SSE 长连接
- 暂时没做"暂停/恢复"按钮（pause/resume 状态机要等 M7 daemon 真在跑才有意义；M5 范围内 stop/start 已经够用）

## 状态: 可测试 ✅
---

## 任务背景

按计划 M5：原 /p/[slug] 改为只读观察页 + 轻量控制按钮（Run once / Pause / Resume / Clear logs）；
重定向 /p/[slug] → /observe/[slug]。

## 范围限定

M5 不实现「daemon 产生的实时事件 SSE 广播」（那个要等 M7 daemon 真的能跑后才有意义）；
现阶段：
- 5s 轮询 `/api/projects/{id}/runtime` 拿状态
- 列最近 N 条 message（走 /api/sessions/{id}/messages，取 project 的 orchestrator session）
- 5 个按钮：Run Once / Start / Stop / Restart / Clear Memory
- 顶部状态徽章 + 心跳/last_error 展示

后续 M7：把 daemon 跑出的事件流通过 broadcast hub 推 SSE 到本页。
