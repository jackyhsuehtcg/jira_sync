# JIRA-Lark 同步系統專案概覽

## 專案目的
這是一個 JIRA 到 Lark Base 的同步系統，主要功能包括：
- 單向同步 JIRA Issues 到 Lark Base 表格
- 父子記錄關係自動更新
- 批次處理和動態欄位對應
- 多團隊支援和配置驅動

## 技術堆疊
- **語言**: Python 3.8+
- **主要依賴**: Flask, requests, PyYAML, watchdog
- **架構**: 模組化設計，支援熱重載配置
- **API**: JIRA REST API, Lark Base API

## 核心元件
- `main.py` - 主程式入口
- `sync_coordinator.py` - 同步協調器
- `parent_child_relationship_updater.py` - 父子記錄關係更新器 
- `jira_client.py` - JIRA API 客戶端
- `lark_client.py` - Lark API 客戶端
- `field_processor.py` - 欄位處理器

## 專案結構
- `/` - 核心系統檔案
- `/study_tools/` - 研究和分析工具
- `/data/` - 資料庫檔案 (SQLite)
- `/templates/` - Web 介面模板