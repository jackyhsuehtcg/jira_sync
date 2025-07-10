#!/usr/bin/env python3
"""
同步協調器

負責最高層的協調和事務管理：
- 多團隊和多表格同步協調
- 全局配置管理
- 錯誤處理和回滾
- 同步任務排程
- 系統健康監控

設計理念：
- 作為整個同步系統的入口點
- 協調所有組件的初始化和配置
- 提供統一的 API 介面
- 實現企業級的錯誤處理和監控
"""

import time
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from jira_client import JiraClient
from lark_client import LarkClient
from field_processor import FieldProcessor
from user_mapper import UserMapper
from sync_state_manager import SyncStateManager
from sync_workflow_manager import SyncWorkflowManager, SyncWorkflowConfig
from sync_metrics_collector import SyncMetricsCollector


@dataclass
class TeamSyncConfig:
    """團隊同步配置"""
    team_name: str
    enabled_tables: List[Dict[str, Any]]
    jira_config: Dict[str, Any]
    lark_config: Dict[str, Any]
    user_mapping_config: Dict[str, Any]
    sync_settings: Dict[str, Any]


@dataclass
class SyncCoordinatorResult:
    """同步協調器結果"""
    success: bool
    total_teams: int
    total_tables: int
    successful_tables: int
    failed_tables: int
    total_processed: int
    total_created: int
    total_updated: int
    total_failed: int
    processing_time: float
    start_time: str
    end_time: str
    team_results: Dict[str, Any]
    error: Optional[str] = None


class SyncCoordinator:
    """同步協調器 - 系統最高層協調"""
    
    def __init__(self, config_manager, schema_path: str = "new/schema.yaml", 
                 base_data_dir: str = "data", logger=None):
        """
        初始化同步協調器
        
        Args:
            config_manager: 配置管理器
            schema_path: Schema 配置檔案路徑
            base_data_dir: 基礎資料目錄
            logger: 日誌記錄器（可選）
        """
        self.config_manager = config_manager
        self.schema_path = schema_path
        self.base_data_dir = Path(base_data_dir)
        self.base_data_dir.mkdir(exist_ok=True)
        
        # 設定日誌
        self.logger = logger or logging.getLogger(f"{__name__}.SyncCoordinator")
        
        # 初始化全局組件
        self.sync_state_manager = SyncStateManager(str(self.base_data_dir), self.logger)
        self.metrics_collector = SyncMetricsCollector(self.logger)
        
        # 組件快取
        self._jira_clients = {}
        self._lark_clients = {}
        self._field_processors = {}
        self._user_mappers = {}
        self._workflow_managers = {}
        
        # 同步統計
        self.reset_global_stats()
        
        self.logger.info("同步協調器初始化完成")
    
    def reset_global_stats(self):
        """重置全局統計"""
        self.global_stats = {
            'total_teams': 0,
            'total_tables': 0,
            'successful_tables': 0,
            'failed_tables': 0,
            'total_processed': 0,
            'total_created': 0,
            'total_updated': 0,
            'total_failed': 0
        }
    
    def sync_all_teams(self, full_update: bool = False) -> SyncCoordinatorResult:
        """
        同步所有啟用的團隊
        
        Args:
            full_update: 是否執行全量更新
            
        Returns:
            同步協調器結果
        """
        start_time = time.time()
        start_time_str = datetime.now().isoformat()
        
        self.reset_global_stats()
        team_results = {}
        
        try:
            self.logger.info("開始全團隊同步")
            
            # 獲取所有啟用的團隊
            enabled_teams = self.config_manager.get_enabled_teams()
            if not enabled_teams:
                self.logger.warning("沒有啟用的團隊")
                return SyncCoordinatorResult(
                    success=True,
                    total_teams=0,
                    total_tables=0,
                    successful_tables=0,
                    failed_tables=0,
                    total_processed=0,
                    total_created=0,
                    total_updated=0,
                    total_failed=0,
                    processing_time=time.time() - start_time,
                    start_time=start_time_str,
                    end_time=datetime.now().isoformat(),
                    team_results={}
                )
            
            # 並行處理所有團隊
            with ThreadPoolExecutor(max_workers=3) as executor:
                future_to_team = {
                    executor.submit(self.sync_team, team_name, full_update): team_name
                    for team_name in enabled_teams
                }
                
                for future in as_completed(future_to_team):
                    team_name = future_to_team[future]
                    try:
                        team_result = future.result()
                        team_results[team_name] = team_result
                        
                        # 更新全局統計
                        self._update_global_stats(team_result)
                        
                    except Exception as e:
                        self.logger.error(f"團隊 {team_name} 同步失敗: {e}")
                        team_results[team_name] = {
                            'success': False,
                            'error': str(e),
                            'total_tables': 0,
                            'successful_tables': 0,
                            'failed_tables': 1
                        }
                        self.global_stats['failed_tables'] += 1
            
            # 生成最終結果
            end_time_str = datetime.now().isoformat()
            processing_time = time.time() - start_time
            
            result = SyncCoordinatorResult(
                success=self.global_stats['failed_tables'] == 0,
                total_teams=len(enabled_teams),
                total_tables=self.global_stats['total_tables'],
                successful_tables=self.global_stats['successful_tables'],
                failed_tables=self.global_stats['failed_tables'],
                total_processed=self.global_stats['total_processed'],
                total_created=self.global_stats['total_created'],
                total_updated=self.global_stats['total_updated'],
                total_failed=self.global_stats['total_failed'],
                processing_time=processing_time,
                start_time=start_time_str,
                end_time=end_time_str,
                team_results=team_results
            )
            
            self.logger.info(f"全團隊同步完成: {result.successful_tables}/{result.total_tables} 表格成功, "
                           f"耗時 {processing_time:.2f} 秒")
            
            # 收集指標
            self.metrics_collector.record_sync_session(result)
            
            return result
            
        except Exception as e:
            self.logger.error(f"全團隊同步失敗: {e}")
            return SyncCoordinatorResult(
                success=False,
                total_teams=0,
                total_tables=0,
                successful_tables=0,
                failed_tables=0,
                total_processed=0,
                total_created=0,
                total_updated=0,
                total_failed=0,
                processing_time=time.time() - start_time,
                start_time=start_time_str,
                end_time=datetime.now().isoformat(),
                team_results=team_results,
                error=str(e)
            )
    
    def sync_team(self, team_name: str, full_update: bool = False) -> Dict[str, Any]:
        """
        同步指定團隊
        
        Args:
            team_name: 團隊名稱
            full_update: 是否執行全量更新
            
        Returns:
            團隊同步結果
        """
        start_time = time.time()
        
        try:
            self.logger.info(f"開始團隊同步: {team_name}")
            
            # 獲取團隊配置
            team_config = self._get_team_sync_config(team_name)
            if not team_config:
                return {
                    'success': False,
                    'error': f'找不到團隊配置: {team_name}',
                    'total_tables': 0,
                    'successful_tables': 0,
                    'failed_tables': 0
                }
            
            # 獲取工作流管理器
            workflow_manager = self._get_workflow_manager(team_name, team_config)
            
            # 同步所有啟用的表格
            table_results = {}
            successful_tables = 0
            failed_tables = 0
            
            for table_info in team_config.enabled_tables:
                table_name = table_info['name']
                table_id = table_info['table_id']
                jql_query = table_info['jql_query']
                
                try:
                    # 創建工作流配置
                    workflow_config = SyncWorkflowConfig(
                        table_id=table_id,
                        jql_query=jql_query,
                        ticket_field_name=table_info.get('ticket_field', 'Issue Key'),
                        enable_user_mapping=team_config.user_mapping_config.get('enabled', True),
                        enable_cold_start_detection=not full_update
                    )
                    
                    # 執行同步
                    sync_result = workflow_manager.execute_sync_workflow(workflow_config)
                    table_results[table_name] = sync_result
                    
                    if sync_result.success:
                        successful_tables += 1
                    else:
                        failed_tables += 1
                        
                except Exception as e:
                    self.logger.error(f"表格 {table_name} 同步失敗: {e}")
                    failed_tables += 1
                    table_results[table_name] = {
                        'success': False,
                        'error': str(e)
                    }
            
            # 生成團隊結果
            team_result = {
                'success': failed_tables == 0,
                'total_tables': len(team_config.enabled_tables),
                'successful_tables': successful_tables,
                'failed_tables': failed_tables,
                'processing_time': time.time() - start_time,
                'table_results': table_results
            }
            
            self.logger.info(f"團隊同步完成: {team_name}, "
                           f"{successful_tables}/{len(team_config.enabled_tables)} 表格成功")
            
            return team_result
            
        except Exception as e:
            self.logger.error(f"團隊同步失敗: {team_name}, {e}")
            return {
                'success': False,
                'error': str(e),
                'total_tables': 0,
                'successful_tables': 0,
                'failed_tables': 1,
                'processing_time': time.time() - start_time
            }
    
    def sync_single_table(self, team_name: str, table_name: str, 
                         full_update: bool = False) -> Dict[str, Any]:
        """
        同步單一表格
        
        Args:
            team_name: 團隊名稱
            table_name: 表格名稱
            full_update: 是否執行全量更新
            
        Returns:
            表格同步結果
        """
        try:
            self.logger.info(f"開始單一表格同步: {team_name}.{table_name}")
            
            # 獲取團隊配置
            team_config = self._get_team_sync_config(team_name)
            if not team_config:
                return {
                    'success': False,
                    'error': f'找不到團隊配置: {team_name}'
                }
            
            # 找到指定表格
            table_info = None
            for table in team_config.enabled_tables:
                if table['name'] == table_name:
                    table_info = table
                    break
            
            if not table_info:
                return {
                    'success': False,
                    'error': f'找不到表格配置: {table_name}'
                }
            
            # 獲取工作流管理器
            workflow_manager = self._get_workflow_manager(team_name, team_config)
            
            # 創建工作流配置
            workflow_config = SyncWorkflowConfig(
                table_id=table_info['table_id'],
                jql_query=table_info['jql_query'],
                ticket_field_name=table_info.get('ticket_field', 'Issue Key'),
                enable_user_mapping=team_config.user_mapping_config.get('enabled', True),
                enable_cold_start_detection=not full_update
            )
            
            # 執行同步
            sync_result = workflow_manager.execute_sync_workflow(workflow_config)
            
            self.logger.info(f"單一表格同步完成: {team_name}.{table_name}")
            
            return {
                'success': sync_result.success,
                'sync_result': sync_result,
                'table_name': table_name,
                'team_name': team_name
            }
            
        except Exception as e:
            self.logger.error(f"單一表格同步失敗: {team_name}.{table_name}, {e}")
            return {
                'success': False,
                'error': str(e),
                'table_name': table_name,
                'team_name': team_name
            }
    
    def sync_single_issue(self, team_name: str, table_name: str, 
                         issue_key: str) -> Dict[str, Any]:
        """
        同步單一 Issue
        
        Args:
            team_name: 團隊名稱
            table_name: 表格名稱
            issue_key: Issue Key
            
        Returns:
            Issue 同步結果
        """
        try:
            self.logger.info(f"開始單一 Issue 同步: {issue_key}")
            
            # 獲取團隊配置
            team_config = self._get_team_sync_config(team_name)
            if not team_config:
                return {
                    'success': False,
                    'error': f'找不到團隊配置: {team_name}'
                }
            
            # 找到指定表格
            table_info = None
            for table in team_config.enabled_tables:
                if table['name'] == table_name:
                    table_info = table
                    break
            
            if not table_info:
                return {
                    'success': False,
                    'error': f'找不到表格配置: {table_name}'
                }
            
            # 獲取工作流管理器
            workflow_manager = self._get_workflow_manager(team_name, team_config)
            
            # 創建工作流配置
            workflow_config = SyncWorkflowConfig(
                table_id=table_info['table_id'],
                jql_query=table_info['jql_query'],
                ticket_field_name=table_info.get('ticket_field', 'Issue Key'),
                enable_user_mapping=team_config.user_mapping_config.get('enabled', True)
            )
            
            # 執行單一 Issue 同步
            sync_result = workflow_manager.execute_single_issue_sync(workflow_config, issue_key)
            
            self.logger.info(f"單一 Issue 同步完成: {issue_key}")
            
            return {
                'success': sync_result.success,
                'sync_result': sync_result,
                'issue_key': issue_key,
                'table_name': table_name,
                'team_name': team_name
            }
            
        except Exception as e:
            self.logger.error(f"單一 Issue 同步失敗: {issue_key}, {e}")
            return {
                'success': False,
                'error': str(e),
                'issue_key': issue_key,
                'table_name': table_name,
                'team_name': team_name
            }
    
    def get_system_status(self) -> Dict[str, Any]:
        """
        獲取系統狀態
        
        Returns:
            系統狀態資訊
        """
        try:
            # 獲取所有團隊的狀態
            enabled_teams = self.config_manager.get_enabled_teams()
            team_statuses = {}
            
            for team_name in enabled_teams:
                team_config = self._get_team_sync_config(team_name)
                if team_config:
                    team_status = {
                        'total_tables': len(team_config.enabled_tables),
                        'table_statuses': {}
                    }
                    
                    for table_info in team_config.enabled_tables:
                        table_status = self.sync_state_manager.get_sync_state_summary(
                            table_info['table_id']
                        )
                        team_status['table_statuses'][table_info['name']] = table_status
                    
                    team_statuses[team_name] = team_status
            
            # 獲取指標統計
            metrics_summary = self.metrics_collector.get_metrics_summary()
            
            return {
                'system_healthy': True,
                'total_teams': len(enabled_teams),
                'team_statuses': team_statuses,
                'metrics_summary': metrics_summary,
                'data_directory': str(self.base_data_dir),
                'schema_path': self.schema_path
            }
            
        except Exception as e:
            self.logger.error(f"獲取系統狀態失敗: {e}")
            return {
                'system_healthy': False,
                'error': str(e)
            }
    
    def cleanup_old_data(self, days_to_keep: int = 30) -> Dict[str, Any]:
        """
        清理舊資料
        
        Args:
            days_to_keep: 保留天數
            
        Returns:
            清理結果
        """
        try:
            self.logger.info(f"開始清理舊資料，保留 {days_to_keep} 天")
            
            # 清理處理日誌
            cleanup_result = self.sync_state_manager.cleanup_old_records(days_to_keep)
            
            # 清理指標資料
            metrics_cleanup = self.metrics_collector.cleanup_old_metrics(days_to_keep)
            
            # 優化資料庫
            vacuum_result = self.sync_state_manager.vacuum_databases()
            
            result = {
                'success': True,
                'days_to_keep': days_to_keep,
                'processing_logs_cleaned': cleanup_result.get('total_cleaned', 0),
                'metrics_cleaned': metrics_cleanup.get('total_cleaned', 0),
                'databases_vacuumed': vacuum_result.get('success_count', 0)
            }
            
            self.logger.info(f"舊資料清理完成: {result}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"清理舊資料失敗: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _get_team_sync_config(self, team_name: str) -> Optional[TeamSyncConfig]:
        """獲取團隊同步配置"""
        try:
            team_config = self.config_manager.get_team_config(team_name)
            if not team_config:
                return None
            
            enabled_tables = self.config_manager.get_enabled_tables(team_name)
            jira_config = self.config_manager.get_jira_config()
            lark_config = self.config_manager.get_lark_base_config()
            user_mapping_config = self.config_manager.get_user_mapping_config()
            
            return TeamSyncConfig(
                team_name=team_name,
                enabled_tables=enabled_tables,
                jira_config=jira_config,
                lark_config=lark_config,
                user_mapping_config=user_mapping_config,
                sync_settings=team_config.get('sync_settings', {})
            )
            
        except Exception as e:
            self.logger.error(f"獲取團隊配置失敗: {team_name}, {e}")
            return None
    
    def _get_workflow_manager(self, team_name: str, team_config: TeamSyncConfig) -> SyncWorkflowManager:
        """獲取工作流管理器"""
        if team_name not in self._workflow_managers:
            # 初始化所需組件
            jira_client = self._get_jira_client(team_config.jira_config)
            lark_client = self._get_lark_client(team_config.lark_config)
            field_processor = self._get_field_processor(team_config.jira_config)
            user_mapper = self._get_user_mapper(team_config)
            
            # 創建工作流管理器
            self._workflow_managers[team_name] = SyncWorkflowManager(
                jira_client=jira_client,
                lark_client=lark_client,
                field_processor=field_processor,
                user_mapper=user_mapper,
                sync_state_manager=self.sync_state_manager,
                logger=self.logger
            )
        
        return self._workflow_managers[team_name]
    
    def _get_jira_client(self, jira_config: Dict[str, Any]) -> JiraClient:
        """獲取 JIRA 客戶端"""
        config_key = f"{jira_config['server_url']}_{jira_config['username']}"
        
        if config_key not in self._jira_clients:
            self._jira_clients[config_key] = JiraClient(
                server_url=jira_config['server_url'],
                username=jira_config['username'],
                password=jira_config['password'],
                logger=self.logger
            )
        
        return self._jira_clients[config_key]
    
    def _get_lark_client(self, lark_config: Dict[str, Any]) -> LarkClient:
        """獲取 Lark 客戶端"""
        config_key = f"{lark_config['app_id']}_{lark_config['app_secret']}"
        
        if config_key not in self._lark_clients:
            self._lark_clients[config_key] = LarkClient(
                app_id=lark_config['app_id'],
                app_secret=lark_config['app_secret']
            )
        
        return self._lark_clients[config_key]
    
    def _get_field_processor(self, jira_config: Dict[str, Any]) -> FieldProcessor:
        """獲取欄位處理器"""
        if 'field_processor' not in self._field_processors:
            self._field_processors['field_processor'] = FieldProcessor(
                schema_path=self.schema_path,
                jira_server_url=jira_config['server_url'],
                logger=self.logger
            )
        
        return self._field_processors['field_processor']
    
    def _get_user_mapper(self, team_config: TeamSyncConfig) -> Optional[UserMapper]:
        """獲取用戶映射器"""
        if not team_config.user_mapping_config.get('enabled', True):
            return None
        
        config_key = f"{team_config.team_name}_user_mapper"
        
        if config_key not in self._user_mappers:
            lark_client = self._get_lark_client(team_config.lark_config)
            
            self._user_mappers[config_key] = UserMapper(
                sync_logger=self.logger,
                config_manager=self.config_manager,
                lark_client=lark_client
            )
        
        return self._user_mappers[config_key]
    
    def _update_global_stats(self, team_result: Dict[str, Any]):
        """更新全局統計"""
        self.global_stats['total_teams'] += 1
        self.global_stats['total_tables'] += team_result.get('total_tables', 0)
        self.global_stats['successful_tables'] += team_result.get('successful_tables', 0)
        self.global_stats['failed_tables'] += team_result.get('failed_tables', 0)
        
        # 統計處理數量
        for table_result in team_result.get('table_results', {}).values():
            if hasattr(table_result, 'total_created'):
                self.global_stats['total_created'] += table_result.total_created
                self.global_stats['total_updated'] += table_result.total_updated
                self.global_stats['total_failed'] += table_result.failed_operations
                self.global_stats['total_processed'] += (
                    table_result.total_created + table_result.total_updated + table_result.failed_operations
                )


# 測試模組
if __name__ == '__main__':
    import logging
    from unittest.mock import Mock
    
    # 設定日誌
    logging.basicConfig(level=logging.INFO)
    
    try:
        # 創建模擬配置管理器
        mock_config_manager = Mock()
        mock_config_manager.get_enabled_teams.return_value = ['test_team']
        mock_config_manager.get_team_config.return_value = {'name': 'test_team'}
        mock_config_manager.get_enabled_tables.return_value = [
            {
                'name': 'test_table',
                'table_id': 'test_table_id',
                'jql_query': 'project = TEST'
            }
        ]
        mock_config_manager.get_jira_config.return_value = {
            'server_url': 'https://test.atlassian.net',
            'username': 'test',
            'password': 'test'
        }
        mock_config_manager.get_lark_base_config.return_value = {
            'app_id': 'test_app_id',
            'app_secret': 'test_app_secret'
        }
        mock_config_manager.get_user_mapping_config.return_value = {
            'enabled': True
        }
        
        # 創建同步協調器
        coordinator = SyncCoordinator(
            config_manager=mock_config_manager,
            logger=logging.getLogger()
        )
        
        print("同步協調器測試:")
        print(f"資料目錄: {coordinator.base_data_dir}")
        
        # 測試系統狀態
        status = coordinator.get_system_status()
        print(f"系統狀態: {status.get('system_healthy', False)}")
        
        print("同步協調器測試完成")
        
    except Exception as e:
        print(f"測試失敗: {e}")
        import traceback
        traceback.print_exc()