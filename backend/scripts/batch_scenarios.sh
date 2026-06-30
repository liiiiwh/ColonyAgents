#!/usr/bin/env bash
# 批跑剩余领域（QR-build-block 已修后）：每域在 Colony Builder 下新建 mission(goal_hint)→
# 驱动构建(自动批 plan/skill/config 等闸门)→等 finalizer 落 super+schedule→给 super 派任务→
# 核验领域正确(无漂移)+能跑出输出。真实系统驱动（approve=点确认，run=触发 tick）。
set -uo pipefail
BASE=http://localhost:19022
BSUP="697ea6b1-4088-467c-8ca3-4a0fd8e476bb"
T=$(curl -s -X POST "$BASE/api/auth/login" -d 'username=admin&password=admin123' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
H="Authorization: Bearer $T"
PSQL() { docker exec colony-postgres psql -U postgres -d colony -t -A -F'|' -c "$1" 2>/dev/null; }
pick() { echo "$1" | tr '|' '\n' | grep -iE '确认|继续|开始|安装|全部|Install all|就按这个|进入|批准' | grep -viE '让我|我自己|放弃|取消|跳过|调整|扫|QR|scan' | head -1 | sed 's/^ *//;s/ *$//'; }

run_domain() {
  local key="$1" name="$2" goal="$3" task="$4" drift="$5"
  echo "===== [$key] $name ====="
  local t0; t0=$(PSQL "SELECT now()::timestamp(0)::text")   # 时间戳基线（可靠检测新 super）
  local mid; mid=$(curl -s -X POST "$BASE/api/missions" -H "$H" -H 'Content-Type: application/json' \
    -d "{\"super_agent_id\":\"$BSUP\",\"name\":\"$name\",\"goal_hint\":\"$goal\"}" | python3 -c "import sys,json;print(json.load(sys.stdin).get('mission',{}).get('id',''))")
  [ -z "$mid" ] && { echo "[$key] FAIL spawn"; return; }
  curl -s -X POST "$BASE/api/missions/$mid/lifecycle/start" -H "$H" -o /dev/null
  curl -s -X POST "$BASE/api/missions/$mid/lifecycle/run_once" -H "$H" -o /dev/null
  local newsup=""
  for i in $(seq 1 45); do
    newsup=$(PSQL "SELECT id FROM agents WHERE kind='super' AND created_at > '$t0' LIMIT 1")
    [ -n "$newsup" ] && break
    local rid; rid=$(PSQL "SELECT request_id FROM pending_approvals WHERE mission_id='$mid' AND status='pending' LIMIT 1")
    if [ -n "$rid" ]; then
      local title; title=$(PSQL "SELECT title FROM pending_approvals WHERE request_id='$rid'")
      local opts; opts=$(PSQL "SELECT array_to_string(ARRAY(SELECT jsonb_array_elements_text(options::jsonb)),'|') FROM pending_approvals WHERE request_id='$rid'")
      # 扫码/绑微信门：选「跳过」（构建不该卡在人工扫码；协议已改但防御）
      local opt
      if echo "$title$opts" | grep -qiE '扫码|绑定微信|scan|QR'; then
        opt=$(echo "$opts"|tr '|' '\n'|grep -iE '跳过|稍后|skip|later'|head -1|sed 's/^ *//;s/ *$//')
      else
        opt=$(pick "$opts")
      fi
      [ -z "$opt" ] && opt=$(echo "$opts"|cut -d'|' -f1)
      curl -s -X POST "$BASE/api/pending-approvals/$rid/decide" -H "$H" -H 'Content-Type: application/json' -d "{\"option\":\"$opt\",\"decided_by\":\"batch\"}" -o /dev/null
    else
      curl -s -X POST "$BASE/api/missions/$mid/lifecycle/run_once" -H "$H" -o /dev/null
    fi
    sleep 6
  done
  if [ -z "$newsup" ]; then echo "[$key] ⚠️ no super built (timeout)"; return; fi
  local sname smid sslug sched drifthit
  sname=$(PSQL "SELECT name FROM agents WHERE id='$newsup'")
  smid=$(PSQL "SELECT id FROM missions WHERE supervisor_agent_id='$newsup' LIMIT 1")
  sslug=$(PSQL "SELECT slug FROM missions WHERE id='$smid'")
  sched=$(PSQL "SELECT coalesce(string_agg(kind||':'||coalesce(expr,''),','),'NONE') FROM mission_schedule WHERE mission_id='$smid'")
  drifthit=$(PSQL "SELECT count(*) FROM messages WHERE mission_id='$mid' AND ($drift)")
  echo "[$key] ✅ super='$sname' slug='$sslug' schedule='$sched' drift=$drifthit"
  # 派任务核验能跑出输出
  curl -s -X POST "$BASE/api/super/$sslug/chat" -H "$H" -H 'Content-Type: application/json' -d "{\"content\":\"$task\",\"auto_start\":true}" -o /dev/null
  sleep 35
  local out; out=$(PSQL "SELECT left(regexp_replace(content,E'[\n\r]+',' ','g'),140) FROM messages WHERE mission_id='$smid' AND role='assistant' AND length(content)>80 ORDER BY created_at DESC LIMIT 1")
  echo "[$key] run_output: ${out:-（仍在跑）}"
}

D="$1"  # 一次只跑一个域（参数化，便于逐个观察）
case "$D" in
 legal)   run_domain legal "合同条款审查" "我要一个合同条款审查助理：自动检查合同条款风险并标注，出具审查结论前需法务审批。请配好 worker 和定时调度。" "有一份采购合同，请检查其中的风险条款并走结论审批。" "content LIKE '%小红书%' OR content LIKE '%运维%' OR content LIKE '%对账%' OR content LIKE '%简历%'";;
 research)run_domain research "行业市场调研" "我要一个行业市场调研助理：定期抓取行业资讯并归纳要点，形成调研简报发布前需我审批。请配好 worker 和定时调度。" "就『国产大模型竞争格局』归纳一份调研简报并走发布审批。" "content LIKE '%小红书%' OR content LIKE '%运维%' OR content LIKE '%对账%' OR content LIKE '%合同%'";;
 edu)     run_domain edu "在线教学辅导" "我要一个在线教学辅导助理：根据学生提问生成讲解，布置作业前需老师审批。请配好 worker 和定时调度。" "学生问『什么是递归，举个例子』，请讲解并布置一道作业走审批。" "content LIKE '%小红书%' OR content LIKE '%运维%' OR content LIKE '%对账%' OR content LIKE '%合同%'";;
 community)run_domain community "社群运营管理" "我要一个社群运营管理助理：监控群消息自动答常见问题，踢人/禁言这类管理动作需审批。请配好 worker 和定时调度。" "群里有人反复刷广告，请按流程处理（管理动作走审批）。" "content LIKE '%运维%' OR content LIKE '%对账%' OR content LIKE '%合同%' OR content LIKE '%简历%'";;
 logistics)run_domain logistics "物流调度排程" "我要一个物流调度排程助理：根据订单自动规划配送路线，跨区域调拨需审批。请配好 worker 和定时调度。" "今天有一批跨城订单，请规划配送路线，跨区域调拨走审批。" "content LIKE '%小红书%' OR content LIKE '%对账%' OR content LIKE '%合同%' OR content LIKE '%简历%'";;
 iot)     run_domain iot "设备告警巡检" "我要一个设备告警巡检助理：周期巡检 IoT 设备状态，发现告警自动分级，现场派工需审批。请配好 worker 和定时调度。" "巡检发现某台设备温度告警，请分级并按流程处理（派工走审批）。" "content LIKE '%小红书%' OR content LIKE '%对账%' OR content LIKE '%合同%' OR content LIKE '%简历%'";;
 hr)      run_domain hr "招聘简历筛选" "我要一个招聘简历筛选助理：自动筛选简历并按岗位打分，给候选人发面试邀约前需我审批。请配好 worker 和定时调度。" "有一份后端工程师简历投递进来，请筛选打分并走面试邀约审批。" "content LIKE '%小红书%' OR content LIKE '%对账%' OR content LIKE '%合同%' OR content LIKE '%运维%'";;
 ecom)    run_domain ecom "电商店铺巡检" "我要一个电商店铺巡检助理：每天巡检商品价格与库存，价格异常自动预警，改价操作需审批。请配好 worker 和定时调度。" "巡检发现某商品价格疑似设置过低，请按流程处理（改价走审批）。" "content LIKE '%小红书%' OR content LIKE '%对账%' OR content LIKE '%合同%' OR content LIKE '%简历%'";;
 *) echo "usage: $0 <legal|research|edu|community|logistics|iot>";;
esac
echo "== DONE $D =="
