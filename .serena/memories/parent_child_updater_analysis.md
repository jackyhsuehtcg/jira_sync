# ParentChildRelationshipUpdater 分析

## 現有功能
`parent_child_relationship_updater.py` 的主要功能是基於 JIRA 的 sub-task 關係自動更新 Lark 表格中的父子記錄關係。

## 核心流程
1. **初始化**: 載入配置，建立 JIRA 和 Lark 連線
2. **讀取記錄**: 從 Lark 表格獲取所有記錄的票據號碼
3. **查詢關係**: 批次從 JIRA 獲取父子關係 (parent field)
4. **篩選驗證**: 確認父票據在 Lark 表格中存在
5. **批次更新**: 更新子記錄的父記錄關係

## 關鍵方法
- `get_jira_parent_relationships()`: 批次查詢 JIRA parent 欄位
- `filter_valid_relationships()`: 篩選有效的父子關係
- `batch_update_relationships()`: 執行批次更新

## 目前限制
- 只處理父子記錄關係 (parent field)
- 不涉及其他欄位的同步
- 每次只能更新一個欄位類型