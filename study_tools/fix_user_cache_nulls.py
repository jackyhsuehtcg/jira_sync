#!/usr/bin/env python3
"""
用戶緩存 NULL 值修復工具

修復 user_mapping_cache.db 中 is_empty 和 is_pending 為 NULL 的記錄
這些 NULL 值會導致 user_id_fixer 無法正確找到需要處理的記錄

使用方法:
python fix_user_cache_nulls.py [--dry-run]
"""

import sqlite3
import argparse
from datetime import datetime


def fix_null_values(db_path: str, dry_run: bool = True):
    """
    修復 user_mappings 表中的 NULL 值
    
    Args:
        db_path: 資料庫路徑
        dry_run: 是否只是模擬運行
    """
    print(f"正在檢查資料庫: {db_path}")
    
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # 檢查有多少記錄有 NULL 值
        cursor.execute("""
            SELECT COUNT(*) FROM user_mappings 
            WHERE is_empty IS NULL OR is_pending IS NULL
        """)
        null_count = cursor.fetchone()[0]
        
        if null_count == 0:
            print("✅ 沒有發現 NULL 值，資料庫狀態正常")
            return
            
        print(f"🔍 發現 {null_count} 筆記錄有 NULL 值")
        
        # 列出受影響的記錄
        cursor.execute("""
            SELECT username, lark_email, is_empty, is_pending 
            FROM user_mappings 
            WHERE is_empty IS NULL OR is_pending IS NULL
            ORDER BY username
        """)
        
        affected_records = cursor.fetchall()
        print("\n受影響的記錄:")
        for record in affected_records[:10]:  # 只顯示前10筆
            username, email, is_empty, is_pending = record
            print(f"  - {username}: email={email}, is_empty={is_empty}, is_pending={is_pending}")
        
        if len(affected_records) > 10:
            print(f"  ... 還有 {len(affected_records) - 10} 筆記錄")
        
        if dry_run:
            print("\n[DRY RUN] 模擬修復操作:")
            print("  - 將所有 NULL is_empty 設為 0")
            print("  - 將所有 NULL is_pending 設為 0")
            print("  - 更新 updated_at 時間戳")
            print("\n要執行實際修復，請加上 --execute 參數")
        else:
            print("\n🔧 開始修復...")
            
            # 修復 is_empty NULL 值
            cursor.execute("""
                UPDATE user_mappings 
                SET is_empty = 0, updated_at = ?
                WHERE is_empty IS NULL
            """, (datetime.now().isoformat(),))
            is_empty_fixed = cursor.rowcount
            
            # 修復 is_pending NULL 值
            cursor.execute("""
                UPDATE user_mappings 
                SET is_pending = 0, updated_at = ?
                WHERE is_pending IS NULL
            """, (datetime.now().isoformat(),))
            is_pending_fixed = cursor.rowcount
            
            conn.commit()
            
            print(f"✅ 修復完成:")
            print(f"  - 修復 is_empty NULL 值: {is_empty_fixed} 筆")
            print(f"  - 修復 is_pending NULL 值: {is_pending_fixed} 筆")
            
            # 驗證修復結果
            cursor.execute("""
                SELECT COUNT(*) FROM user_mappings 
                WHERE is_empty IS NULL OR is_pending IS NULL
            """)
            remaining_nulls = cursor.fetchone()[0]
            
            if remaining_nulls == 0:
                print("🎉 所有 NULL 值已成功修復！")
            else:
                print(f"⚠️ 仍有 {remaining_nulls} 筆記錄存在 NULL 值")


def main():
    parser = argparse.ArgumentParser(description="修復用戶緩存中的 NULL 值")
    parser.add_argument("--db-path", default="data/user_mapping_cache.db", 
                       help="資料庫檔案路徑 (預設: data/user_mapping_cache.db)")
    parser.add_argument("--execute", action="store_true", 
                       help="執行實際修復 (預設為 dry-run 模式)")
    
    args = parser.parse_args()
    
    try:
        fix_null_values(args.db_path, dry_run=not args.execute)
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())