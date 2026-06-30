# ADR-008 · 生产就绪 · 人机协同闭环 + WeChat Router + Builder 硬校验

**Status**: Accepted (2026-06-03)
**Builds on**: ADR-007 (v7 统一流式)

## Context

v7 验证了 daemon 流式 + idle-trigger（真实 LLM e2e 通）。但审计「用户交互页面是否完善 / 人不在时自动运行 + 主动审批 / Builder 能否造合规 agent」发现 5 个缺口：

1. **UI flood（V7.4 regression）**：删 ChatTickCard 后，daemon 流式产出的 agent_log 追踪消息在 mission 页**平铺刷屏**（空灰盒子 ×20/tick）
2. **审批回复不即时（v7 缺口）**：daemon 模式下非 affirmative 审批回复（「调整方案」）不触发 tick，super 等下次 cron 才处理
3. **审批无平台入口**：WeChat 审批消息无 URL，用户只能在微信回纯文本，不能进平台 UI 审核/提意见
4. **WeChat 多 super 路由缺失**：一个微信账号服务 N 个 super（ProjectApprovalChannel 多对一），但用户发自由消息时无法判断发给哪个 super 的哪个 session（当前只按 request_id 匹配审批）
5. **Builder 造 agent 校验软**：capability_contract 内部结构不校、缺 skill 静默跳过、backward_compat 非强制 → 可能静默造出畸形/缺技能 agent

## Decision

### D1 · MessageTickCard（消息驱动折叠）
重建 tick 折叠卡，但**消息驱动**（不是 V7.4 删掉的 agent_activities 驱动）：mission 页把同 `turn_id` 的 agent_log（tool/thinking）+ assistant 回复聚合成一张可展开卡，默认折叠显示「super 跑了一轮·N 步·耗时」，展开看每步（复用 R4-3 的 `lib/chat/timeline.ts:toTimeline` 从 meta.raw 重建 tool 卡）。

### D2 · 审批回复统一触发 tick
`pending_approval_service.decide()` 后，daemon 模式不再只在 affirmative 时 dispatch_publisher。改为：写 [approval_response] 消息 → 走 v7 同一条 idle-trigger/auto-drain（super idle 立即起 tick，忙则排队完即抽）。affirmative/非 affirmative 一视同仁，super 自己读 [approval_response] 决定怎么继续。

### D3 · 审批带平台深链
WeChat 审批消息追加 `{settings.FRONTEND_BASE_URL}/mission/{slug}`（带 session 上下文）。用户点击进平台 UI，在 ApprovalCard 上审核/提意见。微信回纯文本仍兼容（两条路并存）。

### D4 · WeChat Router（轻量路由服务 + LLM 歧义消解）
**不是自主 super**（无 tick/无调度）。新增 `app/services/wechat_router.py`：
1. 入站微信消息（user X @ account A）
2. 先试现有审批匹配（request_id/option）→ 命中走审批路径
3. 否则查 user X 在 account A 下可访问的候选 super（ProjectApprovalChannel）：
   - 0 个 → 回「你还没有可对话的 super」
   - 1 个 → 直接路由
   - N 个 → 先 LLM 语义匹配（消息 vs super 描述）；不确定 → 发编号菜单「发给哪个？1.小红书super 2.colony推广」→ 用户回数字 → 路由
4. 路由 = 注入 user_chat 消息到选定 super session → v7 idle-trigger
5. **缓存本次会话目标**（account.context_tokens[wechat_user] = last_super_session）→ 连续消息粘同 session，直到用户显式切换

### D5 · Builder 工厂硬门 fail-fast
`apply_super_spec` / `apply_worker_spec`（factory.py）加强制校验：
- **capability_contract 结构**：advertises 每项必有 action + side_effects + requires_approval（缺字段抛 ValueError）
- **skill 存在性**：请求的 skill 不存在 → **抛错不静默跳过**，返回 missing 列表让 Builder 先 install
- **backward_compat**：升级现有 capability 时**自动**跑 validate_backward_compat（不再 opt-in）

## Rollout（TDD 分阶段）

- **P1 · MessageTickCard**（前端）：lib/chat/timeline 复用 + 折叠卡 + 按 turn_id 分组；vitest
- **P2 · 审批→tick**（后端）：decide() 接 idle-trigger；纯函数测路由决策
- **P3 · 审批深链**（后端）：approval message 加 URL；测含链接
- **P4 · WeChat Router**（后端）：wechat_router 服务 + 候选查询 + LLM 消歧 + 菜单 + session 缓存；纯函数测候选筛选/消歧/菜单解析
- **P5 · Builder 硬门**（后端）：factory 校验 + skill 存在性 fail；测畸形 contract/缺 skill 报错

## Consequences

**+**：人机协同闭环真正完整（人不在 → 微信审批带链接 → 点进平台或微信回 → 即时触发 tick）；多 super 微信路由；Builder 不再静默造坏 agent；UI 不刷屏又能看细节。

**−**：WeChat Router 是新服务面；Builder 硬门可能让一些"凑合能跑"的旧 spec 报错（但这正是目的）。

## 命名（加入 CONTEXT.md）
- **WeChat Router**：微信入站消息 → super session 的路由服务（轻量 + LLM 消歧，非 super）
- **MessageTickCard**：消息驱动的 tick 折叠卡（替代 V7.4 删掉的 agent_activities 驱动 ChatTickCard）
