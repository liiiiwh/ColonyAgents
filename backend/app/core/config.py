"""应用配置：从环境变量 / .env 文件读取。"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """统一配置入口。所有字段通过环境变量或 `.env` 加载。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── 应用元信息 ──────────────────────────────────────────────
    APP_NAME: str = "colony"
    APP_ENV: str = Field(default="development", description="development / production")
    DEBUG: bool = False

    # ── 数据库 ─────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/colony",
        description="SQLAlchemy async DSN（必须使用 postgresql+asyncpg 前缀）",
    )
    DB_ECHO: bool = Field(
        default=False,
        description="是否打开 SQLAlchemy SQL echo（每条 SQL 刷日志）。默认关——太吵会盖过真日志；需逐句排查时临时设 true。",
    )
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 1800
    AUTO_INSTALL: bool = Field(
        default=False,
        description=(
            "ADR-015 · 启动时是否自动跑 platform-install（Builder Mission / 自检会话 / catalog / KB）。"
            "默认 false：fresh install 走后台一键初始化向导（is_install=0）。CI/dev/e2e 设 true 免手点。"
            "存量库（已有 Builder Mission / is_install=1）不受此开关影响，始终自动 install。"
        ),
    )

    # ── 安全 ───────────────────────────────────────────────────
    SECRET_KEY: str = Field(
        default="CHANGE_ME_IN_PRODUCTION_AT_LEAST_32_CHARS_LONG",
        description="JWT 签名密钥，生产环境必须替换",
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    ENCRYPTION_KEY: str = Field(
        default="",
        description="Fernet 加密密钥（base64 32 bytes）。用于加密 Provider API Key",
    )

    # ── CORS ───────────────────────────────────────────────────
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000",
        description="允许的 CORS Origin，多个用逗号分隔",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # ── 前端基址（ADR-008 P3 · 审批消息平台深链）────────────────
    FRONTEND_BASE_URL: str = Field(
        default="",
        description="前端站点根地址（如 https://colony.example.com）；空则回退 CORS 第一个 origin。用于审批消息里的平台深链。",
    )

    @property
    def frontend_base_url(self) -> str:
        base = (self.FRONTEND_BASE_URL or "").strip()
        if not base:
            origins = self.cors_origins_list
            base = origins[0] if origins else ""
        return base.rstrip("/")

    # ── 对象存储（S3 / MinIO） ─────────────────────────────────
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    # presigned URL 专用「浏览器可达」端点：docker 里后端用内网名 minio:9000 直连，但浏览器
    # 打不开该 host；presign 必须对浏览器实际访问的 host 签名（SigV4 host 进签名，不能事后改）。
    # 空 → 回退 S3_ENDPOINT_URL。典型：bundled MinIO 映射到宿主 → "http://localhost:9000"。
    S3_PUBLIC_ENDPOINT_URL: str = ""
    S3_ACCESS_KEY_ID: str = "minioadmin"
    S3_SECRET_ACCESS_KEY: str = "minioadmin"
    S3_BUCKET_NAME: str = "colony"
    S3_REGION: str = "us-east-1"
    S3_PRESIGNED_URL_EXPIRE: int = 900  # 15 分钟，用于 Admin 存储 API
    S3_ARTIFACT_URL_EXPIRE: int = 259200  # 3 天（工作台交付物 presigned URL）
    # 私有 S3 兼容服务（如爱奇艺 bj.s3.qiyi.storage）通常需要 path 风格而不是
    # virtual-hosted 风格（否则会把 bucket 名拼到 Host 前缀）
    S3_FORCE_PATH_STYLE: bool = True
    # 第三方 URL 镜像短路：判断给定 URL 是否已属于"我们自己的"S3/CDN 域名时使用，
    # 命中即不再二次镜像。空值表示禁用短路检测（任何外部 URL 都会被下载并上传）。
    # 典型设置：MinIO 自建 → "localhost:9000"；公有云 → "<bucket>.s3.<region>.amazonaws.com"
    S3_PUBLIC_URL_HOST: str = ""

    # ── ClawHub（M6 远程 Skill 仓库） ─────────────────────────
    CLAWHUB_TOKEN: str = ""  # https://clawhub.ai/ Bearer token；空 → 走匿名读
    CLAWHUB_BASE_URL: str = "https://clawhub.ai"
    CLAWHUB_INSTALL_DIR: str = "runtime/skills"  # 远程 skill 解压目录（被 .gitignore 排除）

    # ── 管理员初始账号（首次启动时创建） ───────────────────────
    INIT_ADMIN_USERNAME: str = "admin"
    INIT_ADMIN_EMAIL: str = "admin@colony.com"
    INIT_ADMIN_PASSWORD: str = "admin123"

    # ── Agent 默认主模型 ─────────────────────────────────────
    # seed 脚本 / Admin UI 新建 Agent 时的默认主模型 model_id。
    # 必须是 llm_models 表里已同步过的某条 model_id 字段值（不是 UUID）。
    # 建议支持 vision + function_calling，否则多模态与工具调用会失效。
    DEFAULT_AGENT_MODEL_ID: str = Field(
        default="",
        description=(
            "Agent 默认主模型。**推荐格式 `provider_name/model_id`**；兼容裸 `model_id`（唯一即可解析）。"
            "ADR-016：默认模型由用户在 onboarding/设置页 UI 显式选（写 system_settings），**config 不再写死**"
            "—— 留空让全新安装弹「选默认模型」引导，不静默塞某家模型（ADR-014 不做降级兼容）。"
            "无人值守部署可在 .env 显式覆盖 DEFAULT_AGENT_MODEL_ID / DEFAULT_SUPERVISOR_MODEL_ID 跳过引导。"
        ),
    )
    # Supervisor 单独指定（默认与 Worker 相同；可在 .env 覆盖为更强的推理模型）
    DEFAULT_SUPERVISOR_MODEL_ID: str = Field(
        default="",
        description=(
            "Supervisor 默认主模型，支持 `provider_name/model_id`。ADR-016：默认留空 → 由 UI 显式选；"
            "无人值守可在 .env 覆盖（服务不做模型可用性降级兼容，见 ADR-014）。"
        ),
    )

    # Knowledge Base 默认 embedding 模型（UUID 或留空让 live_embedder 自动找）
    DEFAULT_EMBEDDING_MODEL_ID: str = Field(
        default="",
        description=(
            "知识库默认 embedding 模型 UUID。留空时 live_embedder 自动选第一个 enabled "
            "的 embedding 类 LLMModel。建议显式指定，例如 `text-embedding-3-small` "
            "对应的 UUID。"
        ),
    )

    # E19：是否强制覆盖 admin 在 UI 上手改的 Builder 系统 Agent 的 soul/protocol
    # 默认 false → admin 改动**不**会被下次 seed 覆盖（仅在为空时填充）
    # 仅当确实需要 reset 所有 Builder Agent 协议时设 true
    SYSTEM_AGENTS_FORCE_SYNC: bool = Field(
        default=False,
        description=(
            "是否强制覆盖 admin 在 UI 上手改的 Builder 系统 Agent 的 soul_md / protocol_md。"
            "默认 false（保留 admin 改动）。需要重置时手动设 true 重启一次。"
        ),
    )

    # ── LLM 调用韧性（ResilientChatLiteLLM 消费）───────────────────
    # 每次 LLM 调用最多重试次数（不含初始 1 次）
    # 触发重试的条件：
    #   1) 首 token 超过 LLM_FIRST_TOKEN_TIMEOUT_S 秒未返回 → 取消流 + 重试
    #   2) 上游抛出可重试异常（502 / 503 / 504 / timeout / connection reset 等）
    # 一旦已向下游 yield 过至少一个 chunk，立即停止重试（避免重放）
    LLM_RETRY_MAX: int = Field(
        default=3,
        ge=0,
        le=10,
        description="LLM 调用自动重试次数（0 表示禁用重试）",
    )
    WORKER_INVOKE_TIMEOUT_SEC: float = Field(
        default=600.0,
        ge=60.0,
        le=3600.0,
        description=(
            "单个 Worker Agent ainvoke 超时（秒），供 supervisor_skills 消费。"
            "实战 Nebula + Claude 生成 5000 tok 的 Markdown 交付物一次约 90s；"
            "考虑一个 Worker 内可能有 3-4 轮 LLM 调用（read → think → write → finalize），"
            "加上 TTFT 重试兜底，600s 是稳定不浪费的默认值。调大仅在用户极慢链路需要。"
        ),
    )
    TURN_TIMEOUT_SEC: float = Field(
        default=1800.0,
        ge=60.0,
        le=7200.0,
        description=(
            "单轮 chat turn 总超时（秒），api/sessions.py::_turn_task_fn 消费。"
            "必须 > WORKER_INVOKE_TIMEOUT_SEC（建议 ≥ 2× worker timeout），因为 Supervisor"
            "一轮里可能串行调度多个 Worker（如'确认并继续'后顺序跑 6 项交付物中的一项失败重试）。"
        ),
    )
    # ── 上下文自动压缩 ─────────────────────────────────────────
    # 当**整个组装 context**（supervisor 系统提示 + memory_md + workspace 快照 + 未压缩对话）
    # 的估算 token 数 ≥ 该阈值时，compression_service.maybe_compress_context 会调用 LLM 摘要
    # 把早期消息压成 memory_md，仅保留最近 keep_recent 条原文。
    # 默认 300000 ≈ 30 万 token，覆盖 Claude / Gemini 1M 窗口 1/3 的安全边界。
    # 单个 Mission 仍可在 admin/projects/[id] 页面手工覆写本字段。
    DEFAULT_CONTEXT_COMPRESSION_THRESHOLD: int = Field(
        default=300_000,
        ge=1_000,
        le=1_000_000,
        description=(
            "新建 Mission 时 context_compression_threshold 的默认值（token 数，"
            "用 len(text) 作保守估计）。"
        ),
    )

    LLM_FIRST_TOKEN_TIMEOUT_S: float = Field(
        default=30.0,
        gt=0.0,
        le=300.0,
        description=(
            "LLM 首 token 预算（秒）。超过则取消上游流并触发一次重试。"
            "过小：把合理的长 prefill（如 Supervisor 4k+ 字符 + 20 工具 schema 的 prompt）"
            "误判为失败；过大：真正卡死时用户感知差。"
            "经验值 Nebula + Claude + 真实 Supervisor 规模：10-18s；30s 覆盖 p99。"
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回 Settings 单例（lru_cache 保证进程内只实例化一次）。"""
    return Settings()


settings = get_settings()
