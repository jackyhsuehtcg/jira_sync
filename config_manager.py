#!/usr/bin/env python3
"""
配置管理模組（新架構版本）
負責載入和驗證系統配置，符合新的 6 模組架構
簡化複雜的熱重載和檔案鎖定功能，專注於核心配置管理
"""

import yaml
import os
import threading
from typing import Dict, Any, List, Optional
from logger import ModuleLogger, SyncLogger


class ConfigManager:
    """配置管理器（新架構版本）"""
    
    def __init__(self, sync_logger: Optional[SyncLogger], config_file: str):
        """
        初始化配置管理器
        
        Args:
            sync_logger: 日誌管理器（可選）
            config_file: 配置檔案路徑
        """
        self.logger = ModuleLogger(sync_logger, 'ConfigManager') if sync_logger else None
        self.config_file = os.path.abspath(config_file)
        self.config = {}
        self.config_lock = threading.RLock()
        
        self._load_config()
        self._validate_config()
    
    def _load_config(self):
        """載入配置檔案"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"配置檔案不存在: {self.config_file}")
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {}
            
            if self.logger:
                self.logger.info(f"配置檔案載入成功: {self.config_file}")
                
        except Exception as e:
            error_msg = f"載入配置檔案失敗: {e}"
            if self.logger:
                self.logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def _validate_config(self):
        """驗證配置完整性"""
        errors = []
        
        # 檢查必要的頂層配置
        required_sections = ['global', 'jira', 'lark_base', 'teams']
        for section in required_sections:
            if section not in self.config:
                errors.append(f"缺少必要配置區段: {section}")
        
        # 檢查全域配置
        global_config = self.config.get('global', {})
        if 'schema_file' not in global_config:
            errors.append("全域配置缺少 schema_file")
        if 'data_directory' not in global_config:
            errors.append("全域配置缺少 data_directory")
        
        # 檢查 JIRA 配置
        jira_config = self.config.get('jira', {})
        required_jira_fields = ['server_url', 'username', 'password']
        for field in required_jira_fields:
            if not jira_config.get(field):
                errors.append(f"JIRA 配置缺少: {field}")
        
        # 檢查 Lark Base 配置
        lark_config = self.config.get('lark_base', {})
        required_lark_fields = ['app_id', 'app_secret']
        for field in required_lark_fields:
            if not lark_config.get(field):
                errors.append(f"Lark Base 配置缺少: {field}")
        
        # 檢查用戶映射配置
        user_mapping = self.config.get('user_mapping', {})
        if 'cache_db' not in user_mapping:
            errors.append("用戶映射配置缺少 cache_db")
        
        # 檢查團隊配置
        teams = self.config.get('teams', {})
        if not teams:
            errors.append("至少需要配置一個團隊")
        
        for team_name, team_config in teams.items():
            # 檢查基本團隊配置
            if not team_config.get('enabled', True):
                continue  # 跳過未啟用的團隊
                
            if not team_config.get('wiki_token'):
                errors.append(f"團隊 {team_name} 缺少 wiki_token")
            
            # 檢查表格配置
            tables = team_config.get('tables', {})
            if not tables:
                if self.logger:
                    self.logger.warning(f"團隊 {team_name} 沒有配置任何表格")
                continue
            
            for table_name, table_config in tables.items():
                if not table_config.get('enabled', True):
                    continue  # 跳過未啟用的表格
                    
                # 檢查新架構的必要欄位
                required_table_fields = ['table_id', 'jql_query', 'name']
                for field in required_table_fields:
                    if not table_config.get(field):
                        errors.append(f"團隊 {team_name} 表格 {table_name} 缺少: {field}")
                
                # 驗證 jql_query 不為空
                jql_query = table_config.get('jql_query', '').strip()
                if not jql_query:
                    errors.append(f"團隊 {team_name} 表格 {table_name} 的 jql_query 不能為空")
        
        if errors:
            error_msg = "配置驗證失敗:\n" + "\n".join(f"  - {error}" for error in errors)
            if self.logger:
                self.logger.error(error_msg)
            raise ValueError(error_msg)
        
        if self.logger:
            self.logger.info("配置驗證通過")
    
    def get_global_config(self) -> Dict[str, Any]:
        """取得全域配置"""
        with self.config_lock:
            return self.config.get('global', {}).copy()
    
    def get_jira_config(self) -> Dict[str, Any]:
        """取得 JIRA 配置"""
        with self.config_lock:
            return self.config.get('jira', {}).copy()
    
    def get_lark_base_config(self) -> Dict[str, Any]:
        """取得 Lark Base 配置"""
        with self.config_lock:
            return self.config.get('lark_base', {}).copy()
    
    def get_user_mapping_config(self) -> Dict[str, Any]:
        """取得用戶映射配置"""
        with self.config_lock:
            return self.config.get('user_mapping', {}).copy()
    
    def get_user_mapping_cache_file(self) -> str:
        """取得用戶映射快取檔案路徑"""
        user_mapping = self.get_user_mapping_config()
        return user_mapping.get('cache_db', 'data/user_mapping_cache.db')
    
    def get_teams(self) -> Dict[str, Any]:
        """取得所有團隊配置"""
        with self.config_lock:
            return self.config.get('teams', {}).copy()
    
    def get_enabled_teams(self) -> List[str]:
        """取得啟用的團隊名稱列表"""
        teams = self.get_teams()
        enabled_teams = []
        
        for team_name, team_config in teams.items():
            if team_config.get('enabled', True):
                enabled_teams.append(team_name)
        
        return enabled_teams
    
    def get_team_config(self, team_name: str) -> Optional[Dict[str, Any]]:
        """
        取得指定團隊的配置
        
        Args:
            team_name: 團隊名稱
            
        Returns:
            Dict: 團隊配置，如果不存在或未啟用則返回 None
        """
        teams = self.get_teams()
        team_config = teams.get(team_name)
        
        if team_config and team_config.get('enabled', True):
            return team_config.copy()
        
        return None
    
    def get_enabled_tables(self, team_name: str) -> List[Dict[str, Any]]:
        """
        取得指定團隊的啟用表格列表
        
        Args:
            team_name: 團隊名稱
            
        Returns:
            List[Dict]: 啟用的表格配置列表
        """
        team_config = self.get_team_config(team_name)
        if not team_config:
            return []
        
        tables = team_config.get('tables', {})
        enabled_tables = []
        
        for table_name, table_config in tables.items():
            if table_config.get('enabled', True):
                # 確保表格配置包含 table_name
                table_config_copy = table_config.copy()
                table_config_copy['table_name'] = table_name
                enabled_tables.append(table_config_copy)
        
        return enabled_tables
    
    def get_table_config(self, team_name: str, table_name: str) -> Optional[Dict[str, Any]]:
        """
        取得指定表格的配置
        
        Args:
            team_name: 團隊名稱
            table_name: 表格名稱
            
        Returns:
            Dict: 表格配置，如果不存在或未啟用則返回 None
        """
        team_config = self.get_team_config(team_name)
        if not team_config:
            return None
        
        tables = team_config.get('tables', {})
        table_config = tables.get(table_name)
        
        if table_config and table_config.get('enabled', True):
            table_config_copy = table_config.copy()
            table_config_copy['table_name'] = table_name
            return table_config_copy
        
        return None
    
    def get_sync_interval(self, team_name: str = None, table_name: str = None) -> int:
        """
        獲取同步間隔時間（表格 > 團隊 > 全域）
        
        Args:
            team_name: 團隊名稱（可選）
            table_name: 表格名稱（可選，需要同時提供 team_name）
            
        Returns:
            int: 同步間隔時間（秒）
        """
        # 表格層級優先
        if team_name and table_name:
            table_config = self.get_table_config(team_name, table_name)
            if table_config and 'sync_interval' in table_config:
                return table_config['sync_interval']
        
        # 團隊層級次之
        if team_name:
            team_config = self.get_team_config(team_name)
            if team_config and 'sync_interval' in team_config:
                return team_config['sync_interval']
        
        # 全域預設
        global_config = self.get_global_config()
        return global_config.get('default_sync_interval', 300)
    
    def get_all_sync_intervals(self) -> Dict[str, Dict[str, int]]:
        """
        獲取所有表格的同步間隔設定
        
        Returns:
            Dict: {team_name: {table_name: sync_interval}}
        """
        all_intervals = {}
        
        for team_name in self.get_enabled_teams():
            team_intervals = {}
            enabled_tables = self.get_enabled_tables(team_name)
            
            for table_config in enabled_tables:
                table_name = table_config.get('table_name')
                if table_name:
                    interval = self.get_sync_interval(team_name, table_name)
                    team_intervals[table_name] = interval
            
            if team_intervals:
                all_intervals[team_name] = team_intervals
        
        return all_intervals
    
    def print_config_summary(self):
        """列印配置摘要"""
        print("📋 配置摘要:")
        
        # 全域設定
        global_config = self.get_global_config()
        print(f"  日誌級別: {global_config.get('log_level', 'INFO')}")
        print(f"  資料目錄: {global_config.get('data_directory', 'data')}")
        print(f"  Schema 檔案: {global_config.get('schema_file', 'schema.yaml')}")
        print(f"  預設同步間隔: {global_config.get('default_sync_interval', 300)} 秒")
        
        # JIRA 設定
        jira_config = self.get_jira_config()
        print(f"  JIRA 伺服器: {jira_config.get('server_url', 'N/A')}")
        print(f"  JIRA 用戶: {jira_config.get('username', 'N/A')}")
        
        # 用戶映射設定
        user_mapping = self.get_user_mapping_config()
        print(f"  用戶映射: {'啟用' if user_mapping.get('enabled') else '停用'}")
        print(f"  用戶快取: {user_mapping.get('cache_db', 'N/A')}")
        
        # 團隊和表格
        enabled_teams = self.get_enabled_teams()
        print(f"  啟用團隊: {len(enabled_teams)} 個")
        
        for team_name in enabled_teams:
            team_config = self.get_team_config(team_name)
            enabled_tables = self.get_enabled_tables(team_name)
            team_interval = self.get_sync_interval(team_name)
            
            print(f"    {team_name}: {team_config.get('display_name', team_name)}")
            print(f"      Wiki Token: {team_config.get('wiki_token', '')[:20]}...")
            print(f"      團隊同步間隔: {team_interval} 秒")
            print(f"      啟用表格: {len(enabled_tables)} 個")
            
            for table_config in enabled_tables:
                table_name = table_config.get('table_name', 'N/A')
                table_display_name = table_config.get('name', table_name)
                table_interval = self.get_sync_interval(team_name, table_name)
                print(f"        - {table_name}: {table_display_name} ({table_interval}s)")
    
    def reload_config(self):
        """重新載入配置檔案"""
        try:
            with self.config_lock:
                old_config = self.config.copy()
                self._load_config()
                self._validate_config()
                
                if self.logger:
                    self.logger.info("配置檔案重載成功")
                    
                return True
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"配置檔案重載失敗: {e}")
            return False
    
    def get_config_with_lock(self) -> Dict[str, Any]:
        """線程安全地獲取完整配置"""
        with self.config_lock:
            return self.config.copy()
    
    def get_config(self) -> Dict[str, Any]:
        """獲取配置"""
        return self.config.copy()
    
    def save_config(self, config: Dict[str, Any]):
        """保存配置到檔案，保留註解"""
        with self.config_lock:
            try:
                from schema_utils import save_yaml_with_comments
                save_yaml_with_comments(self.config_file, config)
                self.config = config
                if self.logger:
                    self.logger.info(f"配置已保存到: {self.config_file}（保留註解）")
            except Exception as e:
                error_msg = f"保存配置失敗: {e}"
                if self.logger:
                    self.logger.error(error_msg)
                raise RuntimeError(error_msg)