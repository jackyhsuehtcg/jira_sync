#!/usr/bin/env python3
"""
用戶緩存轉換工具
將舊版 JSON 格式的用戶映射緩存轉換為新版 SQLite 格式
"""

import json
import os
import sqlite3
from datetime import datetime
from typing import Dict, Any


def load_old_json_cache(json_file_path: str) -> Dict[str, Any]:
    """
    載入舊版 JSON 格式的用戶緩存
    
    Args:
        json_file_path: JSON 文件路徑
        
    Returns:
        用戶緩存字典
    """
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('mappings', {})
    except Exception as e:
        print(f"載入舊版緩存失敗: {e}")
        return {}


def create_new_sqlite_cache(db_file_path: str):
    """
    創建新版 SQLite 緩存數據庫
    
    Args:
        db_file_path: SQLite 數據庫文件路徑
    """
    try:
        # 如果數據庫文件已存在，備份並刪除
        if os.path.exists(db_file_path):
            backup_path = f"{db_file_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            os.rename(db_file_path, backup_path)
            print(f"舊數據庫已備份至: {backup_path}")
        
        # 創建新數據庫
        conn = sqlite3.connect(db_file_path)
        cursor = conn.cursor()
        
        # 創建用戶映射表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_mappings (
                username TEXT PRIMARY KEY,
                lark_email TEXT,
                lark_user_id TEXT,
                lark_name TEXT,
                is_empty BOOLEAN DEFAULT 0,
                is_pending BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 創建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_username ON user_mappings(username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_lark_user_id ON user_mappings(lark_user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_is_empty ON user_mappings(is_empty)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_is_pending ON user_mappings(is_pending)')
        
        conn.commit()
        conn.close()
        
        print(f"新版 SQLite 數據庫創建成功: {db_file_path}")
        
    except Exception as e:
        print(f"創建新版數據庫失敗: {e}")
        raise


def convert_user_record(username: str, record: Dict[str, Any]) -> Dict[str, Any]:
    """
    轉換單個用戶記錄從舊版格式到新版格式
    
    Args:
        username: 用戶名
        record: 舊版用戶記錄
        
    Returns:
        新版用戶記錄
    """
    new_record = {
        'username': username,
        'lark_email': None,
        'lark_user_id': None,
        'lark_name': None,
        'is_empty': False,
        'is_pending': False,
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }
    
    # 檢查是否為空值記錄
    if record.get('is_empty', False):
        new_record['is_empty'] = True
        print(f"轉換空值記錄: {username}")
    else:
        # 正常用戶記錄
        new_record['lark_email'] = record.get('lark_email')
        new_record['lark_user_id'] = record.get('lark_user_id')
        new_record['lark_name'] = record.get('lark_name')
        print(f"轉換正常記錄: {username} -> {new_record['lark_email']}")
    
    return new_record


def insert_user_records(db_file_path: str, user_records: Dict[str, Any]):
    """
    將用戶記錄插入到 SQLite 數據庫
    
    Args:
        db_file_path: SQLite 數據庫文件路徑
        user_records: 用戶記錄字典
    """
    try:
        conn = sqlite3.connect(db_file_path)
        cursor = conn.cursor()
        
        success_count = 0
        error_count = 0
        
        for username, record in user_records.items():
            try:
                new_record = convert_user_record(username, record)
                
                cursor.execute('''
                    INSERT OR REPLACE INTO user_mappings 
                    (username, lark_email, lark_user_id, lark_name, is_empty, is_pending, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    new_record['username'],
                    new_record['lark_email'],
                    new_record['lark_user_id'],
                    new_record['lark_name'],
                    new_record['is_empty'],
                    new_record['is_pending'],
                    new_record['created_at'],
                    new_record['updated_at']
                ))
                
                success_count += 1
                
            except Exception as e:
                print(f"插入用戶記錄失敗 {username}: {e}")
                error_count += 1
        
        conn.commit()
        conn.close()
        
        print(f"用戶記錄插入完成: {success_count} 成功, {error_count} 失敗")
        
    except Exception as e:
        print(f"插入用戶記錄失敗: {e}")
        raise


def verify_conversion(db_file_path: str):
    """
    驗證轉換結果
    
    Args:
        db_file_path: SQLite 數據庫文件路徑
    """
    try:
        conn = sqlite3.connect(db_file_path)
        cursor = conn.cursor()
        
        # 統計總記錄數
        cursor.execute('SELECT COUNT(*) FROM user_mappings')
        total_count = cursor.fetchone()[0]
        
        # 統計正常記錄數
        cursor.execute('SELECT COUNT(*) FROM user_mappings WHERE is_empty = 0 AND is_pending = 0')
        normal_count = cursor.fetchone()[0]
        
        # 統計空值記錄數
        cursor.execute('SELECT COUNT(*) FROM user_mappings WHERE is_empty = 1')
        empty_count = cursor.fetchone()[0]
        
        # 統計待查記錄數
        cursor.execute('SELECT COUNT(*) FROM user_mappings WHERE is_pending = 1')
        pending_count = cursor.fetchone()[0]
        
        conn.close()
        
        print(f"\n轉換結果驗證:")
        print(f"總記錄數: {total_count}")
        print(f"正常記錄數: {normal_count}")
        print(f"空值記錄數: {empty_count}")
        print(f"待查記錄數: {pending_count}")
        
        # 檢查關鍵用戶是否轉換成功
        test_users = ['syron.d', 'paul.pua', 'nicole.g', 'alex.l']
        conn = sqlite3.connect(db_file_path)
        cursor = conn.cursor()
        
        print(f"\n關鍵用戶檢查:")
        for username in test_users:
            cursor.execute('SELECT username, lark_email, is_empty FROM user_mappings WHERE username = ?', (username,))
            result = cursor.fetchone()
            if result:
                print(f"  {username}: {'空值記錄' if result[2] else f'正常記錄 -> {result[1]}'}")
            else:
                print(f"  {username}: 未找到")
        
        conn.close()
        
    except Exception as e:
        print(f"驗證轉換結果失敗: {e}")


def main():
    """主函數"""
    # 文件路徑
    old_json_file = '/Users/hideman/code/jira_sync_v3/archive/user_mapping_cache.json'
    new_sqlite_file = '/Users/hideman/code/jira_sync_v3/data/user_mapping_cache.db'
    
    print("開始轉換用戶緩存...")
    print(f"舊版 JSON 文件: {old_json_file}")
    print(f"新版 SQLite 文件: {new_sqlite_file}")
    
    try:
        # 1. 載入舊版 JSON 緩存
        print(f"\n1. 載入舊版 JSON 緩存...")
        old_cache = load_old_json_cache(old_json_file)
        print(f"載入了 {len(old_cache)} 個用戶記錄")
        
        # 2. 創建新版 SQLite 數據庫
        print(f"\n2. 創建新版 SQLite 數據庫...")
        create_new_sqlite_cache(new_sqlite_file)
        
        # 3. 轉換並插入用戶記錄
        print(f"\n3. 轉換並插入用戶記錄...")
        insert_user_records(new_sqlite_file, old_cache)
        
        # 4. 驗證轉換結果
        print(f"\n4. 驗證轉換結果...")
        verify_conversion(new_sqlite_file)
        
        print(f"\n✅ 用戶緩存轉換完成!")
        
    except Exception as e:
        print(f"\n❌ 轉換失敗: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()