#!/bin/bash
# 啟動 JIRA-Lark 同步監控系統

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 檢查 Python 版本
if ! command -v python3 &> /dev/null; then
    echo "錯誤: 找不到 python3"
    exit 1
fi

# 檢查必要檔案
if [ ! -f "sync_monitor.py" ]; then
    echo "錯誤: 找不到 sync_monitor.py"
    exit 1
fi

if [ ! -f "table_scan_cleaner.py" ]; then
    echo "錯誤: 找不到 table_scan_cleaner.py"
    exit 1
fi

if [ ! -f "config.yaml" ]; then
    echo "錯誤: 找不到 config.yaml"
    exit 1
fi

find_sync_monitor_pids() {
    pgrep -f "sync_monitor.py"
}

# 避免重複啟動同步監控
if find_sync_monitor_pids >/dev/null 2>&1; then
    echo "同步監控已在運行中，略過啟動。"
    exit 0
fi

# 啟動監控系統
echo "正在啟動 JIRA-Lark 多團隊同步監控系統..."
python3 sync_monitor.py
