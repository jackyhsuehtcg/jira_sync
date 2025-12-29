#!/usr/bin/env python3
"""
用戶映射模組 - 重構版

專注於 JIRA 和 Lark 用戶之間的映射業務邏輯：
- 用戶名提取和標準化
- 用戶映射邏輯處理
- 待查用戶管理
- 映射結果格式轉換

緩存管理委託給 UserCacheManager
用戶查詢委託給 LarkUserManager
"""

import logging
from typing import Dict, Any, Optional, Set
from datetime import datetime
from functools import lru_cache
from logger import ModuleLogger
from user_cache_manager import UserCacheManager


class UserMapper:
    """用戶映射類別 - 專注於業務邏輯"""
    
    def __init__(self, sync_logger, config_manager, lark_client):
        """
        初始化用戶映射器
        
        Args:
            sync_logger: 同步日誌器
            config_manager: 配置管理器
            lark_client: Lark Client (含 LarkUserManager)
        """
        self.logger = ModuleLogger(sync_logger, 'UserMapper')
        self.config_manager = config_manager
        self.lark_client = lark_client
        
        # 初始化緩存管理器
        cache_file = config_manager.get_user_mapping_cache_file()
        # 將 .json 改為 .db
        if cache_file.endswith('.json'):
            cache_file = cache_file[:-5] + '.db'
        
        self.cache_manager = UserCacheManager(cache_file)
        
        # 待查用戶管理（本次同步發現的）
        self.pending_users = set()  # 本次同步發現的待查用戶
        
        self.logger.info("用戶映射器初始化完成（重構版）")
    
    @lru_cache(maxsize=1000)
    def extract_username_from_jira_email(self, jira_identifier: str) -> Optional[str]:
        """
        從 JIRA email 或 username 提取用戶名
        
        Args:
            jira_identifier: JIRA 用戶識別符（email 或 username）
            
        Returns:
            提取的用戶名，失敗則返回 None
        """
        if not jira_identifier:
            return None
        
        # 如果包含 @ 符號，說明是 email，提取 @ 前面的部分
        if '@' in jira_identifier:
            return jira_identifier.split('@')[0]
        else:
            # 如果不包含 @ 符號，說明已經是 username，直接返回
            return jira_identifier.strip()
    
    @lru_cache(maxsize=2000)
    def find_lark_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """
        通過用戶名查找 Lark 用戶 - 快取優先，非阻塞模式
        
        Args:
            username: 用戶名
            
        Returns:
            Lark 用戶資訊字典，未找到則返回 None
        """
        if not username:
            return None
        
        # 檢查緩存
        cache_entry = self.cache_manager.get_user_mapping(username)
        if cache_entry:
            # 檢查是否為空值記錄
            if cache_entry.get('is_empty', False):
                self.logger.debug(f"命中用戶映射緩存（空值記錄）: {username}")
                return None
            
            # 檢查是否為待查記錄
            if cache_entry.get('is_pending', False):
                self.logger.debug(f"命中用戶映射緩存（待查記錄）: {username}")
                return None
            
            # 正常記錄
            self.logger.debug(f"命中用戶映射緩存: {username}")
            return {
                'lark_email': cache_entry['lark_email'],
                'lark_user_id': cache_entry['lark_user_id'],
                'lark_name': cache_entry['lark_name']
            }
        
        # 緩存未命中，標記為待查但不阻塞同步
        self._mark_user_as_pending(username)
        return None
    
    def perform_user_lookup(self, username: str) -> Optional[Dict[str, Any]]:
        """
        執行實際的用戶查詢並緩存結果
        
        Args:
            username: 用戶名
            
        Returns:
            Lark 用戶資訊字典，未找到則返回 None
        """
        domains = self.config_manager.get_user_mapping_domains()
        
        if not domains:
            self.logger.warning("未配置用戶映射域名")
            # 緩存配置錯誤為空值記錄
            self._cache_empty_result(username, "未配置用戶映射域名")
            return None
        
        for domain in domains:
            # 處理特殊格式 .tcg@gmail.com
            if domain.startswith('.tcg@'):
                email = f"{username}.tcg@gmail.com"
            else:
                email = f"{username}@{domain}"
            
            self.logger.debug(f"嘗試查詢 Lark 用戶: {email}")
            
            try:
                # 使用 LarkUserManager 查詢
                lark_user = self.lark_client.get_user_by_email(email)
                if lark_user:
                    self.logger.info(f"Lark 用戶查詢成功: {username} -> {email}")
                    
                    # 準備緩存數據
                    user_data = {
                        "lark_email": email,
                        "lark_user_id": lark_user.get('id'),
                        "lark_name": lark_user.get('name')
                    }
                    
                    # 緩存成功的映射
                    self.cache_manager.set_user_mapping(username, user_data)
                    
                    return user_data
                    
            except Exception as e:
                self.logger.debug(f"查詢失敗 {email}: {e}")
        
        # 所有域名查詢失敗，緩存空值記錄
        self.logger.warning(f"所有域名查詢失敗: {username}，已嘗試域名: {domains}")
        self._cache_empty_result(username, f"所有域名查詢失敗: {domains}")
        return None
    
    def map_jira_user_to_lark(self, jira_user: Dict[str, Any]) -> Optional[list]:
        """
        將 JIRA 用戶映射為 Lark 用戶格式（通用方法）
        
        Args:
            jira_user: JIRA 用戶字典（可能是 assignee、reporter、creator 等）
            
        Returns:
            Lark Base 人員欄位格式的列表，未找到則返回 None
        """
        return self._map_jira_user_to_lark_internal(jira_user)
    
    def map_jira_assignee_to_lark(self, jira_assignee: Dict[str, Any]) -> Optional[list]:
        """
        將 JIRA assignee 映射為 Lark 用戶格式（向後兼容）
        
        Args:
            jira_assignee: JIRA assignee 字典
            
        Returns:
            Lark Base 人員欄位格式的列表，未找到則返回 None
        """
        return self._map_jira_user_to_lark_internal(jira_assignee)
    
    def _map_jira_user_to_lark_internal(self, jira_user: Dict[str, Any]) -> Optional[list]:
        """
        內部方法：將 JIRA 用戶映射為 Lark 用戶格式
        
        Args:
            jira_user: JIRA 用戶字典
            
        Returns:
            Lark Base 人員欄位格式的列表，未找到則返回 None
        """
        if not jira_user:
            self.logger.debug("JIRA 用戶為空，返回 None")
            return None
        
        # 優先從 JIRA email 獲取，回退到 username
        jira_identifier = jira_user.get('emailAddress')
        if jira_identifier:
            # 有 email，正常處理
            username = self.extract_username_from_jira_email(jira_identifier)
        else:
            # 沒有 email，回退到 username
            jira_identifier = jira_user.get('name')
            if jira_identifier:
                self.logger.debug(f"JIRA 用戶無 emailAddress，使用 username: {jira_identifier}")
                username = self.extract_username_from_jira_email(jira_identifier)
            else:
                jira_display = jira_user.get('displayName', 'Unknown')
                self.logger.warning(f"JIRA 用戶缺少 emailAddress 和 name 欄位: {jira_display}")
                return None
        
        if not username:
            self.logger.warning(f"無法從 JIRA 識別符提取用戶名: {jira_identifier}，返回 None")
            return None
        
        # 查找對應的 Lark 用戶
        lark_user = self.find_lark_user_by_username(username)
        if not lark_user:
            jira_display = jira_user.get('displayName', username)
            
            # 檢查是否為已知的空值記錄，降低日誌等級避免噪音
            cache_entry = self.cache_manager.get_user_mapping(username)
            if cache_entry and cache_entry.get('is_empty', False):
                self.logger.debug(f"用戶映射緩存命中（空值）: {username} ({jira_display})")
            else:
                self.logger.warning(f"無法找到 Lark 用戶映射: {username} ({jira_display})，返回 None")
            return None
        
        # 驗證必要欄位
        user_id = lark_user.get('lark_user_id')
        if not user_id:
            self.logger.error(f"Lark 用戶缺少 user_id: {username}，返回 None")
            return None
        
        # 返回 Lark Base 人員欄位需要的格式（物件陣列）
        result = [{"id": user_id}]
        
        self.logger.debug(f"用戶映射成功: {username} -> {user_id}")
        return result
    
    def _mark_user_as_pending(self, username: str):
        """
        標記用戶為待查狀態，不阻塞同步
        
        Args:
            username: 用戶名
        """
        # 檢查是否已經是待查狀態
        cache_entry = self.cache_manager.get_user_mapping(username)
        if cache_entry and cache_entry.get('is_pending', False):
            return  # 已經是待查狀態，不需要重複處理
        
        # 設置待查記錄
        pending_record = {
            "is_pending": True
        }
        
        self.cache_manager.set_user_mapping(username, pending_record)
        self.pending_users.add(username)
        
        self.logger.debug(f"標記用戶為待查: {username}")
    
    def _cache_empty_result(self, username: str, reason: str = ""):
        """
        緩存查詢失敗的空值記錄
        
        Args:
            username: 用戶名
            reason: 失敗原因（保留參數以維持相容性）
        """
        empty_record = {
            "is_empty": True
        }
        
        self.cache_manager.set_user_mapping(username, empty_record)
        self.logger.debug(f"緩存空值記錄: {username}")
    
    def report_pending_users(self) -> Dict[str, Any]:
        """
        報告本次同步發現的待查用戶
        
        Returns:
            待查用戶報告字典
        """
        pending_count = len(self.pending_users)
        
        if pending_count > 0:
            users_list = list(self.pending_users)
            self.logger.info(f"本次同步發現 {pending_count} 個待查用戶: {users_list}")
            
            # 清空待查列表，為下次同步做準備
            self.pending_users.clear()
            
            return {
                "pending_users_found": pending_count,
                "users": users_list
            }
        else:
            self.logger.debug("本次同步無新的待查用戶")
            return {
                "pending_users_found": 0,
                "users": []
            }
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        獲取緩存統計資訊
        
        Returns:
            統計資訊字典
        """
        stats = self.cache_manager.get_cache_stats()
        
        # 添加本次同步的待查用戶數
        stats['current_pending_users'] = len(self.pending_users)
        
        return stats
    
    def batch_lookup_pending_users(self, limit: int = 50) -> Dict[str, Any]:
        """
        批量查詢待查用戶
        
        Args:
            limit: 查詢限制數量
            
        Returns:
            查詢結果統計
        """
        pending_users = self.cache_manager.get_pending_users()
        
        if not pending_users:
            self.logger.info("沒有待查用戶需要處理")
            return {
                "total_pending": 0,
                "processed": 0,
                "successful": 0,
                "failed": 0
            }
        
        # 限制處理數量
        to_process = pending_users[:limit]
        successful_count = 0
        failed_count = 0
        
        self.logger.info(f"開始批量查詢 {len(to_process)} 個待查用戶...")
        
        for username in to_process:
            try:
                # 執行實際查詢
                result = self.perform_user_lookup(username)
                if result:
                    successful_count += 1
                    self.logger.info(f"用戶查詢成功: {username}")
                else:
                    failed_count += 1
                    self.logger.debug(f"用戶查詢失敗: {username}")
                    
            except Exception as e:
                failed_count += 1
                self.logger.error(f"用戶查詢異常: {username}, {e}")
        
        result = {
            "total_pending": len(pending_users),
            "processed": len(to_process),
            "successful": successful_count,
            "failed": failed_count
        }
        
        self.logger.info(f"批量用戶查詢完成: {result}")
        return result
    
    def clear_pending_users(self) -> int:
        """
        清除所有待查用戶記錄
        
        Returns:
            清除的記錄數
        """
        return self.cache_manager.clear_pending_users()
    
    def vacuum_cache(self) -> bool:
        """
        清理和優化緩存數據庫
        
        Returns:
            是否成功
        """
        return self.cache_manager.vacuum_database()


# 測試模組
if __name__ == '__main__':
    import sys
    sys.path.append('/Users/hideman/code/jira_sync_v3')
    
    from logger import setup_logging
    from config_manager import ConfigManager
    from new.lark_client import LarkClient
    
    # 設定日誌
    log_config = {
        'log_level': 'DEBUG',
        'log_file': 'user_mapper_test.log',
        'max_size': '10MB',
        'backup_count': 1
    }
    sync_logger = setup_logging(log_config)
    
    try:
        # 初始化組件
        config_manager = ConfigManager(sync_logger, '../config.yaml')
        lark_config = config_manager.get_lark_base_config()
        lark_client = LarkClient(lark_config['app_id'], lark_config['app_secret'])
        
        # 建立重構版用戶映射器
        user_mapper = UserMapper(sync_logger, config_manager, lark_client)
        
        print("重構版用戶映射器測試:")
        print(f"配置的域名: {config_manager.get_user_mapping_domains()}")
        
        # 測試緩存統計
        stats = user_mapper.get_cache_stats()
        print(f"緩存統計: {stats}")
        
        # 測試用戶名提取
        test_email = "nicole.g@tc-gaming.com"
        username = user_mapper.extract_username_from_jira_email(test_email)
        print(f"從 {test_email} 提取用戶名: {username}")
        
        # 測試用戶查找
        lark_user = user_mapper.find_lark_user_by_username(username)
        print(f"查找 Lark 用戶: {lark_user}")
        
        # 測試待查用戶報告
        pending_report = user_mapper.report_pending_users()
        print(f"待查用戶報告: {pending_report}")
        
        print("重構版用戶映射器測試完成")
        
    except Exception as e:
        print(f"測試失敗: {e}")
        import traceback
        traceback.print_exc()