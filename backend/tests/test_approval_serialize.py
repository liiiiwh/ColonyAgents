"""S2 · 审批序列化（读时合并 #1 + thread 过滤 #3，ADR-024）。

serialize_approval(pa) 把审批行转成前端 ApprovalCardData：
- 始终带 thread_key（None→'main'），供前端按 thread 过滤（worker 线程不再串 main 审批）；
- decided 时带 resolution（option/decided_by/via），刷新后已决卡保持「已决定/禁用」，不再幽灵复活。
"""

from __future__ import annotations

import uuid

from app.models.approvals import PendingApproval
from app.services.pending_approval_service import serialize_approval


def _pa(**kw) -> PendingApproval:
    base = dict(
        mission_id=uuid.uuid4(), request_id="abc12345", title="t", message="m",
        options=["同意", "拒绝"], status="pending", thread_key="main",
    )
    base.update(kw)
    return PendingApproval(**base)


def test_pending_has_no_resolution():
    d = serialize_approval(_pa(status="pending"))
    assert d["request_id"] == "abc12345"
    assert d["thread_key"] == "main"
    assert d["status"] == "pending"
    assert "resolution" not in d


def test_decided_has_resolution():
    d = serialize_approval(_pa(status="decided", decided_option="同意", decided_by="admin"))
    assert d["status"] == "decided"
    assert d["resolution"]["option"] == "同意"
    assert d["resolution"]["decided_by"] == "admin"
    assert d["resolution"]["via"] == "inline"


def test_thread_key_defaults_main():
    d = serialize_approval(_pa(thread_key=None))
    assert d["thread_key"] == "main"


def test_worker_thread_key_preserved():
    d = serialize_approval(_pa(thread_key="worker:abc:def"))
    assert d["thread_key"] == "worker:abc:def"
