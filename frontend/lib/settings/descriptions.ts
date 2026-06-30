// 系统设置每条 setting 的双语描述（前端 map，按 key；跟随语言切换，回退 DB description）。
// 干净措辞，去掉历史 V## 代号。
type DescMap = Record<string, string>;

const en: DescMap = {
  'compression.threshold_tokens': 'Platform default: trigger context compression once accumulated tokens reach this.',
  'compression.keep_recent_messages': 'Platform default: keep the N most recent messages uncompressed.',
  'compression.target_ratio': 'Platform default: compress older context to ~this fraction of the original.',
  'compression.cache_ttl_seconds': 'TTL for the in-process compression-config cache; an admin save invalidates it immediately.',
  'escalation.daily_quota_per_project': 'Max escalations a mission may raise per day.',
  'escalation.capability_quota_per_super': 'Max concurrent pending capability requests per super; excess is rejected.',
  'escalation.auto_dismiss_days': 'Auto-dismiss a pending escalation after N days and push a WeChat reminder.',
  'worker.max_clarification_rounds': 'Max clarification rounds a worker may ask within one invocation; beyond this it must request_approval.',
  'worker.tool_message_max_kb': 'Max size (KB) of a single super↔worker thread message; larger is offloaded to S3 and replaced with a URL.',
  'invoke_worker.timeout_seconds': 'Per-call worker run timeout; on timeout the invocation is recorded as status=timeout.',
  'invoke_worker.max_nesting_depth': 'Max nesting depth for worker→worker calls; exceeding it raises (workers calling invoke_worker is disabled by default).',
  'return_result.artifact_bytes_max_mb': 'Max inline artifact size (MB) per return_result; larger is forced through s3_upload + artifact_url.',
  'factory.worker_protocol_forbidden_words': 'super-only words forbidden in a worker.protocol_md; a match fails factory validation.',
  'worker_invocation_log.ttl_days': 'Retention (days) for worker invocation logs before housekeeping deletes them.',
  'worker_invocation_log.archive_summary_enabled': 'Before TTL deletion, archive a weekly aggregate to the worker_invocation_archive table.',
  'daemon.heartbeat_interval_seconds': 'Super daemon heartbeat frequency; the scheduler uses it to judge liveness / mark stale.',
  'dev.max_daemon_ticks': 'Token guard: when > 0, a super auto-stops after this many runs (prevents forgotten loops burning budget). 0 = no cap.',
  'is_install': 'Platform install flag: 0 = not installed (shows the setup wizard), 1 = installed.',
  'event_bus.backend': 'Event bus backend implementation (currently in-process).',
  'inline_approval_enabled': 'Whether request_approval pushes an inline card into the chat stream; false = WeChat only.',
  'live_events_enabled': 'Whether super SSE uses the real-time event bus; false falls back to 2s polling.',
  'memory_edit_enabled': "Whether admins may edit a super's long-term memory (off by default; only view + clear otherwise).",
  'super.auto_trigger_on_user_msg': 'Whether a user message immediately triggers the next tick (false = queue only, wait for the next schedule).',
  'super.cancel_burst_window_seconds': 'Burst window for counting cancels; exceeding the threshold writes a throttle log.',
  'super.max_pending_msgs_per_super': 'Max pending messages per super; excess rejects new user messages (anti-DoS).',
  'super.pending_msg_max_kb_per_msg': 'Max size of a single pending message; larger is offloaded to S3.',
  'super.user_chat_cancel_timeout_seconds': 'Max seconds to wait for a worker to cooperatively cancel after cancelling the current tick; then force-cancel.',
  'default_supervisor_model_id': 'Default model used by supervisor (super) agents (set during onboarding).',
  'default_agent_model_id': 'Default model used by worker agents (set during onboarding).',
};

const zh: DescMap = {
  'compression.threshold_tokens': '平台默认：累计 token 达到此值即触发上下文压缩。',
  'compression.keep_recent_messages': '平台默认：保留最近 N 条消息不压缩。',
  'compression.target_ratio': '平台默认：把旧上下文压到约原文的该比例。',
  'compression.cache_ttl_seconds': '进程内压缩配置缓存 TTL；admin 保存后立即 invalidate。',
  'escalation.daily_quota_per_project': '单个 mission 每天可发起的 escalation 上限。',
  'escalation.capability_quota_per_super': '同一 super 最多并发的 pending capability 请求数；超出拒绝。',
  'escalation.auto_dismiss_days': 'pending escalation 超过 N 天自动 dismiss 并推送微信提醒。',
  'worker.max_clarification_rounds': '单次 invoke_worker 内 worker 可反问的最大轮数；超出须 request_approval。',
  'worker.tool_message_max_kb': 'super↔worker thread 单条消息大小上限（KB）；超出转 S3 并替换为 URL。',
  'invoke_worker.timeout_seconds': 'invoke_worker 单次运行超时；超时记 status=timeout。',
  'invoke_worker.max_nesting_depth': 'worker→worker 调用嵌套深度上限；超出抛错（默认禁止 worker 调 invoke_worker）。',
  'return_result.artifact_bytes_max_mb': '单次 return_result 内联 artifact 大小上限（MB）；超出强制走 s3_upload + artifact_url。',
  'factory.worker_protocol_forbidden_words': 'worker.protocol_md 不可含的 super-only 词；命中即工厂校验失败。',
  'worker_invocation_log.ttl_days': 'worker 调用日志保留天数；超期由 housekeeping 删除。',
  'worker_invocation_log.archive_summary_enabled': 'TTL 删除前先把周聚合归档到 worker_invocation_archive 表。',
  'daemon.heartbeat_interval_seconds': 'super daemon 心跳频率；scheduler 据此判活 / 标 stale。',
  'dev.max_daemon_ticks': 'token guard：> 0 时 super 跑该次数后自动 stop（防忘关烧钱）。0 = 无上限。',
  'is_install': '平台安装标记：0 = 未安装（弹初始化向导），1 = 已安装。',
  'event_bus.backend': 'event_bus 后端实现（当前仅 in-process）。',
  'inline_approval_enabled': 'request_approval 是否在 chat 流推 inline 卡；false 仅走微信。',
  'live_events_enabled': 'super SSE 是否走实时 event_bus；false 退化到 2s 轮询。',
  'memory_edit_enabled': '是否允许 admin 编辑 super 长期记忆（默认关；否则仅查看 + 清空）。',
  'super.auto_trigger_on_user_msg': '用户发消息后是否立即触发下一次 tick（false = 仅入队列等下次 schedule）。',
  'super.cancel_burst_window_seconds': 'burst 窗口内 cancel 计数；超过阈值写 throttle log。',
  'super.max_pending_msgs_per_super': '单 super pending 消息上限；超出拒绝用户新消息（防 DoS）。',
  'super.pending_msg_max_kb_per_msg': '单条 pending 消息大小上限；超出转 S3。',
  'super.user_chat_cancel_timeout_seconds': 'cancel 当前 tick 后等待 worker 协作取消的最大秒数；超时强制 cancel。',
  'default_supervisor_model_id': 'supervisor（super）agent 使用的默认模型（onboarding 时设定）。',
  'default_agent_model_id': 'worker agent 使用的默认模型（onboarding 时设定）。',
};

export function settingDescription(key: string, lang: string): string | undefined {
  const map = lang?.startsWith('zh') ? zh : en;
  return map[key];
}
