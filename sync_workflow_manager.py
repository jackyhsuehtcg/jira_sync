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
    excluded_fields: List[str] = None
    
    def __post_init__(self):
        if self.excluded_fields is None:
            self.excluded_fields = []


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
    
    def _get_filtered_field_mappings(self, table_id: str, original_mappings: Dict[str, Any], excluded_fields: List[str] = None) -> Tuple[Dict[str, Any], List[str]]:
        """
        獲取過濾後的欄位映射（只包含 Lark Base 表格中實際存在的欄位，並排除指定欄位）
        
        Args:
            table_id: 表格 ID
            original_mappings: 原始欄位映射配置
            excluded_fields: 排除不同步的欄位清單
            
        Returns:
            Tuple[Dict[str, Any], List[str]]: (過濾後的欄位映射配置, 可用欄位列表)
        """
        try:
            # 獲取表格的可用欄位列表（添加更詳細的日誌）
            self.logger.info(f"正在獲取表格 {table_id} 的欄位列表...")
            available_fields = self.lark_client.get_available_field_names(table_id)
            if not available_fields:
                self.logger.warning(f"無法獲取表格 {table_id} 的欄位列表，使用原始配置")
                return original_mappings, []
            self.logger.info(f"成功獲取表格 {table_id} 的欄位列表")
            
            self.logger.info(f"表格 {table_id} 可用欄位: {len(available_fields)} 個")
            self.logger.debug(f"可用欄位列表: {available_fields}")
            
            # 過濾欄位映射
            filtered_mappings = {}
            skipped_fields = []
            excluded_fields = excluded_fields or []
            
            for jira_field, config in original_mappings.items():
                lark_field = config.get('lark_field')
                
                # 檢查是否在排除清單中
                if jira_field in excluded_fields:
                    skipped_fields.append(f"{jira_field} -> {lark_field} (excluded)")
                    continue
                
                # 檢查是否有匹配的欄位
                has_match = False
                if isinstance(lark_field, list):
                    # 數組形式，檢查是否有任何一個在 available_fields 中
                    for possible_field in lark_field:
                        if possible_field in available_fields:
                            has_match = True
                            break
                elif lark_field and lark_field in available_fields:
                    # 單一欄位形式
                    has_match = True
                
                if has_match:
                    filtered_mappings[jira_field] = config
                else:
                    # 顯示跳過的欄位信息
                    if isinstance(lark_field, list):
                        skipped_fields.append(f"{jira_field} -> {lark_field} (not found)")
                    else:
                        skipped_fields.append(f"{jira_field} -> {lark_field} (not found)")
            
            if skipped_fields:
                self.logger.info(f"跳過 {len(skipped_fields)} 個不存在的欄位: {skipped_fields}")
            
            self.logger.info(f"動態欄位過濾完成: {len(original_mappings)} -> {len(filtered_mappings)} 個欄位")
            
            return filtered_mappings, available_fields
            
        except Exception as e:
            self.logger.warning(f"動態欄位過濾失敗: {e}，使用原始配置")
            return original_mappings, []
    
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
            
            # 步驟 2: 獲取 JIRA 資料（full-update 模式跳過此步驟）
            if not config.enable_cold_start_detection:
                # Full-update 模式：直接跳過，在後續步驟中從 Lark 獲取
                jira_issues = []
                self.logger.info("Full-update 模式：跳過初始 JIRA 資料獲取")
            else:
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
            
            # 步驟 6-7: 執行批次同步（使用事務）
            sync_results = self._execute_batch_sync_with_transaction(config, sync_operations)
            
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
            
            # 獲取 schema 中定義的必要欄位（性能優化）
            required_fields = self.field_processor.get_required_jira_fields()
            
            # 使用 JIRA 客戶端獲取資料，只獲取必要欄位
            jira_issues = self.jira_client.search_issues(
                jql=config.jql_query,
                fields=required_fields
            )
            
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
    
    def _extract_ticket_key(self, ticket_value: Any) -> Optional[str]:
        """
        從票據欄位值中提取 Issue Key
        
        Args:
            ticket_value: 票據欄位值（可能是文字、連結或陣列）
            
        Returns:
            提取的 Issue Key 或 None
        """
        try:
            if not ticket_value:
                return None
                
            # 處理不同類型的票據欄位值
            if isinstance(ticket_value, dict):
                # 連結類型，取 text 值
                ticket_key = ticket_value.get('text', '').strip()
            elif isinstance(ticket_value, list) and ticket_value:
                # 陣列類型，取第一個元素
                first_item = ticket_value[0]
                if isinstance(first_item, dict):
                    ticket_key = first_item.get('text', '').strip()
                else:
                    ticket_key = str(first_item).strip()
            else:
                # 純文字值
                ticket_key = str(ticket_value).strip()
            
            # 驗證是否為有效的 Issue Key 格式（如 TP-3153, ICR-123）
            if ticket_key and '-' in ticket_key:
                return ticket_key
                
        except Exception as e:
            self.logger.warning(f"提取 Issue Key 失敗: {e}")
            
        return None
    
    def _fetch_jira_issues_in_batches(self, issue_keys: List[str], required_fields: List[str], 
                                     batch_size: int = 50) -> List[Dict[str, Any]]:
        """
        分批從 JIRA 獲取 Issues，避免 URI 過長
        
        Args:
            issue_keys: Issue Keys 列表
            required_fields: 需要的欄位列表
            batch_size: 批次大小（預設 50）
            
        Returns:
            JIRA Issues 資料列表
        """
        if not issue_keys:
            return []
        
        all_issues = []
        total_batches = (len(issue_keys) + batch_size - 1) // batch_size
        
        self.logger.info(f"分批獲取 {len(issue_keys)} 個 Issue Keys，批次大小 {batch_size}，共 {total_batches} 批")
        
        for i in range(0, len(issue_keys), batch_size):
            batch_keys = issue_keys[i:i + batch_size]
            batch_num = i // batch_size + 1
            
            try:
                keys_str = ', '.join([f'"{key}"' for key in batch_keys])
                jql = f"key IN ({keys_str})"
                
                self.logger.debug(f"批次 {batch_num}/{total_batches}: 獲取 {len(batch_keys)} 個 Issues")
                
                # 獲取這批 Issues
                batch_issues_dict = self.jira_client.search_issues(jql, required_fields)
                batch_issues = list(batch_issues_dict.values())
                
                all_issues.extend(batch_issues)
                
                self.logger.debug(f"批次 {batch_num}/{total_batches}: 成功獲取 {len(batch_issues)} 個 Issues")
                
            except Exception as e:
                self.logger.error(f"批次 {batch_num}/{total_batches} 獲取失敗: {e}")
                # 繼續處理下一批，不中斷整個流程
                continue
        
        # 統計結果
        found_keys = set(issue['key'] for issue in all_issues)
        missing_keys = set(issue_keys) - found_keys
        
        if missing_keys:
            self.logger.warning(f"未找到 {len(missing_keys)} 個 Issue Keys: {list(missing_keys)[:10]}...")
        
        self.logger.info(f"分批獲取完成：成功獲取 {len(all_issues)} 筆 JIRA Issues")
        return all_issues
    
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
            # 在 full-update 模式下 (enable_cold_start_detection=False)，從 Lark 表格獲取 Issue Keys
            if not config.enable_cold_start_detection:
                self.logger.info("Full-update 模式：從 Lark 表格獲取現有記錄")
                
                # 1. 從 Lark 表格獲取所有記錄
                existing_records = self.lark_client.get_all_records(config.table_id)
                
                # 2. 提取 Issue Keys 並使用字典自動去重
                issue_keys_dict = {}
                for record in existing_records:
                    fields = record.get('fields', {})
                    ticket_value = fields.get(config.ticket_field_name)
                    
                    ticket_key = self._extract_ticket_key(ticket_value)
                    if ticket_key:
                        issue_keys_dict[ticket_key] = True  # 字典自動去重
                
                # 3. 根據 Issue Keys 從 JIRA 分批獲取最新資料
                if issue_keys_dict:
                    keys_list = list(issue_keys_dict.keys())
                    
                    # 獲取必要欄位
                    required_fields = self.field_processor.get_required_jira_fields()
                    
                    # 使用分批處理方法
                    filtered_issues = self._fetch_jira_issues_in_batches(keys_list, required_fields, batch_size=50)
                else:
                    filtered_issues = []
                
                filter_stats = {
                    'total_lark_records': len(existing_records),
                    'extracted_keys': len(issue_keys_dict),
                    'fetched_issues': len(filtered_issues),
                    'total_issues': len(filtered_issues),
                    'filtered_issues': len(filtered_issues),
                    'skipped_issues': 0,
                    'filter_rate': 0
                }
                
                self.logger.info(f"Full-update 模式統計: Lark 記錄 {len(existing_records)} → "
                               f"Issue Keys {len(issue_keys_dict)} → JIRA Issues {len(filtered_issues)}")
            else:
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
            # 在 full-update 模式下，強制所有已存在記錄都進行更新
            if not config.enable_cold_start_detection:
                self.logger.info("Full-update 模式：強制更新所有已存在記錄")
                operations_dict = self.sync_state_manager.determine_sync_operations_with_force_update(
                    config.table_id, filtered_issues
                )
            else:
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
            
            # 獲取動態過濾的欄位映射
            filtered_field_mappings, available_fields = self._get_filtered_field_mappings(
                config.table_id, self.field_processor.field_mappings, config.excluded_fields
            )
            
            # 執行批次處理  
            # 注意：excluded_fields 已經在 _get_filtered_field_mappings 中處理過了
            sync_results = self.batch_processor.process_sync_operations(
                config.table_id, sync_operations, filtered_field_mappings, available_fields
            )
            
            return sync_results
            
        except Exception as e:
            self.logger.error(f"批次同步失敗: {e}")
            return []
    
    def _execute_batch_sync_with_transaction(self, config: SyncWorkflowConfig, 
                                           sync_operations: List[SyncOperation]) -> List[Any]:
        """
        使用事務執行批次同步
        
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
            
            # 使用事務執行同步和記錄
            log_manager = self.sync_state_manager.get_processing_log_manager(config.table_id)
            
            with log_manager._get_transaction() as transaction_conn:
                # 1. 獲取動態過濾的欄位映射
                filtered_field_mappings, available_fields = self._get_filtered_field_mappings(
                    config.table_id, self.field_processor.field_mappings, config.excluded_fields
                )
                
                # 2. 執行批次處理
                # 注意：excluded_fields 已經在 _get_filtered_field_mappings 中處理過了  
                sync_results = self.batch_processor.process_sync_operations(
                    config.table_id, sync_operations, filtered_field_mappings, available_fields
                )
                
                # 2. 檢查是否有任何失敗的操作
                failed_operations = [r for r in sync_results if not r.success]
                
                if failed_operations:
                    # 如果有失敗的操作，記錄錯誤並回滾事務
                    self.logger.warning(f"批次同步中有 {len(failed_operations)} 個失敗操作，回滾事務")
                    
                    # 拋出異常以觸發事務回滾
                    raise Exception(f"批次同步失敗: {len(failed_operations)} 個操作失敗")
                
                # 3. 所有操作都成功，記錄結果到事務中
                self.sync_state_manager.record_sync_results_with_transaction(
                    config.table_id, sync_results, transaction_conn
                )
                
                # 4. 如果執行到這裡，事務將自動提交
                self.logger.info(f"批次同步事務完成: {len(sync_results)} 個操作成功")
                
                return sync_results
            
        except Exception as e:
            self.logger.error(f"批次同步事務失敗: {e}")
            # 回滾事務（由 _get_transaction 自動處理）
            # 返回空結果表示失敗
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