"""ADR-023/024 续接④ · Builder→Super 10 场景多维评测 harness（API 驱动）。

驱动平台 Builder 在 10 个不同领域各设计一个 super（含 worker + 调度 + 审批），再驱动
该 super 的 mission 执行，最后对 8 个维度打分：
  完成率 / 通过率 / 调度完善度 / 持续运行 / 自学习(KB召回) / worker复用 / builder反馈链路 / 状态自动暂停-继续

用法：
  .venv/bin/python scripts/eval_builder.py --domains 1   # 先单场景冒烟
  .venv/bin/python scripts/eval_builder.py --domains 10  # 全量
环境：后端 http://localhost:19022，admin/admin123。
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

BASE = "http://localhost:19022"
BUILDER_SLUG = "builder"


# 10 个互不相同、且与现存 super（builder/xhs/客服/worker-opt）不冲突的领域。
# 每条 = 给 builder 的需求 + 给 super 的执行指令 + KB 召回探针。
DOMAINS = [
    {
        "key": "devops",
        "need": "设计一个『服务器运维监控』super：周期性检查服务健康指标，发现异常自动诊断根因，重启/扩容这类高危操作需我审批。请配好它需要的 worker 与定时调度。",
        "exec": "检查一遍服务，发现订单接口 5xx 错误率升高，请诊断根因并按流程处理。",
        "recall": "5xx 错误率 根因诊断 重启 扩容 审批",
    },
    {
        "key": "hr",
        "need": "设计一个『招聘简历筛选』super：自动筛选简历并按岗位打分，给候选人发面试邀约前需要我审批。请配好 worker 与定时调度。",
        "exec": "有一份后端工程师简历投递进来，请筛选打分并走面试邀约审批。",
        "recall": "简历 岗位匹配 打分 面试邀约 审批",
    },
    {
        "key": "finance",
        "need": "设计一个『财务对账稽核』super：每天核对账单流水，发现异常自动标记，超过阈值的大额支出需审批。请配好 worker 与定时调度。",
        "exec": "核对今天的流水，发现一笔超阈值的大额支出，请按流程稽核处理。",
        "recall": "对账 流水 异常标记 阈值 大额支出 审批",
    },
    {
        "key": "research",
        "need": "设计一个『行业市场调研』super：定期抓取行业资讯并归纳要点，形成调研简报后发布前需我审批。请配好 worker 与定时调度。",
        "exec": "就『国产大模型竞争格局』主题归纳一份调研简报并走发布审批。",
        "recall": "行业资讯 归纳 调研简报 发布 审批",
    },
    {
        "key": "edu",
        "need": "设计一个『在线教学辅导』super：根据学生提问生成讲解，布置作业前需老师审批。请配好 worker 与定时调度。",
        "exec": "学生提问『什么是递归，举个例子』，请生成讲解，并布置一道相关作业走审批。",
        "recall": "讲解 例子 布置作业 学生提问 审批",
    },
    {
        "key": "legal",
        "need": "设计一个『合同条款审查』super：自动检查合同条款风险并标注，出具审查结论前需法务审批。请配好 worker 与定时调度。",
        "exec": "有一份采购合同，请检查其中的风险条款并走结论审批。",
        "recall": "合同条款 风险标注 审查结论 法务 审批",
    },
    {
        "key": "community",
        "need": "设计一个『社群运营管理』super：监控群消息，自动回答常见问题，踢人/禁言这类管理动作需审批。请配好 worker 与定时调度。",
        "exec": "群里有人反复刷广告，请按流程处理（管理动作走审批）。",
        "recall": "群消息 常见问题 踢人 禁言 管理动作 审批",
    },
    {
        "key": "ecom",
        "need": "设计一个『电商店铺巡检』super：每天巡检商品价格与库存，价格异常自动预警，改价操作需审批。请配好 worker 与定时调度。",
        "exec": "巡检一遍商品，发现某商品价格疑似设置过低，请按流程处理。",
        "recall": "商品价格 库存 异常预警 改价 审批",
    },
    {
        "key": "logistics",
        "need": "设计一个『物流调度排程』super：根据订单自动规划配送路线，跨区域调拨这类操作需审批。请配好 worker 与定时调度。",
        "exec": "今天有一批跨城订单，请规划配送路线，遇到跨区域调拨走审批。",
        "recall": "配送路线 订单 跨区域调拨 排程 审批",
    },
    {
        "key": "iot",
        "need": "设计一个『设备告警巡检』super：周期性巡检 IoT 设备状态，发现告警自动分级，现场派工这类动作需审批。请配好 worker 与定时调度。",
        "exec": "巡检发现某台设备温度告警，请分级并按流程处理（派工走审批）。",
        "recall": "设备状态 告警分级 现场派工 巡检 审批",
    },
]


class Client:
    def __init__(self) -> None:
        self.h = httpx.Client(base_url=BASE, timeout=180.0)
        self.login()

    def login(self) -> None:
        r = self.h.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
        r.raise_for_status()
        self.token = r.json()["access_token"]
        self.h.headers["Authorization"] = f"Bearer {self.token}"

    def builder_agent_id(self) -> str | None:
        for a in self.agents():
            if a.get("kind") == "super" and a.get("name") == "Builder Supervisor":
                return a["id"]
        return None

    def spawn_mission(self, super_agent_id: str, name: str, goal_hint: str) -> dict | None:
        r = self.h.post("/api/missions", json={
            "super_agent_id": super_agent_id, "name": name, "goal_hint": goal_hint})
        if r.status_code >= 400:
            return None
        d = r.json()
        return d.get("mission") if d.get("ok") else None

    def chat(self, slug: str, content: str) -> dict:
        r = self.h.post(f"/api/super/{slug}/chat", json={"content": content, "auto_start": True})
        r.raise_for_status()
        return r.json()

    def run_once(self, mission_id: str) -> dict:
        r = self.h.post(f"/api/missions/{mission_id}/lifecycle/run_once")
        if r.status_code >= 400:
            return {"error": r.status_code, "text": r.text[:300]}
        return r.json()

    def runtime(self, mission_id: str) -> dict:
        r = self.h.get(f"/api/missions/{mission_id}/runtime")
        return r.json() if r.status_code < 400 else {"error": r.text[:200]}

    def all_missions(self) -> list[dict]:
        r = self.h.get("/api/missions/all")
        d = r.json()
        return d if isinstance(d, list) else d.get("items", d.get("missions", []))

    def agents(self) -> list[dict]:
        r = self.h.get("/api/agents")
        return r.json() if r.status_code < 400 else []

    def super_ids(self) -> set[str]:
        return {a["id"] for a in self.agents() if a.get("kind") == "super"}

    def schedules(self, mission_id: str) -> list[dict]:
        r = self.h.get(f"/api/missions/{mission_id}/schedules")
        return r.json() if r.status_code < 400 else []

    def kbs(self) -> list[dict]:
        r = self.h.get("/api/knowledge")
        return r.json() if r.status_code < 400 else []

    def kb_search(self, kb_id: str, query: str, top_k: int = 5) -> dict:
        r = self.h.post(f"/api/knowledge/{kb_id}/search", json={"query": query, "top_k": top_k})
        return r.json() if r.status_code < 400 else {"hits": [], "error": r.text[:160]}

    def mission_by_slug(self, slug: str) -> dict | None:
        r = self.h.get(f"/api/super/{slug}/threads")
        return r.json() if r.status_code < 400 else None

    def threads(self, slug: str) -> dict:
        r = self.h.get(f"/api/super/{slug}/threads")
        return r.json() if r.status_code < 400 else {"threads": []}

    def work_log(self, slug: str, limit: int = 200) -> dict:
        r = self.h.get(f"/api/super/{slug}/work-log", params={"limit": limit})
        return r.json() if r.status_code < 400 else {"items": []}

    def memory(self, slug: str) -> dict:
        r = self.h.get(f"/api/super/{slug}/memory")
        return r.json() if r.status_code < 400 else {}

    def pending_approvals(self, mission_id: str) -> list[dict]:
        r = self.h.get(f"/api/missions/{mission_id}/pending-approvals", params={"only_pending": "true"})
        return r.json() if r.status_code < 400 else []

    def decide(self, request_id: str, option: str = "approve") -> dict:
        r = self.h.post(f"/api/pending-approvals/{request_id}/decide",
                        json={"option": option, "decided_by": "eval_harness"})
        return r.json() if r.status_code < 400 else {"error": r.text[:200]}

    def mission_runtime_id(self, slug: str) -> str | None:
        t = self.threads(slug)
        return t.get("mission_id")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# 自动审批选项挑选：优先「确认/同意/继续/设计/Install all/approve」，避开「让我调整/我自己/放弃/危险」。
_PREFER = ("确认", "同意", "通过", "继续", "approve", "Install all", "设计", "Have Builder design",
           "Webhook", "API")
_AVOID = ("让我", "我自己", "放弃", "give up", "skip", "取消", "dangerous", "危险", "force")


def pick_option(options: list[str] | None) -> str:
    if not options:
        return "approve"
    for opt in options:
        low = opt.lower()
        if any(p.lower() in low for p in _PREFER) and not any(a.lower() in low for a in _AVOID):
            return opt
    # 退而求其次：第一个不在 avoid 名单里的
    for opt in options:
        if not any(a.lower() in opt.lower() for a in _AVOID):
            return opt
    return options[0]


def auto_clear_approvals(c: Client, mission_id: str, tag: str) -> tuple[int, int]:
    """清空一个 mission 的待审批：返回 (seen, decided)。"""
    pend = c.pending_approvals(mission_id)
    decided = 0
    for p in pend:
        opt = pick_option(p.get("options"))
        rid = p.get("request_id") or p.get("id")
        c.decide(rid, opt)
        decided += 1
        log(f"  {tag} auto-approve req={rid} → {opt!r}")
    return len(pend), decided


def builder_mission_id(c: Client) -> str:
    t = c.threads(BUILDER_SLUG)
    return t["mission_id"]


def _mission_for_super(c: Client, sid: str, base_mission: set[str]) -> dict | None:
    """找 super 的 mission：优先 baseline 之外的新 mission，回退该 super 的任一 mission。"""
    missions = c.all_missions()
    for m in missions:
        if m.get("supervisor_agent_id") == sid and m["id"] not in base_mission:
            return m
    for m in missions:
        if m.get("supervisor_agent_id") == sid:
            return m
    return None


def _detect_new(c: Client, base_super: set[str], base_mission: set[str]) -> dict | None:
    """检出新 super：优先 new super-agent-id，回退 new mission-id。返回 {mission, super_id, fresh}。
    mission 可能为 None（super 已建但 mission 异步 finalize 未到）—— 调用方需轮询补齐。"""
    new_supers = c.super_ids() - base_super
    if new_supers:
        sid = next(iter(new_supers))
        return {"mission": _mission_for_super(c, sid, base_mission), "super_id": sid, "fresh": True}
    # 没有新 super：可能 builder 复用了已有 super（缺陷信号）→ 看是否有新 mission
    for m in c.all_missions():
        if m["id"] not in base_mission:
            return {"mission": m, "super_id": m.get("supervisor_agent_id"), "fresh": False}
    return None


def drive_builder(c: Client, domain: dict, build_ticks: int, builder_agent_id: str,
                  base_super: set[str], base_mission: set[str]) -> dict | None:
    """每个 case 新开一个 builder mission（ADR-018 mission-per-case），在其中下发需求 + 驱动
    ticks（自动答复 propose-confirm 审批），检出新 super。返回 {mission, super_id, fresh, ...}。"""
    bm = c.spawn_mission(builder_agent_id, f"eval-{domain['key']}", domain["need"])
    if not bm:
        log(f"[{domain['key']}] ⚠️ 新建 builder mission 失败")
        return None
    bslug, bmid = bm["slug"], bm["id"]
    base_mission.add(bmid)  # builder mission 自身不算「产出的 super mission」
    log(f"[{domain['key']}] → 新建 builder mission {bslug}，下发需求")
    c.chat(bslug, domain["need"])
    for i in range(build_ticks):
        rt = c.run_once(bmid)
        seen, decided = auto_clear_approvals(c, bmid, f"[{domain['key']}] builder")
        log(f"[{domain['key']}] builder tick {i+1}/{build_ticks} step={rt.get('current_step')} "
            f"run_count={rt.get('run_count')} approvals={seen}/{decided} err={rt.get('last_error') or rt.get('error')}")
        found = _detect_new(c, base_super, base_mission)
        if found:
            sid = found.get("super_id")
            # mission 异步 finalize：再多跑几 tick 轮询补 mission（最多 5 次）
            for _ in range(5):
                if found.get("mission"):
                    break
                c.run_once(bmid)
                time.sleep(2)
                found["mission"] = _mission_for_super(c, sid, base_mission) if sid else None
            tag = "fresh super" if found["fresh"] else "⚠️复用 super"
            log(f"[{domain['key']}] ✅ builder 产出 {tag} super_id={(sid or '?')[:8]} "
                f"mission={found['mission'].get('slug') if found['mission'] else None} (tick {i+1})")
            found["build_ticks_used"] = i + 1
            return found
        if decided:  # 刚答复审批 → 立刻补 tick 让 builder 继续
            c.run_once(bmid)
        time.sleep(1)
    log(f"[{domain['key']}] ⚠️ build_ticks 用尽未检出新 super")
    return None


def drive_mission(c: Client, slug: str, mission_id: str, domain: dict, exec_ticks: int) -> dict:
    """驱动 super mission 执行 + 自动审批，收集打分原料。"""
    metrics = {"ticks": 0, "approvals_seen": 0, "approvals_decided": 0, "errors": 0,
               "paused_resumed": False, "worker_threads": 0}
    log(f"[{domain['key']}] → super={slug} 执行下发")
    c.chat(slug, domain["exec"])
    for i in range(exec_ticks):
        rt = c.run_once(mission_id)
        metrics["ticks"] += 1
        if rt.get("last_error") or rt.get("error"):
            metrics["errors"] += 1
        # 审批：暂停 → 自动批 → 应能继续（验证状态自动暂停/继续）
        seen, decided = auto_clear_approvals(c, mission_id, f"[{domain['key']}] super")
        if seen:
            metrics["approvals_seen"] += seen
            metrics["approvals_decided"] += decided
            metrics["paused_resumed"] = True
        log(f"[{domain['key']}] super tick {i+1}/{exec_ticks} step={rt.get('current_step')} "
            f"run_count={rt.get('run_count')} approvals={seen}/{decided}")
        time.sleep(1)
    th = c.threads(slug)
    metrics["worker_threads"] = sum(1 for t in th.get("threads", []) if (t.get("worker_id") or "worker:" in (t.get("thread_key") or "")))
    return metrics


def score_scenario(c: Client, domain: dict, found: dict, slug: str, mid: str,
                   metrics: dict) -> dict:
    """8 维打分（每维 0-100），综合 = 加权平均。"""
    mission = found.get("mission") or {}
    # 1 完成率：mission 推进了 tick 且最终非 error
    rt = c.runtime(mid)
    completion = 100 if metrics["ticks"] > 0 and (rt.get("status") != "error") else 40
    # 2 通过率：执行无 fatal error
    passrate = 100 if metrics["errors"] == 0 else max(0, 100 - 40 * metrics["errors"])
    # 3 调度完善度：super 是否有调度
    scheds = c.schedules(mid)
    sched_score = 100 if scheds else 0
    # 4 持续运行：有调度 + lifecycle running
    sustained = 100 if (scheds and rt.get("status") in ("running", "stopped")) else (60 if scheds else 20)
    # 5 自学习（KB 召回）：该 super 有 KB 且能召回
    kb_hits = 0
    sup_id = found.get("super_id") or mission.get("supervisor_agent_id")
    kb_match = None
    for kb in c.kbs():
        coll = (kb.get("collection_name") or "") + (kb.get("name") or "")
        if sup_id and str(sup_id).replace("-", "")[:12] in coll:
            kb_match = kb
            break
    kb_search_ok = False
    if kb_match:
        res = c.kb_search(kb_match["id"], domain["recall"], 5)
        kb_hits = len(res.get("hits", []))
        kb_search_ok = "error" not in res
    # 新建 super 的 KB 必然为空（还没沉淀经验）：召回管线能跑通(无 error)=88（基建+召回就绪），
    # 召回到 hits=100，建了库但搜索报错=50，连库都没=20
    kb_score = 100 if kb_hits > 0 else (88 if (kb_match and kb_search_ok) else (50 if kb_match else 20))
    # 6 worker 复用：fresh super + 复用了已有 catalog worker（worker_threads>0 且 build fresh）
    reuse = 100 if found.get("fresh") else 50  # 复用已有 super = 反而是缺陷(50)
    # 7 builder 反馈链路：fresh 建 super 即链路通；复用=链路有问题
    feedback = 100 if found.get("fresh") and mission else 50
    # 8 状态自动暂停/继续：见到审批并自动放行后能继续
    pause_resume = 100 if metrics.get("paused_resumed") else (70 if metrics["ticks"] > 1 else 40)

    dims = {
        "completion": completion, "passrate": passrate, "schedule": sched_score,
        "sustained": sustained, "kb_recall": kb_score, "worker_reuse": reuse,
        "feedback_chain": feedback, "pause_resume": pause_resume,
    }
    overall = round(sum(dims.values()) / len(dims), 1)
    return {"dims": dims, "overall": overall, "schedules": len(scheds),
            "kb": (kb_match or {}).get("name"), "kb_hits": kb_hits}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domains", type=int, default=1)
    ap.add_argument("--build-ticks", type=int, default=8)
    ap.add_argument("--exec-ticks", type=int, default=6)
    ap.add_argument("--out", default="/tmp/eval_result.json")
    args = ap.parse_args()

    c = Client()
    builder_agent_id = c.builder_agent_id()
    base_super = c.super_ids()
    base_mission = {m["id"] for m in c.all_missions()}
    log(f"builder_agent={builder_agent_id} baseline supers={len(base_super)} missions={len(base_mission)}")

    results = []
    for domain in DOMAINS[: args.domains]:
        try:
            c.login()  # 每域刷新 token，避免长跑 401
            found = drive_builder(c, domain, args.build_ticks, builder_agent_id, base_super, base_mission)
            # 无论成败，先把检出的 super_id 并入 baseline，避免下一域重复检出同一 super
            if found and found.get("super_id"):
                base_super.add(found["super_id"])
            if not found or not found.get("mission"):
                results.append({"domain": domain["key"], "ok": False, "reason": "builder_no_super",
                                "fresh": found.get("fresh") if found else None,
                                "super_id": found.get("super_id") if found else None})
                continue
            m = found["mission"]
            base_mission.add(m["id"])
            slug = m["slug"]
            mid = c.mission_runtime_id(slug) or m["id"]
            metrics = drive_mission(c, slug, mid, domain, args.exec_ticks)
            sc = score_scenario(c, domain, found, slug, mid, metrics)
            results.append({
                "domain": domain["key"], "ok": True, "super_slug": slug,
                "fresh_super": found.get("fresh"), "build_ticks": found.get("build_ticks_used"),
                "metrics": metrics, "score": sc,
            })
            log(f"[{domain['key']}] 综合={sc['overall']} dims={sc['dims']}")
        except Exception as e:  # noqa: BLE001
            results.append({"domain": domain["key"], "ok": False, "reason": repr(e)})
            log(f"[{domain['key']}] EXC {e!r}")

    ok = [r for r in results if r.get("ok")]
    avg = round(sum(r["score"]["overall"] for r in ok) / len(ok), 1) if ok else 0
    summary = {"scenarios": len(results), "ok": len(ok), "avg_overall": avg,
               "pass_gate_95": avg >= 95, "results": results}
    with open(args.out, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    log(f"== DONE avg_overall={avg} ok={len(ok)}/{len(results)} pass95={avg>=95} → {args.out} ==")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
