#!/usr/bin/env python3
"""
用戶 ID 補齊工具

專門處理有 username 和 lark_email，但缺少 lark_user_id 的記錄
通過 Lark API 查詢用戶資訊並補齊 lark_user_id
"""

import sqlite3
import os
from typing import List, Dict, Optional
from datetime import datetime


class UserIdFixer:
    """用戶 ID 修復器"""
    
    def __init__(self, db_path: str, lark_client):
        """
        初始化修復器
        
        Args:
            db_path: 用戶緩存資料庫路徑
            lark_client: Lark 客戶端實例
        """
        self.db_path = os.path.abspath(db_path)
        self.lark_client = lark_client
        
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"資料庫文件不存在: {self.db_path}")
    
    def get_incomplete_users(self) -> List[Dict[str, any]]:
        """獲取需要補齊 user_id 的用戶"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT username, lark_email, lark_name
                FROM user_mappings 
                WHERE username IS NOT NULL AND username != ''
                  AND lark_email IS NOT NULL AND lark_email != ''
                  AND (lark_user_id IS NULL OR lark_user_id = '')
                ORDER BY username
            """)
            
            columns = ['username', 'lark_email', 'lark_name']
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def get_users_with_email(self) -> List[Dict[str, any]]:
        """獲取所有有 email 的用戶（full-update 模式用）"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT username, lark_email, lark_name, lark_user_id
                FROM user_mappings 
                WHERE username IS NOT NULL AND username != ''
                  AND lark_email IS NOT NULL AND lark_email != ''
                ORDER BY username
            """)
            
            columns = ['username', 'lark_email', 'lark_name', 'lark_user_id']
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def query_lark_user_by_email(self, email: str) -> Optional[Dict[str, any]]:
        """
        通過 email 查詢 Lark 用戶資訊
        
        Args:
            email: 用戶 email
            
        Returns:
            用戶資訊或 None
        """
        try:
            # 使用 Lark 客戶端查詢用戶
            user_info = self.lark_client.user_manager.get_user_by_email(email)
            
            if user_info and user_info.get('id'):
                return {
                    'user_id': user_info['id'],
                    'name': user_info.get('name', email.split('@')[0]),  # 使用 email 前綴作為名稱
                    'email': user_info.get('email', email)
                }
            
            return None
            
        except Exception as e:
            print(f"    ❌ 查詢 {email} 時發生錯誤: {e}")
            return None
    
    def update_user_id(self, username: str, user_id: str, name: str = None, email: str = None, dry_run: bool = True) -> bool:
        """
        更新用戶的 lark_user_id
        
        Args:
            username: 用戶名
            user_id: Lark 用戶 ID
            name: Lark 用戶名稱
            email: Lark 用戶 Email
            dry_run: 是否只是模擬運行
            
        Returns:
            是否成功更新
        """
        if dry_run:
            print(f"    [DRY RUN] 將更新 {username} 的 user_id: {user_id}")
            if name:
                print(f"    [DRY RUN] 同時更新名稱: {name}")
            if email:
                print(f"    [DRY RUN] 同時更新 Email: {email}")
            return True
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 構建動態更新語句
                update_fields = ["lark_user_id = ?", "is_pending = 0", "updated_at = ?"]
                update_values = [user_id, datetime.now().isoformat()]
                
                if name:
                    update_fields.append("lark_name = ?")
                    update_values.append(name)
                
                if email:
                    update_fields.append("lark_email = ?")
                    update_values.append(email)
                
                update_values.append(username)  # WHERE username = ?
                
                sql = f"""
                    UPDATE user_mappings 
                    SET {', '.join(update_fields)}
                    WHERE username = ?
                """
                
                cursor.execute(sql, update_values)
                
                if cursor.rowcount > 0:
                    print(f"    ✅ 成功更新 {username} 的 user_id")
                    return True
                else:
                    print(f"    ❌ 更新 {username} 失敗：未找到記錄")
                    return False
                    
        except Exception as e:
            print(f"    ❌ 更新 {username} 時發生錯誤: {e}")
            return False
    
    def run_fix(self, dry_run: bool = True, full_update: bool = False) -> Dict[str, int]:
        """
        執行 user_id 補齊操作
        
        Args:
            dry_run: 是否只是模擬運行
            full_update: 是否為全量更新模式（更新所有有 email 的用戶）
            
        Returns:
            修復統計
        """
        mode_text = "全量更新" if full_update else "補齊缺失"
        print(f"🔧 開始{mode_text} lark_user_id{'（模擬模式）' if dry_run else ''}...")
        
        # 根據模式獲取用戶
        if full_update:
            users_to_process = self.get_users_with_email()
            print(f"📊 發現 {len(users_to_process)} 個有 email 的用戶（全量更新模式）")
        else:
            users_to_process = self.get_incomplete_users()
            print(f"📊 發現 {len(users_to_process)} 個需要補齊 user_id 的用戶")
        
        if not users_to_process:
            action_text = "處理" if full_update else "補齊"
            print(f"✅ 沒有需要{action_text}的用戶")
            return {'total_checked': 0, 'fixed': 0, 'failed': 0, 'not_found': 0, 'updated': 0}
        
        stats = {
            'total_checked': 0,
            'fixed': 0,
            'failed': 0,
            'not_found': 0,
            'updated': 0,
            'unchanged': 0
        }
        
        for user in users_to_process:
            username = user['username']
            lark_email = user['lark_email']
            current_user_id = user.get('lark_user_id', '')
            stats['total_checked'] += 1
            
            if full_update and current_user_id:
                print(f"\n🔍 處理用戶: {username} (email: {lark_email}) [當前ID: {current_user_id[:12]}...]")
            else:
                print(f"\n🔍 處理用戶: {username} (email: {lark_email})")
            
            # 通過 email 查詢 Lark 用戶資訊
            lark_info = self.query_lark_user_by_email(lark_email)
            
            if lark_info:
                new_user_id = lark_info['user_id']
                
                # 在 full_update 模式下檢查是否需要更新
                if full_update and current_user_id == new_user_id:
                    print(f"    ℹ️  用戶 ID 無變化，跳過更新")
                    stats['unchanged'] += 1
                    continue
                
                # 更新用戶 ID
                if self.update_user_id(username, new_user_id, lark_info['name'], lark_info['email'], dry_run):
                    if full_update:
                        stats['updated'] += 1
                    else:
                        stats['fixed'] += 1
                else:
                    stats['failed'] += 1
            else:
                # 沒找到用戶
                print(f"    ⚠️  在 Lark 中找不到 email: {lark_email}")
                stats['not_found'] += 1
        
        # 根據模式顯示不同的統計信息
        action_text = "更新" if full_update else "補齊"
        print(f"\n📊 {action_text}完成統計:")
        print(f"  總處理: {stats['total_checked']}")
        
        if full_update:
            print(f"  成功更新: {stats['updated']}")
            print(f"  無需更新: {stats['unchanged']}")
        else:
            print(f"  成功補齊: {stats['fixed']}")
        
        print(f"  查詢失敗: {stats['failed']}")
        print(f"  未找到用戶: {stats['not_found']}")
        
        return stats


def main():
    """主函數"""
    import argparse
    import sys
    sys.path.append('.')
    
    from config_manager import ConfigManager
    from lark_client import LarkClient
    
    parser = argparse.ArgumentParser(description='用戶 ID 補齊工具')
    parser.add_argument('--db-path', default='data/user_mapping_cache.db',
                       help='用戶緩存資料庫路徑')
    parser.add_argument('--config', default='config.yaml',
                       help='配置文件路徑')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='模擬運行，不實際修改資料庫')
    parser.add_argument('--execute', action='store_true',
                       help='實際執行修復（覆蓋 --dry-run）')
    parser.add_argument('--full-update', action='store_true',
                       help='全量更新模式（更新所有有 email 的用戶）')
    
    args = parser.parse_args()
    
    # 確定是否為 dry_run
    dry_run = args.dry_run and not args.execute
    
    try:
        # 載入配置和初始化 Lark 客戶端
        print("🔧 初始化 Lark 客戶端...")
        config_manager = ConfigManager(None, args.config)
        lark_config = config_manager.get_lark_base_config()
        lark_client = LarkClient(lark_config['app_id'], lark_config['app_secret'])
        
        # 初始化修復器
        fixer = UserIdFixer(args.db_path, lark_client)
        
        # 執行修復
        stats = fixer.run_fix(dry_run=dry_run, full_update=args.full_update)
        
        if dry_run:
            mode_text = "全量更新" if args.full_update else "修復"
            print(f"\n💡 這是模擬運行。使用 --execute 參數執行實際{mode_text}。")
        
        # 顯示額外資訊
        if args.full_update:
            print(f"\n🔄 全量更新模式已完成，檢查了所有有 email 的用戶。")
        
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())