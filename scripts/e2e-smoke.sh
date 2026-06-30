#!/usr/bin/env bash
# 端到端 smoke 测试：验证 auth / provider / skill / agent / project / session / chat / upload 全链路
# 前置：后端已在 http://localhost:9022 运行；真实 PG + S3 已配置
set -euo pipefail

API="${API:-http://localhost:9022}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-admin123}"

# LLM 凭证从环境变量注入（绝不硬编码进库）。本地/CI 运行前 export GEMINI_KEY / GEMINI_BASE。
GEMINI_KEY="${GEMINI_KEY:?set GEMINI_KEY env var (do not hardcode secrets)}"
GEMINI_BASE="${GEMINI_BASE:?set GEMINI_BASE env var}"

log() { printf "\n\033[1;34m▶ %s\033[0m\n" "$*"; }
fail() { printf "\033[1;31m✗ %s\033[0m\n" "$*"; exit 1; }

# ────────────── 1. health ──────────────
log "1. /api/health"
curl -sf "$API/api/health" >/dev/null || fail "health 失败"
curl -sf "$API/api/health/db" >/dev/null || fail "health/db 失败"
echo '  ✅ health + db'

# ────────────── 2. login ──────────────
log "2. 登录 admin"
TOKEN=$(curl -sf -X POST "$API/api/auth/login" \
  -d "username=$ADMIN_USER&password=$ADMIN_PASS" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
[ -n "$TOKEN" ] || fail "无 access_token"
H="Authorization: Bearer $TOKEN"
echo "  ✅ token len=${#TOKEN}"

# 获取 admin 用户自身 id（用于 /me 流程）
ME=$(curl -sf "$API/api/auth/me" -H "$H" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["username"], d["role"])')
echo "  ✅ /me → $ME"

# ────────────── 3. skills seed ──────────────
log "3. Skills 是否播种 21 个内置"
COUNT=$(curl -sf "$API/api/skills" -H "$H" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(sum(1 for s in d if s["is_builtin"]))')
[ "$COUNT" = "21" ] || fail "内置 skill 数 $COUNT != 21"
echo "  ✅ 20 内置 skill"

# ────────────── 4. provider + sync models ──────────────
log "4. 创建 Gemini provider 并同步真实模型"
# 级联清理：Project → Agent → KnowledgeBase → Provider（llm_models 被 agents 与 knowledge_bases 双重 RESTRICT）
for PID in $(curl -sf "$API/api/projects" -H "$H" | python3 -c 'import sys, json
try:
    print(" ".join(p["id"] for p in json.load(sys.stdin)))
except Exception:
    pass'); do
  curl -s -X DELETE "$API/api/projects/$PID" -H "$H" >/dev/null || true
done
for AID in $(curl -sf "$API/api/agents" -H "$H" | python3 -c 'import sys, json
try:
    print(" ".join(a["id"] for a in json.load(sys.stdin)))
except Exception:
    pass'); do
  curl -s -X DELETE "$API/api/agents/$AID" -H "$H" >/dev/null || true
done
for KID in $(curl -sf "$API/api/knowledge" -H "$H" | python3 -c 'import sys, json
try:
    print(" ".join(k["id"] for k in json.load(sys.stdin)))
except Exception:
    pass'); do
  curl -s -X DELETE "$API/api/knowledge/$KID" -H "$H" >/dev/null || true
done
EXIST=$(curl -sf "$API/api/providers" -H "$H" | python3 -c 'import sys, json
try:
    d = [p["id"] for p in json.load(sys.stdin) if p["name"]=="e2e-gemini"]
    print(d[0] if d else "")
except Exception:
    print("")')
[ -n "$EXIST" ] && curl -s -X DELETE "$API/api/providers/$EXIST" -H "$H" >/dev/null || true

PROV=$(curl -sf -X POST "$API/api/providers" -H "$H" -H 'Content-Type: application/json' \
  -d "{\"name\":\"e2e-gemini\",\"provider_type\":\"gemini\",\"api_key\":\"$GEMINI_KEY\",\"base_url\":\"$GEMINI_BASE\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "  provider=$PROV"

sleep 1  # 让 create_provider 的 auto-sync 完成
MODELS_JSON=$(curl -sf "$API/api/providers/$PROV/models" -H "$H")
N_MODELS=$(echo "$MODELS_JSON" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))')
[ "$N_MODELS" -gt 0 ] || fail "sync 未拉到模型"
echo "  ✅ auto-sync 拉到 $N_MODELS 个真实模型"

CHAT_MID=$(echo "$MODELS_JSON" | python3 -c '
import sys,json
for m in json.load(sys.stdin):
    if m["model_id"] == "gemini-2.5-flash":
        print(m["id"]); break
')
[ -n "$CHAT_MID" ] || fail "找不到 gemini-2.5-flash"
echo "  gemini-2.5-flash id=$CHAT_MID"

# ────────────── 5. agent ──────────────
log "5. 创建 Supervisor + Worker agent + 绑定 skill"
# 清理同名
for NAME in e2e-supervisor e2e-worker; do
  EXIST=$(curl -sf "$API/api/agents" -H "$H" | python3 -c "import sys,json; d=[a['id'] for a in json.load(sys.stdin) if a['name']=='$NAME']; print(d[0] if d else '')")
  [ -n "$EXIST" ] && curl -sf -X DELETE "$API/api/agents/$EXIST" -H "$H" || true
done

SUP=$(curl -sf -X POST "$API/api/agents" -H "$H" -H 'Content-Type: application/json' \
  -d "{\"name\":\"e2e-supervisor\",\"model_id\":\"$CHAT_MID\",\"soul_md\":\"你是玩具设计项目主管，善于拆分任务并使用 dispatch_to_worker 调度具体节点。\",\"protocol_md\":\"收到任务后简要确认，再决定是否调度 parse / generate 节点。\",\"max_iterations\":12,\"temperature\":0.3}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
WRK=$(curl -sf -X POST "$API/api/agents" -H "$H" -H 'Content-Type: application/json' \
  -d "{\"name\":\"e2e-worker\",\"model_id\":\"$CHAT_MID\",\"soul_md\":\"你是玩具设计师，擅长用 workspace_write 提交 Markdown 报告。\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

# 给 supervisor 绑定 dispatch_to_worker + workspace_read
SKILLS=$(curl -sf "$API/api/skills" -H "$H")
DISPATCH_ID=$(echo "$SKILLS" | python3 -c 'import sys,json; print(next(s["id"] for s in json.load(sys.stdin) if s["slug"]=="dispatch_to_worker"))')
WS_READ_ID=$(echo "$SKILLS" | python3 -c 'import sys,json; print(next(s["id"] for s in json.load(sys.stdin) if s["slug"]=="workspace_read"))')
WS_WRITE_ID=$(echo "$SKILLS" | python3 -c 'import sys,json; print(next(s["id"] for s in json.load(sys.stdin) if s["slug"]=="workspace_write"))')

curl -sf -X POST "$API/api/agents/$SUP/skills/$DISPATCH_ID" -H "$H" -H 'Content-Type: application/json' -d '{}' >/dev/null
curl -sf -X POST "$API/api/agents/$SUP/skills/$WS_READ_ID" -H "$H" -H 'Content-Type: application/json' -d '{}' >/dev/null
# 给 worker 绑定 workspace_write
curl -sf -X POST "$API/api/agents/$WRK/skills/$WS_WRITE_ID" -H "$H" -H 'Content-Type: application/json' -d '{}' >/dev/null

echo "  ✅ supervisor=$SUP (dispatch+read) / worker=$WRK (write)"

# ────────────── 6. project + node + activate ──────────────
log "6. 创建并激活 Project"
EXIST=$(curl -sf "$API/api/projects" -H "$H" | python3 -c 'import sys,json; d=[p["id"] for p in json.load(sys.stdin) if p["slug"]=="e2e"]; print(d[0] if d else "")')
[ -n "$EXIST" ] && curl -sf -X DELETE "$API/api/projects/$EXIST" -H "$H" || true

PROJ=$(curl -sf -X POST "$API/api/projects" -H "$H" -H 'Content-Type: application/json' \
  -d "{\"name\":\"E2E Smoke\",\"slug\":\"e2e\",\"supervisor_agent_id\":\"$SUP\",\"context_compression_threshold\":200000}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
for i in 0 1; do
  NAME=$( [ "$i" = "0" ] && echo "parse" || echo "generate" )
  curl -sf -X POST "$API/api/projects/$PROJ/nodes" -H "$H" -H 'Content-Type: application/json' \
    -d "{\"agent_id\":\"$WRK\",\"node_name\":\"$NAME\",\"node_order\":$i}" >/dev/null
done
ACT=$(curl -sf -X POST "$API/api/projects/$PROJ/activate" -H "$H" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ok"])')
[ "$ACT" = "True" ] || fail "激活失败"
echo "  ✅ project=$PROJ active"

# ────────────── 7. storage user-upload ──────────────
log "7. storage/user-upload 测试（20MB 以下）"
echo "hello colony e2e $(date)" > /tmp/e2e-note.txt
UPLOAD=$(curl -sf -X POST "$API/api/storage/user-upload" -H "$H" -F "file=@/tmp/e2e-note.txt")
URL=$(echo "$UPLOAD" | python3 -c 'import sys,json; print(json.load(sys.stdin)["url"])')
KEY=$(echo "$UPLOAD" | python3 -c 'import sys,json; print(json.load(sys.stdin)["key"])')
echo "  ✅ user-upload key=$KEY"
echo "     presigned url 前缀：$(echo $URL | cut -c 1-80)..."

# ────────────── 8. session + chat ──────────────
log "8. 创建 session + 真实 chat（带附件）"
SID=$(curl -sf -X POST "$API/api/sessions" -H "$H" -H 'Content-Type: application/json' \
  -d '{"project_slug":"e2e","title":"e2e smoke"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "  session=$SID"

# 验证 include_progress=1 字段形态
PROGRESS_SHAPE=$(SID_ENV="$SID" curl -sf "$API/api/sessions?include_progress=true" -H "$H" | SID_ENV="$SID" python3 -c '
import sys, json, os
sid = os.environ["SID_ENV"]
data = json.load(sys.stdin)
ours = [s for s in data if s.get("id") == sid]
assert ours, "created session not in list"
s = ours[0]
assert "title" in s, "no title field"
prog = s.get("progress")
assert prog is not None, "progress field missing when include_progress=true"
for k in ("total_nodes", "completed_nodes", "is_delivered"):
    assert k in prog, f"progress schema missing key: {k}"
title = s["title"]
total = prog["total_nodes"]
done = prog["completed_nodes"]
delivered = prog["is_delivered"]
print(f"title={title!r} total={total} done={done} delivered={delivered}")
')
echo "  ✅ include_progress shape: $PROGRESS_SHAPE"

# 带附件的 chat：
CHAT_RESP=$(curl -sN -X POST "$API/api/sessions/$SID/chat" -H "$H" -H 'Content-Type: application/json' \
  -d "{\"message\":\"请简要介绍一下这个平台，然后调用 dispatch_to_worker 节点名 parse，交给它任务：把附件内容写成一个 Markdown 产物放到 analyze 节点\",\"attachments\":[{\"type\":\"file\",\"name\":\"e2e-note.txt\",\"content\":\"$URL\"}]}" 2>&1 | head -200)
echo "$CHAT_RESP" | head -20
[ "$(echo "$CHAT_RESP" | grep -c '"type": "start"')" -ge 1 ] || fail "SSE 无 start"
[ "$(echo "$CHAT_RESP" | grep -c '"type": "finish"')" -ge 1 ] || fail "SSE 无 finish"
echo "  ✅ SSE 正常结束"

# ────────────── 9. branch 回退 ──────────────
log "9. branch 列表 + rollback"
BRANCHES=$(curl -sf "$API/api/sessions/$SID/branches" -H "$H" | python3 -c 'import sys,json; d=json.load(sys.stdin)["branches"]; print(len(d), d[0]["version_label"])')
echo "  branches: $BRANCHES"

ROLLBACK=$(curl -sf -X POST "$API/api/sessions/$SID/rollback" -H "$H" -H 'Content-Type: application/json' \
  -d '{"node_name":"generate","reason":"e2e smoke rollback"}' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["version_label"], d["branch_number"])' )
echo "  ✅ rollback 新分支：$ROLLBACK"

# ────────────── 10. messages 历史 ──────────────
log "10. 历史消息（含附件 meta）"
MSGS=$(curl -sf "$API/api/sessions/$SID/messages" -H "$H" | python3 -c '
import sys, json
msgs = json.load(sys.stdin)
for m in msgs:
    atts = (m.get("meta") or {}).get("attachments") or []
    role = m["role"]
    content_len = len(m["content"])
    print("  - {:9s} [{} 字符，{} 附件]".format(role, content_len, len(atts)))
' )
echo "$MSGS"

# ────────────── 11. knowledge base ──────────────
log "11. 知识库创建 + 索引 + 检索"
EMBED_MID=$(echo "$MODELS_JSON" | python3 -c '
import sys, json
for m in json.load(sys.stdin):
    if m["model_type"] == "embedding":
        print(m["id"]); break
')
if [ -n "$EMBED_MID" ]; then
  # 先清老 KB
  LIST_JSON=$(curl -s "$API/api/knowledge" -H "$H")
  EXIST=$(echo "$LIST_JSON" | python3 -c '
import sys, json
try:
    data = json.load(sys.stdin)
    d = [k["id"] for k in data if k.get("collection_name")=="e2e_kb"]
    print(d[0] if d else "")
except Exception:
    print("")
')
  [ -n "$EXIST" ] && curl -s -X DELETE "$API/api/knowledge/$EXIST" -H "$H" >/dev/null || true
  CREATE_RESP=$(curl -s -X POST "$API/api/knowledge" -H "$H" -H 'Content-Type: application/json' \
    -d "{\"name\":\"e2e-kb\",\"collection_name\":\"e2e_kb\",\"embedding_model_id\":\"$EMBED_MID\"}")
  KB=$(echo "$CREATE_RESP" | python3 -c '
import sys, json
try:
    print(json.load(sys.stdin).get("id") or "")
except Exception:
    print("")
')
  if [ -z "$KB" ]; then
    echo "  ⚠️  创建 KB 失败：$CREATE_RESP（跳过后续）"
  else
    curl -s -X POST "$API/api/knowledge/$KB/documents" -H "$H" -H 'Content-Type: application/json' \
      -d '{"filename":"policy.md","content":"灵优造物主要采用 ABS 与 TPE 环保塑料。产品需符合 GB-6675 玩具安全规范。"}' >/dev/null
    SEARCH_RESP=$(curl -s -X POST "$API/api/knowledge/$KB/search" -H "$H" -H 'Content-Type: application/json' \
      -d '{"query":"玩具安全材料","top_k":2}')
    SEARCH=$(echo "$SEARCH_RESP" | python3 -c '
import sys, json
try:
    print(len(json.load(sys.stdin).get("hits", [])))
except Exception:
    print(0)
')
    echo "  ✅ knowledge search 命中 $SEARCH 条"
  fi
else
  echo "  ⚠️  无 embedding 模型，跳过 knowledge 测试"
fi

# ────────────── 12. 清理 ──────────────
log "12. 清理（可选；默认保留，便于浏览器继续查看）"
if [ "${CLEANUP:-0}" = "1" ]; then
  curl -sf -X DELETE "$API/api/sessions/$SID" -H "$H" >/dev/null
  curl -sf -X DELETE "$API/api/projects/$PROJ" -H "$H" >/dev/null
  curl -sf -X DELETE "$API/api/agents/$SUP" -H "$H" >/dev/null
  curl -sf -X DELETE "$API/api/agents/$WRK" -H "$H" >/dev/null
  curl -sf -X DELETE "$API/api/providers/$PROV" -H "$H" >/dev/null
  [ -n "${KB:-}" ] && curl -sf -X DELETE "$API/api/knowledge/$KB" -H "$H" >/dev/null || true
  echo "  已清理"
else
  echo "  保留数据（设置 CLEANUP=1 可清理）"
fi

log "🎉 E2E smoke 全部通过"
