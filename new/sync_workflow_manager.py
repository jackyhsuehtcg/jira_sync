#!/usr/bin/env python3
"""
同步工作流管理器

負責業務邏輯整合和工作流程管理：
- 整合所有同步組件
- 實現完整的同步工作流程
- 冷啟動和增量同步邏輯
- 錯誤處理和重試機制
- 業務規則和驗證

設計理念：
- 組合多個專門組件實現複雜業務邏輯
- 清晰的工作流程步驟
- 強健的錯誤處理
- 靈活的配置和擴展
"""

import time
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

from jira_client import JiraClient
from lark_client import LarkClient
from field_processor import FieldProcessor
from user_mapper import UserMapper
from sync_state_manager import SyncStateManager
from sync_batch_processor import SyncBatchProcessor, SyncOperation


@dataclass
class SyncWorkflowConfig:
    """同步工作流配置"""
    table_id: str
    jql_query: str
    ticket_field_name: str = "Issue Key"
    enable_user_mapping: bool = True
    batch_size: int = 100
    max_retries: int = 3
    retry_delay: float = 1.0
    enable_cold_start_detection: bool = True


@dataclass
class SyncWorkflowResult:
    """同步工作流結果"""
    table_id: str
    success: bool
    total_jira_issues: int
    filtered_issues: int
    created_records: int
    updated_records: int
    failed_operations: int
    processing_time: float
    is_cold_start: bool
    error: Optional[str] = None
    detailed_stats: Optional[Dict[str, Any]] = None


class SyncWorkflowManager:
    """同步工作流管理器"""
    
    def __init__(self, jira_client: JiraClient, lark_client: LarkClient,
                 field_processor: FieldProcessor, user_mapper: UserMapper = None,
                 sync_state_manager: SyncStateManager = None, logger=None):
        """
        初始化同步工作流管理器
        
        Args:
            jira_client: JIRA 客戶端
            lark_client: Lark 客戶端
            field_processor: 欄位處理器
            user_mapper: 用戶映射器（可選）
            sync_state_manager: 同步狀態管理器（可選）
            logger: 日誌記錄器（可選）
        """
        self.jira_client = jira_client
        self.lark_client = lark_client
        self.field_processor = field_processor
        self.user_mapper = user_mapper
        
        # 設定日誌
        self.logger = logger or logging.getLogger(f"{__name__}.SyncWorkflowManager")
        
        # 初始化狀態管理器
        self.sync_state_manager = sync_state_manager or SyncStateManager(logger=self.logger)
        
        # 初始化批次處理器
        self.batch_processor = SyncBatchProcessor(
            lark_client=lark_client,
            field_processor=field_processor,
            user_mapper=user_mapper,
            logger=self.logger
        )
        
        self.logger.info("同步工作流管理器初始化完成")
    
    def execute_sync_workflow(self, config: SyncWorkflowConfig) -> SyncWorkflowResult:
        """
        執行同步工作流程
        
        Args:
            config: 同步工作流配置
            
        Returns:
            同步工作流結果
        """
        start_time = time.time()
        
        try:
            self.logger.info(f"開始同步工作流程: {config.table_id}")
            
            # 步驟 1: 檢查是否需要冷啟動
            is_cold_start = self._check_cold_start(config)
            
            # 步驟 2: 獲取 JIRA 資料
            jira_issues = self._fetch_jira_issues(config)
            if not jira_issues:
                return SyncWorkflowResult(
                    table_id=config.table_id,
                    success=True,
                    total_jira_issues=0,
                    filtered_issues=0,
                    created_records=0,
                    updated_records=0,
                    failed_operations=0,
                    processing_time=time.time() - start_time,
                    is_cold_start=is_cold_start
                )
            
            # 步驟 3: 冷啟動處理（如果需要）
            if is_cold_start:
                cold_start_result = self._handle_cold_start(config)
                if not cold_start_result:
                    return SyncWorkflowResult(
                        table_id=config.table_id,
                        success=False,
                        total_jira_issues=len(jira_issues),
                        filtered_issues=0,
                        created_records=0,
                        updated_records=0,
                        failed_operations=0,
                        processing_time=time.time() - start_time,
                        is_cold_start=is_cold_start,
                        error="冷啟動失敗"
                    )
            
            # 步驟 4: 過濾需要處理的 Issues
            filtered_issues, filter_stats = self._filter_issues_for_processing(config, jira_issues)
            
            # 步驟 5: 決定同步操作類型
            sync_operations = self._determine_sync_operations(config, filtered_issues)
            
            # 步驟 6: 執行批次同步
            sync_results = self._execute_batch_sync(config, sync_operations)
            
            # 步驟 7: 記錄同步結果
            self._record_sync_results(config, sync_results)
            
            # 步驟 8: 生成最終結果
            final_result = self._generate_final_result(
                config, jira_issues, filtered_issues, sync_results, 
                start_time, is_cold_start
            )
            
            self.logger.info(f"同步工作流程完成: {final_result.created_records} 創建, "
                           f"{final_result.updated_records} 更新, "
                           f"{final_result.failed_operations} 失敗")
            
            return final_result
            
        except Exception as e:
            self.logger.error(f"同步工作流程失敗: {e}")
            return SyncWorkflowResult(
                table_id=config.table_id,
                success=False,
                total_jira_issues=0,
                filtered_issues=0,
                created_records=0,
                updated_records=0,
                failed_operations=0,
                processing_time=time.time() - start_time,
                is_cold_start=False,
                error=str(e)
            )
    
    def _check_cold_start(self, config: SyncWorkflowConfig) -> bool:
        """
        檢查是否需要冷啟動
        
        Args:
            config: 同步工作流配置
            
        Returns:
            是否需要冷啟動
        """
        if not config.enable_cold_start_detection:
            return False
        
        try:
            is_cold_start = self.sync_state_manager.is_cold_start(config.table_id)
            if is_cold_start:
                self.logger.info(f"檢測到冷啟動需求: {config.table_id}")
            return is_cold_start
        except Exception as e:
            self.logger.error(f"冷啟動檢查失敗: {e}")
            return True  # 錯誤時預設為冷啟動
    
    def _fetch_jira_issues(self, config: SyncWorkflowConfig) -> List[Dict[str, Any]]:
        """
        獲取 JIRA Issues
        
        Args:
            config: 同步工作流配置
            
        Returns:
            JIRA Issues 列表
        """
        try:
            self.logger.info(f"獲取 JIRA 資料: {config.jql_query}")
            
            # 使用 JIRA 客戶端獲取資料
            jira_issues = self.jira_client.search_issues(config.jql_query)
            
            if isinstance(jira_issues, dict):
                # 如果返回的是字典格式，轉換為列表
                issues_list = list(jira_issues.values())
            else:
                issues_list = jira_issues
            
            self.logger.info(f"獲取到 {len(issues_list)} 筆 JIRA Issues")
            return issues_list
            
        except Exception as e:
            self.logger.error(f"獲取 JIRA 資料失敗: {e}")
            return []
    
    def _handle_cold_start(self, config: SyncWorkflowConfig) -> bool:
        """
        處理冷啟動
        
        Args:
            config: 同步工作流配置
            
        Returns:
            是否成功
        """
        try:
            self.logger.info(f"執行冷啟動: {config.table_id}")
            
            # 獲取現有 Lark 記錄
            existing_records = self.lark_client.get_all_records(config.table_id)
            
            # 準備冷啟動
            cold_start_result = self.sync_state_manager.prepare_cold_start(
                config.table_id, existing_records, config.ticket_field_name
            )
            
            if cold_start_result['success']:
                self.logger.info(f"冷啟動完成: {cold_start_result['recorded_count']} 筆記錄已註冊")
                return True
            else:
                self.logger.error(f"冷啟動失敗: {cold_start_result}")
                return False
                
        except Exception as e:
            self.logger.error(f"冷啟動處理失敗: {e}")
            return False
    
    def _filter_issues_for_processing(self, config: SyncWorkflowConfig, 
                                    jira_issues: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        過濾需要處理的 Issues
        
        Args:
            config: 同步工作流配置
            jira_issues: JIRA Issues 列表
            
        Returns:
            (過濾後的 Issues, 過濾統計)
        """
        try:
            filtered_issues, filter_stats = self.sync_state_manager.filter_issues_for_processing(
                config.table_id, jira_issues
            )
            
            self.logger.info(f"Issues 過濾: {filter_stats['total_issues']} → "
                           f"{filter_stats['filtered_issues']} 筆 "
                           f"({filter_stats['filter_rate']:.1f}% 過濾)")
            
            return filtered_issues, filter_stats
            
        except Exception as e:
            self.logger.error(f"Issues 過濾失敗: {e}")
            return jira_issues, {'total_issues': len(jira_issues), 'filtered_issues': len(jira_issues)}
    
    def _determine_sync_operations(self, config: SyncWorkflowConfig, 
                                 filtered_issues: List[Dict[str, Any]]) -> List[SyncOperation]:
        """
        決定同步操作
        
        Args:
            config: 同步工作流配置
            filtered_issues: 過濾後的 Issues
            
        Returns:
            同步操作列表
        """
        try:
            # 使用狀態管理器決定操作類型
            operations_dict = self.sync_state_manager.determine_sync_operations(
                config.table_id, filtered_issues
            )
            
            # 轉換為 SyncOperation 物件
            sync_operations = self.batch_processor.create_sync_operations_from_issues(
                operations_dict['create'],
                operations_dict['update']
            )
            
            self.logger.info(f"同步操作決定: {len(operations_dict['create'])} 創建, "
                           f"{len(operations_dict['update'])} 更新")
            
            return sync_operations
            
        except Exception as e:
            self.logger.error(f"決定同步操作失敗: {e}")
            return []
    
    def _execute_batch_sync(self, config: SyncWorkflowConfig, 
                          sync_operations: List[SyncOperation]) -> List[Any]:
        """
        執行批次同步
        
        Args:
            config: 同步工作流配置
            sync_operations: 同步操作列表
            
        Returns:
            同步結果列表
        """
        try:
            if not sync_operations:
                self.logger.info("沒有需要同步的操作")
                return []
            
            # 執行批次處理
            sync_results = self.batch_processor.process_sync_operations(
                config.table_id, sync_operations
            )
            
            return sync_results
            
        except Exception as e:
            self.logger.error(f"批次同步失敗: {e}")
            return []
    
    def _record_sync_results(self, config: SyncWorkflowConfig, sync_results: List[Any]):
        """
        記錄同步結果
        
        Args:
            config: 同步工作流配置
            sync_results: 同步結果列表
        """
        try:
            if not sync_results:
                return
            
            # 轉換結果格式
            processing_results = []
            for result in sync_results:
                processing_results.append({
                    'issue_key': result.issue_key,
                    'jira_updated_time': result.jira_updated_time or 0,
                    'success': result.success,
                    'lark_record_id': result.lark_record_id,
                    'error': result.error
                })
            
            # 記錄到狀態管理器
            record_stats = self.sync_state_manager.record_sync_results(
                config.table_id, processing_results
            )
            
            self.logger.info(f"同步結果記錄: {record_stats['success']} 成功, "
                           f"{record_stats['error']} 失敗")
            
        except Exception as e:
            self.logger.error(f"記錄同步結果失敗: {e}")
    
    def _generate_final_result(self, config: SyncWorkflowConfig, 
                             jira_issues: List[Dict[str, Any]],
                             filtered_issues: List[Dict[str, Any]],
                             sync_results: List[Any],
                             start_time: float,
                             is_cold_start: bool) -> SyncWorkflowResult:
        """
        生成最終結果
        
        Args:
            config: 同步工作流配置
            jira_issues: 原始 JIRA Issues
            filtered_issues: 過濾後的 Issues
            sync_results: 同步結果
            start_time: 開始時間
            is_cold_start: 是否冷啟動
            
        Returns:
            同步工作流結果
        """
        # 統計結果
        created_count = sum(1 for r in sync_results if r.operation_type == 'create' and r.success)
        updated_count = sum(1 for r in sync_results if r.operation_type == 'update' and r.success)
        failed_count = sum(1 for r in sync_results if not r.success)
        
        # 獲取詳細統計
        batch_stats = self.batch_processor.get_processing_stats()
        
        return SyncWorkflowResult(
            table_id=config.table_id,
            success=True,
            total_jira_issues=len(jira_issues),
            filtered_issues=len(filtered_issues),
            created_records=created_count,
            updated_records=updated_count,
            failed_operations=failed_count,
            processing_time=time.time() - start_time,
            is_cold_start=is_cold_start,
            detailed_stats=batch_stats
        )
    
    def execute_single_issue_sync(self, config: SyncWorkflowConfig, 
                                issue_key: str) -> SyncWorkflowResult:
        """
        執行單一 Issue 同步
        
        Args:
            config: 同步工作流配置
            issue_key: Issue Key
            
        Returns:
            同步工作流結果
        """
        start_time = time.time()
        
        try:
            self.logger.info(f"開始單一 Issue 同步: {issue_key}")
            
            # 構建 JQL 查詢
            single_issue_jql = f"key = {issue_key}"
            
            # 創建單一 Issue 配置
            single_config = SyncWorkflowConfig(
                table_id=config.table_id,
                jql_query=single_issue_jql,
                ticket_field_name=config.ticket_field_name,
                enable_user_mapping=config.enable_user_mapping,
                enable_cold_start_detection=False  # 單一 Issue 不需要冷啟動
            )
            
            # 執行同步工作流程
            result = self.execute_sync_workflow(single_config)
            
            self.logger.info(f"單一 Issue 同步完成: {issue_key}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"單一 Issue 同步失敗: {e}")
            return SyncWorkflowResult(
                table_id=config.table_id,
                success=False,
                total_jira_issues=0,
                filtered_issues=0,
                created_records=0,
                updated_records=0,
                failed_operations=1,
                processing_time=time.time() - start_time,
                is_cold_start=False,
                error=str(e)
            )
    
    def get_sync_status(self, table_id: str) -> Dict[str, Any]:
        """
        獲取同步狀態
        
        Args:
            table_id: 表格 ID
            
        Returns:
            同步狀態資訊
        """
        try:
            return self.sync_state_manager.get_sync_state_summary(table_id)
        except Exception as e:
            self.logger.error(f"獲取同步狀態失敗: {e}")
            return {'error': str(e)}
    
    def cleanup_old_data(self, table_id: str = None, days_to_keep: int = 30) -> Dict[str, Any]:
        """
        清理舊資料
        
        Args:
            table_id: 表格 ID（可選）
            days_to_keep: 保留天數
            
        Returns:
            清理結果
        """
        try:
            return self.sync_state_manager.cleanup_old_records(days_to_keep, table_id)
        except Exception as e:
            self.logger.error(f"清理舊資料失敗: {e}")
            return {'error': str(e)}


# 測試模組
if __name__ == '__main__':
    import logging
    from unittest.mock import Mock
    
    # 設定日誌
    logging.basicConfig(level=logging.DEBUG)
    
    try:
        # 創建模擬客戶端
        mock_jira_client = Mock()
        mock_jira_client.search_issues.return_value = [
            {'key': 'TEST-001', 'fields': {'summary': 'Test 1', 'updated': '2023-01-01T00:00:00.000+0000'}},
            {'key': 'TEST-002', 'fields': {'summary': 'Test 2', 'updated': '2023-01-02T00:00:00.000+0000'}}
        ]
        
        mock_lark_client = Mock()
        mock_lark_client.get_all_records.return_value = []
        mock_lark_client.batch_create_records.return_value = (True, ['rec_1', 'rec_2'], [])
        
        mock_field_processor = Mock()
        mock_field_processor.process_issues.return_value = {
            'TEST-001': {'Issue Key': 'TEST-001', 'Title': 'Test 1'},
            'TEST-002': {'Issue Key': 'TEST-002', 'Title': 'Test 2'}
        }
        
        # 創建工作流管理器
        workflow_manager = SyncWorkflowManager(
            jira_client=mock_jira_client,
            lark_client=mock_lark_client,
            field_processor=mock_field_processor,
            logger=logging.getLogger()
        )
        
        print("同步工作流管理器測試:")
        
        # 創建測試配置
        config = SyncWorkflowConfig(
            table_id='test_table',
            jql_query='project = TEST',
            ticket_field_name='Issue Key'
        )
        
        # 執行同步工作流程
        result = workflow_manager.execute_sync_workflow(config)
        
        print(f"同步結果: {'成功' if result.success else '失敗'}")
        print(f"統計: {result.total_jira_issues} 總計, {result.filtered_issues} 過濾, "
              f"{result.created_records} 創建, {result.updated_records} 更新")
        
        print("同步工作流管理器測試完成")
        
    except Exception as e:
        print(f"測試失敗: {e}")
        import traceback
        traceback.print_exc()