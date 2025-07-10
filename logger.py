#!/usr/bin/env python3
"""
統一日誌管理模組
提供清楚的日誌格式和分級記錄
"""

import logging
import logging.handlers
import os
import sys
from datetime import datetime
from typing import Optional, Dict, Any


class SyncLogger:
    """同步系統專用日誌管理器"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化日誌系統
        
        Args:
            config: 包含日誌配置的字典
        """
        self.config = config
        self.log_level = config.get('log_level', 'INFO')
        self.log_file = config.get('log_file', 'jira_lark_sync.log')
        self.max_size = config.get('max_size', '10MB')
        self.backup_count = config.get('backup_count', 5)
        
        # 設定根日誌器
        self._setup_root_logger()
        
        # 取得主日誌器
        self.logger = logging.getLogger('JiraLarkSync')
        
    def _setup_root_logger(self):
        """設定根日誌器"""
        # 清除現有的處理器
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # 設定日誌級別
        level = getattr(logging, self.log_level.upper(), logging.INFO)
        root_logger.setLevel(level)
        
        # 設定日誌格式
        formatter = logging.Formatter(
            '%(asctime)s | %(name)-15s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 控制台處理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        
        # 檔案處理器（輪替）
        if self.log_file:
            # 確保日誌目錄存在
            log_dir = os.path.dirname(self.log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)
            
            # 轉換大小格式
            max_bytes = self._parse_size(self.max_size)
            
            file_handler = logging.handlers.RotatingFileHandler(
                self.log_file,
                maxBytes=max_bytes,
                backupCount=self.backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
    
    def _parse_size(self, size_str: str) -> int:
        """解析大小字串為位元組數"""
        size_str = size_str.upper()
        if size_str.endswith('KB'):
            return int(size_str[:-2]) * 1024
        elif size_str.endswith('MB'):
            return int(size_str[:-2]) * 1024 * 1024
        elif size_str.endswith('GB'):
            return int(size_str[:-2]) * 1024 * 1024 * 1024
        else:
            return int(size_str)
    
    def get_logger(self, name: str) -> logging.Logger:
        """
        取得指定名稱的日誌器
        
        Args:
            name: 日誌器名稱
            
        Returns:
            Logger: 配置好的日誌器
        """
        return logging.getLogger(f"JiraLarkSync.{name}")
    
    def log_sync_start(self, team: str, table_name: str):
        """記錄同步開始"""
        self.logger.info(f"🚀 開始同步 | 團隊: {team} | 表格: {table_name} | 方向: jira_to_lark")
    
    def log_sync_complete(self, team: str, table_name: str, stats: Dict[str, int]):
        """記錄同步完成"""
        created = stats.get('created', 0)
        updated = stats.get('updated', 0)
        skipped = stats.get('skipped', 0)
        errors = stats.get('errors', 0)
        
        self.logger.info(
            f"✅ 同步完成 | 團隊: {team} | 表格: {table_name} | "
            f"新增: {created} | 更新: {updated} | 跳過: {skipped} | 錯誤: {errors}"
        )
    
    def log_sync_error(self, team: str, table_name: str, error: Exception):
        """記錄同步錯誤"""
        self.logger.error(
            f"❌ 同步失敗 | 團隊: {team} | 表格: {table_name} | 錯誤: {str(error)}",
            exc_info=True
        )
    
    def log_field_mapping(self, ticket_type: str, field_count: int):
        """記錄欄位對應載入"""
        self.logger.info(f"📋 載入欄位對應 | 類型: {ticket_type} | 欄位數: {field_count}")
    
    def log_api_call(self, service: str, method: str, endpoint: str, status: str):
        """記錄 API 呼叫"""
        self.logger.debug(f"🌐 API 呼叫 | {service} | {method} {endpoint} | 狀態: {status}")
    
    def log_record_operation(self, operation: str, record_id: str, issue_key: str, status: str):
        """記錄記錄操作"""
        self.logger.debug(f"📝 記錄操作 | {operation} | ID: {record_id} | Issue: {issue_key} | 狀態: {status}")
    
    def log_batch_operation(self, operation: str, count: int, success_count: int):
        """記錄批次操作"""
        self.logger.info(f"📦 批次{operation} | 總數: {count} | 成功: {success_count}")
    
    def log_config_load(self, config_file: str, teams_count: int, tables_count: int):
        """記錄配置載入"""
        self.logger.info(f"⚙️ 載入配置 | 檔案: {config_file} | 團隊: {teams_count} | 表格: {tables_count}")
    
    def log_jira_query(self, jql: str, issue_count: int):
        """記錄 JIRA 查詢"""
        self.logger.debug(f"🔍 JIRA 查詢 | JQL: {jql} | 結果: {issue_count} 筆")
    
    def log_field_change_detected(self, field_name: str, old_type: str, new_type: str):
        """記錄欄位變更檢測"""
        self.logger.warning(f"⚠️ 欄位變更 | {field_name} | {old_type} → {new_type}")
    
    def log_hyperlink_conversion(self, field_name: str, issue_key: str, url: str):
        """記錄超連結轉換"""
        self.logger.debug(f"🔗 超連結轉換 | {field_name} | {issue_key} → {url}")
    
    def log_status_mapping(self, ticket_type: str, lark_status: str, jira_status: str):
        """記錄狀態對應"""
        self.logger.debug(f"🔄 狀態對應 | {ticket_type} | {lark_status} → {jira_status}")
    
    def log_dry_run(self, operation: str, details: str):
        """記錄乾跑模式操作"""
        self.logger.info(f"🧪 乾跑模式 | {operation} | {details}")


class ModuleLogger:
    """模組專用日誌器包裝"""
    
    def __init__(self, sync_logger: SyncLogger, module_name: str):
        """
        初始化模組日誌器
        
        Args:
            sync_logger: 主日誌管理器
            module_name: 模組名稱
        """
        self.logger = sync_logger.get_logger(module_name)
        self.module_name = module_name
    
    def info(self, message: str, **kwargs):
        """資訊級別日誌"""
        self.logger.info(f"[{self.module_name}] {message}", **kwargs)
    
    def debug(self, message: str, **kwargs):
        """除錯級別日誌"""
        self.logger.debug(f"[{self.module_name}] {message}", **kwargs)
    
    def warning(self, message: str, **kwargs):
        """警告級別日誌"""
        self.logger.warning(f"[{self.module_name}] {message}", **kwargs)
    
    def error(self, message: str, **kwargs):
        """錯誤級別日誌"""
        self.logger.error(f"[{self.module_name}] {message}", **kwargs)
    
    def critical(self, message: str, **kwargs):
        """嚴重錯誤級別日誌"""
        self.logger.critical(f"[{self.module_name}] {message}", **kwargs)


def setup_logging(config: Dict[str, Any]) -> SyncLogger:
    """
    設定全域日誌系統
    
    Args:
        config: 日誌配置
        
    Returns:
        SyncLogger: 配置好的日誌管理器
    """
    return SyncLogger(config)


# 使用範例
if __name__ == '__main__':
    # 測試日誌系統
    test_config = {
        'log_level': 'DEBUG',
        'log_file': 'test_sync.log',
        'max_size': '5MB',
        'backup_count': 3
    }
    
    # 設定日誌
    sync_logger = setup_logging(test_config)
    
    # 取得模組日誌器
    jira_logger = ModuleLogger(sync_logger, 'JIRA')
    lark_logger = ModuleLogger(sync_logger, 'Lark')
    
    # 測試各種日誌
    sync_logger.log_config_load('config.yaml', 2, 4)
    sync_logger.log_sync_start('CRD', 'TP Table', 'jira_to_lark')
    
    jira_logger.info('連接 JIRA 伺服器成功')
    jira_logger.debug('執行 JQL 查詢: project = TP')
    
    lark_logger.info('連接 Lark Base 成功')
    lark_logger.warning('檢測到欄位類型變更')
    
    sync_logger.log_sync_complete('CRD', 'TP Table', {
        'created': 5, 'updated': 10, 'skipped': 2, 'errors': 0
    })
    
    print("日誌測試完成，請檢查 test_sync.log 檔案")