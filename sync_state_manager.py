#!/usr/bin/env python3
"""
同步狀態管理器

負責同步狀態追蹤和智能過濾邏輯：
- 整合 ProcessingLogManager 實現時間戳過濾
- 管理冷啟動和增量同步狀態
- 多表格狀態管理
- 同步狀態持久化

設計理念：
- 以 ProcessingLogManager 為基礎的狀態管理
- 智能冷啟動檢測和處理
- 高效的增量同步過濾
- 支援多表格並行同步
"""

import os
import time
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from pathlib import Path

from processing_log_manager import ProcessingLogManager


class SyncStateManager:
    """同步狀態管理器"""
    
    def __init__(self, base_data_dir: str = "data", logger=None):
        """
        初始化同步狀態管理器
        
        Args:
            base_data_dir: 基礎資料目錄
            logger: 日誌記錄器（可選）
        """
        self.base_data_dir = Path(base_data_dir)
        self.base_data_dir.mkdir(exist_ok=True)
        
        # 設定日誌
        self.logger = logger or logging.getLogger(f"{__name__}.SyncStateManager")
        
        # 處理日誌管理器實例字典 {table_id: ProcessingLogManager}
        self.processing_log_managers = {}
        
        # 同步狀態緩存
        self.sync_states = {}
        
        self.logger.info(f"同步狀態管理器初始化完成，資料目錄: {self.base_data_dir}")
    
    def get_processing_log_manager(self, table_id: str) -> ProcessingLogManager:
        """
        獲取指定表格的處理日誌管理器
        
        Args:
            table_id: 表格 ID
            
        Returns:
            ProcessingLogManager 實例
        """
        if table_id not in self.processing_log_managers:
            # 為每個表格創建獨立的 SQLite 資料庫
            db_path = self.base_data_dir / f"processing_log_{table_id}.db"
            self.processing_log_managers[table_id] = ProcessingLogManager(
                str(db_path), 
                self.logger
            )
        
        return self.processing_log_managers[table_id]
    
    def is_cold_start(self, table_id: str) -> bool:
        """
        檢查是否需要冷啟動
        
        Args:
            table_id: 表格 ID
            
        Returns:
            是否需要冷啟動
        """
        try:
            log_manager = self.get_processing_log_manager(table_id)
            stats = log_manager.get_processing_stats()
            
            # 檢查是否有任何處理記錄
            if stats['total_records'] == 0:
                self.logger.info(f"表格 {table_id} 無處理記錄，需要冷啟動")
                return True
            
            # 檢查最後處理時間是否太久之前（超過 7 天視為冷啟動）
            last_processed = stats['last_processed_at']
            if last_processed:
                current_time = int(time.time() * 1000)
                days_since_last = (current_time - last_processed) / (1000 * 60 * 60 * 24)
                
                if days_since_last > 7:
                    self.logger.info(f"表格 {table_id} 最後處理時間過久（{days_since_last:.1f} 天），需要冷啟動")
                    return True
            
            self.logger.debug(f"表格 {table_id} 無需冷啟動")
            return False
            
        except Exception as e:
            self.logger.error(f"檢查冷啟動狀態失敗: {e}")
            # 發生錯誤時預設為冷啟動
            return True
    
    def prepare_cold_start(self, table_id: str, existing_lark_records: List[Dict[str, Any]], 
                          ticket_field_name: str = "Issue Key") -> Dict[str, Any]:
        """
        準備冷啟動：將現有 Lark 記錄註冊到處理日誌
        
        Args:
            table_id: 表格 ID
            existing_lark_records: 現有 Lark 記錄列表
            ticket_field_name: 票據欄位名稱
            
        Returns:
            冷啟動準備結果
        """
        try:
            log_manager = self.get_processing_log_manager(table_id)
            
            # 建立 ticket -> record_id 映射
            ticket_to_record_map = {}
            valid_records = 0
            
            for record in existing_lark_records:
                record_id = record.get('record_id')
                if not record_id:
                    continue
                
                # 從 fields 中提取票據號碼
                fields = record.get('fields', {})
                ticket_field = fields.get(ticket_field_name)
                
                if ticket_field:
                    # 處理票據欄位可能是字典或其他複雜結構的情況
                    if isinstance(ticket_field, dict):
                        # 如果是字典，嘗試提取 text 或 url 或其他字符串欄位
                        ticket_key = ticket_field.get('text') or ticket_field.get('url') or ticket_field.get('link') or str(ticket_field)
                    elif isinstance(ticket_field, list) and ticket_field:
                        # 如果是列表，取第一個元素
                        first_item = ticket_field[0]
                        if isinstance(first_item, dict):
                            ticket_key = first_item.get('text') or first_item.get('url') or first_item.get('link') or str(first_item)
                        else:
                            ticket_key = str(first_item)
                    else:
                        # 其他情況直接轉換為字符串
                        ticket_key = str(ticket_field)
                    
                    # 確保票據鍵是有效的字符串
                    if ticket_key and ticket_key.strip():
                        ticket_to_record_map[ticket_key.strip()] = record_id
                        valid_records += 1
            
            # 批次記錄到 ProcessingLogManager
            processing_results = []
            current_time = int(time.time() * 1000)
            
            for ticket_key, record_id in ticket_to_record_map.items():
                processing_results.append({
                    'issue_key': ticket_key,
                    'jira_updated_time': 0,  # 設為 0 確保下次同步時會重新更新此記錄
                    'processing_result': 'cold_start_existing',
                    'lark_record_id': record_id,
                    'table_id': table_id
                })
            
            # 批次寫入處理日誌
            success, recorded_count = log_manager.batch_record_processing_results(processing_results)
            
            result = {
                'table_id': table_id,
                'total_lark_records': len(existing_lark_records),
                'valid_records': valid_records,
                'recorded_count': recorded_count,
                'success': success,
                'ticket_to_record_map': ticket_to_record_map
            }
            
            self.logger.info(f"冷啟動準備完成: {valid_records} 筆有效記錄，{recorded_count} 筆已記錄")
            
            return result
            
        except Exception as e:
            self.logger.error(f"冷啟動準備失敗: {e}")
            return {
                'table_id': table_id,
                'total_lark_records': 0,
                'valid_records': 0,
                'recorded_count': 0,
                'success': False,
                'error': str(e)
            }
    
    def filter_issues_for_processing(self, table_id: str, 
                                   jira_issues: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        過濾需要處理的 Issues
        
        Args:
            table_id: 表格 ID
            jira_issues: JIRA Issues 列表
            
        Returns:
            (需要處理的 Issues, 過濾統計)
        """
        if not jira_issues:
            return [], {'total_issues': 0, 'filtered_issues': 0, 'filter_rate': 0}
        
        try:
            log_manager = self.get_processing_log_manager(table_id)
            
            # 使用 ProcessingLogManager 進行時間戳過濾
            filtered_issues = log_manager.filter_issues_by_timestamp(jira_issues)
            
            # 計算過濾統計
            total_count = len(jira_issues)
            filtered_count = len(filtered_issues)
            filter_rate = (total_count - filtered_count) / total_count * 100 if total_count > 0 else 0
            
            filter_stats = {
                'total_issues': total_count,
                'filtered_issues': filtered_count,
                'skipped_issues': total_count - filtered_count,
                'filter_rate': filter_rate,
                'table_id': table_id
            }
            
            self.logger.info(f"過濾完成: {total_count} → {filtered_count} 筆 ({filter_rate:.1f}% 過濾)")
            
            return filtered_issues, filter_stats
            
        except Exception as e:
            self.logger.error(f"過濾 Issues 失敗: {e}")
            return jira_issues, {
                'total_issues': len(jira_issues),
                'filtered_issues': len(jira_issues),
                'filter_rate': 0,
                'error': str(e)
            }
    
    def determine_sync_operations(self, table_id: str, 
                                filtered_issues: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        決定同步操作類型（create 或 update）
        
        Args:
            table_id: 表格 ID
            filtered_issues: 過濾後的 Issues 列表
            
        Returns:
            {'create': [issues], 'update': [issues_with_record_id]}
        """
        if not filtered_issues:
            return {'create': [], 'update': []}
        
        try:
            log_manager = self.get_processing_log_manager(table_id)
            
            create_operations = []
            update_operations = []
            
            for issue in filtered_issues:
                issue_key = issue.get('key')
                if not issue_key:
                    continue
                
                # 查詢是否已有 Lark 記錄 ID
                lark_record_id = log_manager.get_lark_record_id(issue_key)
                
                if lark_record_id:
                    # 有記錄 ID，執行更新
                    issue_with_record_id = issue.copy()
                    issue_with_record_id['lark_record_id'] = lark_record_id
                    update_operations.append(issue_with_record_id)
                else:
                    # 沒有記錄 ID，執行創建
                    create_operations.append(issue)
            
            operation_stats = {
                'create': len(create_operations),
                'update': len(update_operations),
                'total': len(filtered_issues)
            }
            
            self.logger.info(f"同步操作決定: {operation_stats['create']} 筆創建, "
                           f"{operation_stats['update']} 筆更新")
            
            return {
                'create': create_operations,
                'update': update_operations,
                'stats': operation_stats
            }
            
        except Exception as e:
            self.logger.error(f"決定同步操作失敗: {e}")
            return {
                'create': filtered_issues,  # 發生錯誤時預設為創建
                'update': [],
                'stats': {'create': len(filtered_issues), 'update': 0, 'total': len(filtered_issues)}
            }
    
    def determine_sync_operations_with_force_update(self, table_id: str, 
                                                   filtered_issues: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        決定同步操作類型（full-update 模式，強制更新所有已存在記錄）
        
        Args:
            table_id: 表格 ID
            filtered_issues: 過濾後的 Issues 列表
            
        Returns:
            {'create': [issues], 'update': [issues_with_record_id]}
        """
        if not filtered_issues:
            return {'create': [], 'update': []}
        
        try:
            log_manager = self.get_processing_log_manager(table_id)
            
            create_operations = []
            update_operations = []
            
            for issue in filtered_issues:
                issue_key = issue.get('key')
                if not issue_key:
                    self.logger.warning("Issue 缺少 key，跳過")
                    continue
                
                # 檢查是否已存在於 Lark 表格中
                lark_record_id = log_manager.get_lark_record_id(issue_key)
                
                if lark_record_id:
                    # 有記錄 ID，強制執行更新（忽略時間戳檢查）
                    issue_with_record_id = issue.copy()
                    issue_with_record_id['lark_record_id'] = lark_record_id
                    update_operations.append(issue_with_record_id)
                else:
                    # 沒有記錄 ID，執行創建
                    create_operations.append(issue)
            
            operation_stats = {
                'create': len(create_operations),
                'update': len(update_operations),
                'total': len(filtered_issues)
            }
            
            self.logger.info(f"Full-update 同步操作決定: {operation_stats['create']} 筆創建, "
                           f"{operation_stats['update']} 筆強制更新")
            
            return {
                'create': create_operations,
                'update': update_operations,
                'stats': operation_stats
            }
            
        except Exception as e:
            self.logger.error(f"決定 full-update 同步操作失敗: {e}")
            return {
                'create': filtered_issues,  # 發生錯誤時預設為創建
                'update': [],
                'stats': {'create': len(filtered_issues), 'update': 0, 'total': len(filtered_issues)}
            }
    
    def record_sync_results(self, table_id: str, sync_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        記錄同步結果
        
        Args:
            table_id: 表格 ID
            sync_results: 同步結果列表，每個元素包含：
                - issue_key: Issue Key
                - jira_updated_time: JIRA 更新時間戳
                - operation: 操作類型 ('create' 或 'update')
                - success: 是否成功
                - lark_record_id: Lark 記錄 ID（可選）
                - error: 錯誤資訊（可選）
                
        Returns:
            記錄統計結果
        """
        if not sync_results:
            return {'total': 0, 'success': 0, 'error': 0}
        
        try:
            log_manager = self.get_processing_log_manager(table_id)
            
            # 準備批次記錄資料
            processing_results = []
            success_count = 0
            error_count = 0
            
            for result in sync_results:
                if result.success:
                    processing_result = 'success'
                    success_count += 1
                else:
                    processing_result = f"error: {result.error or 'unknown'}"
                    error_count += 1
                
                processing_results.append({
                    'issue_key': result.issue_key,
                    'jira_updated_time': result.jira_updated_time or 0,
                    'processing_result': processing_result,
                    'lark_record_id': result.lark_record_id
                })
            
            # 批次記錄結果
            batch_success, recorded_count = log_manager.batch_record_processing_results(processing_results)
            
            record_stats = {
                'total': len(sync_results),
                'success': success_count,
                'error': error_count,
                'recorded_count': recorded_count,
                'batch_success': batch_success
            }
            
            self.logger.info(f"同步結果記錄完成: {success_count} 成功, {error_count} 失敗")
            
            return record_stats
            
        except Exception as e:
            self.logger.error(f"記錄同步結果失敗: {e}")
            return {
                'total': len(sync_results),
                'success': 0,
                'error': len(sync_results),
                'recorded_count': 0,
                'batch_success': False,
                'error': str(e)
            }
    
    def record_sync_results_with_transaction(self, table_id: str, sync_results: List[Dict[str, Any]], 
                                           transaction_conn: Any) -> Dict[str, Any]:
        """
        使用事務記錄同步結果（只記錄成功的結果）
        
        Args:
            table_id: 表格 ID
            sync_results: 同步結果列表
            transaction_conn: 事務連接
            
        Returns:
            記錄統計結果
        """
        if not sync_results:
            return {'total': 0, 'success': 0, 'error': 0}
        
        try:
            log_manager = self.get_processing_log_manager(table_id)
            
            # 只處理成功的結果
            successful_results = []
            success_count = 0
            error_count = 0
            
            for result in sync_results:
                if result.success:
                    successful_results.append({
                        'issue_key': result.issue_key,
                        'jira_updated_time': result.jira_updated_time or 0,
                        'processing_result': 'success',
                        'lark_record_id': result.lark_record_id
                    })
                    success_count += 1
                else:
                    error_count += 1
            
            # 使用事務記錄成功的結果
            if successful_results:
                batch_success, recorded_count = log_manager.batch_record_processing_results_with_transaction(
                    successful_results, transaction_conn
                )
            else:
                batch_success, recorded_count = True, 0
            
            record_stats = {
                'total': len(sync_results),
                'success': success_count,
                'error': error_count,
                'recorded_count': recorded_count,
                'batch_success': batch_success
            }
            
            self.logger.info(f"同步結果記錄完成（事務中）: {success_count} 成功, {error_count} 失敗")
            
            return record_stats
            
        except Exception as e:
            self.logger.error(f"記錄同步結果失敗: {e}")
            raise  # 重新拋出異常以觸發事務回滾
    
    def get_sync_state_summary(self, table_id: str = None) -> Dict[str, Any]:
        """
        獲取同步狀態摘要
        
        Args:
            table_id: 表格 ID（可選，不提供則返回所有表格摘要）
            
        Returns:
            同步狀態摘要
        """
        try:
            if table_id:
                # 單一表格摘要
                log_manager = self.get_processing_log_manager(table_id)
                stats = log_manager.get_processing_stats()
                
                return {
                    'table_id': table_id,
                    'is_cold_start': self.is_cold_start(table_id),
                    'stats': stats
                }
            else:
                # 所有表格摘要
                all_tables_summary = {}
                
                for table_id, log_manager in self.processing_log_managers.items():
                    stats = log_manager.get_processing_stats()
                    all_tables_summary[table_id] = {
                        'is_cold_start': self.is_cold_start(table_id),
                        'stats': stats
                    }
                
                return {
                    'tables': all_tables_summary,
                    'total_tables': len(self.processing_log_managers)
                }
                
        except Exception as e:
            self.logger.error(f"獲取同步狀態摘要失敗: {e}")
            return {'error': str(e)}
    
    def cleanup_old_records(self, days_to_keep: int = 30, table_id: str = None) -> Dict[str, Any]:
        """
        清理舊記錄
        
        Args:
            days_to_keep: 保留天數
            table_id: 表格 ID（可選，不提供則清理所有表格）
            
        Returns:
            清理結果統計
        """
        try:
            cleanup_results = {}
            total_cleaned = 0
            
            if table_id:
                # 清理單一表格
                log_manager = self.get_processing_log_manager(table_id)
                cleaned_count = log_manager.cleanup_old_records(days_to_keep, table_id)
                cleanup_results[table_id] = cleaned_count
                total_cleaned = cleaned_count
            else:
                # 清理所有表格
                for table_id, log_manager in self.processing_log_managers.items():
                    cleaned_count = log_manager.cleanup_old_records(days_to_keep, table_id)
                    cleanup_results[table_id] = cleaned_count
                    total_cleaned += cleaned_count
            
            self.logger.info(f"清理舊記錄完成: 總共清理 {total_cleaned} 筆記錄")
            
            return {
                'days_to_keep': days_to_keep,
                'tables_cleaned': cleanup_results,
                'total_cleaned': total_cleaned
            }
            
        except Exception as e:
            self.logger.error(f"清理舊記錄失敗: {e}")
            return {'error': str(e)}
    
    def vacuum_databases(self, table_id: str = None) -> Dict[str, Any]:
        """
        清理和優化資料庫
        
        Args:
            table_id: 表格 ID（可選，不提供則清理所有表格）
            
        Returns:
            清理結果
        """
        try:
            vacuum_results = {}
            
            if table_id:
                # 清理單一表格
                log_manager = self.get_processing_log_manager(table_id)
                vacuum_results[table_id] = log_manager.vacuum_database()
            else:
                # 清理所有表格
                for table_id, log_manager in self.processing_log_managers.items():
                    vacuum_results[table_id] = log_manager.vacuum_database()
            
            success_count = sum(1 for result in vacuum_results.values() if result)
            
            self.logger.info(f"資料庫清理完成: {success_count}/{len(vacuum_results)} 成功")
            
            return {
                'tables_vacuumed': vacuum_results,
                'success_count': success_count,
                'total_count': len(vacuum_results)
            }
            
        except Exception as e:
            self.logger.error(f"資料庫清理失敗: {e}")
            return {'error': str(e)}


# 測試模組
if __name__ == '__main__':
    import tempfile
    import logging
    
    # 設定日誌
    logging.basicConfig(level=logging.DEBUG)
    
    # 創建臨時資料目錄
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # 測試 SyncStateManager
            state_manager = SyncStateManager(temp_dir)
            
            print("同步狀態管理器測試:")
            print(f"資料目錄: {temp_dir}")
            
            # 測試冷啟動檢查
            is_cold = state_manager.is_cold_start('test_table')
            print(f"是否冷啟動: {is_cold}")
            
            # 測試冷啟動準備
            mock_lark_records = [
                {
                    'record_id': 'rec_123',
                    'fields': {'Issue Key': 'TEST-001'}
                },
                {
                    'record_id': 'rec_456',
                    'fields': {'Issue Key': 'TEST-002'}
                }
            ]
            
            cold_start_result = state_manager.prepare_cold_start('test_table', mock_lark_records)
            print(f"冷啟動準備結果: {cold_start_result}")
            
            # 測試過濾
            mock_jira_issues = [
                {
                    'key': 'TEST-001',
                    'fields': {'updated': '2023-01-01T00:00:00.000+0000'}
                },
                {
                    'key': 'TEST-003',
                    'fields': {'updated': '2023-01-02T00:00:00.000+0000'}
                }
            ]
            
            filtered_issues, filter_stats = state_manager.filter_issues_for_processing('test_table', mock_jira_issues)
            print(f"過濾結果: {len(filtered_issues)} 筆，統計: {filter_stats}")
            
            # 測試操作決定
            operations = state_manager.determine_sync_operations('test_table', filtered_issues)
            print(f"同步操作: {operations['stats']}")
            
            # 測試狀態摘要
            summary = state_manager.get_sync_state_summary('test_table')
            print(f"狀態摘要: {summary}")
            
            print("同步狀態管理器測試完成")
            
        except Exception as e:
            print(f"測試失敗: {e}")
            import traceback
            traceback.print_exc()