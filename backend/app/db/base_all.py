"""集中 import 所有 ORM 模型，供 Alembic autogenerate 使用。

后续新增模型时，必须在此文件中 import，否则 Alembic 无法检测。
"""

# ruff: noqa: F401

from app.db.base import Base
# V7.4 · AgentActivity 模型已删（ADR-007 ActivityTree 退役）
from app.models.agent import (
    Agent,
    AgentAuxModel,
    AgentMCPServer,
    AgentProtocolHistory,
    AgentProtocolProposal,
    AgentSkill,
)
from app.models.approvals import (
    PendingApproval,
    MissionApprovalChannel,
    WechatClawbotAccount,
)
from app.models.wechat_outbox import WechatOutbox
from app.models.builder_governance import BuilderWorkClaim, BuilderWorkLog
from app.models.knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.models.mission import (
    Mission,
    MissionAgentMemory,
    MissionEscalation,
    MissionRunState,
    MissionSchedule,
)
from app.models.provider import LLMModel, LLMProvider
from app.models.message import (  # noqa: F401
    Message,
    ThreadAgentMemory,
    ThreadCompressionState,
)
from app.models.shell_audit import ShellAuditLog
from app.models.skill import MCPServer, RemoteSkillInstall, Skill
from app.models.user import User
