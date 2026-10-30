#!/usr/bin/env bash
# Wrapper script chuyển tiếp về thư mục gốc
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT_DIR/deploy.sh" "$@"

