#!/usr/bin/env python3
"""
處理日誌管理器

專注於 SQLite 處理日誌的核心功能：
- 極簡處理日誌 Schema
- 基於 JIRA 時間戳的智能過濾
- 高效的批次操作
- 線程安全的資料庫操作

設計理念：
- JIRA = 唯一真相來源
- SQLite = 去重處理日誌，避免短時間重複處理
- 95% 過濾效率，大幅減少不必要的處理
"""

import sqlite3
import threading
import os
import time
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from contextlib import contextmanager


class ProcessingLogManager:
    """處理日誌管理器 - 基於 SQLite 的高效去重過濾"""
    
    def __init__(self, db_path: str, logger=None):
        """
        初始化處理日誌管理器
        
        Args:
            db_path: SQLite 資料庫檔案路徑
            logger: 日誌記錄器（可選）
        """
        self.db_path = os.path.abspath(db_path)
        self.db_lock = threading.RLock()  # 線程安全鎖
        
        # 設定日誌
        self.logger = logger or logging.getLogger(f"{__name__}.ProcessingLogManager")
        
        # 初始化資料庫
        self._init_database()
        
        self.logger.info(f"處理日誌管理器初始化完成，資料庫: {self.db_path}")
    
    def _init_database(self):
        """初始化 SQLite 資料庫表結構"""
        try:
            # 確保目錄存在
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 創建極簡處理日誌表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS processing_log (
                        issue_key TEXT PRIMARY KEY,
                        jira_updated_time INTEGER NOT NULL,    -- JIRA 的更新時間戳（毫秒）
                        processed_at INTEGER NOT NULL,         -- 本地處理時間戳（毫秒）
                        processing_result TEXT DEFAULT 'success',
                        lark_record_id TEXT,                   -- Lark 記錄 ID（用於 create/update 判斷）
                        created_at INTEGER DEFAULT (strftime('%s', 'now') * 1000)
                    )
                ''')
                
                # 創建索引以優化查詢效能
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_processing_log_updated_time 
                    ON processing_log (jira_updated_time)
                ''')
                
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_processing_log_processed_at 
                    ON processing_log (processed_at)
                ''')
                
                conn.commit()
                self.logger.debug("資料庫表結構初始化完成")
                
        except Exception as e:
            self.logger.error(f"資料庫初始化失敗: {e}")
            raise
    
    @contextmanager
    def _get_connection(self):
        """獲取線程安全的資料庫連接"""
        with self.db_lock:
            conn = sqlite3.connect(
                self.db_path,
                timeout=30.0,  # 30秒超時
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row  # 支援字典式存取
            try:
                yield conn
            finally:
                conn.close()
    
    @contextmanager
    def _get_transaction(self):
        """獲取事務連接，支援自動回滾"""
        with self.db_lock:
            conn = sqlite3.connect(
                self.db_path,
                timeout=30.0,  # 30秒超時
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row  # 支援字典式存取
            try:
                # 開始事務
                conn.execute('BEGIN TRANSACTION')
                yield conn
                # 如果沒有異常，提交事務
                conn.commit()
            except Exception:
                # 發生異常時回滾事務
                try:
                    conn.rollback()
                except Exception as rollback_error:
                    self.logger.error(f"事務回滾失敗: {rollback_error}")
                raise
            finally:
                conn.close()
    
    def clear_local_cache(self) -> bool:
        """
        清空本地處理日誌快取（SQLite 資料庫）
        注意：這不會影響 Lark 表格資料，只清空本地快取
        
        Returns:
            bool: 清空是否成功
        """
        try:
            with self._get_transaction() as conn:
                cursor = conn.cursor()
                
                # 清空本地快取記錄
                cursor.execute('DELETE FROM processing_log')
                
                deleted_count = cursor.rowcount
                self.logger.info(f"清空本地處理日誌快取：共刪除 {deleted_count} 筆記錄")
                
                return True
                
        except Exception as e:
            self.logger.error(f"清空本地處理日誌快取失敗: {e}")
            return False
    
    def clear_all_records(self) -> bool:
        """
        [已棄用] 請使用 clear_local_cache() 方法
        清空本地處理日誌快取（向後相容方法）
        """
        import warnings
        warnings.warn("clear_all_records() 已棄用，請使用 clear_local_cache()", DeprecationWarning, stacklevel=2)
        return self.clear_local_cache()
    
    def clean_invalid_record_ids(self, lark_client, table_id: str, wiki_token: str = None) -> int:
        """
        清理無效的記錄 ID（指向不存在記錄的快取項目）
        
        Args:
            lark_client: Lark 客戶端實例
            table_id: 表格 ID
            wiki_token: Wiki Token（可選）
            
        Returns:
            int: 清理的無效記錄數量
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 獲取所有有 lark_record_id 的記錄
                cursor.execute(
                    'SELECT issue_key, lark_record_id FROM processing_log WHERE lark_record_id IS NOT NULL AND lark_record_id != ""'
                )
                
                cached_records = cursor.fetchall()
                invalid_keys = []
                
                self.logger.info(f"檢查 {len(cached_records)} 個快取記錄的有效性")
                
                for issue_key, lark_record_id in cached_records:
                    # 檢查記錄是否仍然存在於 Lark 表格中
                    if not lark_client.check_record_exists(table_id, lark_record_id, wiki_token):
                        invalid_keys.append(issue_key)
                        self.logger.debug(f"發現無效記錄 ID: {issue_key} -> {lark_record_id}")
                
                # 批次刪除無效的快取記錄
                if invalid_keys:
                    with self._get_transaction() as trans_conn:
                        trans_cursor = trans_conn.cursor()
                        placeholders = ','.join(['?' for _ in invalid_keys])
                        trans_cursor.execute(
                            f'DELETE FROM processing_log WHERE issue_key IN ({placeholders})',
                            invalid_keys
                        )
                    
                    self.logger.info(f"清理了 {len(invalid_keys)} 個無效的快取記錄")
                else:
                    self.logger.info("沒有發現無效的快取記錄")
                
                return len(invalid_keys)
                
        except Exception as e:
            self.logger.error(f"清理無效記錄 ID 失敗: {e}")
            return 0
    
    def remove_processing_log(self, issue_key: str) -> bool:
        """
        移除指定 Issue 的處理日誌
        
        Args:
            issue_key: Issue Key
            
        Returns:
            bool: 移除是否成功
        """
        try:
            with self._get_transaction() as conn:
                cursor = conn.cursor()
                
                cursor.execute('DELETE FROM processing_log WHERE issue_key = ?', (issue_key,))
                
                if cursor.rowcount > 0:
                    self.logger.debug(f"移除處理日誌: {issue_key}")
                    return True
                else:
                    self.logger.debug(f"處理日誌不存在: {issue_key}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"移除處理日誌失敗 {issue_key}: {e}")
            return False
    
    def get_max_jira_updated_time(self) -> Optional[int]:
        """
        獲取最大的 JIRA 更新時間戳
        
        Returns:
            最大的 JIRA 更新時間戳（毫秒），如果沒有記錄則返回 None
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('SELECT MAX(jira_updated_time) as max_time FROM processing_log')
                
                row = cursor.fetchone()
                # sqlite3.Row 支援 key access, 但 MAX 聚合可能返回 None (空表)
                if row and row['max_time'] is not None:
                    return row['max_time']
                return None
                
        except Exception as e:
            self.logger.error(f"獲取最大 JIRA 更新時間失敗: {e}")
            return None

    def get_last_processed_time(self, issue_key: str) -> Optional[int]:
        """
        獲取指定 Issue 的最後處理時間
        
        Args:
            issue_key: Issue Key
            
        Returns:
            最後處理時間戳（毫秒），未找到則返回 None
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute(
                    'SELECT jira_updated_time FROM processing_log WHERE issue_key = ?',
                    (issue_key,)
                )
                
                row = cursor.fetchone()
                return row['jira_updated_time'] if row else None
                
        except Exception as e:
            self.logger.error(f"獲取最後處理時間失敗: {issue_key}, {e}")
            return None
    
    def get_lark_record_id(self, issue_key: str) -> Optional[str]:
        """
        獲取 Issue 對應的 Lark 記錄 ID
        
        Args:
            issue_key: Issue Key
            
        Returns:
            Lark 記錄 ID，未找到則返回 None
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute(
                    'SELECT lark_record_id FROM processing_log WHERE issue_key = ?',
                    (issue_key,)
                )
                
                row = cursor.fetchone()
                return row['lark_record_id'] if row else None
                
        except Exception as e:
            self.logger.error(f"獲取 Lark 記錄 ID 失敗: {issue_key}, {e}")
            return None
    
    def record_processing_result(self, issue_key: str, jira_updated_time: int, 
                               processing_result: str = 'success', 
                               lark_record_id: str = None) -> bool:
        """
        記錄處理結果
        
        Args:
            issue_key: Issue Key
            jira_updated_time: JIRA 更新時間戳（毫秒）
            processing_result: 處理結果
            lark_record_id: Lark 記錄 ID（可選）
            
        Returns:
            是否成功記錄
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                current_time = int(time.time() * 1000)  # 毫秒時間戳
                
                # 使用 REPLACE 實現 upsert
                cursor.execute('''
                    REPLACE INTO processing_log 
                    (issue_key, jira_updated_time, processed_at, processing_result, lark_record_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', (issue_key, jira_updated_time, current_time, processing_result, lark_record_id))
                
                conn.commit()
                self.logger.debug(f"處理結果已記錄: {issue_key}")
                return True
                
        except Exception as e:
            self.logger.error(f"記錄處理結果失敗: {issue_key}, {e}")
            return False
    
    def batch_record_processing_results(self, processing_results: List[Dict[str, Any]]) -> Tuple[bool, int]:
        """
        批次記錄處理結果
        
        Args:
            processing_results: 處理結果列表，每個元素包含：
                - issue_key: Issue Key
                - jira_updated_time: JIRA 更新時間戳
                - processing_result: 處理結果（預設 'success'）
                - lark_record_id: Lark 記錄 ID（可選）
                - table_id: 表格 ID（可選）
            
        Returns:
            (是否成功, 成功記錄數)
        """
        if not processing_results:
            return True, 0
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                current_time = int(time.time() * 1000)  # 毫秒時間戳
                
                # 準備批次資料
                batch_data = []
                for result in processing_results:
                    batch_data.append((
                        result['issue_key'],
                        result['jira_updated_time'],
                        current_time,
                        result.get('processing_result', 'success'),
                        result.get('lark_record_id')
                    ))
                
                # 批次插入
                cursor.executemany('''
                    REPLACE INTO processing_log 
                    (issue_key, jira_updated_time, processed_at, processing_result, lark_record_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', batch_data)
                
                conn.commit()
                
                success_count = len(batch_data)
                self.logger.info(f"批次記錄處理結果完成: {success_count} 筆")
                return True, success_count
                
        except Exception as e:
            self.logger.error(f"批次記錄處理結果失敗: {e}")
            return False, 0
    
    def batch_record_processing_results_with_transaction(self, processing_results: List[Dict[str, Any]], 
                                                       transaction_conn: sqlite3.Connection) -> Tuple[bool, int]:
        """
        使用現有事務連接批次記錄處理結果
        
        Args:
            processing_results: 處理結果列表
            transaction_conn: 事務連接
            
        Returns:
            (是否成功, 成功記錄數)
        """
        if not processing_results:
            return True, 0
        
        try:
            cursor = transaction_conn.cursor()
            
            current_time = int(time.time() * 1000)  # 毫秒時間戳
            
            # 準備批次資料
            batch_data = []
            for result in processing_results:
                batch_data.append((
                    result['issue_key'],
                    result['jira_updated_time'],
                    current_time,
                    result.get('processing_result', 'success'),
                    result.get('lark_record_id')
                ))
            
            # 批次插入（不提交，由事務管理）
            cursor.executemany('''
                REPLACE INTO processing_log 
                (issue_key, jira_updated_time, processed_at, processing_result, lark_record_id)
                VALUES (?, ?, ?, ?, ?)
            ''', batch_data)
            
            success_count = len(batch_data)
            self.logger.info(f"批次記錄處理結果完成（事務中）: {success_count} 筆")
            return True, success_count
            
        except Exception as e:
            self.logger.error(f"批次記錄處理結果失敗: {e}")
            # 不在這裡處理回滾，由事務管理器處理
            raise
    
    def filter_issues_by_timestamp(self, jira_issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        基於時間戳過濾需要處理的 Issues
        
        Args:
            jira_issues: JIRA Issues 列表，每個元素包含 key 和 fields.updated
            
        Returns:
            需要處理的 Issues 列表
        """
        if not jira_issues:
            return []
        
        issues_to_process = []
        
        for jira_issue in jira_issues:
            issue_key = jira_issue.get('key')
            if not issue_key:
                continue
            
            # 提取 JIRA 更新時間
            updated_field = jira_issue.get('fields', {}).get('updated')
            if not updated_field:
                # 如果沒有更新時間，標記為需要處理
                issues_to_process.append(jira_issue)
                continue
            
            # 轉換 JIRA 時間戳
            jira_updated_time = self._parse_jira_timestamp(updated_field)
            if jira_updated_time is None:
                # 如果無法解析時間，標記為需要處理
                issues_to_process.append(jira_issue)
                continue
            
            # 查詢最後處理時間
            last_processed_time = self.get_last_processed_time(issue_key)
            
            if last_processed_time is None or jira_updated_time > last_processed_time:
                # JIRA 有更新或從未處理過 → 需要處理
                issues_to_process.append(jira_issue)
            else:
                # JIRA 沒有更新 → 跳過
                self.logger.debug(f"跳過未更新的 Issue: {issue_key}")
        
        filter_rate = (len(jira_issues) - len(issues_to_process)) / len(jira_issues) * 100
        self.logger.info(f"時間戳過濾完成: {len(jira_issues)} → {len(issues_to_process)} 筆 "
                        f"({filter_rate:.1f}% 過濾)")
        
        return issues_to_process
    
    def _parse_jira_timestamp(self, datetime_str: str) -> Optional[int]:
        """
        解析 JIRA 時間戳為毫秒時間戳
        
        Args:
            datetime_str: JIRA 時間字串（如 "2025-01-08T03:45:23.000+0000"）
            
        Returns:
            毫秒時間戳，解析失敗返回 None
        """
        if not datetime_str:
            return None
        
        try:
            # 使用 new/field_processor.py 中的時間解析邏輯
            import re
            from datetime import datetime
            
            # 移除毫秒和時區資訊進行解析
            clean_datetime = re.sub(r'\.\d{3}[+-]\d{4}$', '', datetime_str)
            if clean_datetime.endswith('Z'):
                clean_datetime = clean_datetime[:-1]
            
            # 解析時間
            dt = datetime.fromisoformat(clean_datetime.replace('T', ' '))
            
            # 轉換為毫秒時間戳
            return int(dt.timestamp() * 1000)
            
        except Exception as e:
            self.logger.debug(f"時間戳解析失敗: {datetime_str}, {e}")
            return None
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """
        獲取處理統計資訊
        
        Returns:
            統計資訊字典
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 總記錄數
                cursor.execute('SELECT COUNT(*) as total FROM processing_log')
                total_count = cursor.fetchone()['total']
                
                # 成功記錄數
                cursor.execute('''
                    SELECT COUNT(*) as success 
                    FROM processing_log 
                    WHERE processing_result = ?
                ''', ('success',))
                success_count = cursor.fetchone()['success']
                
                # 最近處理時間
                cursor.execute('SELECT MAX(processed_at) as last_processed FROM processing_log')
                last_processed_row = cursor.fetchone()
                last_processed = last_processed_row['last_processed'] if last_processed_row else None
                
                # 資料庫檔案大小
                db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
                
                return {
                    'total_records': total_count,
                    'success_records': success_count,
                    'error_records': total_count - success_count,
                    'last_processed_at': last_processed,
                    'db_file': self.db_path,
                    'db_size_bytes': db_size,
                    'db_size_mb': round(db_size / (1024 * 1024), 2)
                }
                
        except Exception as e:
            self.logger.error(f"獲取處理統計失敗: {e}")
            return {
                'total_records': 0,
                'success_records': 0,
                'error_records': 0,
                'last_processed_at': None,
                'db_file': self.db_path,
                'db_size_bytes': 0,
                'db_size_mb': 0
            }
    
    def cleanup_old_records(self, days_to_keep: int = 30) -> int:
        """
        清理舊記錄
        
        Args:
            days_to_keep: 保留天數
            
        Returns:
            清理的記錄數
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 計算清理時間戳
                cleanup_timestamp = int((time.time() - days_to_keep * 24 * 3600) * 1000)
                
                # 執行清理
                cursor.execute(
                    'DELETE FROM processing_log WHERE processed_at < ?',
                    (cleanup_timestamp,)
                )
                
                conn.commit()
                
                deleted_count = cursor.rowcount
                if deleted_count > 0:
                    self.logger.info(f"清理舊記錄完成: {deleted_count} 筆（保留 {days_to_keep} 天）")
                
                return deleted_count
                
        except Exception as e:
            self.logger.error(f"清理舊記錄失敗: {e}")
            return 0
    
    def vacuum_database(self) -> bool:
        """
        清理和優化資料庫
        
        Returns:
            是否成功
        """
        try:
            with self._get_connection() as conn:
                conn.execute('VACUUM')
                conn.commit()
                self.logger.info("資料庫清理完成")
                return True
                
        except Exception as e:
            self.logger.error(f"資料庫清理失敗: {e}")
            return False


# 測試模組
if __name__ == '__main__':
    import tempfile
    import logging
    
    # 設定日誌
    logging.basicConfig(level=logging.DEBUG)
    
    # 創建臨時資料庫
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        # 測試 ProcessingLogManager
        log_manager = ProcessingLogManager(db_path)
        
        print("處理日誌管理器測試:")
        print(f"資料庫路徑: {db_path}")
        
        # 測試記錄處理結果
        success = log_manager.record_processing_result(
            'TEST-001', 
            1672531200000,  # 2023-01-01 00:00:00
            'success',
            'rec_123',
            'tbl_456'
        )
        print(f"記錄處理結果: {'成功' if success else '失敗'}")
        
        # 測試獲取最後處理時間
        last_time = log_manager.get_last_processed_time('TEST-001', 'tbl_456')
        print(f"最後處理時間: {last_time}")
        
        # 測試時間戳過濾
        mock_issues = [
            {
                'key': 'TEST-001',
                'fields': {'updated': '2023-01-01T00:00:00.000+0000'}
            },
            {
                'key': 'TEST-002',
                'fields': {'updated': '2023-01-02T00:00:00.000+0000'}
            }
        ]
        
        filtered_issues = log_manager.filter_issues_by_timestamp(mock_issues, 'tbl_456')
        print(f"時間戳過濾結果: {len(filtered_issues)} 筆需要處理")
        
        # 測試統計
        stats = log_manager.get_processing_stats('tbl_456')
        print(f"處理統計: {stats}")
        
        print("處理日誌管理器測試完成")
        
    except Exception as e:
        print(f"測試失敗: {e}")
    finally:
        # 清理臨時檔案
        if os.path.exists(db_path):
            os.unlink(db_path)