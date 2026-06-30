#!/usr/bin/env bash
# 评测前重置（用户授权「清实验态+重置 builder 线程」）：删除所有非系统 mission +
# 它们的 super（cascade），清空 builder 对话历史/记忆，run_count 归零。
# 保留：providers / volcengine / embedding 设置 / catalog workers / 系统 Agent。
set -euo pipefail
BASE=http://localhost:19022
T=$(curl -s -X POST "$BASE/api/auth/login" -d 'username=admin&password=admin123' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
PSQL() { docker exec colony-postgres psql -U postgres -d colony -t -A -F'|' -c "$1" 2>/dev/null; }

# 1. 删除所有非系统 mission（is_system=false）—— 这些都是评测产物
for MID in $(PSQL "SELECT id FROM missions WHERE is_system=false"); do
  slug=$(PSQL "SELECT slug FROM missions WHERE id='$MID'")
  code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/api/missions/$MID?cascade_agents=true" -H "Authorization: Bearer $T")
  echo "deleted mission $slug -> $code"
done

# 2. 残留的非系统 super agent（被多 mission 共享、cascade 跳过的）直接清掉
for AID in $(PSQL "SELECT id FROM agents WHERE kind='super' AND name NOT IN ('Builder Supervisor','Colony Worker Optimization')"); do
  PSQL "DELETE FROM agents WHERE id='$AID';" >/dev/null && echo "deleted orphan super $AID"
done

# 3. 清 builder 对话历史/记忆 + run_count 归零
BID=$(PSQL "SELECT id FROM missions WHERE slug='builder'")
for tbl in messages mission_agent_memory thread_agent_memories thread_compression_state super_pending_messages pending_approvals; do
  PSQL "DELETE FROM $tbl WHERE mission_id='$BID';" >/dev/null 2>&1 || true
done
PSQL "UPDATE mission_run_state SET run_count=0, status='stopped' WHERE mission_id='$BID';" >/dev/null

echo "=== post-reset ==="
echo "supers: $(PSQL "SELECT string_agg(name,',') FROM agents WHERE kind='super'")"
echo "non-system missions: $(PSQL "SELECT count(*) FROM missions WHERE is_system=false")"
echo "builder run_count: $(PSQL "SELECT run_count FROM mission_run_state WHERE mission_id='$BID'")"
echo "providers: $(PSQL "SELECT string_agg(name||':'||is_enabled,' ') FROM llm_providers")"
echo "embedding: $(PSQL "SELECT value FROM system_settings WHERE key='default_embedding_model_id'")"
