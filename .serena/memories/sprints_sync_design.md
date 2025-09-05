# Sprints 欄位同步功能設計

## 需求分析
在 `parent_child_relationship_updater.py` 中加入子單的 Sprints 欄位要跟母單同步的功能。

## 設計概念
1. **擴展現有邏輯**: 在父子關係更新時，同時同步 Sprints 欄位
2. **資料來源**: 從 JIRA 母單 (parent) 獲取 customfield_10020 (Sprints) 資訊
3. **同步目標**: 將母單的 Sprints 更新到子單的相應欄位

## 技術方案
### 1. 修改 JIRA 查詢
- 在 `get_jira_parent_relationships()` 中，除了查詢 'parent' 欄位，也查詢 'customfield_10020' (Sprints)
- 獲取每個父票據的 Sprints 資訊

### 2. 新增 Sprints 處理方法
- 建立 `get_parent_sprints_data()` 方法來獲取父票據的 Sprints
- 建立 `sync_sprints_to_children()` 方法來同步 Sprints 到子票據

### 3. 整合到批次更新
- 修改 `batch_update_relationships()` 方法
- 在更新父子關係的同時，也更新 Sprints 欄位

## 實作步驟
1. 修改 `get_jira_parent_relationships()` 增加 Sprints 欄位查詢
2. 新增 Sprints 資料處理方法
3. 修改批次更新邏輯整合 Sprints 同步
4. 更新 `run()` 方法支援 Sprints 欄位參數
5. 測試和驗證