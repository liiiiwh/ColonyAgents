# ADR-011 · 构建期 vs 运营期边界 + Builder 首跑中继（super 运营问题透传给用户）

**Status**: Accepted (2026-06-06)
**Builds on**: ADR-009（Builder 治理闭环）、ADR-010（能力自动就绪 / 人类残留卡）

## Context

端到端重跑暴露:Colony Builder 在**构建期**向用户征询了「账号定位(niche/风格/受众/禁忌)」。
这是**运营信息**,不影响怎么"搭"出 super 的结构,Builder 越权伸进了 super 的运营域。

用户拍板的正确模型:
- **构建期信息**(Builder 该问):capability 列表 / xhs-mcp 路径端口 / schedule 节奏 —— 决定 super 结构。
- **运营定位**(账号 niche 等):归 **super 运营期自己问**,存进自己记忆/goal_spec 并自演化
  (契合「Builder 最小化创建、super 自演化目标」的既定愿景)。

但有个衔接问题:Builder 建完 super 后,用户still待在 **Builder 的会话**里,并不在 super 的会话里。
若让 super 首跑时问定位,问题会"卡"在 super 自己的会话(没人看)。

→ 用户设计的「**Builder 首跑中继**」:Builder 建完**自动激活 super 第一个 session**;若该 session 里
super 抛出问题/表单,Builder 把它**透传进 Builder 自己的会话**问用户;用户回答后,Builder 以普通
消息形式**回灌给 super 对应的那个 session**。用户全程在一个会话里,super 运营自主性也保住。

## Decision

### R1 · 构建期/运营期边界(Builder Gather 收敛)
- Builder Gather/Design 协议**只问构建必需**(capability / MCP 路径端口 / schedule 节奏)。
  **不再问**账号定位 niche/风格/受众/禁忌等运营信息。

### R2 · Super 运营期自采集定位(soul 注入)
- Builder 建 super 时,在 super soul_md 注入:「**首次运行**时,先用 `request_structured_input`
  收集账号定位(niche/风格/受众/禁忌/参考号),存入记忆/goal_spec,再开展运营;之后基于量化
  数据自演化,不再重复问。」(Design Supervisor 协议补这段 soul 模板。)

### R3 · Builder 建完激活 super 首 session(post-build kickoff + 挂中继)
- Assemble 创建项目后,Builder 调 `activate_super_first_run(project_id)`:
  - 确保 super daemon session 存在;
  - 把该 super session 的 `relay_to_session_id` 指向**当前 Builder session**(中继目标);
  - 触发 super 首次 tick(kickoff)。

### R4 · 跨会话中继:super 问题 → Builder 会话(display relay)
- `sessions.relay_to_session_id`(uuid, nullable)新列。
- `request_structured_input` / `request_approval` 工具:若**当前 session 带 relay_to_session_id**,
  在原 super session 落库之外,**再把同一张卡(form_request / approval)投递到中继目标 session**
  (Builder 的),meta 带 `relay_origin_session_id` / `relay_origin_project_id` / `request_id`。
  → 直接在 Builder mission 页渲染(FormRequestCard / ApprovalCard 已支持)。

### R5 · 答案回灌:Builder 会话的回答 → super session(answer routing)
- **审批**:`pending_approval_service.decide` 已按 `row.session_id`(= super session)写回响应 +
  触发该 project tick。故审批只需 display relay(R4),答案天然回灌 super,无需改路由。✓
- **表单**:用户在 Builder 会话提交 `[form_response request_id=X]` 时,若 X 的 form_request 是
  被中继来的(meta 有 relay_origin_session_id),intake 把该 form_response **写入 origin super
  session**(而非 Builder session)+ 触发 super project tick。super 下次 tick 读到答案继续。
- 一次性:首跑 gather 完成后中继可清(`relay_to_session_id=NULL`),之后 super 正常独立运营。

## Rollout(TDD 分阶段)

- **R4a** session.relay_to_session_id 列 + 迁移(底座)
- **R4b** request_structured_input / request_approval:relay-aware display(纯判定 `relay_target(session)` 先红绿)
- **R5** form_response 路由:relayed 请求 → 写 origin session(纯函数 `route_form_response(meta, sessions)` 红绿)
- **R3** activate_super_first_run skill(挂中继 + kickoff)
- **R2/R1** super soul 首跑 gather 模板 + Builder Gather 协议收敛(去运营问题)
- **E2E**:清数据 → Builder 建 super(只问构建必需)→ 自动激活 super 首 session → super 问账号定位
  → 透传进 Builder 会话 → 用户答 → 回灌 super → super 存定位继续 → mcp_ensure_ready 弹二维码 → 扫码。

## Consequences

- ✅ 职责清晰:Builder 搭结构、super 管运营;改账号定位不用重建 super。
- ✅ 用户全程单会话(Builder)完成 建→首跑接生,不用切页。
- ✅ 复用既有 FormRequestCard / ApprovalCard / decide 路径,新增面小。
- ⚠️ 中继是「首跑」一次性;super 后续问题走它自己的会话(用户直接在 super mission 页交互)。
- ⚠️ relay display 双投递需保证幂等(同 request_id 不重复渲染——前端已按 id dedup)。
