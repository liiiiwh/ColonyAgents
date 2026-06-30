"""FastAPI 应用入口。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

# 代码层修复 · 启动即开启 litellm.drop_params：各模型不支持的参数（reasoning_effort 等）
# 静默丢弃而非 UnsupportedParamsError 崩 worker。在 main 顶部设，保证早于任何 LLM 调用、
# 不依赖 resilient_llm 的惰性导入时机。
import litellm

litellm.drop_params = True

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    admin_clawhub,
    admin_system_settings,
    agent_import,
    agents,
    auth,
    clawbot_accounts,
    health,
    knowledge,
    mcp_servers,
    missions,
    missions_admin,
    observe,
    super_conversation,
    pending_approvals,
    providers,
    schedules,
    skills,
    storage,
    users,
)
from app.core.config import settings
from app.db.init_db import run_startup_seeds
from app.db.session import AsyncSessionLocal, async_engine

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# 第三方库日志降噪：litellm 的 cost-计算 debug（deepseek-v4-pro 不在它价目表里，每次调用刷一大段，
# 纯会计噪声、不影响功能）、SQLAlchemy 的 SQL echo、httpx/httpcore 传输层 debug 都太吵 → 一律压到 WARNING。
# 不动应用自身日志级别。
for _noisy in ("litellm", "LiteLLM", "sqlalchemy.engine", "sqlalchemy.engine.Engine",
               "sqlalchemy.pool", "httpcore", "httpx", "apscheduler"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
try:
    import litellm as _litellm
    _litellm.suppress_debug_info = True
    _litellm.set_verbose = False
except Exception:  # noqa: BLE001
    pass
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用启动 / 关闭钩子。"""
    logger.info("🚀 启动 %s (env=%s)", settings.APP_NAME, settings.APP_ENV)
    # ADR-023 · S3 启动期 fail-loud：坏凭据/不可达显式 error，不再让 write_artifact 的静默降级掩盖
    try:
        from app.services.storage_service import health_check as _s3_health
        _ok, _detail = await _s3_health()
        if _ok:
            logger.info("✅ 对象存储就绪（交付物/产物上传可用）")
        else:
            logger.error(
                "❌ 对象存储不可用：%s —— 交付物/产物上传会失败，请检查 "
                "S3_ENDPOINT_URL / S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY 是否与对象存储一致",
                _detail,
            )
    except Exception:
        logger.exception("S3 健康检查异常（不阻塞启动）")
    # 执行 DB 播种
    async with AsyncSessionLocal() as db:
        try:
            await run_startup_seeds(db)
        except Exception:
            logger.exception("启动时数据播种失败")
            # 不阻止应用启动（如 DB 未就绪，由健康检查反映）

    # 本地 http MCP 自动拉起（如 xhs-mcp：配了 startup_command 的 binary）—— 冷启动后
    # 没人 spawn 它，worker 调用会 connect refused。best-effort，不阻塞启动。
    try:
        from app.services import mcp_autostart

        async with AsyncSessionLocal() as db:
            await mcp_autostart.autostart_local_mcp_servers(db)
    except Exception:
        logger.exception("mcp_autostart 失败（本地 MCP 需手动启动或由 worker 自愈）")

    # M1: reconcile project daemon 状态（把上次未优雅退出的 running 标 error）
    try:
        from app.services import mission_daemon

        await mission_daemon.reconcile_on_boot()
        mission_daemon.start_heartbeat_sweeper()
    except Exception:
        logger.exception("mission_daemon.reconcile_on_boot 失败")

    # M2: 启动 APScheduler 并从 DB rehydrate schedule
    try:
        from app.services import scheduler_service

        await scheduler_service.start()
    except Exception:
        logger.exception("scheduler_service.start 失败")

    # M7+: 把 live_embedder 接入 knowledge_service —— 否则 KB 的 embedding 是 hash 噪声
    try:
        from app.services import live_embedder

        live_embedder.wire_to_knowledge_service()
    except Exception:
        logger.exception("live_embedder.wire_to_knowledge_service 失败（KB 将走 hash fallback）")

    # WeChat Clawbot 长轮询：每个 enabled 账号一条 asyncio task
    try:
        from app.services import wechat_poller

        await wechat_poller.start_pollers()
    except Exception:
        logger.exception("wechat_poller.start_pollers 失败（微信审批渠道不可用，仍可走 observe 页审）")

    # B4：周期性自检 heartbeat sweeper 是否健在；死了就重启
    import asyncio as _asyncio
    async def _watchdog_sweeper() -> None:
        from app.services import mission_daemon as _pd
        while True:
            try:
                await _asyncio.sleep(300)  # 5 分钟一次
                task = _pd._HEARTBEAT_SWEEPER_TASK
                if task is None or task.done():
                    logger.warning("[watchdog] heartbeat sweeper 已退出，自动重启")
                    _pd.start_heartbeat_sweeper()
            except _asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("[watchdog] 自检失败（继续）")

    watchdog_task = _asyncio.create_task(_watchdog_sweeper(), name="daemon-watchdog")
    app.state._daemon_watchdog_task = watchdog_task

    yield

    # 关闭 watchdog
    with suppress(Exception):
        watchdog_task.cancel()

    # M2: graceful shutdown scheduler
    try:
        from app.services import scheduler_service

        await scheduler_service.stop()
    except Exception:
        logger.exception("scheduler_service.stop 失败")

    # WeChat poller stop
    try:
        from app.services import wechat_poller

        await wechat_poller.stop_pollers()
    except Exception:
        logger.exception("wechat_poller.stop_pollers 失败")

    # M1: graceful shutdown — 停掉所有 running daemon
    try:
        from app.services import mission_daemon

        await mission_daemon.shutdown_all()
    except Exception:
        logger.exception("mission_daemon.shutdown_all 失败")

    logger.info("👋 关闭应用，释放 DB 连接池")
    await async_engine.dispose()


app = FastAPI(
    title="Colony",
    description="多智能体工作流管理平台 — 后端 API",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────
# v5 · 加 allow_origin_regex 兼容 Claude Preview / dev autoPort 随机端口
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 路由 ──────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(providers.router)
app.include_router(skills.router)
app.include_router(mcp_servers.router)
app.include_router(agents.router)
app.include_router(agent_import.router)
app.include_router(missions_admin.router)
app.include_router(missions.router)
app.include_router(schedules.router)
app.include_router(storage.router)
app.include_router(knowledge.router)
app.include_router(admin_clawhub.router)
app.include_router(admin_system_settings.router)
app.include_router(clawbot_accounts.router)
app.include_router(pending_approvals.router)
app.include_router(users.router)
app.include_router(observe.router)
app.include_router(super_conversation.router)
# V7.4 · /api/activities 已退役（ADR-007 ActivityTree 退役；intervene 走 pending_approvals）


# ── 全局异常处理 ──────────────────────────────────────────────
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "请求参数校验失败", "errors": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "服务器内部错误"},
    )

