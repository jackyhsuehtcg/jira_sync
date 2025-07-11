# JIRA-Lark Base 同步系統

## 📚 文檔導航

- **[👨‍💻 開發文檔](CLAUDE.md)** - 系統架構、開發指引和技術細節

---

## 概述

這是一個簡化的 JIRA 到 Lark Base 同步系統，支援批次處理和單向同步。系統採用模組化設計，易於維護和擴展。

## 系統需求

- Python 3.8 或更高版本
- 網路連線 (存取 JIRA 和 Lark Base API)

## 安裝

### 1. 安裝 Python 依賴

```bash
pip install -r requirements.txt
```

### 2. 驗證安裝

```bash
python main.py --help
```

## 核心功能

- **單向同步**: JIRA → Lark Base 方向
- **批次處理**: 使用 Lark Base API 的批次新增/更新功能，支援大量資料處理
- **多團隊支援**: 支援多個團隊的獨立配置
- **動態欄位對應**: 自動掃描 Lark 表格欄位，配置驅動的欄位對應
- **🔥 即時配置重載**: 零停機配置更新，支援檔案監控和熱重載
- **直接 JQL 配置**: 在配置檔中直接指定完整的 JQL 查詢字串
- **智慧批次分割**: 自動處理 API 限制，避免批次過大或 URL 過長問題
- **乾跑模式**: 測試同步邏輯而不實際執行

## 系統檔案結構

### 🔧 **核心系統檔案**

**主程式入口**
- `main.py` - 主程式執行檔
- `start_web.py` - Web API 啟動
- `stop_web.py` - Web API 停止

**配置檔案**
- `config.yaml` - 開發環境配置
- `config_prod.yaml` - 生產環境配置  
- `schema.yaml` - 欄位映射 Schema
- `requirements.txt` - Python 依賴清單

**核心業務邏輯**
- `sync_coordinator.py` - 同步協調器（最高層）
- `sync_workflow_manager.py` - 工作流管理器
- `sync_state_manager.py` - 狀態管理器
- `sync_batch_processor.py` - 批次處理器
- `sync_metrics_collector.py` - 指標收集器

**客戶端與處理器**
- `jira_client.py` - JIRA 客戶端
- `lark_client.py` - Lark 客戶端
- `field_processor.py` - 欄位處理器
- `user_mapper.py` - 用戶映射器

**管理與工具**
- `config_manager.py` - 配置管理器
- `user_cache_manager.py` - 用戶快取管理
- `processing_log_manager.py` - 日誌管理器
- `logger.py` - 日誌記錄器
- `schema_utils.py` - Schema 工具

**Web API**
- `web_api.py` - Web API 服務

### 🔧 **研究工具 (Study Tools)**

**study_tools/**
- `jira_ticket_fetcher.py` - 獨立 JIRA 票據取得工具
- `lark_record_analyzer.py` - Lark Base 記錄分析工具
- `parent_child_record_creator.py` - 父子記錄管理工具

**研究工具功能**:
- **完全獨立**: 不依賴主系統，可單獨使用
- **資料分析**: 用於研究和分析 JIRA 票據和 Lark 記錄
- **關係管理**: 支援 Lark Base 父子記錄的創建、更新和刪除
- **靈活輸出**: 支援 JSON 輸出和格式化顯示

### 🔧 **維護工具**

**用戶管理工具**
- `user_id_fixer.py` - 用戶 ID 補齊工具

**系統維護**
- `data_cleaner.py` - 資料清理工具
- `scheduled_cleanup.py` - 定期清理工具
- `sync_tables.sh` - 表格同步腳本

### 📁 **資料目錄**

**data/**
- `user_mapping_cache.db` - 用戶映射快取資料庫
- `sync_metrics.db` - 同步指標資料庫
- `processing_log_*.db` - 各表格處理日誌資料庫

### 🌐 **Web 介面**

**templates/**
- `index.html` - Web 管理介面模板

### 🎯 **最小運行集合**

核心必要檔案（最小化部署）：
- 主程式和配置：`main.py`, `config.yaml`, `schema.yaml`
- 同步核心：`sync_coordinator.py`, `sync_workflow_manager.py`, `sync_state_manager.py`, `sync_batch_processor.py`
- 客戶端：`jira_client.py`, `lark_client.py`, `field_processor.py`, `user_mapper.py`
- 管理器：`config_manager.py`, `user_cache_manager.py`, `processing_log_manager.py`, `logger.py`
- 工具：`schema_utils.py`, `sync_metrics_collector.py`
- 資料：`data/` 目錄及其資料庫檔案

## 快速開始

### 1. 安裝依賴

```bash
pip install requests pyyaml
```

### 2. 配置設定

編輯 `config.yaml` 檔案：

```yaml
# JIRA 設定
jira:
  server_url: "https://your-jira.com"
  username: "your-username"
  password: "your-password"

# Lark Base 設定
lark_base:
  app_id: "your-app-id"
  app_secret: "your-app-secret"

# 全域欄位對應表
field_mappings:
  ticket_fields:
    - "Ticket Number"
    - "TCG Tickets"
    - "Issue"
    - "Ticket"
  jira_to_lark:
    "summary": "Title"
    "status.name": "JIRA Status"
    "components[0].name": "Components"
    # 更多欄位對應...

# 團隊配置
teams:
  your_team:
    wiki_token: "your-wiki-token"
    tables:
      tp_table:
        enabled: true
        table_id: "your-table-id"
        table_name: "TP Project Backlog"
        jql_query_string: "project = TP AND status NOT IN (Closed) ORDER BY updated DESC"
        dry_run: false
```

### 3. 執行同步

```bash
# 同步指定團隊
python main.py sync --team your_team

# 同步指定表格
python main.py sync --team your_team --table tp_table

# 全量更新模式：更新 Lark 表格中所有現有 ticket 的值
python main.py sync --team your_team --table tp_table --full-update

# 乾跑模式測試
python main.py sync --team your_team  # 在 config.yaml 中設定 dry_run: true

# 守護程式模式
python main.py daemon

# 檢視系統狀態
python main.py status
```

## 研究工具使用

### JIRA 票據取得工具

```bash
# 獲取單一票據
python study_tools/jira_ticket_fetcher.py --ticket TCG-108387 --summary

# 獲取多個票據
python study_tools/jira_ticket_fetcher.py --ticket TCG-108387 --ticket TP-3999

# 指定特定欄位
python study_tools/jira_ticket_fetcher.py --ticket TP-3999 --fields summary,status,assignee

# 輸出到 JSON 檔案
python study_tools/jira_ticket_fetcher.py --ticket TP-3999 --output ticket_analysis.json
```

### Lark 記錄分析工具

```bash
# 分析 Lark Base 記錄
python study_tools/lark_record_analyzer.py --url "https://example.larksuite.com/wiki/xxxxx" --search "Story-ARD-00001"

# 輸出到檔案
python study_tools/lark_record_analyzer.py --url "https://example.larksuite.com/wiki/xxxxx" --output analysis.json
```

### 父子記錄管理工具

```bash
# 創建父子記錄
python study_tools/parent_child_record_creator.py --url "https://example.larksuite.com/wiki/xxxxx" \
    --create --parent-story "Story-ARD-00010" --child-story "Story-ARD-00011"

# 更新父子關係
python study_tools/parent_child_record_creator.py --url "https://example.larksuite.com/wiki/xxxxx" \
    --update --child-story "Story-ARD-00011" --new-parent-story "Story-ARD-00001"

# 刪除父記錄關係
python study_tools/parent_child_record_creator.py --url "https://example.larksuite.com/wiki/xxxxx" \
    --remove-parent --child-story "Story-ARD-00011"
```

## 動態欄位對應

系統使用配置驅動的動態欄位對應，自動掃描 Lark 表格欄位並根據配置檔進行對應：

### 欄位對應流程
1. **自動掃描**: 同步前掃描 Lark 表格的實際欄位結構
2. **票據欄位識別**: 從 `ticket_fields` 清單中自動識別票據欄位
3. **條件式對應**: 只對應表格中實際存在的欄位
4. **時間欄位轉換**: 自動將 JIRA 時間格式轉換為 Lark 時間戳

### 支援的欄位類型
- **票據欄位**: 超連結格式的 JIRA Issue Key
- **文字欄位**: Title、Status、Components 等
- **時間欄位**: Created、Updated、Due Date 等
- **自定義欄位**: 支援 JIRA 自定義欄位對應

### 配置範例
```yaml
field_mappings:
  jira_to_lark:
    "summary": "Title"                    # 標題
    "status.name": "JIRA Status"          # 狀態
    "components[0].name": "Components"    # 組件
    "created": "Created"                  # 建立時間
    "updated": "Updated Date"             # 更新時間
    "customfield_10502": "SIT Date"       # 自定義欄位
```

## 批次處理

系統採用兩階段批次處理：

1. **分類階段**: 將 JIRA Issues 分為「新增」和「更新」兩組
2. **批次執行**: 
   - 使用 `batch_create_records()` 一次新增所有新記錄
   - 使用 `batch_update_records()` 一次更新所有現有記錄

### 效能優勢
- API 呼叫次數從 N 次減少到 2 次
- 顯著減少網路延遲
- 降低 Rate Limit 風險
- 智慧批次分割：Lark Base API 自動分批（每批最多 500 記錄）
- JQL 查詢分批：避免 414 Request-URI Too Large 錯誤

## 同步模式

### 標準同步模式
- 根據 JQL 查詢條件從 JIRA 取得 Issues
- 新增不存在的記錄，更新已存在的記錄
- 適合日常增量同步

### 全量更新模式 (`--full-update`)
- 掃描 Lark 表格中所有現有的 ticket
- 動態掃描表格欄位結構
- 分批查詢 JIRA（每批 100 個 Issue Keys，避免 URL 過長）
- 使用動態欄位對應更新所有記錄
- 適合初次同步或需要刷新所有資料時使用
- 使用範例：`python main.py sync --team ard --table tp_table --full-update`

## JQL 查詢配置

系統使用簡化的直接配置方式，在表格配置中直接指定完整的 JQL 查詢字串：

### 配置方式

```yaml
tables:
  tp_table:
    jql_query_string: "project = TP AND status NOT IN (Closed) AND component IN (CRM, \"CRD CRM\") ORDER BY updated DESC"
  tcg_table:
    jql_query_string: "project = TCG AND updated >= -30d ORDER BY created DESC"
```

### 特點
- **直接配置**: JQL 查詢字串完全由用戶在配置檔中指定
- **無動態生成**: 系統不再提供條件組合功能，完全依賴配置的 JQL
- **靈活性**: 支援任意複雜的 JQL 語法和自定義邏輯
- **可維護性**: 每個表格獨立的查詢條件，便於個別調整
- **批次處理**: 系統在 full-update 模式下自動分批避免 URL 長度限制

### JQL 範例

```jql
# 基本專案過濾
"project = TP ORDER BY updated DESC"

# 狀態和組件過濾
"project = TP AND status NOT IN (Closed) AND component IN (CRM, \"CRD CRM\")"

# 時間範圍過濾
"project = TCG AND updated >= -30d ORDER BY created DESC"

# 複雜條件組合
"project = TP AND issuetype in standardIssueTypes() AND status in (Open, \"In Progress\", Reopened) AND component in (CRM, Payment, TAC)"
```

**注意**: 系統已移除自動 JQL 條件組合功能，所有查詢邏輯需要在 `jql_query_string` 中完整指定。

## 命令列介面

```bash
python main.py <command> [options]

Commands:
  sync      執行同步操作
  daemon    守護程式模式
  status    顯示系統狀態
  issue     同步單一 Issue

Options:
  --team TEAM      指定團隊名稱
  --table TABLE    指定表格名稱
  --config CONFIG  指定配置檔案路徑
```

## 日誌系統

系統提供詳細的日誌記錄：

- **同步開始/完成**: 記錄同步操作的狀態
- **批次處理**: 記錄批次新增/更新的數量
- **錯誤處理**: 詳細的錯誤資訊和堆疊追蹤
- **乾跑模式**: 顯示會執行的操作而不實際執行

## 錯誤處理

- **連接失敗**: 自動重試 JIRA 和 Lark Base 連接
- **API 錯誤**: 記錄詳細錯誤資訊並繼續處理其他記錄
- **欄位對應錯誤**: 跳過有問題的記錄並記錄警告

## 注意事項

1. **單向同步**: 僅支援 JIRA → Lark Base 方向，Lark Base 的修改會被覆蓋
2. **動態欄位**: 支援所有在 config.yaml 中定義的欄位對應
3. **API 限制**: 
   - Lark Base 批次操作限制 500 記錄（系統自動處理）
   - JIRA JQL 查詢 URL 長度限制（full-update 模式自動分批）
4. **權限要求**: 確保 Lark Base 應用程式有足夠的權限操作目標表格
5. **⚠️ 重要：票據欄位必須是超連結欄位**: 
   - 票據欄位名稱必須在 `field_mappings.ticket_fields` 清單中
   - 欄位類型必須是超連結 (type 15)，不能是文字欄位
   - 系統會自動識別第一個符合條件的票據欄位
   - 如果票據欄位不是超連結類型，同步時會出現 TextFieldConvFail 錯誤

## 故障排除

### 常見問題

1. **找不到表格**: 檢查 `wiki_token` 和 `table_id` 是否正確
2. **無法識別票據欄位**: 確認票據欄位名稱在 `ticket_fields` 清單中，且為超連結類型
3. **認證失敗**: 檢查 JIRA 和 Lark Base 的認證資訊
4. **JQL 錯誤**: 驗證 `jql_query_string` 語法是否正確
5. **TextFieldConvFail 錯誤**: 票據欄位不是超連結欄位，需要修改欄位類型
6. **批次處理錯誤**: 檢查是否超過 API 限制，系統會自動分批處理
7. **欄位對應失敗**: 確認 `field_mappings.jira_to_lark` 中的對應關係正確

### 除錯模式

設定日誌級別為 DEBUG：

```yaml
global:
  log_level: "DEBUG"
```

## 授權

此專案僅供內部使用。