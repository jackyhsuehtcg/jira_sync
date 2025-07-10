#!/usr/bin/env python3
"""
同步批次處理器

負責高效批次處理和衝突解決：
- 批次 create/update 操作
- 智能 upsert 邏輯實現
- 錯誤處理和重試機制
- 用戶映射整合
- 效能優化的並行處理

設計理念：
- 利用 Lark API 的 create_record/update_record 實現 upsert
- 批次操作提升效能
- 智能錯誤處理和重試
- 與 FieldProcessor 和 UserMapper 深度整合
"""

import time
import logging
from typing import Dict, List, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from field_processor import FieldProcessor
from user_mapper import UserMapper


@dataclass
class SyncOperation:
    """同步操作資料結構"""
    issue_key: str
    jira_issue: Dict[str, Any]
    operation_type: str  # 'create' or 'update'
    lark_record_id: Optional[str] = None
    processed_fields: Optional[Dict[str, Any]] = None
    jira_updated_time: Optional[int] = None


@dataclass
class SyncResult:
    """同步結果資料結構"""
    issue_key: str
    operation_type: str
    success: bool
    lark_record_id: Optional[str] = None
    error: Optional[str] = None
    jira_updated_time: Optional[int] = None
    processing_time: Optional[float] = None


class SyncBatchProcessor:
    """同步批次處理器"""
    
    def __init__(self, lark_client, field_processor: FieldProcessor = None, 
                 user_mapper: UserMapper = None, logger=None):
        """
        初始化同步批次處理器
        
        Args:
            lark_client: Lark Base 客戶端
            field_processor: 欄位處理器（可選）
            user_mapper: 用戶映射器（可選）
            logger: 日誌記錄器（可選）
        """
        self.lark_client = lark_client
        self.field_processor = field_processor
        self.user_mapper = user_mapper
        
        # 設定日誌
        self.logger = logger or logging.getLogger(f"{__name__}.SyncBatchProcessor")
        
        # 批次處理配置
        self.batch_size = 100  # 每批次處理數量
        self.max_workers = 5   # 最大並行工作者數
        self.retry_attempts = 3  # 重試次數
        self.retry_delay = 1.0   # 重試延遲（秒）
        
        # 統計計數器
        self.reset_stats()
        
        self.logger.info("同步批次處理器初始化完成")
    
    def reset_stats(self):
        """重置統計計數器"""
        self.stats = {
            'total_processed': 0,
            'successful_creates': 0,
            'successful_updates': 0,
            'failed_operations': 0,
            'field_processing_time': 0.0,
            'lark_api_time': 0.0,
            'total_time': 0.0,
            'user_mapping_stats': {
                'total_users': 0,
                'successful_mappings': 0,
                'pending_users': 0,
                'cache_hits': 0
            }
        }
    
    def process_sync_operations(self, table_id: str, sync_operations: List[SyncOperation], filtered_field_mappings: Dict[str, Any] = None, available_fields: List[str] = None) -> List[SyncResult]:
        """
        處理同步操作批次
        
        Args:
            table_id: 表格 ID
            sync_operations: 同步操作列表
            filtered_field_mappings: 過濾後的欄位映射（可選）
            available_fields: Lark 表格中可用的欄位列表（可選）
            
        Returns:
            同步結果列表
        """
        if not sync_operations:
            return []
        
        start_time = time.time()
        self.reset_stats()
        
        try:
            # 步驟 1：批次欄位處理
            self.logger.info(f"開始批次處理 {len(sync_operations)} 個同步操作")
            processed_operations = self._batch_process_fields(sync_operations, filtered_field_mappings, available_fields)
            
            # 步驟 2：分組執行 create/update 操作
            results = self._execute_sync_operations(table_id, processed_operations)
            
            # 步驟 3：統計和日誌
            self._finalize_processing_stats(start_time, results)
            
            return results
            
        except Exception as e:
            self.logger.error(f"批次處理失敗: {e}")
            # 返回失敗結果
            return [
                SyncResult(
                    issue_key=op.issue_key,
                    operation_type=op.operation_type,
                    success=False,
                    error=str(e),
                    jira_updated_time=op.jira_updated_time
                )
                for op in sync_operations
            ]
    
    def _batch_process_fields(self, sync_operations: List[SyncOperation], filtered_field_mappings: Dict[str, Any] = None, available_fields: List[str] = None) -> List[SyncOperation]:
        """
        批次處理欄位轉換
        
        Args:
            sync_operations: 同步操作列表
            filtered_field_mappings: 過濾後的欄位映射（可選）
            available_fields: Lark 表格中可用的欄位列表（可選）
            
        Returns:
            處理後的同步操作列表
        """
        if not self.field_processor:
            self.logger.warning("沒有欄位處理器，跳過欄位處理")
            return sync_operations
        
        field_start_time = time.time()
        
        try:
            # 準備批次資料
            raw_issues_dict = {op.issue_key: op.jira_issue for op in sync_operations}
            
            # 批次欄位處理
            if filtered_field_mappings is not None:
                if available_fields is not None:
                    # 使用動態票據欄位處理
                    processed_issues = self.field_processor.process_issues_with_dynamic_ticket_field(
                        raw_issues_dict, filtered_field_mappings, available_fields
                    )
                else:
                    # 使用過濾後的欄位映射
                    processed_issues = self.field_processor.process_issues_with_mappings(raw_issues_dict, filtered_field_mappings)
            else:
                # 使用原始欄位映射
                processed_issues = self.field_processor.process_issues(raw_issues_dict)
            
            # 更新操作物件
            processed_operations = []
            for op in sync_operations:
                processed_op = SyncOperation(
                    issue_key=op.issue_key,
                    jira_issue=op.jira_issue,
                    operation_type=op.operation_type,
                    lark_record_id=op.lark_record_id,
                    processed_fields=processed_issues.get(op.issue_key, {}),
                    jira_updated_time=op.jira_updated_time
                )
                processed_operations.append(processed_op)
            
            # 更新統計
            self.stats['field_processing_time'] = time.time() - field_start_time
            
            # 收集用戶映射統計
            if self.user_mapper:
                user_stats = self.user_mapper.report_pending_users()
                self.stats['user_mapping_stats']['pending_users'] = user_stats.get('pending_users_found', 0)
            
            self.logger.info(f"批次欄位處理完成: {len(processed_operations)} 筆")
            
            return processed_operations
            
        except Exception as e:
            self.logger.error(f"批次欄位處理失敗: {e}")
            raise
    
    def _execute_sync_operations(self, table_id: str, operations: List[SyncOperation]) -> List[SyncResult]:
        """
        執行同步操作
        
        Args:
            table_id: 表格 ID
            operations: 同步操作列表
            
        Returns:
            同步結果列表
        """
        if not operations:
            return []
        
        # 分組操作
        create_operations = [op for op in operations if op.operation_type == 'create']
        update_operations = [op for op in operations if op.operation_type == 'update']
        
        all_results = []
        
        # 執行創建操作
        if create_operations:
            create_results = self._execute_create_operations(table_id, create_operations)
            all_results.extend(create_results)
        
        # 執行更新操作
        if update_operations:
            update_results = self._execute_update_operations(table_id, update_operations)
            all_results.extend(update_results)
        
        return all_results
    
    def _execute_create_operations(self, table_id: str, operations: List[SyncOperation]) -> List[SyncResult]:
        """
        執行創建操作
        
        Args:
            table_id: 表格 ID
            operations: 創建操作列表
            
        Returns:
            創建結果列表
        """
        if not operations:
            return []
        
        results = []
        
        try:
            # 準備批次創建資料
            batch_records = []
            for op in operations:
                if op.processed_fields:
                    batch_records.append(op.processed_fields)
            
            if not batch_records:
                self.logger.warning("沒有有效的創建資料")
                return [
                    SyncResult(
                        issue_key=op.issue_key,
                        operation_type='create',
                        success=False,
                        error="沒有有效的欄位資料",
                        jira_updated_time=op.jira_updated_time
                    )
                    for op in operations
                ]
            
            # 執行批次創建
            api_start_time = time.time()
            success, created_ids, error_messages = self.lark_client.batch_create_records(
                table_id, batch_records
            )
            self.stats['lark_api_time'] += time.time() - api_start_time
            
            # 處理結果
            if success and len(created_ids) == len(operations):
                # 全部成功
                for i, op in enumerate(operations):
                    results.append(SyncResult(
                        issue_key=op.issue_key,
                        operation_type='create',
                        success=True,
                        lark_record_id=created_ids[i],
                        jira_updated_time=op.jira_updated_time
                    ))
                    self.stats['successful_creates'] += 1
                
                self.logger.info(f"批次創建成功: {len(created_ids)} 筆")
                
            else:
                # 部分失敗，需要逐個處理
                self.logger.warning(f"批次創建部分失敗，轉為逐個創建: {len(operations)} 筆")
                results = self._fallback_individual_creates(table_id, operations)
            
        except Exception as e:
            self.logger.error(f"批次創建失敗: {e}")
            # 嘗試逐個創建
            results = self._fallback_individual_creates(table_id, operations)
        
        return results
    
    def _fallback_individual_creates(self, table_id: str, operations: List[SyncOperation]) -> List[SyncResult]:
        """
        回退到逐個創建
        
        Args:
            table_id: 表格 ID
            operations: 創建操作列表
            
        Returns:
            創建結果列表
        """
        results = []
        
        for op in operations:
            try:
                if not op.processed_fields:
                    results.append(SyncResult(
                        issue_key=op.issue_key,
                        operation_type='create',
                        success=False,
                        error="沒有有效的欄位資料",
                        jira_updated_time=op.jira_updated_time
                    ))
                    continue
                
                # 單筆創建
                api_start_time = time.time()
                record_id = self.lark_client.create_record(table_id, op.processed_fields)
                self.stats['lark_api_time'] += time.time() - api_start_time
                
                if record_id:
                    results.append(SyncResult(
                        issue_key=op.issue_key,
                        operation_type='create',
                        success=True,
                        lark_record_id=record_id,
                        jira_updated_time=op.jira_updated_time
                    ))
                    self.stats['successful_creates'] += 1
                else:
                    results.append(SyncResult(
                        issue_key=op.issue_key,
                        operation_type='create',
                        success=False,
                        error="創建記錄失敗",
                        jira_updated_time=op.jira_updated_time
                    ))
                    self.stats['failed_operations'] += 1
                
            except Exception as e:
                results.append(SyncResult(
                    issue_key=op.issue_key,
                    operation_type='create',
                    success=False,
                    error=str(e),
                    jira_updated_time=op.jira_updated_time
                ))
                self.stats['failed_operations'] += 1
        
        return results
    
    def _execute_update_operations(self, table_id: str, operations: List[SyncOperation]) -> List[SyncResult]:
        """
        執行更新操作
        
        Args:
            table_id: 表格 ID
            operations: 更新操作列表
            
        Returns:
            更新結果列表
        """
        if not operations:
            return []
        
        results = []
        
        # 使用批次更新提升效能
        valid_operations = []
        for op in operations:
            if not op.processed_fields or not op.lark_record_id:
                results.append(SyncResult(
                    issue_key=op.issue_key,
                    operation_type='update',
                    success=False,
                    error="缺少必要的更新資料",
                    lark_record_id=op.lark_record_id,
                    jira_updated_time=op.jira_updated_time
                ))
                continue
            valid_operations.append(op)
        
        if valid_operations:
            # 準備批次更新資料
            updates = [(op.lark_record_id, op.processed_fields) for op in valid_operations]
            
            # 執行批次更新
            api_start_time = time.time()
            success = self.lark_client.batch_update_records(table_id, updates)
            self.stats['lark_api_time'] += time.time() - api_start_time
            
            # 根據批次更新結果生成個別結果
            for op in valid_operations:
                if success:
                    results.append(SyncResult(
                        issue_key=op.issue_key,
                        operation_type='update',
                        success=True,
                        lark_record_id=op.lark_record_id,
                        jira_updated_time=op.jira_updated_time
                    ))
                    self.stats['successful_updates'] += 1
                else:
                    results.append(SyncResult(
                        issue_key=op.issue_key,
                        operation_type='update',
                        success=False,
                        error="批次更新記錄失敗",
                        lark_record_id=op.lark_record_id,
                        jira_updated_time=op.jira_updated_time
                    ))
                    self.stats['failed_operations'] += 1
        
        return results
    
    def _finalize_processing_stats(self, start_time: float, results: List[SyncResult]):
        """
        完成處理統計
        
        Args:
            start_time: 開始時間
            results: 處理結果列表
        """
        self.stats['total_time'] = time.time() - start_time
        self.stats['total_processed'] = len(results)
        
        success_count = sum(1 for r in results if r.success)
        failure_count = len(results) - success_count
        
        self.logger.info(f"批次處理完成: {success_count} 成功, {failure_count} 失敗, "
                        f"耗時 {self.stats['total_time']:.2f} 秒")
        
        # 詳細統計
        self.logger.info(f"詳細統計: 創建 {self.stats['successful_creates']} 筆, "
                        f"更新 {self.stats['successful_updates']} 筆, "
                        f"失敗 {self.stats['failed_operations']} 筆")
        
        # 效能統計
        self.logger.info(f"效能統計: 欄位處理 {self.stats['field_processing_time']:.2f}s, "
                        f"Lark API {self.stats['lark_api_time']:.2f}s")
        
        # 用戶映射統計
        if self.stats['user_mapping_stats']['pending_users'] > 0:
            self.logger.info(f"用戶映射: {self.stats['user_mapping_stats']['pending_users']} 個待查用戶")
    
    def create_sync_operations_from_issues(self, issues_for_create: List[Dict[str, Any]], 
                                         issues_for_update: List[Dict[str, Any]]) -> List[SyncOperation]:
        """
        從 Issues 列表創建同步操作
        
        Args:
            issues_for_create: 需要創建的 Issues
            issues_for_update: 需要更新的 Issues（包含 lark_record_id）
            
        Returns:
            同步操作列表
        """
        sync_operations = []
        
        # 創建操作
        for issue in issues_for_create:
            jira_updated_time = self._extract_jira_updated_time(issue)
            
            sync_operations.append(SyncOperation(
                issue_key=issue['key'],
                jira_issue=issue,
                operation_type='create',
                jira_updated_time=jira_updated_time
            ))
        
        # 更新操作
        for issue in issues_for_update:
            jira_updated_time = self._extract_jira_updated_time(issue)
            
            sync_operations.append(SyncOperation(
                issue_key=issue['key'],
                jira_issue=issue,
                operation_type='update',
                lark_record_id=issue.get('lark_record_id'),
                jira_updated_time=jira_updated_time
            ))
        
        return sync_operations
    
    def _extract_jira_updated_time(self, jira_issue: Dict[str, Any]) -> Optional[int]:
        """
        提取 JIRA 更新時間戳
        
        Args:
            jira_issue: JIRA Issue 字典
            
        Returns:
            毫秒時間戳，提取失敗返回 None
        """
        try:
            updated_field = jira_issue.get('fields', {}).get('updated')
            if not updated_field:
                return None
            
            # 使用 FieldProcessor 的時間解析邏輯
            if self.field_processor:
                return self.field_processor._convert_datetime(updated_field)
            
            # 簡化的時間解析
            import re
            from datetime import datetime
            
            clean_datetime = re.sub(r'\.\d{3}[+-]\d{4}$', '', updated_field)
            if clean_datetime.endswith('Z'):
                clean_datetime = clean_datetime[:-1]
            
            dt = datetime.fromisoformat(clean_datetime.replace('T', ' '))
            return int(dt.timestamp() * 1000)
            
        except Exception as e:
            self.logger.debug(f"提取 JIRA 更新時間失敗: {e}")
            return None
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """
        獲取處理統計資訊
        
        Returns:
            統計資訊字典
        """
        return self.stats.copy()


# 測試模組
if __name__ == '__main__':
    import logging
    from unittest.mock import Mock
    
    # 設定日誌
    logging.basicConfig(level=logging.DEBUG)
    
    try:
        # 創建模擬客戶端
        mock_lark_client = Mock()
        mock_lark_client.batch_create_records.return_value = (True, ['rec_1', 'rec_2'], [])
        mock_lark_client.create_record.return_value = 'rec_123'
        mock_lark_client.update_record.return_value = True
        
        # 創建模擬欄位處理器
        mock_field_processor = Mock()
        mock_field_processor.process_issues.return_value = {
            'TEST-001': {'Issue Key': 'TEST-001', 'Title': 'Test Issue 1'},
            'TEST-002': {'Issue Key': 'TEST-002', 'Title': 'Test Issue 2'}
        }
        
        # 測試批次處理器
        processor = SyncBatchProcessor(
            mock_lark_client,
            mock_field_processor,
            logger=logging.getLogger()
        )
        
        print("同步批次處理器測試:")
        
        # 創建測試操作
        sync_operations = [
            SyncOperation(
                issue_key='TEST-001',
                jira_issue={'key': 'TEST-001', 'fields': {'summary': 'Test 1'}},
                operation_type='create',
                jira_updated_time=1672531200000
            ),
            SyncOperation(
                issue_key='TEST-002',
                jira_issue={'key': 'TEST-002', 'fields': {'summary': 'Test 2'}},
                operation_type='update',
                lark_record_id='rec_existing',
                jira_updated_time=1672531300000
            )
        ]
        
        # 執行處理
        results = processor.process_sync_operations('test_table', sync_operations)
        
        print(f"處理結果: {len(results)} 筆")
        for result in results:
            print(f"  {result.issue_key}: {result.operation_type} - {'成功' if result.success else '失敗'}")
        
        # 查看統計
        stats = processor.get_processing_stats()
        print(f"統計: {stats}")
        
        print("同步批次處理器測試完成")
        
    except Exception as e:
        print(f"測試失敗: {e}")
        import traceback
        traceback.print_exc()