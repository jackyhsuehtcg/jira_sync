# Sprints 欄位同步功能實作完成

## 已完成的功能

### 1. 修改現有方法
- `get_jira_parent_relationships()`: 增加查詢 customfield_10020 (Sprints) 
- `filter_valid_relationships()`: 整合父票據 Sprints 獲取邏輯
- `batch_update_relationships()`: 支援 Sprints 欄位同步更新
- `preview_updates()`: 顯示 Sprints 同步資訊
- `run()`: 支援 sprints_field 參數

### 2. 新增方法
- `get_parent_sprints_data()`: 批次獲取父票據的 Sprints 資訊
- `format_sprints_for_lark()`: 將 JIRA Sprints 格式化為 Lark 多選格式
- `validate_sprints_field()`: 驗證 Sprints 欄位是否為多選欄位

### 3. 更新命令列介面
- 增加 `--sprints-field` 參數
- 更新幫助文字和執行結果顯示

## 使用方法

### 基本語法
```bash
python parent_child_relationship_updater.py \
    --url "https://example.larksuite.com/wiki/xxxxx" \
    --parent-field "Parent Tickets" \
    --sprints-field "Sprints" \
    --preview
```

### 功能特色
1. **雙重同步**: 同時更新父子關係和 Sprints 欄位
2. **向後相容**: 不指定 sprints-field 時仍可正常運作
3. **批次處理**: 有效率地處理大量資料
4. **詳細預覽**: 清楚顯示將要同步的 Sprints 資訊
5. **欄位驗證**: 確保 Sprints 欄位為多選類型

## 工作流程
1. 獲取子票據的父子關係
2. 批次查詢父票據的 Sprints 資訊
3. 篩選有效關係並準備同步資料
4. 批次更新父子關係和 Sprints 欄位