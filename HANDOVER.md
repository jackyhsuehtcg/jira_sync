# JIRA-Lark Base 同步系統交接文件

## 系統概述

這是一個高效的 JIRA 到 Lark Base 同步系統，採用現代化的批次處理架構。系統具備即時配置重載、Web 管理介面、全量更新模式等功能。

## 🎯 核心設計原則

### 資料完整性優先原則
**「資料的唯一跟正確性是絕對需要優先考慮的原則，再來才是效能」**

1. **多層去重保護機制**
   - JIRA API 層：去重查詢結果，保留最新記錄
   - 處理邏輯層：標準同步和 Full Update 模式都有去重檢查
   - TableCache 層：載入時自動檢測重複記錄，保留最新的

2. **原子操作與事務安全**
   - 所有文件操作使用臨時文件 + 原子 `os.replace()` 模式
   - 批次處理確保要麼全部成功，要麼全部失敗
   - 多重重試機制與指數退避策略

3. **資料一致性驗證**
   - 強制票據欄位必須是超連結類型
   - 動態欄位掃描，只對應表格中實際存在的欄位
   - Issue Key 唯一性檢查與詳細警告機制

## 系統架構

### 核心組件
```
main.py                    # CLI 入口，命令路由
sync_engine.py             # 同步核心，批次處理邏輯
field_mapper.py            # 動態欄位對應，配置驅動映射
config_manager.py          # 配置管理，JQL 生成
jira_client.py             # JIRA API 客戶端
lark_client.py             # Lark Base API 客戶端
table_cache.py             # 表格快取管理
logger.py                  # 統一日誌系統
config.yaml                # 系統配置檔
templates/index.html       # Web 管理介面
```

### 配置結構
```yaml
global:
  poll_interval: 180
  log_level: "WARNING"
  log_file: "jira_lark_sync.log"

jira:
  server_url: "https://jira.tc-gaming.co/jira"
  username: "jacky.h"
  password: "Abcd1234"

lark_base:
  app_id: "cli_a8d1077685be102f"
  app_secret: "kS35CmIAjP5tVib1LpPIqUkUJjuj3pIt"

field_mappings:
  ticket_fields:
    - "Ticket Number"
    - "TCG Tickets"
    - "Issue"
    - "Ticket"
  jira_to_lark:
    "summary": "Title"
    "status.name": "JIRA Status"
    "assignee": "Assignee"
    # ... 更多欄位對應

teams:
  ard:
    display_name: "ARD"
    wiki_token: "MKdDwAgbwiVbzDkSkTHl3D8Hg0e"
    tables:
      ard_table:
        table_id: "tbl8qFv3feIwFmtM"
        jql_query_string: "status in (Open, \"In Progress\", Resolved, Closed) AND component in (\"WSD. WL Core\", \"WSD. WL Solution\") AND updated > -100d"
```

## 核心功能

### 1. 同步模式
- **標準同步**: 基於 JQL 查詢的增量同步
- **全量更新**: 更新所有現有記錄的完整資料
- **單一票據同步**: 針對特定 Issue 的即時同步

### 2. 批次處理
- 自動分組新增/更新操作
- 避免 API 限制（500 記錄/批次）
- 智慧錯誤處理與重試機制

### 3. 動態欄位對應
- 自動掃描 Lark 表格欄位結構
- 配置驅動的欄位映射
- 支援嵌套欄位和複雜資料類型

### 4. 即時配置重載
- 零停機配置檔案更新
- 檔案監控與自動重載
- 組件熱重新初始化

### 5. Web 管理介面
- Gmail 風格的操作介面
- 即時同步控制
- 三層級全量更新支援

## 常用命令

### 基本同步
```bash
# 同步特定團隊
python main.py sync --team ard

# 同步特定表格
python main.py sync --team ard --table ard_table

# 全量更新模式
python main.py sync --team ard --table ard_table --full-update

# 守護程式模式
python main.py daemon

# 單一票據同步
python main.py issue ard ard_table TP-3153
```

### 資料清理
```bash
# 清理舊資料
python data_cleaner.py --team ard --table ard_table --jql "status = Closed AND updated < -30d"

# 重複記錄清理
python data_cleaner.py --team ard --table ard_table --detect-duplicates --duplicate-strategy keep-latest
```

### 狀態檢查
```bash
# 檢視同步狀態
python main.py status

# 測試連線
python -c "from jira_client import JiraClient; from config_manager import ConfigManager; cm = ConfigManager(None, 'config.yaml'); jc = JiraClient(None, cm.get_jira_config()); print(jc.test_connection())"
```

## 重要技術細節

### 1. 票據欄位要求
- 必須是超連結欄位類型（type 15）
- 欄位名稱必須在 `ticket_fields` 清單中
- 格式：`{"link": "https://jira.tc-gaming.co/jira/browse/TP-3153", "text": "TP-3153"}`

### 2. 去重機制
- JIRA 查詢結果去重（保留最新 updated 記錄）
- Lark 表格載入時重複檢測
- 批次處理前的存在性檢查

### 3. 錯誤處理
- 指數退避重試策略
- 降級策略（API 失敗時的備選方案）
- 詳細日誌記錄與錯誤統計

### 4. 效能優化
- 批次 API 操作（減少 95% API 呼叫）
- 表格快取機制
- 智慧批次分割

## 故障排除

### 常見問題

1. **TextFieldConvFail 錯誤**
   - 原因：嘗試將超連結資料寫入文字欄位
   - 解決：確保票據欄位是超連結類型

2. **重複記錄**
   - 原因：快取過期或並行操作
   - 解決：使用 `data_cleaner.py` 清理重複記錄

3. **API 限制錯誤**
   - 原因：批次大小超過 500 記錄
   - 解決：系統自動分批處理

4. **JQL 查詢失敗**
   - 原因：查詢條件語法錯誤
   - 解決：檢查 config.yaml 中的 `jql_query_string`

### 除錯命令
```bash
# 啟用詳細日誌
# 在 config.yaml 中設定 log_level: "DEBUG"

# 檢視即時日誌
tail -f jira_lark_sync.log

# 檢查表格欄位結構
python -c "from lark_client import LarkBaseClient; # ... 檢查欄位代碼"

# 測試特定功能
python config_manager.py
python field_mapper.py
python jira_client.py
```

## 部署與維護

### 環境要求
- Python 3.7+
- 依賴套件：見 requirements.txt
- 網路存取：JIRA 伺服器和 Lark API

### 部署步驟
1. 複製程式碼到目標環境
2. 安裝依賴：`pip install -r requirements.txt`
3. 配置 config.yaml
4. 測試連線：`python main.py status`
5. 啟動服務：`python main.py daemon`

### 維護建議
- 定期清理舊日誌檔案
- 監控重複記錄情況
- 定期備份用戶映射快取
- 檢查 API 憑證有效性

## 安全考量

- 配置檔中敏感資訊的保護
- API 呼叫使用 SSL/TLS 加密
- 建議使用 JIRA API Token 而非密碼
- 日誌檔案存取權限控制

## 擴展指南

### 添加新團隊
1. 在 config.yaml 中添加團隊配置
2. 設定 wiki_token 和表格配置
3. 配置 JQL 查詢條件
4. 測試同步功能

### 添加新欄位
1. 在 `field_mappings.jira_to_lark` 中添加對應
2. 確保 Lark 表格中存在目標欄位
3. 測試欄位對應功能

### 自定義處理邏輯
1. 在 `field_mappings.field_processing_rules` 中定義規則
2. 在 field_mapper.py 中實現處理器
3. 測試新的處理邏輯

## 已知限制

1. **單向同步**：僅支援 JIRA → Lark Base 方向
2. **批次限制**：Lark Base API 單次最多 500 記錄
3. **欄位類型限制**：票據欄位必須是超連結類型
4. **並行限制**：建議同一時間只執行一個同步程序

## 未來改進建議

1. **雙向同步**：支援 Lark Base → JIRA 的資料回寫
2. **增量同步優化**：基於時間戳的更精確增量同步
3. **監控儀表板**：實時監控同步狀態和效能指標
4. **自動化部署**：Docker 容器化和 CI/CD 管道

## 聯絡資訊

- 系統維護：技術團隊
- 配置變更：需要技術團隊審核
- 緊急問題：立即聯繫技術支援

---

**最後更新時間：2025-07-08**  
**版本：v2.0**  
**維護者：ARD 技術團隊**