#!/bin/bash

# JIRA-Lark 表格同步腳本
# 根據 config.yaml 中的間隔設定，定時同步各個表格

# 設定基本變數
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/config.yaml"
PYTHON_SCRIPT="${SCRIPT_DIR}/main.py"
LOG_FILE="${SCRIPT_DIR}/sync_tables.log"

# 檢查必要檔案是否存在
if [ ! -f "$CONFIG_FILE" ]; then
    echo "錯誤: 找不到配置檔案 $CONFIG_FILE"
    exit 1
fi

if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "錯誤: 找不到主程式 $PYTHON_SCRIPT"
    exit 1
fi

# 日誌函數
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 解析 YAML 配置檔案的函數
parse_yaml() {
    local file=$1
    local prefix=$2
    python3 -c "
import yaml
import sys

try:
    with open('$file', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    def flatten_dict(d, parent_key='', sep='_'):
        items = []
        if isinstance(d, dict):
            for k, v in d.items():
                new_key = f'{parent_key}{sep}{k}' if parent_key else k
                if isinstance(v, dict):
                    items.extend(flatten_dict(v, new_key, sep=sep).items())
                elif isinstance(v, list):
                    # 跳過列表類型，這個腳本主要處理簡單配置
                    continue
                elif v is not None:
                    # 處理布林值
                    if isinstance(v, bool):
                        value_str = 'true' if v else 'false'
                    else:
                        value_str = str(v)
                    items.append((new_key, value_str))
        return dict(items)
    
    flat_config = flatten_dict(config)
    for key, value in flat_config.items():
        # 轉義特殊字符
        safe_value = value.replace('\\\"', '\\\\\\\"').replace('\\$', '\\\\\\$')
        print(f'${prefix}{key}=\\\"{safe_value}\\\"')
        
except Exception as e:
    print(f'# YAML parsing error: {e}', file=sys.stderr)
    sys.exit(1)
"
}

# 解析配置檔案
log "正在解析配置檔案: $CONFIG_FILE"
# 使用臨時檔案避免 eval 的問題
TMP_CONFIG=$(mktemp)
parse_yaml "$CONFIG_FILE" "CONFIG_" > "$TMP_CONFIG"
source "$TMP_CONFIG"
rm -f "$TMP_CONFIG"

# 取得預設同步間隔
DEFAULT_INTERVAL=${CONFIG_global_default_sync_interval:-300}
log "預設同步間隔: $DEFAULT_INTERVAL 秒"

# 收集所有表格資訊 (使用臨時檔案替代關聯陣列)
TABLES_FILE=$(mktemp)
INTERVALS_FILE=$(mktemp)
NEXT_SYNC_FILE=$(mktemp)

# 清理函數
cleanup() {
    rm -f "$TABLES_FILE" "$INTERVALS_FILE" "$NEXT_SYNC_FILE"
}
trap cleanup EXIT

# 解析團隊和表格配置
for team in management aid_trm wsd; do
    team_enabled_var="CONFIG_teams_${team}_enabled"
    team_interval_var="CONFIG_teams_${team}_sync_interval"
    
    if [ "${!team_enabled_var}" = "true" ]; then
        team_interval=${!team_interval_var:-$DEFAULT_INTERVAL}
        log "團隊 $team 已啟用，間隔: $team_interval 秒"
        
        # 檢查該團隊的表格
        case $team in
            "management")
                tables="tp_table tcg_table icr_table"
                ;;
            "aid_trm")
                tables="aid_table trm_table"
                ;;
            "wsd")
                tables="wsd_table"
                ;;
        esac
        
        for table in $tables; do
            table_enabled_var="CONFIG_teams_${team}_tables_${table}_enabled"
            table_interval_var="CONFIG_teams_${team}_tables_${table}_sync_interval"
            
            if [ "${!table_enabled_var}" = "true" ]; then
                table_interval=${!table_interval_var:-$team_interval}
                key="${team}.${table}"
                echo "$key|$team $table" >> "$TABLES_FILE"
                echo "$key|$table_interval" >> "$INTERVALS_FILE"
                log "表格 $key 已啟用，間隔: $table_interval 秒"
            fi
        done
    fi
done

# 初始化表格的下次同步時間
current_time=$(date +%s)

while IFS='|' read -r key value; do
    [ -z "$key" ] && continue
    echo "$key|$current_time" >> "$NEXT_SYNC_FILE"
    log "表格 $key 將立即開始第一次同步"
done < "$TABLES_FILE"

# 同步單一表格的函數
sync_table() {
    local team=$1
    local table=$2
    local key="${team}.${table}"
    
    log "🔄 開始同步表格: $key"
    
    # 呼叫 Python 腳本進行同步
    cd "$SCRIPT_DIR"
    if python3 "$PYTHON_SCRIPT" sync --team "$team" --table "$table"; then
        log "✅ 表格 $key 同步成功"
        return 0
    else
        log "❌ 表格 $key 同步失敗"
        return 1
    fi
}

# 主循環
log "🚀 開始表格同步排程器"
table_count=$(wc -l < "$TABLES_FILE" 2>/dev/null || echo "0")
log "監控 $table_count 個表格"

# 設定信號處理
trap 'log "📋 收到終止信號，正在停止..."; exit 0' SIGTERM SIGINT

while true; do
    current_time=$(date +%s)
    synced_any=false
    
    # 檢查每個表格是否需要同步
    while IFS='|' read -r key table_info; do
        [ -z "$key" ] && continue
        
        # 取得下次同步時間
        next_sync=$(grep "^$key|" "$NEXT_SYNC_FILE" | cut -d'|' -f2)
        
        if [ $current_time -ge $next_sync ]; then
            # 解析團隊和表格名稱
            team=$(echo "$table_info" | cut -d' ' -f1)
            table=$(echo "$table_info" | cut -d' ' -f2)
            
            # 執行同步
            sync_table "$team" "$table"
            
            # 取得間隔時間
            interval=$(grep "^$key|" "$INTERVALS_FILE" | cut -d'|' -f2)
            new_next_sync=$((current_time + interval))
            
            # 更新下次同步時間
            sed -i.bak "s/^$key|.*/$key|$new_next_sync/" "$NEXT_SYNC_FILE"
            
            next_sync_time=$(date -r $new_next_sync '+%H:%M:%S' 2>/dev/null || date -d "@$new_next_sync" '+%H:%M:%S' 2>/dev/null || echo "未知")
            log "📅 表格 $key 下次同步時間: $next_sync_time"
            
            synced_any=true
        fi
    done < "$TABLES_FILE"
    
    # 如果有同步活動，顯示狀態
    if [ "$synced_any" = true ]; then
        log "📊 下次同步時間表:"
        while IFS='|' read -r key table_info; do
            [ -z "$key" ] && continue
            next_sync=$(grep "^$key|" "$NEXT_SYNC_FILE" | cut -d'|' -f2)
            interval=$(grep "^$key|" "$INTERVALS_FILE" | cut -d'|' -f2)
            next_time=$(date -r $next_sync '+%H:%M:%S' 2>/dev/null || date -d "@$next_sync" '+%H:%M:%S' 2>/dev/null || echo "未知")
            log "  $key: $next_time (間隔: ${interval}s)"
        done < "$TABLES_FILE"
        log "---"
    fi
    
    # 休眠 10 秒後再檢查
    sleep 10
done