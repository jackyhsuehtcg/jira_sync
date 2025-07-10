#!/usr/bin/env python3
"""
用戶快取修復工具

根據現有 cache 中的 email 資訊補齊缺失的用戶映射：
1. 分析 empty/pending 用戶的 username 模式
2. 根據 email domain 規則推測可能的 email
3. 在現有 cache 中查找匹配的 email
4. 更新用戶資訊或標記為 empty
"""

import sqlite3
import os
import re
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime
from pathlib import Path


class UserCacheFixer:
    """用戶快取修復器"""
    
    def __init__(self, db_path: str, config_domains: List[str] = None):
        """
        初始化修復器
        
        Args:
            db_path: 用戶緩存資料庫路徑
            config_domains: 配置中的 email domains 列表
        """
        self.db_path = os.path.abspath(db_path)
        self.config_domains = config_domains or [
            'tc-gaming.com', 'noona-tech.com', 'genesis-tech.ph', 
            'gsdubai.com', 'stack-tech.info', 'itech-my.com',
            'novanine.cc', 'st-win.jp', 'st-win.com.tw', 'real-win.com.tw'
        ]
        
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"資料庫文件不存在: {self.db_path}")
    
    def analyze_cache_status(self) -> Dict[str, any]:
        """分析快取狀態"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 統計各種狀態的用戶數
            cursor.execute("""
                SELECT 
                    COUNT(CASE WHEN is_empty = 1 THEN 1 END) as empty_users,
                    COUNT(CASE WHEN is_pending = 1 THEN 1 END) as pending_users,
                    COUNT(CASE WHEN is_empty = 0 AND is_pending = 0 AND lark_user_id IS NOT NULL THEN 1 END) as valid_users,
                    COUNT(*) as total_users
                FROM user_mappings
            """)
            stats = cursor.fetchone()
            
            # 獲取 email domain 分布
            cursor.execute("""
                SELECT 
                    SUBSTR(lark_email, INSTR(lark_email, '@') + 1) as domain,
                    COUNT(*) as count
                FROM user_mappings 
                WHERE lark_email IS NOT NULL AND lark_email != ''
                GROUP BY domain
                ORDER BY count DESC
            """)
            domains = dict(cursor.fetchall())
            
            return {
                'empty_users': stats[0],
                'pending_users': stats[1], 
                'valid_users': stats[2],
                'total_users': stats[3],
                'fixable_users': stats[0] + stats[1],
                'email_domains': domains
            }
    
    def get_fixable_users(self) -> List[Dict[str, any]]:
        """獲取可修復的用戶列表"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT username, lark_email, lark_user_id, lark_name, is_empty, is_pending
                FROM user_mappings 
                WHERE is_empty = 1 OR is_pending = 1
                ORDER BY username
            """)
            
            columns = ['username', 'lark_email', 'lark_user_id', 'lark_name', 'is_empty', 'is_pending']
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def generate_email_candidates(self, username: str) -> List[str]:
        """
        根據 username 生成可能的 email 候選
        
        Args:
            username: JIRA username
            
        Returns:
            可能的 email 列表
        """
        candidates = []
        
        # 清理 username（移除特殊字符）
        clean_username = re.sub(r'[^a-zA-Z0-9._-]', '', username.lower())
        
        # 為每個 domain 生成候選
        for domain in self.config_domains:
            # 直接組合
            candidates.append(f"{clean_username}@{domain}")
            
            # 如果 username 包含點號，也嘗試不含點號的版本
            if '.' in clean_username:
                no_dot = clean_username.replace('.', '')
                candidates.append(f"{no_dot}@{domain}")
            
            # 如果 username 不含點號，嘗試常見的點號位置
            elif len(clean_username) > 3:
                # 嘗試在中間加點號（如 johnsmith -> john.smith）
                for i in range(2, len(clean_username) - 1):
                    dotted = f"{clean_username[:i]}.{clean_username[i:]}"
                    candidates.append(f"{dotted}@{domain}")
        
        return candidates
    
    def find_email_in_cache(self, email_candidates: List[str]) -> Optional[Dict[str, any]]:
        """
        在快取中查找 email 候選
        
        Args:
            email_candidates: email 候選列表
            
        Returns:
            找到的用戶資訊或 None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            for email in email_candidates:
                cursor.execute("""
                    SELECT username, lark_email, lark_user_id, lark_name
                    FROM user_mappings 
                    WHERE lark_email = ? AND is_empty = 0 AND is_pending = 0
                    AND lark_user_id IS NOT NULL AND lark_user_id != ''
                """, (email,))
                
                result = cursor.fetchone()
                if result:
                    return {
                        'source_username': result[0],
                        'lark_email': result[1], 
                        'lark_user_id': result[2],
                        'lark_name': result[3],
                        'matched_email': email
                    }
        
        return None
    
    def fix_user(self, username: str, source_info: Dict[str, any], dry_run: bool = True) -> bool:
        """
        修復單個用戶
        
        Args:
            username: 要修復的用戶名
            source_info: 來源用戶資訊
            dry_run: 是否只是模擬運行
            
        Returns:
            是否成功修復
        """
        if dry_run:
            print(f"  [DRY RUN] 將更新 {username}:")
            print(f"    - Email: {source_info['lark_email']}")
            print(f"    - User ID: {source_info['lark_user_id']}")
            print(f"    - Name: {source_info['lark_name']}")
            print(f"    - 來源用戶: {source_info['source_username']}")
            return True
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE user_mappings 
                    SET lark_email = ?, 
                        lark_user_id = ?, 
                        lark_name = ?,
                        is_empty = 0,
                        is_pending = 0,
                        updated_at = ?
                    WHERE username = ?
                """, (
                    source_info['lark_email'],
                    source_info['lark_user_id'], 
                    source_info['lark_name'],
                    datetime.now().isoformat(),
                    username
                ))
                
                if cursor.rowcount > 0:
                    print(f"  ✅ 成功修復 {username} (來源: {source_info['source_username']})")
                    return True
                else:
                    print(f"  ❌ 更新 {username} 失敗：未找到記錄")
                    return False
                    
        except Exception as e:
            print(f"  ❌ 修復 {username} 時發生錯誤: {e}")
            return False
    
    def mark_as_empty(self, username: str, dry_run: bool = True) -> bool:
        """
        將用戶標記為 empty
        
        Args:
            username: 用戶名
            dry_run: 是否只是模擬運行
            
        Returns:
            是否成功標記
        """
        if dry_run:
            print(f"  [DRY RUN] 將 {username} 標記為 empty")
            return True
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE user_mappings 
                    SET is_empty = 1,
                        is_pending = 0,
                        updated_at = ?
                    WHERE username = ?
                """, (datetime.now().isoformat(), username))
                
                if cursor.rowcount > 0:
                    print(f"  ✅ 成功將 {username} 標記為 empty")
                    return True
                else:
                    print(f"  ❌ 標記 {username} 失敗：未找到記錄")
                    return False
                    
        except Exception as e:
            print(f"  ❌ 標記 {username} 時發生錯誤: {e}")
            return False
    
    def run_fix(self, dry_run: bool = True, limit: int = None) -> Dict[str, int]:
        """
        執行修復操作
        
        Args:
            dry_run: 是否只是模擬運行
            limit: 限制處理的用戶數量
            
        Returns:
            修復統計
        """
        print(f"🔧 開始用戶快取修復{'（模擬模式）' if dry_run else ''}...")
        
        # 獲取需要修復的用戶
        fixable_users = self.get_fixable_users()
        if limit:
            fixable_users = fixable_users[:limit]
        
        print(f"📊 發現 {len(fixable_users)} 個需要修復的用戶")
        
        stats = {
            'total_checked': 0,
            'fixed_by_email': 0,
            'marked_as_empty': 0,
            'failed': 0
        }
        
        for user in fixable_users:
            username = user['username']
            stats['total_checked'] += 1
            
            print(f"\n🔍 處理用戶: {username}")
            
            # 生成 email 候選
            email_candidates = self.generate_email_candidates(username)
            print(f"  生成 {len(email_candidates)} 個 email 候選")
            
            # 在快取中查找匹配的 email
            found_info = self.find_email_in_cache(email_candidates)
            
            if found_info:
                # 找到匹配，修復用戶
                if self.fix_user(username, found_info, dry_run):
                    stats['fixed_by_email'] += 1
                else:
                    stats['failed'] += 1
            else:
                # 沒找到匹配，標記為 empty
                if self.mark_as_empty(username, dry_run):
                    stats['marked_as_empty'] += 1
                else:
                    stats['failed'] += 1
        
        print(f"\n📊 修復完成統計:")
        print(f"  總處理: {stats['total_checked']}")
        print(f"  通過 email 修復: {stats['fixed_by_email']}")
        print(f"  標記為 empty: {stats['marked_as_empty']}")
        print(f"  失敗: {stats['failed']}")
        
        return stats


def main():
    """主函數"""
    import argparse
    
    parser = argparse.ArgumentParser(description='用戶快取修復工具')
    parser.add_argument('--db-path', default='data/user_mapping_cache.db', 
                       help='用戶緩存資料庫路徑')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='模擬運行，不實際修改資料庫')
    parser.add_argument('--execute', action='store_true',
                       help='實際執行修復（覆蓋 --dry-run）')
    parser.add_argument('--limit', type=int,
                       help='限制處理的用戶數量')
    parser.add_argument('--analyze-only', action='store_true',
                       help='只分析快取狀態，不執行修復')
    
    args = parser.parse_args()
    
    # 確定是否為 dry_run
    dry_run = args.dry_run and not args.execute
    
    try:
        # 初始化修復器
        fixer = UserCacheFixer(args.db_path)
        
        # 顯示快取狀態
        print("📊 分析用戶快取狀態...")
        status = fixer.analyze_cache_status()
        print(f"  總用戶數: {status['total_users']}")
        print(f"  有效用戶: {status['valid_users']}")
        print(f"  Empty 用戶: {status['empty_users']}")
        print(f"  Pending 用戶: {status['pending_users']}")
        print(f"  可修復用戶: {status['fixable_users']}")
        
        print(f"\n📧 Email domains 分布:")
        for domain, count in status['email_domains'].items():
            print(f"  {domain}: {count}")
        
        if args.analyze_only:
            return
        
        # 執行修復
        stats = fixer.run_fix(dry_run=dry_run, limit=args.limit)
        
        if dry_run:
            print(f"\n💡 這是模擬運行。使用 --execute 參數執行實際修復。")
        
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())