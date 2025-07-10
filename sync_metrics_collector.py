#!/usr/bin/env python3
"""
同步指標收集器

負責效能監控和統計收集：
- 同步效能指標收集
- 歷史統計資料分析
- 效能趨勢監控
- 系統健康狀態評估
- 指標資料持久化

設計理念：
- 輕量級的指標收集
- 不影響主要同步流程效能
- 提供有價值的效能洞察
- 支援長期趨勢分析
"""

import os
import time
import json
import logging
import sqlite3
import threading
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class SyncMetrics:
    """同步指標資料結構"""
    session_id: str
    start_time: str
    end_time: str
    processing_time: float
    total_teams: int
    total_tables: int
    successful_tables: int
    failed_tables: int
    total_processed: int
    total_created: int
    total_updated: int
    total_failed: int
    average_processing_rate: float  # 記錄/秒
    success_rate: float  # 成功率
    system_load: Dict[str, Any]  # 系統負載資訊
    memory_usage: Dict[str, Any]  # 記憶體使用資訊


@dataclass
class TableMetrics:
    """表格級指標資料結構"""
    table_id: str
    team_name: str
    sync_time: str
    processing_time: float
    is_cold_start: bool
    total_jira_issues: int
    filtered_issues: int
    created_records: int
    updated_records: int
    failed_operations: int
    filter_rate: float
    processing_rate: float
    success_rate: float


class SyncMetricsCollector:
    """同步指標收集器"""
    
    def __init__(self, db_path: str = "data/sync_metrics.db", logger=None):
        """
        初始化同步指標收集器
        
        Args:
            db_path: SQLite 資料庫檔案路徑
            logger: 日誌記錄器（可選）
        """
        self.db_path = os.path.abspath(db_path)
        self.db_lock = threading.RLock()
        
        # 設定日誌
        self.logger = logger or logging.getLogger(f"{__name__}.SyncMetricsCollector")
        
        # 確保資料庫目錄存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # 初始化資料庫
        self._init_database()
        
        # 當前會話指標
        self.current_session_metrics = {}
        
        self.logger.info(f"同步指標收集器初始化完成，資料庫: {self.db_path}")
    
    def _init_database(self):
        """初始化 SQLite 資料庫表結構"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 創建會話指標表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sync_session_metrics (
                        session_id TEXT PRIMARY KEY,
                        start_time TEXT NOT NULL,
                        end_time TEXT NOT NULL,
                        processing_time REAL NOT NULL,
                        total_teams INTEGER NOT NULL,
                        total_tables INTEGER NOT NULL,
                        successful_tables INTEGER NOT NULL,
                        failed_tables INTEGER NOT NULL,
                        total_processed INTEGER NOT NULL,
                        total_created INTEGER NOT NULL,
                        total_updated INTEGER NOT NULL,
                        total_failed INTEGER NOT NULL,
                        average_processing_rate REAL NOT NULL,
                        success_rate REAL NOT NULL,
                        system_load TEXT,
                        memory_usage TEXT,
                        created_at INTEGER DEFAULT (strftime('%s', 'now') * 1000)
                    )
                ''')
                
                # 創建表格指標表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS table_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        table_id TEXT NOT NULL,
                        team_name TEXT NOT NULL,
                        sync_time TEXT NOT NULL,
                        processing_time REAL NOT NULL,
                        is_cold_start INTEGER NOT NULL,
                        total_jira_issues INTEGER NOT NULL,
                        filtered_issues INTEGER NOT NULL,
                        created_records INTEGER NOT NULL,
                        updated_records INTEGER NOT NULL,
                        failed_operations INTEGER NOT NULL,
                        filter_rate REAL NOT NULL,
                        processing_rate REAL NOT NULL,
                        success_rate REAL NOT NULL,
                        created_at INTEGER DEFAULT (strftime('%s', 'now') * 1000)
                    )
                ''')
                
                # 創建索引
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_session_metrics_start_time 
                    ON sync_session_metrics (start_time)
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_table_metrics_table_id 
                    ON table_metrics (table_id)
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_table_metrics_sync_time 
                    ON table_metrics (sync_time)
                ''')
                
                conn.commit()
                self.logger.debug("指標資料庫初始化完成")
                
        except Exception as e:
            self.logger.error(f"指標資料庫初始化失敗: {e}")
            raise
    
    @contextmanager
    def _get_connection(self):
        """獲取線程安全的資料庫連接"""
        with self.db_lock:
            conn = sqlite3.connect(
                self.db_path,
                timeout=30.0,
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()
    
    def record_sync_session(self, sync_result) -> bool:
        """
        記錄同步會話指標
        
        Args:
            sync_result: 同步結果物件
            
        Returns:
            是否成功記錄
        """
        try:
            # 生成會話 ID
            session_id = f"sync_{int(time.time() * 1000)}"
            
            # 計算指標
            processing_rate = (sync_result.total_processed / sync_result.processing_time 
                             if sync_result.processing_time > 0 else 0)
            
            success_rate = (sync_result.successful_tables / sync_result.total_tables 
                          if sync_result.total_tables > 0 else 0) * 100
            
            # 收集系統資訊
            system_load = self._collect_system_load()
            memory_usage = self._collect_memory_usage()
            
            # 創建指標物件
            metrics = SyncMetrics(
                session_id=session_id,
                start_time=sync_result.start_time,
                end_time=sync_result.end_time,
                processing_time=sync_result.processing_time,
                total_teams=sync_result.total_teams,
                total_tables=sync_result.total_tables,
                successful_tables=sync_result.successful_tables,
                failed_tables=sync_result.failed_tables,
                total_processed=sync_result.total_processed,
                total_created=sync_result.total_created,
                total_updated=sync_result.total_updated,
                total_failed=sync_result.total_failed,
                average_processing_rate=processing_rate,
                success_rate=success_rate,
                system_load=system_load,
                memory_usage=memory_usage
            )
            
            # 記錄到資料庫
            success = self._insert_session_metrics(metrics)
            
            if success:
                self.logger.info(f"同步會話指標已記錄: {session_id}")
                
                # 記錄表格級指標
                self._record_table_metrics(sync_result)
            
            return success
            
        except Exception as e:
            self.logger.error(f"記錄同步會話指標失敗: {e}")
            return False
    
    def _insert_session_metrics(self, metrics: SyncMetrics) -> bool:
        """插入會話指標到資料庫"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT INTO sync_session_metrics 
                    (session_id, start_time, end_time, processing_time, total_teams, 
                     total_tables, successful_tables, failed_tables, total_processed, 
                     total_created, total_updated, total_failed, average_processing_rate, 
                     success_rate, system_load, memory_usage)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    metrics.session_id,
                    metrics.start_time,
                    metrics.end_time,
                    metrics.processing_time,
                    metrics.total_teams,
                    metrics.total_tables,
                    metrics.successful_tables,
                    metrics.failed_tables,
                    metrics.total_processed,
                    metrics.total_created,
                    metrics.total_updated,
                    metrics.total_failed,
                    metrics.average_processing_rate,
                    metrics.success_rate,
                    json.dumps(metrics.system_load),
                    json.dumps(metrics.memory_usage)
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            self.logger.error(f"插入會話指標失敗: {e}")
            return False
    
    def _record_table_metrics(self, sync_result):
        """記錄表格級指標"""
        try:
            table_metrics_list = []
            
            for team_name, team_result in sync_result.team_results.items():
                for table_name, table_result in team_result.get('table_results', {}).items():
                    if hasattr(table_result, 'table_id'):
                        # 計算表格級指標
                        total_operations = (table_result.created_records + 
                                          table_result.updated_records + 
                                          table_result.failed_operations)
                        
                        processing_rate = (total_operations / table_result.processing_time 
                                         if table_result.processing_time > 0 else 0)
                        
                        success_rate = ((table_result.created_records + table_result.updated_records) / 
                                      total_operations if total_operations > 0 else 0) * 100
                        
                        filter_rate = ((table_result.total_jira_issues - table_result.filtered_issues) / 
                                     table_result.total_jira_issues 
                                     if table_result.total_jira_issues > 0 else 0) * 100
                        
                        table_metrics = TableMetrics(
                            table_id=table_result.table_id,
                            team_name=team_name,
                            sync_time=sync_result.start_time,
                            processing_time=table_result.processing_time,
                            is_cold_start=table_result.is_cold_start,
                            total_jira_issues=table_result.total_jira_issues,
                            filtered_issues=table_result.filtered_issues,
                            created_records=table_result.created_records,
                            updated_records=table_result.updated_records,
                            failed_operations=table_result.failed_operations,
                            filter_rate=filter_rate,
                            processing_rate=processing_rate,
                            success_rate=success_rate
                        )
                        
                        table_metrics_list.append(table_metrics)
            
            # 批次插入表格指標
            if table_metrics_list:
                self._batch_insert_table_metrics(table_metrics_list)
                
        except Exception as e:
            self.logger.error(f"記錄表格級指標失敗: {e}")
    
    def _batch_insert_table_metrics(self, table_metrics_list: List[TableMetrics]):
        """批次插入表格指標"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                insert_data = []
                for metrics in table_metrics_list:
                    insert_data.append((
                        metrics.table_id,
                        metrics.team_name,
                        metrics.sync_time,
                        metrics.processing_time,
                        1 if metrics.is_cold_start else 0,
                        metrics.total_jira_issues,
                        metrics.filtered_issues,
                        metrics.created_records,
                        metrics.updated_records,
                        metrics.failed_operations,
                        metrics.filter_rate,
                        metrics.processing_rate,
                        metrics.success_rate
                    ))
                
                cursor.executemany('''
                    INSERT INTO table_metrics 
                    (table_id, team_name, sync_time, processing_time, is_cold_start,
                     total_jira_issues, filtered_issues, created_records, updated_records,
                     failed_operations, filter_rate, processing_rate, success_rate)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', insert_data)
                
                conn.commit()
                self.logger.info(f"批次插入表格指標完成: {len(insert_data)} 筆")
                
        except Exception as e:
            self.logger.error(f"批次插入表格指標失敗: {e}")
    
    def _collect_system_load(self) -> Dict[str, Any]:
        """收集系統負載資訊"""
        try:
            import psutil
            
            return {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'cpu_count': psutil.cpu_count(),
                'load_average': psutil.getloadavg() if hasattr(psutil, 'getloadavg') else None,
                'disk_usage': psutil.disk_usage('/').percent,
                'boot_time': psutil.boot_time()
            }
            
        except ImportError:
            # 如果沒有 psutil，返回基本資訊
            return {
                'cpu_percent': None,
                'cpu_count': None,
                'load_average': None,
                'disk_usage': None,
                'boot_time': None
            }
        except Exception as e:
            self.logger.debug(f"收集系統負載資訊失敗: {e}")
            return {}
    
    def _collect_memory_usage(self) -> Dict[str, Any]:
        """收集記憶體使用資訊"""
        try:
            import psutil
            
            memory = psutil.virtual_memory()
            
            return {
                'total': memory.total,
                'available': memory.available,
                'percent': memory.percent,
                'used': memory.used,
                'free': memory.free
            }
            
        except ImportError:
            return {
                'total': None,
                'available': None,
                'percent': None,
                'used': None,
                'free': None
            }
        except Exception as e:
            self.logger.debug(f"收集記憶體使用資訊失敗: {e}")
            return {}
    
    def get_metrics_summary(self, days: int = 7) -> Dict[str, Any]:
        """
        獲取指標摘要
        
        Args:
            days: 統計天數
            
        Returns:
            指標摘要
        """
        try:
            # 計算時間範圍
            end_time = datetime.now()
            start_time = end_time - timedelta(days=days)
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 會話級統計
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_sessions,
                        AVG(processing_time) as avg_processing_time,
                        AVG(success_rate) as avg_success_rate,
                        AVG(average_processing_rate) as avg_processing_rate,
                        SUM(total_processed) as total_processed,
                        SUM(total_created) as total_created,
                        SUM(total_updated) as total_updated,
                        SUM(total_failed) as total_failed
                    FROM sync_session_metrics 
                    WHERE start_time >= ? AND start_time <= ?
                ''', (start_time.isoformat(), end_time.isoformat()))
                
                session_stats = dict(cursor.fetchone())
                
                # 表格級統計
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_table_syncs,
                        AVG(filter_rate) as avg_filter_rate,
                        AVG(processing_rate) as avg_table_processing_rate,
                        COUNT(CASE WHEN is_cold_start = 1 THEN 1 END) as cold_start_count,
                        AVG(success_rate) as avg_table_success_rate
                    FROM table_metrics 
                    WHERE sync_time >= ? AND sync_time <= ?
                ''', (start_time.isoformat(), end_time.isoformat()))
                
                table_stats = dict(cursor.fetchone())
                
                # 趨勢分析
                trend_data = self._get_trend_data(start_time, end_time)
                
                return {
                    'summary_period': {
                        'start_time': start_time.isoformat(),
                        'end_time': end_time.isoformat(),
                        'days': days
                    },
                    'session_statistics': session_stats,
                    'table_statistics': table_stats,
                    'trend_data': trend_data,
                    'database_info': {
                        'db_path': self.db_path,
                        'db_size_mb': os.path.getsize(self.db_path) / (1024 * 1024) if os.path.exists(self.db_path) else 0
                    }
                }
                
        except Exception as e:
            self.logger.error(f"獲取指標摘要失敗: {e}")
            return {'error': str(e)}
    
    def _get_trend_data(self, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
        """獲取趨勢資料"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT 
                        DATE(start_time) as date,
                        COUNT(*) as session_count,
                        AVG(processing_time) as avg_processing_time,
                        AVG(success_rate) as avg_success_rate,
                        SUM(total_processed) as daily_processed
                    FROM sync_session_metrics 
                    WHERE start_time >= ? AND start_time <= ?
                    GROUP BY DATE(start_time)
                    ORDER BY date
                ''', (start_time.isoformat(), end_time.isoformat()))
                
                trend_data = []
                for row in cursor.fetchall():
                    trend_data.append(dict(row))
                
                return trend_data
                
        except Exception as e:
            self.logger.error(f"獲取趨勢資料失敗: {e}")
            return []
    
    def get_table_performance_report(self, table_id: str, days: int = 30) -> Dict[str, Any]:
        """
        獲取表格效能報告
        
        Args:
            table_id: 表格 ID
            days: 統計天數
            
        Returns:
            表格效能報告
        """
        try:
            end_time = datetime.now()
            start_time = end_time - timedelta(days=days)
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 基本統計
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_syncs,
                        AVG(processing_time) as avg_processing_time,
                        AVG(filter_rate) as avg_filter_rate,
                        AVG(processing_rate) as avg_processing_rate,
                        AVG(success_rate) as avg_success_rate,
                        SUM(created_records) as total_created,
                        SUM(updated_records) as total_updated,
                        SUM(failed_operations) as total_failed,
                        COUNT(CASE WHEN is_cold_start = 1 THEN 1 END) as cold_start_count
                    FROM table_metrics 
                    WHERE table_id = ? AND sync_time >= ? AND sync_time <= ?
                ''', (table_id, start_time.isoformat(), end_time.isoformat()))
                
                basic_stats = dict(cursor.fetchone())
                
                # 最近的同步記錄
                cursor.execute('''
                    SELECT * FROM table_metrics 
                    WHERE table_id = ? AND sync_time >= ? AND sync_time <= ?
                    ORDER BY sync_time DESC
                    LIMIT 10
                ''', (table_id, start_time.isoformat(), end_time.isoformat()))
                
                recent_syncs = [dict(row) for row in cursor.fetchall()]
                
                return {
                    'table_id': table_id,
                    'report_period': {
                        'start_time': start_time.isoformat(),
                        'end_time': end_time.isoformat(),
                        'days': days
                    },
                    'basic_statistics': basic_stats,
                    'recent_syncs': recent_syncs
                }
                
        except Exception as e:
            self.logger.error(f"獲取表格效能報告失敗: {e}")
            return {'error': str(e)}
    
    def cleanup_old_metrics(self, days_to_keep: int = 90) -> Dict[str, Any]:
        """
        清理舊指標資料
        
        Args:
            days_to_keep: 保留天數
            
        Returns:
            清理結果
        """
        try:
            cutoff_time = datetime.now() - timedelta(days=days_to_keep)
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 清理會話指標
                cursor.execute('''
                    DELETE FROM sync_session_metrics 
                    WHERE start_time < ?
                ''', (cutoff_time.isoformat(),))
                
                session_deleted = cursor.rowcount
                
                # 清理表格指標
                cursor.execute('''
                    DELETE FROM table_metrics 
                    WHERE sync_time < ?
                ''', (cutoff_time.isoformat(),))
                
                table_deleted = cursor.rowcount
                
                conn.commit()
                
                # 優化資料庫
                cursor.execute('VACUUM')
                
                result = {
                    'success': True,
                    'days_to_keep': days_to_keep,
                    'session_metrics_deleted': session_deleted,
                    'table_metrics_deleted': table_deleted,
                    'total_cleaned': session_deleted + table_deleted
                }
                
                self.logger.info(f"清理舊指標資料完成: {result}")
                
                return result
                
        except Exception as e:
            self.logger.error(f"清理舊指標資料失敗: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def export_metrics_to_json(self, output_path: str, days: int = 30) -> bool:
        """
        匯出指標資料到 JSON 檔案
        
        Args:
            output_path: 輸出檔案路徑
            days: 匯出天數
            
        Returns:
            是否成功
        """
        try:
            # 獲取指標摘要
            metrics_summary = self.get_metrics_summary(days)
            
            # 寫入 JSON 檔案
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(metrics_summary, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"指標資料已匯出到: {output_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"匯出指標資料失敗: {e}")
            return False


# 測試模組
if __name__ == '__main__':
    import tempfile
    import logging
    from unittest.mock import Mock
    
    # 設定日誌
    logging.basicConfig(level=logging.INFO)
    
    # 創建臨時資料庫
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        # 測試指標收集器
        collector = SyncMetricsCollector(db_path, logging.getLogger())
        
        print("同步指標收集器測試:")
        print(f"資料庫路徑: {db_path}")
        
        # 創建模擬同步結果
        mock_sync_result = Mock()
        mock_sync_result.start_time = '2023-01-01T00:00:00'
        mock_sync_result.end_time = '2023-01-01T00:01:00'
        mock_sync_result.processing_time = 60.0
        mock_sync_result.total_teams = 1
        mock_sync_result.total_tables = 2
        mock_sync_result.successful_tables = 2
        mock_sync_result.failed_tables = 0
        mock_sync_result.total_processed = 100
        mock_sync_result.total_created = 50
        mock_sync_result.total_updated = 50
        mock_sync_result.total_failed = 0
        mock_sync_result.team_results = {}
        
        # 測試記錄會話指標
        success = collector.record_sync_session(mock_sync_result)
        print(f"記錄會話指標: {'成功' if success else '失敗'}")
        
        # 測試獲取指標摘要
        summary = collector.get_metrics_summary(7)
        print(f"指標摘要: {summary.get('session_statistics', {}).get('total_sessions', 0)} 個會話")
        
        # 測試清理舊資料
        cleanup_result = collector.cleanup_old_metrics(30)
        print(f"清理結果: {cleanup_result.get('success', False)}")
        
        print("同步指標收集器測試完成")
        
    except Exception as e:
        print(f"測試失敗: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理臨時檔案
        if os.path.exists(db_path):
            os.unlink(db_path)