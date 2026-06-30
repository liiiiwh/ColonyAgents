# ADR-015 · Worker 自检自迭代闭环 + 平台系统对象不可删除 + 安装向导

**Status**: Accepted (2026-06-15)
**Builds on**: ADR-009（Builder 治理 · 跨 super 兼容硬阻断 + report_worker_issue）、孤立的 `app/domain/optimization/decide.py`（自优化决策机,此前零调用方）

## Context

平台已有大量可观测 + 自优化的**零件**,但**未接线成闭环**:

1. **自优化决策机孤立**:`decide.py`(`detect_regression` / `decide_optimization_action` / `run_optimization_cycle`)有纯函数 + 测试,但**全仓零运行时调用方**——脑子造好了,没人扣扳机。
2. **两条 worker 变更 seam 兼容强度不对称**:
   - **契约层**(`capability_contract` 经 `agent_update`)→ 已强制 `analyze_worker_change_impact` 跨消费者**硬阻断**(在用的 action 删/改即 raise)。
   - **行为层**(`protocol_md` 经 L2 `self_tune`)→ `_quality_gate_pass_rate` **只看触发迭代的单个 project**,而 worker 是**全局共享单行**。项目 A 用 A 自己的指标迭代 worker,项目 B(不同 super/action 组合)拿到改后的 worker **从未被校验**。
3. **worker 自动健康治理只有被动路径**:`report_worker_issue`(super 运行中发现才上报),无**主动持续**扫描。
4. **平台自举对象可被误删**:Builder Supervisor / builtin worker / Builder Project 无保护,删了平台瘫痪。
5. **初始化不可控**:`run_startup_seeds` 每次启动自动幂等灌全套,用户无「一键初始化」掌控感,也无 SQL/一键脚本串联。

## Decision

### D1 · 自检自迭代闭环(WorkerHealthSession)
Builder Project 下建**单例不可删除** `scope='system'` 会话。scheduler 加 `sys-worker-health`(默认 6h)。tick **两段式**:
1. **确定性体检(纯代码)**:读 `worker_invocation_log` 算每 worker 成功率/退化,接上线孤立的 `decide.py:detect_regression` 筛候选。**无候选不唤起 LLM**(省 token)。
2. **LLM 决策**:有候选才把体检报告注入会话,Builder Super LLM 诊断 + 起草 `protocol_md` 修订,走 L2 四件套(propose/apply/evaluate/revert)。

### D2 · 分级修复授权(TieredFixAuthority)— 最大化自动化 + 结构化下限
- **可逆**(protocol_md 措辞 / retry / timeout / 澄清策略):auto-apply,**过跨调用方行为门 + 自动 revert**。
- **不可逆**(删/改 action 语义、加 tool、动 shell-safety / 高危域):走 L3 升级**人工**(对齐 auto_approve + force_human)。

### D3 · 跨调用方兼容门(让"迭代后完美兼容所有调用方"成立)
- **接口层**:复用既有 `analyze_worker_change_impact`——自动迭代若动 `capability_contract`,与 Builder 路径同样**硬阻断**(additive-only 天然成立)。
- **行为层**:把 L2 `_quality_gate_pass_rate` 从单项目升级为**全调用方**——从 `worker_invocation_log` 取该 worker 全部 `(super_agent_id, action)` 分布,任一调用方**明显退化**→自动 revert。
- **黄金回放**:每 (调用方,action) 采样少量历史成功 (params→好输出) 当 golden,迭代后回放,任一破→阻断 apply。
- **门要松**(防能力退化):只拦**明显退化**与**硬破坏**,不限制内部行为优化;golden 集小而稳。

### D4 · 平台系统对象不可删除(SystemObject)
新增 `is_system` 布尔列(agents + projects),`sessions` 复用 `scope='system'`。保护集 = Builder Project + Builder Supervisor + 三 builtin worker + WorkerHealthSession。delete 入口(agent / session / project)命中 → **409 拒删 + 清晰文案**;前端隐删除钮。迁移:已有 slug='builder' 项目 → 回填 is_system=True。
**附带**:后台补 worker 删除功能,删除前查 `project_nodes` 引用(FK 已 RESTRICT)→ 被在用则优雅 409 列出占用方。

### D5 · 安装向导(is_install + InstallWizard)
`run_startup_seeds` 拆两层:
- **boot-critical**(永远自动):admin user + builtin skills(login + 绑定前置)。
- **platform-install**(向导触发 or `AUTO_INSTALL=true` 逃生舱):Builder Project + WorkerHealthSession + worker catalog + KB。
`is_install` 存 system_settings(默认 0;迁移时已有 Builder → 置 1)。后台首启 `is_install=0` → 引导条「一键注入初始化数据」→ `POST /api/admin/install`(幂等)→ 置 1。一键脚本 `scripts/install.sh`:infra → `alembic upgrade head` → 起 app(自动 seed admin)→ 提示打开后台初始化;`AUTO_INSTALL=true` 跳手点(CI/dev/e2e)。

## Consequences

- ✅ 自优化从"零件"变"闭环":主动 + 持续 + LLM 决策,补 `report_worker_issue` 被动路径的盲区。
- ✅ 共享 worker 迭代**对所有调用方**校验,根治"一边好一边坏"的行为层缺口;接口层复用既有硬门。
- ✅ 平台自举对象不可误删;worker 删除有在用守卫。
- ✅ 用户掌控初始化(向导),CI/dev 有逃生舱不被卡。
- ⚠️ 行为门是**统计性**的(基于历史调用分布 + golden 采样),非形式化证明——罕用 action 可能采样不到;靠"门松 + 自动 revert + 不可逆走人工"控制残余风险。
- ⚠️ `decide.py` 接线后,体检阈值(退化判定)需随真实流量校准,初期偏保守(宁可漏报不误迭代)。
- ⚠️ platform-install 收向导后,任何**新增**自举数据必须进 platform-install 路径并保持幂等,否则向导/逃生舱漏灌。
