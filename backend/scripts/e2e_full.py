"""完整 E2E：驱动 Builder 走完 PROPOSE → 确认 → BUILD → 安装/建造 → 激活，每个审批自动选第 1 个选项（=推进项）。

终止条件：
- 出现 activate_super_first_run / 进入 super 按钮 / super_activated → SUCCESS（建到激活完成）
- 出现需人类操作的卡（扫码/二维码/QR/密钥/token/登录）→ HUMAN_GATE（设计内的人工闸门，自动流程到此为止）
- 某轮没有审批、也没推进 → END
- 超过 MAX_TURNS → STOP
"""
import asyncio, json, re, sys
import httpx

API="http://localhost:9022"
WISH=sys.argv[1] if len(sys.argv)>1 else "我想做个小红书美妆账号，平价学生党彩妆，帮我自动运营赚钱"
MAX_TURNS=10
HUMAN_PAT=re.compile(r"扫码|二维码|QR|密钥|token|登录|login|付费|手动")


def short(x,n=150):
    s=x if isinstance(x,str) else json.dumps(x,ensure_ascii=False)
    return s.replace("\n"," ")[:n]


def parse_options(tool_output:str):
    # request_approval 工具回执末尾："...选择：A / B / C"
    m=re.search(r"选择[:：](.+)$", tool_output or "")
    if not m: return []
    return [o.strip() for o in m.group(1).split(" / ") if o.strip()]


async def turn(c,H,sid,msg,state):
    print(f"\n===== TURN: {msg!r} =====")
    state["last_options"]=[]; state["approval"]=False; state["progress"]=False
    async with c.stream("POST",f"/api/sessions/{sid}/chat",headers=H,json={"message":msg}) as resp:
        if resp.status_code>=400:
            print("FAILED",resp.status_code,(await resp.aread()).decode()[:300]); state["fail"]=True; return
        async for line in resp.aiter_lines():
            if not line.startswith("data:"): continue
            raw=line[5:].strip()
            if not raw or raw=="[DONE]": continue
            try: ev=json.loads(raw)
            except: continue
            t=ev.get("type")
            if t=="tool-input-available":
                nm=ev.get("toolName"); state["progress"]=True
                print(f"  → {nm} in={short(ev.get('input'),120)}")
                if nm in ("activate_super_first_run","project_create","agent_create","clawhub_install","mcp_ensure_ready","project_lifecycle_control"):
                    state.setdefault("key_calls",[]).append(nm)
            elif t=="tool-output-available":
                nm=ev.get("toolName"); out=str(ev.get("output",""))
                print(f"    ← {nm} out={short(out,170)}")
                if nm=="request_approval":
                    state["approval"]=True; state["last_options"]=parse_options(out)
                if nm=="activate_super_first_run" and ('"ok": true' in out or 'ok=True' in out or '已' in out):
                    state["activated"]=True
                if HUMAN_PAT.search(out): state["human_hint"]=out[:160]
            elif t=="data-approval-request":
                state["approval"]=True
            elif t=="finish":
                print("  [finish]")


async def main():
    async with httpx.AsyncClient(base_url=API,timeout=600.0,trust_env=False) as c:
        tok=(await c.post("/api/auth/login",data={"username":"admin","password":"admin123"})).json()["access_token"]
        H={"Authorization":f"Bearer {tok}"}
        resume_sid=sys.argv[2] if len(sys.argv)>2 else ""
        state={}
        if resume_sid:
            sid=resume_sid
            msg="继续，把剩下的建造步骤做完：project_create → schedule_create → project_set_approval_channel → project_update → 如需本地 MCP 则 mcp_ensure_ready(target_project_id=新项目) → 最后 activate_super_first_run(project_id) 激活并给「进入 super」按钮。"
            print("RESUME session:",sid)
        else:
            sid=(await c.post("/api/sessions",headers=H,json={"project_slug":"builder","title":f"full {WISH[:5]}{len(WISH)}"})).json()["id"]
            msg=WISH
            print("session:",sid)
        nudges=0
        NUDGE="继续，把 super 建好并 project_create（其余收尾平台会自动做）。"
        for i in range(MAX_TURNS):
            await turn(c,H,sid,msg,state)
            if state.get("fail"): print("\n[VERDICT] FAILED"); break
            # 确定性 finalize 是 post-turn 代码级动作 → 查落库 super_activated 消息（不在 stream 里）
            try:
                _msgs=(await c.get(f"/api/sessions/{sid}/messages", headers=H)).json()
                if any((m.get("meta") or {}).get("type")=="super_activated" for m in _msgs):
                    state["activated"]=True
            except Exception: pass
            if state.get("activated"): print("\n[VERDICT] ✅ SUCCESS — super activated (post-turn finalize)"); break
            opts=state.get("last_options",[])
            # human gate: 审批里含扫码/密钥等人工动作
            if state.get("approval") and opts and HUMAN_PAT.search(" ".join(opts)+(state.get("human_hint","") or "")):
                non_human=[o for o in opts if not HUMAN_PAT.search(o)]
                if not non_human:
                    print(f"\n[VERDICT] ⏸ HUMAN_GATE — 需人工：{opts}"); break
            if state.get("approval") and opts:
                msg=opts[0]; nudges=0
                print(f"  ↪ auto-pick option[0]: {msg!r}")
                continue
            # 无审批但还没激活 → 说明 BUILD 没在一轮里做完，nudge 续建（防呆：最多连 nudge 4 次）
            nudges+=1
            if nudges>4:
                print("\n[VERDICT] STOP — 连续 nudge 仍未激活（BUILD 卡住）"); break
            msg=NUDGE
            print(f"  ↪ nudge#{nudges} 续建")
        else:
            print("\n[VERDICT] STOP — 达到 MAX_TURNS")
        print("[key_calls]", state.get("key_calls"))
        print("[session]", sid)
asyncio.run(main())
