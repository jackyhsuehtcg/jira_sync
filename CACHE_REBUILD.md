# 快取重建功能說明

## 概述

新增的快取重建功能可以將 Lark Base 表格中的現有記錄同步到系統快取中。這個功能解決了當 Lark 表格中已有數據，但系統快取為空時的同步問題。

## 功能特點

- **反向同步**: 從 Lark 表格讀取現有記錄並更新到快取
- **多層級支持**: 支援單一表格、團隊或全系統快取重建
- **自動票據識別**: 自動從表格記錄中提取票據號碼並建立映射
- **批次處理**: 高效率的批次快取更新
- **Web API 支援**: 提供 REST API 介面

## 使用方式

### 命令行介面

```bash
# 重建所有團隊的快取
python main.py cache --rebuild

# 重建指定團隊的快取
python main.py cache --rebuild --team management

# 重建指定表格的快取
python main.py cache --rebuild --team management --table tp_table
```

### Web API 介面

```bash
# 重建所有快取
curl -X POST http://localhost:5000/api/cache/rebuild

# 重建團隊快取
curl -X POST http://localhost:5000/api/cache/rebuild/management

# 重建表格快取
curl -X POST http://localhost:5000/api/cache/rebuild/management/tp_table

# 使用 JSON 參數
curl -X POST http://localhost:5000/api/cache/rebuild \
  -H "Content-Type: application/json" \
  -d '{"team_name": "management", "table_name": "tp_table"}'
```

## 工作原理

1. **掃描 Lark 表格**: 獲取表格中所有現有記錄
2. **提取票據號碼**: 從配置的票據欄位中提取 Issue Key
3. **建立映射關係**: 建立票據號碼到記錄 ID 的映射
4. **批次寫入快取**: 將映射關係批次寫入 processing log 資料庫
5. **初始化時間戳**: 設定初始時間戳為 0，確保下次同步會更新

## 快取結構

快取數據存儲在 SQLite 資料庫中：

- **位置**: `data/processing_log_{table_id}.db`
- **表格**: `processing_logs`
- **主要欄位**:
  - `issue_key`: JIRA Issue Key
  - `lark_record_id`: Lark Base 記錄 ID
  - `jira_updated_time`: JIRA 更新時間戳（重建時設為 0）
  - `processing_result`: 處理結果（重建時標記為 'cold_start_existing'）

## 使用場景

### 1. 初次部署

當系統首次部署且 Lark 表格中已有歷史數據時：

```bash
# 重建所有快取
python main.py cache --rebuild

# 然後執行正常同步
python main.py sync
```

### 2. 快取損壞修復

當快取資料庫損壞或遺失時：

```bash
# 重建指定表格快取
python main.py cache --rebuild --team your_team --table your_table
```

### 3. 新增表格

當配置新的表格且該表格已有數據時：

```bash
# 重建新表格的快取
python main.py cache --rebuild --team your_team --table new_table
```

## 注意事項

1. **票據欄位要求**: 確保表格中的票據欄位包含有效的 JIRA Issue Key
2. **權限檢查**: 確保系統有讀取 Lark 表格的權限
3. **時間消耗**: 大型表格的快取重建可能需要較長時間
4. **資料一致性**: 重建過程中避免同時執行其他同步操作

## 錯誤處理

- **表格不存在**: 檢查團隊和表格配置
- **權限不足**: 檢查 Lark Base 應用權限
- **票據欄位無效**: 檢查票據欄位配置和數據格式
- **網路連線問題**: 檢查網路連線和 API 配額

## API 回應格式

### 成功回應

```json
{
  "status": "success",
  "message": "快取重建完成",
  "duration": 12.34,
  "output": "重建詳細信息..."
}
```

### 失敗回應

```json
{
  "status": "error",
  "message": "快取重建失敗: 錯誤原因",
  "duration": 5.67
}
```

## 整合建議

1. **定期檢查**: 建議定期檢查快取狀態，必要時重建
2. **監控日誌**: 關注重建過程的日誌輸出
3. **分批處理**: 對於大型系統，考慮分批重建快取
4. **備份策略**: 重建前備份現有快取資料庫

這個功能為系統提供了更強的靈活性和復原能力，特別是在處理已有歷史數據的場景時。