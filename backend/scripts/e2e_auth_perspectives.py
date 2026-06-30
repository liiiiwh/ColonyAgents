"""多视角 E2E：授权逻辑（auto / force_human / 选项挑选）端到端验证。

真建一个临时 project + super + daemon session，构造真实 BuiltinToolContext，
直接驱动 request_approval 工具，按 4 个视角核对 DB 落库结果：
  视角1 auto=OFF        → 建 pending，等真人（人工授权）
  视角2 auto=ON         → 自动决策，挑"肯定/推进"项，不建 pending
  视角3 auto=ON+force   → force_human 无视 auto → 建 pending，真停下（兑现"直到X"）
  视角4 auto=ON 反序选项 → ['取消','继续执行'] 自动挑"继续执行"（修盲取[0]漏洞）
"""
import asyncio, sys, uuid
sys.path.insert(0, __file__.rsplit('/', 2)[0])

import app.db.base_all  # noqa
from sqlalchemy import text
from app.db.session import AsyncSessionLocal
from app.skills_builtin.context import BuiltinToolContext
from app.skills_builtin.supervisor_skills import request_approval_tool


async def _set_auto(pid, on):
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE projects SET auto_approve=:v WHERE id=:p"), {"v": on, "p": str(pid)})
        await db.commit()


async def _pending_count(pid):
    async with AsyncSessionLocal() as db:
        return (await db.execute(text("SELECT count(*) FROM pending_approvals WHERE project_id=:p AND status='pending'"), {"p": str(pid)})).scalar()


async def _last_auto_decision(sid):
    async with AsyncSessionLocal() as db:
        r = (await db.execute(text("SELECT meta->>'option' o FROM messages WHERE session_id=:s AND meta->>'type'='decision' AND meta->>'auto_approved'='true' ORDER BY created_at DESC LIMIT 1"), {"s": str(sid)})).first()
        return r.o if r else None


async def main():
    # 1) 搭一个临时 project + super + daemon session
    async with AsyncSessionLocal() as db:
        sup = (await db.execute(text("SELECT id FROM agents WHERE kind='super' LIMIT 1"))).scalar()
        uid = (await db.execute(text("SELECT id FROM users LIMIT 1"))).scalar()
        pid = uuid.uuid4(); slug = f"_t_auth_{str(pid)[:6]}"
        await db.execute(text("INSERT INTO projects (id,name,slug,status,supervisor_agent_id,created_by,auto_approve,created_at,updated_at) VALUES (:i,'auth-test',:s,'active',:sup,:u,false,now(),now())"),
                         {"i": str(pid), "s": slug, "sup": str(sup), "u": str(uid)})
        await db.commit()
    from app.skills_builtin.super_dispatch_skills import _ensure_super_session
    async with AsyncSessionLocal() as db:
        _sess, _branch = await _ensure_super_session(db, sup, pid)
        dsid, bid = _sess.id, _branch.id
        await db.commit()

    def make_ctx():
        return BuiltinToolContext(session_id=dsid, branch_id=bid, project_id=pid,
                                  agent_node_name="supervisor", db_factory=AsyncSessionLocal)
    tool = request_approval_tool(make_ctx())
    results = {}

    # 视角1：auto=OFF → 建 pending
    await _set_auto(pid, False)
    base = await _pending_count(pid)
    out1 = await tool.coroutine(title="发布前审批", message="要发这篇吗", options=["就这么干", "我要调整"])
    results["1_auto_off"] = {"pending_delta": await _pending_count(pid) - base, "auto_decided": "自动选择" in out1, "expect": "pending+1, not auto"}

    # 视角2：auto=ON → 自动决策（挑肯定项），不建 pending
    await _set_auto(pid, True)
    base = await _pending_count(pid)
    out2 = await tool.coroutine(title="发布前审批2", message="发吗", options=["就这么干", "我要调整", "我自己说想法"])
    results["2_auto_on"] = {"pending_delta": await _pending_count(pid) - base, "auto_opt": await _last_auto_decision(dsid), "auto_decided": "自动选择" in out2, "expect": "pending+0, auto_opt=就这么干"}

    # 视角3：auto=ON + force_human → 无视 auto，建 pending（真停）
    base = await _pending_count(pid)
    out3 = await tool.coroutine(title="条件达成：发够10篇", message="请示下一步", options=["继续运营", "我来调整", "先停"], force_human=True)
    results["3_force_human"] = {"pending_delta": await _pending_count(pid) - base, "auto_decided": "自动选择" in out3, "expect": "pending+1 (auto bypassed)"}

    # 视角4：auto=ON 反序选项 → 挑"继续执行"，不盲取"取消"
    base = await _pending_count(pid)
    out4 = await tool.coroutine(title="风险确认", message="发现风险，继续？", options=["取消", "继续执行"])
    results["4_reversed_opts"] = {"auto_opt": await _last_auto_decision(dsid), "expect": "auto_opt=继续执行 (非 取消)"}

    # 打印 + 判定
    print("=== 授权多视角 E2E ===")
    ok = True
    v1 = results["1_auto_off"]; p1 = v1["pending_delta"] == 1 and not v1["auto_decided"]
    v2 = results["2_auto_on"]; p2 = v2["pending_delta"] == 0 and v2["auto_opt"] == "就这么干" and v2["auto_decided"]
    v3 = results["3_force_human"]; p3 = v3["pending_delta"] == 1 and not v3["auto_decided"]
    v4 = results["4_reversed_opts"]; p4 = v4["auto_opt"] == "继续执行"
    for k, v in results.items():
        print(f"  {k}: {v}")
    print(f"\n视角1 auto=OFF 建pending等真人: {'✅' if p1 else '❌'}")
    print(f"视角2 auto=ON 自动挑肯定项不建pending: {'✅' if p2 else '❌'}")
    print(f"视角3 force_human 无视auto真停: {'✅' if p3 else '❌'}")
    print(f"视角4 反序选项挑'继续执行'不盲取'取消': {'✅' if p4 else '❌'}")
    print(f"\n总判定: {'✅ ALL PASS' if all([p1,p2,p3,p4]) else '❌ FAIL'}")

    # 清理临时 project
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM messages WHERE branch_id=:b"), {"b": str(bid)})
        await db.execute(text("DELETE FROM pending_approvals WHERE project_id=:p"), {"p": str(pid)})
        await db.execute(text("DELETE FROM session_branches WHERE session_id=:s"), {"s": str(dsid)})
        await db.execute(text("DELETE FROM sessions WHERE id=:s"), {"s": str(dsid)})
        await db.execute(text("DELETE FROM projects WHERE id=:p"), {"p": str(pid)})
        await db.commit()

asyncio.run(main())
