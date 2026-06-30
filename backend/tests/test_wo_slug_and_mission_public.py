"""回归：work-order mission slug 不得含下划线，且 MissionPublic 读模型不因历史脏 slug 而 500。

真 bug（Chrome e2e 抓到）：`_wo_slug_prefix("health_probe")` 因正则把 `_` 放进允许集，
产出 `wo-health_probe`，拼成 mission slug `wo-health_probe-xxxx`（带下划线）。
`/api/missions/all` 用 `MissionPublic.model_validate` 校验该 slug，pattern `^[a-z0-9][a-z0-9-]*$`
不允许下划线 → 单行炸整个列表 → 后台 Agents 页所有 super 都「暂无运营实例」、进不去 mission。

两条防线：
1) slug 生成不再产生下划线（根因）。
2) 读模型 MissionPublic 不再对已持久化的 slug 做字符集校验（读回不该因一行脏数据全挂）。
"""
from __future__ import annotations

import re
import uuid

from app.schemas.mission import MissionPublic
from app.services.worker_optimization_service import _wo_slug_prefix

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def test_wo_slug_prefix_has_no_underscore():
    """capability 里的下划线必须被规整成连字符，prefix 整体匹配 url-safe slug 规则。"""
    prefix = _wo_slug_prefix("health_probe")
    assert prefix == "wo-health-probe"
    assert _SLUG_RE.match(prefix), f"{prefix!r} 不是合法 slug"
    # 其它常见带下划线 capability 也一并守住
    assert _wo_slug_prefix("img_gen_probe") == "wo-img-gen-probe"
    assert _SLUG_RE.match(_wo_slug_prefix("img_gen_probe"))


def test_mission_public_reads_legacy_underscore_slug():
    """读模型对历史脏 slug 必须容忍（不再 500），保证 /api/missions/all 整表可读。"""
    payload = {
        "id": uuid.uuid4(),
        "name": "Worker 优化 · health_probe",
        "description": "",
        "slug": "wo-health_probe-a321b839",  # 历史脏数据，含下划线
        "supervisor_agent_id": uuid.uuid4(),
        "auto_approve": False,
        "context_compression_threshold": 300_000,
        "status": "archived",
        "runtime_status": "stopped",
        "lifecycle_status": "stopped",
        "is_system": False,
        "created_by": uuid.uuid4(),
        "created_at": "2026-06-25T00:00:00+00:00",
        "updated_at": "2026-06-25T00:00:00+00:00",
    }
    m = MissionPublic.model_validate(payload)
    assert m.slug == "wo-health_probe-a321b839"
