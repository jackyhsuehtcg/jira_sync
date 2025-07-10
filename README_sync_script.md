# 表格同步 Shell Script 使用說明

## 概述
`sync_tables.sh` 是一個自動表格同步腳本，它會讀取 `config.yaml` 中的配置，並根據各表格的同步間隔自動執行同步操作。

## 功能特點
- 📋 **自動讀取配置**：從 `config.yaml` 讀取團隊和表格配置
- ⏰ **智能排程**：根據各表格的 `sync_interval` 設定自動排程
- 📝 **詳細日誌**：記錄所有同步活動到 `sync_tables.log`
- 🔄 **持續運行**：非 daemon 模式，可在前台運行並觀察
- 🛑 **優雅停止**：支援 Ctrl+C 和 SIGTERM 信號

## 使用方法

### 1. 確保腳本有執行權限
```bash
chmod +x sync_tables.sh
```

### 2. 直接運行
```bash
./sync_tables.sh
```

### 3. 背景運行
```bash
./sync_tables.sh &
```

### 4. 使用 nohup 運行（即使終端關閉也會繼續）
```bash
nohup ./sync_tables.sh > sync_output.log 2>&1 &
```

## 配置說明

腳本會自動讀取 `config.yaml` 中的以下配置：

### 全域設定
```yaml
global:
  default_sync_interval: 180  # 預設同步間隔（秒）
```

### 團隊設定
```yaml
teams:
  management:
    enabled: true
    sync_interval: 600  # 團隊級同步間隔
    tables:
      tp_table:
        enabled: true
        sync_interval: 600  # 表格級同步間隔（會覆蓋團隊級設定）
```

## 同步間隔優先級
1. **表格級 sync_interval**（最高優先級）
2. **團隊級 sync_interval**
3. **全域 default_sync_interval**（最低優先級）

## 日誌檔案
- **主日誌**：`sync_tables.log` - 腳本運行日誌
- **同步日誌**：`jira_lark_sync.log` - Python 程式的詳細同步日誌

## 輸出範例
```
[2025-07-10 17:00:00] 🚀 開始表格同步排程器
[2025-07-10 17:00:00] 監控 6 個表格
[2025-07-10 17:00:00] 🔄 開始同步表格: management.tp_table
[2025-07-10 17:00:15] ✅ 表格 management.tp_table 同步成功
[2025-07-10 17:00:15] 📅 表格 management.tp_table 下次同步時間: 17:10:15
[2025-07-10 17:00:15] 📊 下次同步時間表:
[2025-07-10 17:00:15]   management.tp_table: 17:10:15 (間隔: 600s)
[2025-07-10 17:00:15]   management.tcg_table: 17:00:00 (間隔: 600s)
[2025-07-10 17:00:15]   management.icr_table: 17:00:00 (間隔: 600s)
[2025-07-10 17:00:15]   aid_trm.aid_table: 17:00:00 (間隔: 180s)
[2025-07-10 17:00:15]   aid_trm.trm_table: 17:00:00 (間隔: 180s)
[2025-07-10 17:00:15]   wsd.wsd_table: 17:00:00 (間隔: 180s)
```

## 停止腳本
- **前台運行**：按 `Ctrl+C`
- **背景運行**：使用 `kill` 命令或 `killall sync_tables.sh`

## 故障排除

### 1. 權限問題
```bash
chmod +x sync_tables.sh
```

### 2. Python 環境問題
確保 Python 3 已安裝，且 `main.py` 可正常執行：
```bash
python3 main.py sync --team management --table tp_table
```

### 3. 配置檔案問題
檢查 `config.yaml` 是否存在且格式正確：
```bash
python3 -c "import yaml; yaml.safe_load(open('config.yaml'))"
```

### 4. 檢查日誌
```bash
tail -f sync_tables.log
tail -f jira_lark_sync.log
```

## 優點
- ✅ **輕量級**：不依賴額外的排程系統
- ✅ **可觀測**：實時輸出和詳細日誌
- ✅ **靈活性**：可輕易修改和客製化
- ✅ **可控性**：可隨時停止和重啟
- ✅ **與現有系統整合**：使用現有的 Python 同步程式