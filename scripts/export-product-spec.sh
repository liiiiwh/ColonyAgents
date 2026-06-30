#!/usr/bin/env bash
# 导出产品规格文档（product-spec/）
# 用法：
#   bash scripts/export-product-spec.sh              # 导出默认 lingyou 项目
#   bash scripts/export-product-spec.sh --slug lingyou

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/../backend" && pwd)"
cd "$BACKEND_DIR"

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

echo "▶ 从数据库导出 Product Spec 文档..."
PYTHONPATH="$BACKEND_DIR" uv run python scripts/export_lingyou_product_spec.py "$@"
