#!/usr/bin/env python3
"""
用戶緩存管理模組

負責用戶映射數據的 SQLite 緩存管理：
- 高效的 SQLite 數據庫操作
- 緩存項目驗證和統計
- 線程安全的數據訪問
- 自動數據庫初始化
"""

import sqlite3
import threading
import os
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from contextlib import contextmanager


class UserCacheManager:
    """用戶緩存管理器 - 基於 SQLite 的高效緩存"""
    
    def __init__(self, db_path: str):
        """
        初始化用戶緩存管理器
        
        Args:
            db_path: SQLite 數據庫文件路徑
        """
        self.db_path = os.path.abspath(db_path)
        self.db_lock = threading.RLock()  # 線程安全鎖
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.UserCacheManager")
        
        # 初始化數據庫
        self._init_database()
        
        self.logger.info(f"用戶緩存管理器初始化完成，數據庫: {self.db_path}")
    
    def _init_database(self):
        """初始化 SQLite 數據庫表結構"""
        try:
            # 確保目錄存在
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 創建用戶映射表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_mappings (
                        username TEXT PRIMARY KEY,
                        lark_email TEXT,
                        lark_user_id TEXT,
                        lark_name TEXT,
                        is_empty INTEGER DEFAULT 0,
                        is_pending INTEGER DEFAULT 0,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 創建索引
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_user_mappings_lark_email 
                    ON user_mappings (lark_email)
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_user_mappings_status 
                    ON user_mappings (is_empty, is_pending)
                ''')
                
                conn.commit()
                self.logger.debug("數據庫表結構初始化完成")
                
        except Exception as e:
            self.logger.error(f"數據庫初始化失敗: {e}")
            raise
    
    @contextmanager
    def _get_connection(self):
        """獲取線程安全的數據庫連接"""
        with self.db_lock:
            conn = sqlite3.connect(
                self.db_path,
                timeout=30.0,  # 30秒超時
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row  # 支持字典式訪問
            try:
                yield conn
            finally:
                conn.close()
    
    def get_user_mapping(self, username: str) -> Optional[Dict[str, Any]]:
        """
        獲取用戶映射記錄
        
        Args:
            username: 用戶名
            
        Returns:
            用戶映射記錄字典，未找到則返回 None
        """
        if not username:
            return None
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT * FROM user_mappings WHERE username = ?',
                    (username,)
                )
                row = cursor.fetchone()
                
                if row:
                    return dict(row)
                return None
                
        except Exception as e:
            self.logger.warning(f"獲取用戶映射失敗: {username}, {e}")
            return None
    
    def set_user_mapping(self, username: str, mapping_data: Dict[str, Any]) -> bool:
        """
        設置用戶映射記錄
        
        Args:
            username: 用戶名
            mapping_data: 映射數據
            
        Returns:
            是否成功
        """
        if not username:
            return False
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 準備數據
                lark_email = mapping_data.get('lark_email')
                lark_user_id = mapping_data.get('lark_user_id')
                lark_name = mapping_data.get('lark_name')
                is_empty = 1 if mapping_data.get('is_empty', False) else 0
                is_pending = 1 if mapping_data.get('is_pending', False) else 0
                
                # 使用 REPLACE 實現 upsert
                cursor.execute('''
                    REPLACE INTO user_mappings 
                    (username, lark_email, lark_user_id, lark_name, 
                     is_empty, is_pending, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (username, lark_email, lark_user_id, lark_name,
                      is_empty, is_pending))
                
                conn.commit()
                self.logger.debug(f"用戶映射已更新: {username}")
                return True
                
        except Exception as e:
            self.logger.warning(f"設置用戶映射失敗: {username}, {e}")
            return False
    
    def get_all_mappings(self) -> Dict[str, Dict[str, Any]]:
        """
        獲取所有用戶映射記錄
        
        Returns:
            用戶映射字典 {username: mapping_data}
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM user_mappings')
                rows = cursor.fetchall()
                
                mappings = {}
                for row in rows:
                    username = row['username']
                    mapping_data = dict(row)
                    
                    # 轉換布爾值
                    mapping_data['is_empty'] = bool(mapping_data['is_empty'])
                    mapping_data['is_pending'] = bool(mapping_data['is_pending'])
                    
                    mappings[username] = mapping_data
                
                return mappings
                
        except Exception as e:
            self.logger.warning(f"獲取所有用戶映射失敗: {e}")
            return {}
    
    def delete_user_mapping(self, username: str) -> bool:
        """
        刪除用戶映射記錄
        
        Args:
            username: 用戶名
            
        Returns:
            是否成功
        """
        if not username:
            return False
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM user_mappings WHERE username = ?', (username,))
                conn.commit()
                
                deleted_count = cursor.rowcount
                if deleted_count > 0:
                    self.logger.debug(f"用戶映射已刪除: {username}")
                    return True
                return False
                
        except Exception as e:
            self.logger.warning(f"刪除用戶映射失敗: {username}, {e}")
            return False
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        獲取緩存統計資訊
        
        Returns:
            統計資訊字典
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 總記錄數
                cursor.execute('SELECT COUNT(*) as total FROM user_mappings')
                total_count = cursor.fetchone()['total']
                
                # 有效記錄數
                cursor.execute('''
                    SELECT COUNT(*) as valid 
                    FROM user_mappings 
                    WHERE is_empty = 0 AND is_pending = 0
                ''')
                valid_count = cursor.fetchone()['valid']
                
                # 空值記錄數
                cursor.execute('SELECT COUNT(*) as empty FROM user_mappings WHERE is_empty = 1')
                empty_count = cursor.fetchone()['empty']
                
                # 待查記錄數
                cursor.execute('SELECT COUNT(*) as pending FROM user_mappings WHERE is_pending = 1')
                pending_count = cursor.fetchone()['pending']
                
                # 數據庫文件大小
                db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
                
                return {
                    'total_cached_users': total_count,
                    'valid_users': valid_count,
                    'empty_records': empty_count,
                    'pending_records': pending_count,
                    'db_file': self.db_path,
                    'db_size_bytes': db_size,
                    'db_size_mb': round(db_size / (1024 * 1024), 2)
                }
                
        except Exception as e:
            self.logger.error(f"獲取緩存統計失敗: {e}")
            return {
                'total_cached_users': 0,
                'valid_users': 0,
                'empty_records': 0,
                'pending_records': 0,
                'db_file': self.db_path,
                'db_size_bytes': 0,
                'db_size_mb': 0
            }
    
    def get_pending_users(self) -> List[str]:
        """
        獲取所有待查用戶列表
        
        Returns:
            待查用戶名列表
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT username FROM user_mappings WHERE is_pending = 1')
                rows = cursor.fetchall()
                
                return [row['username'] for row in rows]
                
        except Exception as e:
            self.logger.error(f"獲取待查用戶失敗: {e}")
            return []
    
    def clear_pending_users(self) -> int:
        """
        清除所有待查用戶記錄
        
        Returns:
            清除的記錄數
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM user_mappings WHERE is_pending = 1')
                conn.commit()
                
                deleted_count = cursor.rowcount
                if deleted_count > 0:
                    self.logger.info(f"已清除 {deleted_count} 個待查用戶記錄")
                
                return deleted_count
                
        except Exception as e:
            self.logger.error(f"清除待查用戶失敗: {e}")
            return 0
    
    def vacuum_database(self) -> bool:
        """
        清理和優化數據庫
        
        Returns:
            是否成功
        """
        try:
            with self._get_connection() as conn:
                conn.execute('VACUUM')
                conn.commit()
                self.logger.info("數據庫清理完成")
                return True
                
        except Exception as e:
            self.logger.error(f"數據庫清理失敗: {e}")
            return False
    
    def validate_cache_entry(self, username: str, user_data: Dict[str, Any]) -> bool:
        """
        驗證緩存項目的有效性
        
        Args:
            username: 用戶名
            user_data: 用戶數據
            
        Returns:
            是否有效
        """
        if not isinstance(user_data, dict):
            return False
        
        # 檢查是否為空值記錄
        if user_data.get('is_empty', False):
            return True
        
        # 檢查是否為待查記錄
        if user_data.get('is_pending', False):
            return True
        
        # 成功記錄需要完整的用戶資訊
        required_fields = ['lark_email', 'lark_user_id', 'lark_name']
        for field in required_fields:
            if field not in user_data or not user_data[field]:
                return False
        
        return True


# 測試模組
if __name__ == '__main__':
    import tempfile
    import logging
    
    # 設定日誌
    logging.basicConfig(level=logging.DEBUG)
    
    # 創建臨時數據庫
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        # 測試 UserCacheManager
        cache_manager = UserCacheManager(db_path)
        
        print("用戶緩存管理器測試:")
        print(f"數據庫路徑: {db_path}")
        
        # 測試設置用戶映射
        test_mapping = {
            'lark_email': 'test@example.com',
            'lark_user_id': 'user123',
            'lark_name': 'Test User'
        }
        
        success = cache_manager.set_user_mapping('testuser', test_mapping)
        print(f"設置用戶映射: {'成功' if success else '失敗'}")
        
        # 測試獲取用戶映射
        retrieved = cache_manager.get_user_mapping('testuser')
        print(f"獲取用戶映射: {retrieved}")
        
        # 測試空值記錄
        empty_mapping = {
            'is_empty': True,
            'reason': '查詢失敗'
        }
        cache_manager.set_user_mapping('emptyuser', empty_mapping)
        
        # 測試待查記錄
        pending_mapping = {
            'is_pending': True
        }
        cache_manager.set_user_mapping('pendinguser', pending_mapping)
        
        # 測試統計
        stats = cache_manager.get_cache_stats()
        print(f"緩存統計: {stats}")
        
        # 測試獲取待查用戶
        pending_users = cache_manager.get_pending_users()
        print(f"待查用戶: {pending_users}")
        
        print("用戶緩存管理器測試完成")
        
    except Exception as e:
        print(f"測試失敗: {e}")
    finally:
        # 清理臨時文件
        if os.path.exists(db_path):
            os.unlink(db_path)