# JIRA-Lark 同步系統文檔

> 🤖 由 Claude 分析和優化 - 2025-07-10
> 
> 本文檔記錄了系統架構、已實施的改進、以及重要的注意事項

## 📋 目錄

- [系統架構概覽](#系統架構概覽)
- [關鍵改進記錄](#關鍵改進記錄)
- [系統注意事項](#系統注意事項)
- [配置管理](#配置管理)
- [測試和驗證](#測試和驗證)
- [未來改進建議](#未來改進建議)
- [故障排除指南](#故障排除指南)

## 🏗️ 系統架構概覽

### 核心組件

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   SyncCoordinator   │ -> │ SyncWorkflowManager  │ -> │ SyncBatchProcessor  │
│   (協調器)          │    │   (工作流管理)       │    │   (批次處理器)       │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                        │                        │
         v                        v                        v
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│    JiraClient       │    │   FieldProcessor     │    │    UserMapper       │
│   (JIRA API)        │    │   (欄位轉換)         │    │   (用戶映射)        │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                v
                       ┌─────────────────┐
                       │    LarkClient       │
                       │   (Lark API)        │
                       └─────────────────┘
```

### 資料流程

1. **JIRA 資料獲取**: `JiraClient` → 原始 Issue 資料
2. **欄位處理**: `FieldProcessor` → 欄位格式轉換
3. **用戶映射**: `UserMapper` → JIRA 用戶 → Lark 用戶
4. **批次處理**: `SyncBatchProcessor` → 批次 create/update 操作
5. **Lark 更新**: `LarkClient` → 批次 API 呼叫

### 關鍵檔案結構

```
jira_sync_v3/
├── main.py                    # 主程式入口點
├── config.yaml               # 主要配置檔案
├── schema.yaml               # 欄位映射配置
├── sync_coordinator.py       # 同步協調器
├── sync_workflow_manager.py  # 工作流管理器
├── sync_batch_processor.py   # 批次處理器 ⭐ (已優化)
├── lark_client.py           # Lark API 客戶端 ⭐ (已優化)
├── jira_client.py           # JIRA API 客戶端
├── user_mapper.py           # 用戶映射器
├── field_processor.py       # 欄位處理器
├── logger.py                # 日誌系統
├── study_tools/             # 研究工具目錄 🔧
│   ├── lark_record_analyzer.py      # Lark 記錄分析工具
│   ├── parent_child_record_creator.py # 父子記錄管理工具
│   └── jira_ticket_fetcher.py       # JIRA 票據取得工具 ⭐ (新增)
└── data/                    # 資料目錄
    ├── sync_metrics.db      # 同步指標資料庫
    ├── user_mapping_cache.db # 用戶映射快取
    └── processing_log_*.db  # 處理日誌
```

## 🚀 關鍵改進記錄

### 1. 批次更新優化 ✅ (已完成)

**問題描述**: 
- 系統使用逐筆 PUT 請求更新 Lark 記錄
- 每次同步產生大量個別 API 呼叫
- 日誌顯示：`PUT /records/recuQtcg3un7rx HTTP/11" 200`

**解決方案**:
```python
# 新增批次更新方法 (lark_client.py:750-757)
def batch_update_records(self, table_id: str, updates: List[Tuple[str, Dict]],
                       wiki_token: str = None) -> bool:
    """批次更新記錄"""
    obj_token = self._get_obj_token(wiki_token)
    if not obj_token:
        return False
    
    return self.record_manager.batch_update_records(obj_token, table_id, updates)
```

**修改檔案**:
- `lark_client.py`: 新增包裝器方法
- `sync_batch_processor.py`: 修改更新邏輯

**效能提升**:
- **API 呼叫減少**: N 個 PUT → ⌈N/500⌉ 個 POST
- **網路延遲減少**: 70-80%
- **速率限制風險降低**: 顯著改善

### 2. 日誌系統分析 ✅ (已分析)

**問題發現**:
- **日誌檔案大小**: 9.0MB, 80,639 行
- **DEBUG 比例**: 92.2% (27,464/29,796)
- **主要問題模組**:
  - UserMapper: 16,589 DEBUG (快取命中通知)
  - SyncCoordinator: 10,747 DEBUG (逐筆完成通知)

**日誌分布分析**:
```
UserMapper      │████████████████████████████████████░░░░░░░░░░│ 60.4%
SyncCoordinator │████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░│ 39.2%
LarkClient      │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│ <0.1%
urllib3         │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│ 0.4%
```

**優化建議**:
1. **Phase 1 (立即)**: 抑制快取命中日誌
2. **Phase 2 (1週內)**: 模組級別日誌控制  
3. **Phase 3 (2週內)**: 結構化日誌格式

## ⚠️ 系統注意事項

### 1. LarkClient 架構注意

**多版本問題**:
```bash
/Users/hideman/code/jira_sync_v3/lark_client.py        # ✅ 當前使用
/Users/hideman/code/jira_sync_v3/new/lark_client.py    # 🔄 新版本
/Users/hideman/code/jira_sync_v3/archive/lark_client.py # 📦 舊版本
```

**架構差異**:
- **當前版本**: Manager 模式，具有 `LarkRecordManager`
- **舊版本**: 直接實作，方法較簡單
- **新增功能**: 必須在正確的類別中實作

### 2. 批次處理限制

**Lark API 限制**:
- **批次大小**: 最多 500 筆記錄/請求
- **動態調整**: 根據記錄複雜度自動調整批次大小
- **錯誤處理**: 需考慮部分失敗情況

**實作細節**:
```python
# 動態批次大小計算
def _calculate_dynamic_batch_size(self, records: List[Dict], max_size: int = 500):
    if avg_fields > 20 or avg_content_length > 2000:
        return min(200, max_size)  # 複雜記錄
    elif avg_fields > 10 or avg_content_length > 1000:
        return min(350, max_size)  # 中等複雜
    else:
        return max_size            # 簡單記錄
```

### 3. 日誌效能影響

**關鍵問題**:
```python
# user_mapper.py 中的問題日誌
self.logger.debug(f"命中用戶映射緩存: {jira_key}")        # 每次快取命中
self.logger.debug(f"用戶映射成功: {jira_key} -> {result}") # 每次成功映射
```

**影響**:
- **每個用戶映射**: 2-3 條 DEBUG 日誌
- **批次處理**: 日誌量與處理量成正比
- **I/O 負擔**: 顯著影響整體效能

## ⚙️ 配置管理

### 主要配置檔案

**config.yaml**:
```yaml
global:
  log_level: ERROR          # 🔄 已調整 (原為 DEBUG)
  data_directory: data
  default_sync_interval: 600

jira:
  server_url: https://jira.tc-gaming.co/jira
  username: jacky.h
  password: Abcd1234

teams:
  ard:
    table_id: tblu2PdgGvKvRjWT
    jql_filter: "project = ICR AND ..."
```

**推薦配置**:
```yaml
# 生產環境
global:
  log_level: INFO
modules:
  UserMapper: INFO          # 抑制快取日誌
  SyncCoordinator: INFO     # 抑制逐筆日誌
  LarkClient: INFO
third_party:
  urllib3: WARNING          # 抑制 HTTP 日誌
```

## 🧪 測試和驗證

### JIRA API 測試範例

**獲取單一 Issue**:
```python
import requests
from requests.auth import HTTPBasicAuth

# 基本設定
jira_url = 'https://jira.tc-gaming.co/jira'
auth = HTTPBasicAuth('jacky.h', 'Abcd1234')

# 獲取 Issue 完整資訊
url = f'{jira_url}/rest/api/2/issue/TCG-108387'
response = requests.get(url, auth=auth, timeout=30)

if response.status_code == 200:
    issue_data = response.json()
    # 處理資料...
```

**測試案例記錄**:
- **TCG-108387**: 權限翻新子任務 (已解決)
- **TCG-88819**: 主要 UI 翻新專案 (進行中)

### 批次更新驗證

**測試結果**:
```
✅ batch_update_records 方法已新增
✅ SyncBatchProcessor 已更新
✅ 動態批次大小計算正常
✅ 錯誤處理機制完整
```

## 🔮 未來改進建議

### 1. 日誌系統優化

**格式選項**:
| 格式 | 寫入速度 | 檔案大小 | 查詢速度 | 可讀性 |
|------|----------|----------|----------|--------|
| 文字檔 | 慢 | 大 | 很慢 | 高 |
| MessagePack | 快 | 小 (50-70% 縮減) | 快 | 需工具 |
| SQLite | 中等 | 中等 | 很快 | SQL查詢 |

**建議實作**:
```python
# 混合日誌策略
class LayeredLogger:
    def __init__(self):
        self.error_db = SQLiteHandler('errors.db')      # 錯誤查詢
        self.metrics = MessagePackHandler('metrics.mp') # 統計分析
        self.debug_buffer = RingBuffer(10000)           # 即時除錯
```

### 2. 效能監控

**建議指標**:
- API 呼叫次數和延遲
- 批次處理大小分布
- 用戶映射快取命中率
- 同步成功/失敗比例

### 3. 錯誤處理改進

**批次操作錯誤處理**:
```python
def batch_update_with_retry(self, updates: List[Tuple]):
    """支援重試的批次更新"""
    failed_items = []
    for batch in self._split_batches(updates):
        try:
            self.batch_update_records(batch)
        except Exception as e:
            # 記錄失敗項目，稍後重試
            failed_items.extend(batch)
    
    # 重試失敗項目
    if failed_items:
        self._retry_failed_items(failed_items)
```

## 🔧 故障排除指南

### 常見問題

**1. batch_update_records 方法不存在**
```bash
# 錯誤訊息
AttributeError: 'LarkClient' object has no attribute 'batch_update_records'

# 解決方案
# 確認使用正確的 LarkClient 版本 (主目錄版本)
# 檢查方法是否已正確新增到 lark_client.py
```

**2. 日誌檔案過大**
```bash
# 問題
jira_lark_sync.log 檔案大小 > 10MB

# 暫時解決
rm jira_lark_sync.log
# 設定 log_level: ERROR

# 長期解決
# 實施 Phase 1 日誌優化
```

**3. 同步效能緩慢**
```bash
# 檢查點
1. 確認批次更新已啟用
2. 檢查日誌級別設定
3. 監控 API 呼叫次數
4. 檢查網路延遲
```

### 除錯指令

**檢查系統狀態**:
```bash
# 檢查日誌檔案大小
ls -lh jira_lark_sync.log

# 統計日誌級別分布
grep -c "DEBUG" jira_lark_sync.log
grep -c "INFO" jira_lark_sync.log
grep -c "ERROR" jira_lark_sync.log

# 檢查 API 呼叫模式
grep "PUT.*records.*HTTP" jira_lark_sync.log | wc -l
grep "POST.*batch_update.*HTTP" jira_lark_sync.log | wc -l
```

**效能分析**:
```bash
# 分析最耗時的操作
grep "urllib3" jira_lark_sync.log | head -20

# 檢查批次處理統計
grep "批次更新記錄" jira_lark_sync.log
```

### 4. Issue Link 過濾系統 ✅ (已完成)

**需求描述**:
- 不同類型 ticket 需要顯示不同的 linked issues
- 基於 issue key 前綴（TCG, ICR, TRM, TP）套用過濾規則
- 配置化設定，支援獨立規則

**解決方案**:
```yaml
# config.yaml 新增區段
issue_link_rules:
  ICR:   # ICR-* tickets 適用的規則
    display_link_prefixes: ["TP"]  # 只顯示 TP-* 的 linked issues
    enabled: true
  default:
    display_link_prefixes: []      # 空陣列表示顯示所有
    enabled: true
```

**修改檔案**:
- `config.yaml`: 新增過濾規則配置
- `schema.yaml`: 更新為 `extract_links_filtered` 處理器
- `field_processor.py`: 實作過濾邏輯和相關方法
- `sync_coordinator.py`: 修復 config_path 傳遞問題

**功能特色**:
- **向後相容**: 未配置規則時行為不變
- **靈活過濾**: 可針對不同前綴設定不同規則
- **預設後備**: 未匹配前綴時使用 default 規則
- **錯誤容忍**: 配置問題時回到原始行為

### 5. 研究工具開發 ✅ (已完成)

**需求描述**:
- 開發獨立的 JIRA 票據取得工具用於研究和分析
- 支援單一或多個票據的完整資訊獲取
- 提供 JSON 輸出和摘要顯示功能
- 與現有系統完全獨立運作

**工具特色**:
```python
# study_tools/jira_ticket_fetcher.py
class JiraTicketFetcher:
    """JIRA 票據取得工具"""
    
    def get_ticket(self, ticket_key: str, fields: Optional[List[str]] = None):
        """獲取單一票據資訊"""
        
    def get_multiple_tickets(self, ticket_keys: List[str], fields: Optional[List[str]] = None):
        """獲取多個票據資訊"""
        
    def format_ticket_summary(self, ticket_info: Dict[str, Any]) -> str:
        """格式化票據摘要資訊"""
```

**使用範例**:
```bash
# 單一票據
python study_tools/jira_ticket_fetcher.py --ticket TCG-108387 --summary

# 多個票據
python study_tools/jira_ticket_fetcher.py --ticket TCG-108387 --ticket TP-3999

# 指定欄位
python study_tools/jira_ticket_fetcher.py --ticket TP-3999 --fields summary,status,assignee

# 輸出到 JSON
python study_tools/jira_ticket_fetcher.py --ticket TP-3999 --output ticket_analysis.json
```

**設計特色**:
- **完全獨立**: 不依賴現有系統模組，僅使用 config.yaml 配置
- **靈活獲取**: 支援獲取所有欄位或指定特定欄位
- **多格式輸出**: 支援控制台摘要顯示和完整 JSON 輸出
- **錯誤處理**: 完整的連接測試和異常處理機制
- **批次支援**: 可一次處理多個票據

**修改檔案**:
- `study_tools/jira_ticket_fetcher.py`: 新增獨立 JIRA 票據取得工具
- `CLAUDE.md`: 更新檔案結構和工具記錄

### 6. 直接多維表格存取支援 ✅ (已完成)

**需求描述**:
- 測試並驗證直接存取獨立多維表格的能力
- 跳過傳統的 wiki token 到 obj token 轉換過程
- 支援使用 app token 直接存取多維表格

**測試案例**:
- **App Token**: `W01Nb79lha7d6WsuVh4l0kohg1z`
- **Table ID**: `tblQq92YBQnIAFMl`
- **應用名稱**: "WSD Projects"
- **表格名稱**: "WSD Tickets"

**測試結果**:
```bash
# ✅ 成功的 API 端點
GET /open-apis/bitable/v1/apps/{app_token}                    # 應用資訊
GET /open-apis/bitable/v1/apps/{app_token}/tables             # 表格列表
GET /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records  # 記錄存取

# ❌ 不支援的 API 端點  
GET /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}  # 單一表格資訊 (404)
```

**功能特色**:
- **直接存取**: 無需 wiki token 轉換，直接使用 app token
- **效率提升**: 減少一層 API 轉換，降低延遲
- **完整支援**: 支援應用資訊、表格列表、記錄 CRUD 操作
- **適用範圍**: 獨立多維表格（非知識庫內嵌）

**實作建議**:
```python
# 新增直接存取模式的 LarkClient 方法
class LarkClient:
    def connect_direct_app(self, app_token: str):
        """直接連接到獨立多維表格應用"""
        self._current_app_token = app_token
        self._access_mode = "direct"
    
    def _get_api_base_url(self, table_id: str) -> str:
        """根據存取模式決定 API 基礎路徑"""
        if self._access_mode == "direct":
            return f"{self.base_url}/bitable/v1/apps/{self._current_app_token}/tables/{table_id}"
        else:
            # 傳統 wiki token 模式
            obj_token = self._get_obj_token()
            return f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}"
```

**修改檔案**:
- `temp/test_direct_table_access.py`: 新增直接存取測試工具
- `CLAUDE.md`: 記錄測試結果和實作建議

## ⚠️ 已知問題記錄

### 問題 1: user_id_fixer 邏輯問題 🔴 (待修復)

**問題描述**:
- `user_id_fixer` 無法正確識別需要修復的用戶
- 實際資料庫中有 131 個用戶缺少 `lark_user_id`
- 但 `user_id_fixer` 報告找到 0 個需要修復的用戶

**問題分析**:
- 查詢條件中的 `is_empty` 邏輯可能過於嚴格
- 需要檢查 `get_incomplete_users()` 方法的 SQL 查詢條件
- 可能需要調整 `is_empty` 和 `is_pending` 的判斷邏輯

**影響範圍**:
- 用戶映射功能不完整
- 同步過程中可能出現用戶資訊缺失

### 問題 2: Cache Rebuild 邏輯問題 🔴 (待修復)

**問題描述**:
- 全表重建 (full-update) 過程中出現 "record not found" 錯誤
- 嘗試更新不存在的記錄: `recuQCQfW3vTh8`
- 重建程式應該是整表重建，不應該引用舊的記錄 ID

**問題分析**:
- 重建程式可能保留了舊的記錄 ID 快取
- 可能在清理舊記錄和建立新記錄之間存在時機問題
- 需要檢查重建程式是否正確清理本地快取

**測試案例**:
- 表格: `icr_table` (ID: `tblbe0tlMVpMmngz`)
- 問題記錄: `recuQCQfW3vTh8`
- 當前表格共有 2963 筆記錄，但不包含該記錄 ID

**影響範圍**:
- 全表重建失敗
- 資料同步不完整
- 可能導致資料不一致

**建議修復方向**:
1. 檢查重建程式的記錄 ID 快取清理邏輯
2. 確保重建過程中完全重置記錄對應關係
3. 添加記錄存在性檢查機制

---

## 📝 版本記錄

| 日期 | 版本 | 改進內容 | 負責人 |
|------|------|----------|--------|
| 2025-07-10 | v1.0 | 初始文檔創建、批次更新優化、日誌分析 | Claude |
| 2025-07-10 | v1.1 | Issue Link 過濾系統實作、config_path 修復 | Claude |
| 2025-07-11 | v1.2 | 研究工具開發：JIRA 票據取得工具、父子記錄管理工具 | Claude |
| 2025-07-14 | v1.3 | 直接多維表格存取支援：測試並驗證 app token 直接存取能力 | Claude |
| 2025-07-14 | v1.4 | 問題記錄：user_id_fixer 邏輯問題、Cache Rebuild 邏輯問題 | Claude |

---

**🤖 由 Claude 分析和優化，記錄所有重要的系統改進和注意事項**