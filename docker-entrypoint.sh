#!/bin/sh
set -e

if [ ! -f /root/.opsai/config.json ]; then
    if [ -n "$OPSAI_API_KEY" ]; then
        opsai config use-preset "${OPSAI_PRESET:-deepseek-chat}" --api-key "$OPSAI_API_KEY"
    else
        echo "提示：通过环境变量 OPSAI_API_KEY 设置 API Key"
        echo "  docker compose run -e OPSAI_API_KEY=sk-xxx tui"
    fi
fi

exec "$@"
