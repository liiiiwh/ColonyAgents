#!/usr/bin/env bash
# 逐个试用 9 个 super：派真实任务→自动放行 §0 定位/审批→驱动出执行输出→收集，供质量评估。
set -uo pipefail
BASE=http://localhost:19022
T=$(curl -s -X POST "$BASE/api/auth/login" -d 'username=admin&password=admin123' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
H="Authorization: Bearer $T"
PSQL() { docker exec colony-postgres psql -U postgres -d colony -t -A -F'§' -c "$1" 2>/dev/null; }
pick() { echo "$1" | tr '|' '\n' | grep -iE '就这样|Go with this|确认|同意|批准|继续|开始' | grep -viE '让我|我自己|放弃|取消|跳过|调整|扫' | head -1 | sed 's/^ *//;s/ *$//'; }

trial() {
  local slug="$1" task="$2"
  echo "######## [$slug] ########"
  local mid; mid=$(docker exec colony-postgres psql -U postgres -d colony -t -A -c "SELECT id FROM missions WHERE slug='$slug'" 2>/dev/null)
  [ -z "$mid" ] && { echo "  mission 不存在"; return; }
  curl -s -X POST "$BASE/api/super/$slug/chat" -H "$H" -H 'Content-Type: application/json' -d "{\"content\":\"$task\",\"auto_start\":true}" -o /dev/null
  # 驱动 4 轮：有审批就放行（§0 定位/大额等），否则 run_once
  for i in 1 2 3 4 5; do
    sleep 12
    local rid; rid=$(docker exec colony-postgres psql -U postgres -d colony -t -A -c "SELECT request_id FROM pending_approvals WHERE mission_id='$mid' AND status='pending' LIMIT 1" 2>/dev/null)
    if [ -n "$rid" ]; then
      local opts; opts=$(docker exec colony-postgres psql -U postgres -d colony -t -A -c "SELECT array_to_string(ARRAY(SELECT jsonb_array_elements_text(options::jsonb)),'|') FROM pending_approvals WHERE request_id='$rid'" 2>/dev/null)
      local opt; opt=$(pick "$opts"); [ -z "$opt" ] && opt=$(echo "$opts"|cut -d'|' -f1)
      curl -s -X POST "$BASE/api/pending-approvals/$rid/decide" -H "$H" -H 'Content-Type: application/json' -d "{\"option\":\"$opt\",\"decided_by\":\"trial\"}" -o /dev/null
      echo "  放行审批: $opt"
    else
      curl -s -X POST "$BASE/api/missions/$mid/lifecycle/run_once" -H "$H" -o /dev/null 2>/dev/null
    fi
  done
  # 收集：worker 调用数 + 最近一条实质输出
  local wc; wc=$(docker exec colony-postgres psql -U postgres -d colony -t -A -c "SELECT count(*) FROM messages WHERE mission_id='$mid' AND thread_key LIKE 'worker:%'" 2>/dev/null)
  local out; out=$(PSQL "SELECT left(regexp_replace(content,E'[\n\r]+',' ','g'),260) FROM messages WHERE mission_id='$mid' AND role='assistant' AND length(content)>80 ORDER BY created_at DESC LIMIT 1")
  echo "  worker调用数=$wc"
  echo "  输出: ${out:-（无）}"
}

trial server-ops-monitor "检查服务器，发现订单接口 5xx 错误率升高，请诊断根因并按流程处理。"
trial fin-recon-audit "核对今天账单流水，发现一笔 ¥80,000 大额支出，请按流程稽核（大额走审批）。"
trial contract-review "有一份采购合同（金额 500 万，含单方解除权与无限责任条款），请检查风险条款并走结论审批。"
trial industry-research "就『国产大模型竞争格局』出一份调研简报，发布前走审批。"
trial tutoring-assistant "学生问『什么是递归，举个例子』，请讲解并布置一道练习题走审批。"
trial community-ops "群里有人反复刷广告链接，请按流程处理（踢人/禁言走审批）。"
trial logistics-scheduler "今天有一批跨城订单（北京→上海 20 单），请规划配送路线，跨区域调拨走审批。"
trial iot-alert-inspector "巡检发现 3 号机房某服务器温度 85℃ 告警，请分级并按流程处理（派工走审批）。"
trial resume-screening "有一份 5 年后端工程师简历（Go/K8s），岗位要求 3 年+，请筛选打分并走面试邀约审批。"
echo "######## TRIAL DONE ########"
