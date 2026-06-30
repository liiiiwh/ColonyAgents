#!/usr/bin/env bash
# 启动后端开发服务（端口 9022）
# 用法：./scripts/dev-backend.sh
#
# 代理开关：改 USE_PROXY 和 PROXY_URL 就行，不做任何环境判断。
#   USE_PROXY=true  → 启用；HTTPS_PROXY / HTTP_PROXY = PROXY_URL
#   USE_PROXY=false → 不启用；unset 全部 *_PROXY 变量
set -euo pipefail

# ─────────────────────────────────────────────
USE_PROXY=true
PROXY_URL="http://127.0.0.1:7890"
# ─────────────────────────────────────────────

cd "$(dirname "$0")/../backend"

# 开发环境优先使用 backend/.env，避免外部 shell 里残留的 DEFAULT_*MODEL_ID
# 把本地配置覆盖成裸 model_id 后再次命中多 provider 同名歧义。
unset DEFAULT_AGENT_MODEL_ID DEFAULT_SUPERVISOR_MODEL_ID

if [ "$USE_PROXY" = "true" ]; then
    export HTTPS_PROXY="$PROXY_URL"
    export HTTP_PROXY="$PROXY_URL"
    # 本机 / 内网网段直连；182.92.98.228 是 colony 远程 PG (9007) + RustFS S3 (9008) 的同一主机
    export NO_PROXY="localhost,127.0.0.1,::1,.local,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,gemini.yuminshijie.cn,bj.s3.qiyi.storage,182.92.98.228"
    echo "▶ 代理：启用 $PROXY_URL  (NO_PROXY=$NO_PROXY)"
else
    unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
    echo "▶ 代理：关闭（USE_PROXY=false）"
fi

echo "▶ 执行数据库迁移..."
uv run alembic upgrade head

echo "▶ 启动 FastAPI (0.0.0.0:9022)..."
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 9022 --reload
