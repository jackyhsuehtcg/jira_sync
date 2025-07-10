# JIRA 字段處理規範

## 概述

本文檔描述了在 JIRA 到 Lark Base 同步系統中處理 JIRA 字段的最佳實踐和規範。本系統採用基於 `schema.yaml` 的配置驅動架構，支援多種處理器類型和用戶映射整合。

## 核心原則

1. **一致性**: 所有字段應遵循統一的處理邏輯
2. **故障安全**: 必須處理字段不存在或值為 None 的情況
3. **數據完整性**: 確保不會因為字段缺失導致同步失敗
4. **可讀性**: 代碼應該易於理解和維護
5. **配置驅動**: 使用 `schema.yaml` 配置欄位對應和處理器
6. **非阻塞映射**: 用戶映射採用非阻塞設計，不影響同步效能

## 新架構設計

### Schema 配置驅動

本系統使用 `schema.yaml` 配置檔案定義欄位對應和處理器：

```yaml
field_mappings:
  "status": 
    lark_field: "JIRA Status"
    processor: "extract_nested"
    nested_path: "name"
  "assignee": 
    lark_field: "Assignee"
    processor: "extract_user"
  "customfield_11300": 
    lark_field: "Story Points"
    processor: "extract_simple"
```

### 處理器類型

支援 7 種處理器類型：

1. **`extract_simple`** - 直接提取值（None 值返回 None）
2. **`extract_nested`** - 嵌套物件提取（None 值返回空字符串 ''）
3. **`extract_user`** - 用戶映射（整合 UserMapper）
4. **`convert_datetime`** - 時間戳轉換（None 值返回 None）
5. **`extract_components`** - 組件陣列處理（None 值返回 None）
6. **`extract_versions`** - 版本陣列處理（None 值返回 None）
7. **`extract_links`** - 關聯連結處理（None 值返回 None）

### 用戶映射整合

`extract_user` 處理器已整合 UserMapper：

```python
# 自動進行非阻塞用戶映射
"assignee": 
  lark_field: "Assignee"
  processor: "extract_user"
```

- **成功映射**: 返回 Lark Base 人員欄位格式 `[{"id": "user_id"}]`
- **快取命中**: 直接返回快取結果
- **快取未命中**: 標記為 pending，不阻塞同步
- **向後兼容**: 沒有 UserMapper 時返回 displayName

## 基本字段處理模式（舊版參考）

### 1. 普通字符串字段

```python
'Field Name': lambda f: f.get('field_name', ''),
```

**新版本對應**：
```yaml
"field_name":
  lark_field: "Field Name"
  processor: "extract_simple"
```

**行為差異**：
- 舊版本：`f.get('field_name', '')` → 不存在時返回空字符串 `''`
- 新版本：`None` 值返回 `None`，讓上層決定如何處理

### 2. 嵌套字段

```python
'Field Name': lambda f: f.get('parent_field', {}).get('sub_field', ''),
```

**新版本對應**：
```yaml
"parent_field":
  lark_field: "Field Name"
  processor: "extract_nested"
  nested_path: "sub_field"
```

**行為一致性**：
- 舊版本：`f.get('parent_field', {}).get('sub_field', '')` → 不存在時返回空字符串 `''`
- 新版本：`None` 值返回空字符串 `''`，保持一致

### 3. 用戶字段

```python
'Assignee': lambda f: user_mapper.map_jira_user_to_lark(f.get('assignee')),
```

**新版本對應**：
```yaml
"assignee":
  lark_field: "Assignee"
  processor: "extract_user"
```

### 4. 時間字段

```python
'Created': lambda f: self.convert_jira_datetime_to_timestamp(f.get('created')),
```

**新版本對應**：
```yaml
"created":
  lark_field: "Created"
  processor: "convert_datetime"
```

## 常見字段處理案例

### 基礎字段

```python
# 普通字符串字段
'Title': lambda f: f.get('summary', ''),

# 嵌套字段
'JIRA Status': lambda f: f.get('status', {}).get('name', ''),
'Priority': lambda f: f.get('priority', {}).get('name', ''),
'Issue Type': lambda f: f.get('issuetype', {}).get('name', ''),
```

### 條件判斷字段

```python
# 需要判斷是否存在
'Resolution': lambda f: f.get('resolution', {}).get('name', '') if f.get('resolution') else '',

# 數組字段的第一個元素
'Components': lambda f: f.get('components', [{}])[0].get('name', '') if f.get('components') else '',
```

### 自定義字段

```python
# 普通自定義字段
'Product': lambda f: f.get('customfield_11601', ''),

# 數值自定義字段
'Story Points': lambda f: str(f.get('customfield_11300')) if f.get('customfield_11300') is not None else None,
'Sprints': lambda f: f.get('customfield_11603', ''),
```

### 時間字段

```python
# 時間戳轉換
'Created': lambda f: self.convert_jira_datetime_to_timestamp(f.get('created')),
'Updated Date': lambda f: self.convert_jira_datetime_to_timestamp(f.get('updated')),
'Due Day': lambda f: self.convert_jira_datetime_to_timestamp(f.get('duedate')),
```

## 字段處理最佳實踐

### 1. 安全訪問

**推薦做法**：
```python
# 使用 dict.get() 方法安全訪問
'Field Name': lambda f: f.get('field_name', ''),
```

**不推薦做法**：
```python
# 直接訪問可能導致 KeyError
'Field Name': lambda f: f['field_name'],
```

### 2. 嵌套字段處理

**推薦做法**：
```python
# 每層都使用 get() 方法
'Status': lambda f: f.get('status', {}).get('name', ''),
```

**不推薦做法**：
```python
# 中間任何一層為 None 都會導致錯誤
'Status': lambda f: f.get('status')['name'],
```

### 3. 數值字段處理

**推薦做法**：
```python
# 明確檢查 None 值
'Story Points': lambda f: str(f.get('customfield_11300')) if f.get('customfield_11300') is not None else None,
```

**不推薦做法**：
```python
# 沒有處理 None 值的情況
'Story Points': lambda f: str(f.get('customfield_11300')),
```

### 4. 條件判斷

**推薦做法**：
```python
# 先檢查字段存在性，再訪問子字段
'Resolution': lambda f: f.get('resolution', {}).get('name', '') if f.get('resolution') else '',
```

**不推薦做法**：
```python
# 沒有檢查字段存在性
'Resolution': lambda f: f.get('resolution', {}).get('name', ''),
```

## 常見錯誤處理

### 1. 字段不存在

當 JIRA 字段不存在時，`f.get('field_name')` 會返回 `None`，這是正常行為。

### 2. 字段值為 None

當字段存在但值為 `None` 時，需要明確處理：

```python
# 對於字符串字段
'Field Name': lambda f: f.get('field_name', ''),

# 對於數值字段
'Numeric Field': lambda f: str(f.get('field_name')) if f.get('field_name') is not None else None,
```

### 3. 嵌套字段中間層為 None

```python
# 安全做法：每層都使用 get() 方法
'Nested Field': lambda f: f.get('parent', {}).get('child', ''),
```

## 測試建議

### 1. 測試數據準備

準備以下測試數據：
- 完整字段的正常 Issue
- 缺少某些字段的 Issue
- 字段值為 None 的 Issue
- 嵌套字段缺失的 Issue

### 2. 測試案例

```python
# 測試完整字段
test_issue = {
    'fields': {
        'summary': 'Test Issue',
        'status': {'name': 'Open'},
        'customfield_11300': 5.0
    }
}

# 測試缺失字段
test_issue_missing = {
    'fields': {
        'summary': 'Test Issue',
        'status': {'name': 'Open'}
        # customfield_11300 不存在
    }
}

# 測試 None 值
test_issue_none = {
    'fields': {
        'summary': 'Test Issue',
        'status': {'name': 'Open'},
        'customfield_11300': None
    }
}
```

## 擴展指南

### 1. 添加新字段

添加新字段時，遵循以下步驟：

1. 確定字段類型（字符串、數值、嵌套、數組）
2. 選擇合適的處理模式
3. 添加到 `field_mapping_rules` 中
4. 編寫測試用例
5. 驗證同步結果

### 2. 修改現有字段

修改字段處理邏輯時：

1. 確保向後兼容
2. 測試各種邊界情況
3. 更新文檔
4. 在測試環境驗證

## 相關代碼文件

- `new/field_processor.py` - 基於 Schema 的欄位處理器
- `new/schema.yaml` - 欄位對應配置
- `new/user_mapper.py` - 用戶映射管理
- `new/user_cache_manager.py` - SQLite 用戶快取
- `new/jira_client.py` - JIRA API 客戶端
- `new/lark_client.py` - Lark API 客戶端

## 更新歷史

- 2025-01-09: 初始版本，包含基本字段處理規範
- 2025-01-09: 添加 Story Points 字段處理案例
- 2025-07-09: 更新為新架構，增加 Schema 配置驅動和 UserMapper 整合