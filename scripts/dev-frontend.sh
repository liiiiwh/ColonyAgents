#!/usr/bin/env bash
# 启动前端开发服务（端口 3022）
set -euo pipefail
cd "$(dirname "$0")/../frontend"

if [ ! -d node_modules ]; then
  echo "▶ 首次运行，安装依赖..."
  npm install
fi

echo "▶ 启动 Next.js dev server (port 3022)..."
exec npm run dev
