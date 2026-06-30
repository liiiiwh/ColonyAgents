"""Builder domain · v6.

Builder 自动设计 SuperAgent / WorkerAgent 的 deepening：
- AgentSpec / SuperSpec / WorkerSpec — Pydantic 类型化的 spec
- Factory · apply_super_spec / apply_worker_spec — 一次事务化创建

读 CONTEXT.md > "⭐ Builder 自动化（v6 新核心）" 区。
"""
from app.domain.builder.agent_spec import (  # noqa: F401
    AgentSpec,
    SuperSpec,
    WorkerSpec,
)
from app.domain.builder.factory import (  # noqa: F401
    SUPER_REQUIRED_SKILLS,
    WORKER_DEFAULT_SKILLS,
    SuperRef,
    WorkerRef,
    apply_super_spec,
    apply_worker_spec,
)
