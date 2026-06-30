#!/usr/bin/env bash
# Colony · 一键引导安装 (ADR-015)
#
# 极薄包装：复制 .env → `docker compose up -d`（infra + backend + frontend）→ 等后端健康 → 打印后续指引。
# 整栈通过 docker-compose.yml 的 include 一次拉起：postgres(pgvector) + minio + backend + frontend。
# backend 容器启动时自动 `alembic upgrade head`（见 docker-compose.yml command）。
# 幂等：重复运行安全——.env 已存在则不覆盖，compose up 收敛到目标状态。
#
# 用法：
#   bash scripts/install.sh                      # 交互式：整栈拉起 + 健康探活 + 后续指引
#   AUTO_INSTALL=true bash scripts/install.sh    # CI/无人值守：跳过手动「添加 provider」一步的提示
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FRONTEND_PORT=3022
BACKEND_HEALTH_URL="http://localhost:9022/api/health"

echo "▶ Colony 一键安装 · 仓库根 = $ROOT"

# 1) backend/.env（凭证单一事实源）—— 缺失则从 example 复制
echo "▶ [1/4] 检查 backend/.env …"
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "  ⚠️  已从 backend/.env.example 创建 backend/.env"
  echo "      请填写 LLM provider 凭证 / SECRET_KEY / ENCRYPTION_KEY（生成命令见文件内注释）。"
else
  echo "  ✅ backend/.env 已存在（不覆盖）"
fi

# 2) 整栈拉起（infra + app；infra 经 include 引入）
echo "▶ [2/4] docker compose up -d（postgres + minio + backend + frontend）…"
docker compose up -d

# 3) 等后端健康（backend 容器内先跑 alembic 迁移，故启动需要时间）
echo "▶ [3/4] 等待后端健康 ($BACKEND_HEALTH_URL) …"
HEALTHY=false
for i in $(seq 1 60); do
  if curl -fsS "$BACKEND_HEALTH_URL" >/dev/null 2>&1; then
    HEALTHY=true
    echo "  ✅ 后端健康（迁移已完成）"
    break
  fi
  sleep 3
done
if [ "$HEALTHY" != "true" ]; then
  echo "  ❌ 后端 180s 内未健康。排查：docker compose logs backend"
  exit 1
fi

# 4) 后续指引
echo "▶ [4/4] 安装完成。"
cat <<EOF

  打开    http://localhost:${FRONTEND_PORT}
  登录    admin / admin123（见 backend/.env 的 INIT_ADMIN_USERNAME / INIT_ADMIN_PASSWORD）
  然后    进入「LLM Providers / LLM 服务商」→ 添加一个 provider + 选一个默认模型
          —— 平台随即自动初始化（注入 Builder Supervisor / 内置 worker / 技能 / 平台 KB）。

EOF

if [ "${AUTO_INSTALL:-false}" = "true" ]; then
  echo "  AUTO_INSTALL=true → CI/无人值守模式：可跳过上面手动「添加 provider」一步"
  echo "                       （平台按该开关在启动时自动注入业务初始化数据）。"
fi

echo "✅ Colony 一键安装结束"
