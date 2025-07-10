#!/usr/bin/env python3
"""
JIRA-Lark 資料清理工具（新架構版本）

根據 JQL 條件篩選 JIRA 單號，然後清理 Lark Base 表格中對應的記錄。
支援乾跑模式、安全確認、詳細日誌記錄等功能。

使用範例:
python data_cleaner.py --team ard --table tcg_table --jql "project = TCG AND status = Closed AND updated < -30d"
python data_cleaner.py --team ard --table icr_table --jql "project = ICR AND status = Done" --dry-run
"""

import argparse
import sys
import time
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from collections import defaultdict
import logging

# 導入新架構的系統組件
from config_manager import ConfigManager
from jira_client import JiraClient
from lark_client import LarkClient
from sync_state_manager import SyncStateManager
from processing_log_manager import ProcessingLogManager


class DataCleaner:
    """資料清理器 - 根據 JQL 條件清理 Lark Base 記錄（新架構版本）"""
    
    def __init__(self, config_file: str = 'config.yaml'):
        """
        初始化資料清理器
        
        Args:
            config_file: 配置檔案路徑
        """
        # 初始化配置管理器
        self.config_manager = ConfigManager(None, config_file)
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.DataCleaner")
        
        # 初始化 JIRA 客戶端
        jira_config = self.config_manager.get_jira_config()
        self.jira_client = JiraClient(
            config=jira_config,
            logger=self.logger
        )
        
        # 初始化 Lark 客戶端
        lark_config = self.config_manager.get_lark_base_config()
        self.lark_client = LarkClient(
            app_id=lark_config['app_id'],
            app_secret=lark_config['app_secret']
        )
        
        # 初始化同步狀態管理器
        self.sync_state_manager = SyncStateManager(
            base_data_dir=self.config_manager.get_global_config()['data_directory'],
            logger=self.logger
        )
        
        # 統計資訊
        self.stats = {
            'jira_issues_found': 0,
            'lark_records_found': 0,
            'lark_records_deleted': 0,
            'duplicates_found': 0,
            'duplicate_groups': 0,
            'processing_log_cleaned': 0,
            'errors': 0
        }
    
    def extract_issue_keys_from_jql(self, jql: str) -> List[str]:
        """
        使用 JQL 查詢從 JIRA 取得 Issue Keys
        
        Args:
            jql: JQL 查詢字串
            
        Returns:
            List[str]: Issue Key 清單
        """
        self.logger.info(f"執行 JQL 查詢: {jql}")
        
        try:
            # 使用新架構的 JIRA 客戶端執行查詢
            issues_dict = self.jira_client.search_issues(
                jql=jql,
                fields=['key']  # 只需要 key 欄位
            )
            
            issue_keys = list(issues_dict.keys())
            self.stats['jira_issues_found'] = len(issue_keys)
            self.logger.info(f"找到 {len(issue_keys)} 個 JIRA Issues")
            
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(f"Issues: {issue_keys}")
            
            return issue_keys
            
        except Exception as e:
            self.logger.error(f"JQL 查詢失敗: {e}")
            self.stats['errors'] += 1
            return []
    
    def find_lark_records_by_issue_keys(self, team: str, table: str, issue_keys: List[str]) -> List[Dict]:
        """
        在 Lark Base 表格中找出包含指定 Issue Keys 的記錄
        
        Args:
            team: 團隊名稱
            table: 表格名稱
            issue_keys: Issue Key 清單
            
        Returns:
            List[Dict]: 匹配的 Lark 記錄清單
        """
        self.logger.info(f"在 {team}.{table} 表格中搜尋 {len(issue_keys)} 個 Issue Keys")
        
        try:
            # 取得團隊和表格配置
            team_config = self.config_manager.get_team_config(team)
            table_config = team_config['tables'][table]
            
            wiki_token = team_config['wiki_token']
            table_id = table_config['table_id']
            ticket_field = table_config.get('ticket_field', 'Issue Key')
            
            # 設定 wiki token 並取得所有記錄
            self.lark_client.set_wiki_token(wiki_token)
            all_records = self.lark_client.get_all_records(table_id)
            self.logger.info(f"表格中共有 {len(all_records)} 筆記錄")
            
            # 找出匹配的記錄
            matching_records = []
            issue_key_set = set(issue_keys)
            
            for record in all_records:
                # 從指定的票據欄位中提取 Issue Key
                issue_key = self._extract_issue_key_from_record(record, ticket_field)
                if issue_key and issue_key in issue_key_set:
                    record['_extracted_issue_key'] = issue_key  # 保存提取的 Issue Key
                    matching_records.append(record)
            
            self.stats['lark_records_found'] = len(matching_records)
            self.logger.info(f"找到 {len(matching_records)} 筆匹配的記錄")
            
            return matching_records
            
        except Exception as e:
            self.logger.error(f"搜尋 Lark 記錄失敗: {e}")
            self.stats['errors'] += 1
            return []
    
    def _extract_issue_key_from_record(self, record: Dict, ticket_field: str) -> Optional[str]:
        """
        從 Lark 記錄中提取 Issue Key
        
        Args:
            record: Lark 記錄
            ticket_field: 票據欄位名稱
            
        Returns:
            Optional[str]: Issue Key 或 None
        """
        try:
            fields = record.get('fields', {})
            field_value = fields.get(ticket_field)
            
            if field_value:
                # 處理超連結格式
                if isinstance(field_value, dict) and 'text' in field_value:
                    return field_value['text']
                # 處理純文字格式
                elif isinstance(field_value, str):
                    return field_value
            
            return None
            
        except Exception as e:
            self.logger.warning(f"提取 Issue Key 失敗: {e}")
            return None
    
    def detect_duplicate_tickets(self, team: str, table: str, jql_filter: str = None) -> Dict[str, List[Dict]]:
        """
        偵測重複的票據記錄
        
        Args:
            team: 團隊名稱
            table: 表格名稱
            jql_filter: 可選的 JQL 過濾條件，只檢測符合條件的記錄
            
        Returns:
            Dict[str, List[Dict]]: 重複記錄分組，key 為 Issue Key，value 為記錄清單
        """
        self.logger.info(f"開始偵測重複票據: {team}.{table}")
        
        try:
            # 取得團隊和表格配置
            team_config = self.config_manager.get_team_config(team)
            table_config = team_config['tables'][table]
            
            wiki_token = team_config['wiki_token']
            table_id = table_config['table_id']
            ticket_field = table_config.get('ticket_field', 'Issue Key')
            
            # 設定 wiki token 並取得所有記錄
            self.lark_client.set_wiki_token(wiki_token)
            all_records = self.lark_client.get_all_records(table_id)
            
            # 如果有 JQL 過濾條件，先取得符合條件的 Issue Keys
            valid_issue_keys = None
            if jql_filter:
                valid_issue_keys = set(self.extract_issue_keys_from_jql(jql_filter))
                self.logger.info(f"JQL 過濾後有效的 Issue Keys: {len(valid_issue_keys)} 個")
            
            # 按 Issue Key 分組記錄
            groups = defaultdict(list)
            
            for record in all_records:
                issue_key = self._extract_issue_key_from_record(record, ticket_field)
                if issue_key:
                    # 如果有 JQL 過濾條件，只處理符合條件的記錄
                    if valid_issue_keys is None or issue_key in valid_issue_keys:
                        # 保存提取的 Issue Key
                        record['_extracted_issue_key'] = issue_key
                        
                        # 處理時間戳以便排序
                        record['_created_time'] = record.get('created_time', 0)
                        record['_modified_time'] = record.get('modified_time', 0)
                        
                        groups[issue_key].append(record)
            
            # 只保留有重複的組
            duplicates = {k: v for k, v in groups.items() if len(v) > 1}
            
            self.stats['duplicates_found'] = sum(len(records) for records in duplicates.values())
            self.stats['duplicate_groups'] = len(duplicates)
            
            self.logger.info(f"發現 {len(duplicates)} 組重複記錄，共 {self.stats['duplicates_found']} 筆")
            
            return duplicates
            
        except Exception as e:
            self.logger.error(f"偵測重複記錄失敗: {e}")
            self.stats['errors'] += 1
            return {}
    
    def choose_records_to_keep(self, duplicates: Dict[str, List[Dict]], 
                              strategy: str = 'keep-latest') -> List[Dict]:
        """
        根據策略選擇要保留的記錄
        
        Args:
            duplicates: 重複記錄分組
            strategy: 保留策略 ('keep-latest', 'keep-oldest', 'interactive')
            
        Returns:
            List[Dict]: 應該被刪除的記錄
        """
        records_to_delete = []
        
        for issue_key, records in duplicates.items():
            if len(records) <= 1:
                continue  # 沒有重複，跳過
            
            if strategy == 'keep-latest':
                # 保留最新的記錄（根據修改時間或建立時間）
                records_sorted = sorted(
                    records, 
                    key=lambda r: (r.get('_modified_time', 0), r.get('_created_time', 0)), 
                    reverse=True
                )
                records_to_delete.extend(records_sorted[1:])  # 刪除除了第一個（最新）之外的所有記錄
                self.logger.debug(f"Issue {issue_key}: 保留最新記錄，標記刪除 {len(records_sorted)-1} 筆")
                
            elif strategy == 'keep-oldest':
                # 保留最舊的記錄
                records_sorted = sorted(
                    records, 
                    key=lambda r: (r.get('_created_time', 0), r.get('_modified_time', 0))
                )
                records_to_delete.extend(records_sorted[1:])  # 刪除除了第一個（最舊）之外的所有記錄
                self.logger.debug(f"Issue {issue_key}: 保留最舊記錄，標記刪除 {len(records_sorted)-1} 筆")
                
            elif strategy == 'interactive':
                # 互動模式在別的方法中處理
                records_to_delete.extend(records[1:])  # 暫時標記為刪除，稍後會被互動模式覆蓋
        
        return records_to_delete
    
    def interactive_duplicate_resolution(self, duplicates: Dict[str, List[Dict]]) -> List[Dict]:
        """
        互動模式解決重複記錄
        
        Args:
            duplicates: 重複記錄分組
            
        Returns:
            List[Dict]: 使用者選擇刪除的記錄
        """
        records_to_delete = []
        
        for issue_key, records in duplicates.items():
            if len(records) <= 1:
                continue
            
            print(f"\n🔍 發現重複記錄: {issue_key} ({len(records)} 筆)")
            print("=" * 60)
            
            # 顯示所有重複記錄的資訊
            for i, record in enumerate(records, 1):
                print(f"\n選項 {i}:")
                self._display_record_info(record)
            
            # 讓使用者選擇保留哪一筆
            while True:
                try:
                    choice = input(f"\n請選擇要保留的記錄 (1-{len(records)}) 或輸入 's' 跳過: ").strip()
                    
                    if choice.lower() == 's':
                        print("跳過此組重複記錄")
                        break
                    
                    choice_idx = int(choice) - 1
                    if 0 <= choice_idx < len(records):
                        # 標記其他記錄為刪除
                        for i, record in enumerate(records):
                            if i != choice_idx:
                                records_to_delete.append(record)
                        print(f"✅ 選擇保留選項 {choice}")
                        break
                    else:
                        print(f"❌ 請輸入 1-{len(records)} 之間的數字")
                        
                except ValueError:
                    print("❌ 請輸入有效的數字")
        
        return records_to_delete
    
    def _display_record_info(self, record: Dict):
        """
        顯示記錄的詳細資訊
        
        Args:
            record: Lark 記錄
        """
        fields = record.get('fields', {})
        record_id = record.get('record_id', 'Unknown')
        created_time = record.get('created_time', 0)
        modified_time = record.get('modified_time', 0)
        
        print(f"  記錄 ID: {record_id}")
        print(f"  建立時間: {self._format_timestamp(created_time)}")
        print(f"  修改時間: {self._format_timestamp(modified_time)}")
        
        # 顯示主要欄位
        for field_name, field_value in fields.items():
            if field_name in ['Title', 'JIRA Status', 'Assignee', 'Priority']:
                if isinstance(field_value, dict):
                    field_value = field_value.get('text', str(field_value))
                elif isinstance(field_value, list):
                    field_value = ', '.join(str(item) for item in field_value)
                print(f"  {field_name}: {field_value}")
    
    def _format_timestamp(self, timestamp: int) -> str:
        """
        格式化時間戳
        
        Args:
            timestamp: 時間戳（毫秒）
            
        Returns:
            str: 格式化後的時間字串
        """
        if timestamp:
            return datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
        return "未知"
    
    def delete_lark_records(self, team: str, table: str, records: List[Dict], dry_run: bool = True) -> int:
        """
        刪除 Lark 記錄
        
        Args:
            team: 團隊名稱
            table: 表格名稱
            records: 要刪除的記錄清單
            dry_run: 是否為乾跑模式
            
        Returns:
            int: 成功刪除的記錄數
        """
        if not records:
            return 0
        
        try:
            # 取得團隊和表格配置
            team_config = self.config_manager.get_team_config(team)
            table_config = team_config['tables'][table]
            
            wiki_token = team_config['wiki_token']
            table_id = table_config['table_id']
            
            # 提取記錄 ID
            record_ids = []
            for record in records:
                record_id = record.get('record_id')
                if record_id:
                    record_ids.append(record_id)
            
            if dry_run:
                self.logger.info(f"【乾跑模式】將會刪除 {len(record_ids)} 筆記錄")
                if self.logger.level <= logging.DEBUG:
                    for i, record in enumerate(records[:5]):  # 顯示前5筆
                        issue_key = record.get('_extracted_issue_key', 'Unknown')
                        self.logger.debug(f"  {i+1}. {issue_key} (ID: {record.get('record_id')})")
                    if len(records) > 5:
                        self.logger.debug(f"  ... 還有 {len(records) - 5} 筆記錄")
                return len(record_ids)
            else:
                self.logger.info(f"開始刪除 {len(record_ids)} 筆記錄")
                
                # 設定 wiki token
                self.lark_client.set_wiki_token(wiki_token)
                
                # 分批刪除（避免 API 限制）
                batch_size = 100
                deleted_count = 0
                
                for i in range(0, len(record_ids), batch_size):
                    batch_ids = record_ids[i:i + batch_size]
                    
                    try:
                        # 使用新架構的刪除方法
                        success = self.lark_client.batch_delete_records(table_id, batch_ids)
                        if success:
                            deleted_count += len(batch_ids)
                            self.logger.info(f"已刪除 {len(batch_ids)} 筆記錄 (總計: {deleted_count}/{len(record_ids)})")
                        else:
                            self.logger.error(f"刪除批次記錄失敗 (批次 {i//batch_size + 1})")
                            self.stats['errors'] += 1
                    except Exception as e:
                        self.logger.error(f"刪除批次記錄異常: {e}")
                        self.stats['errors'] += 1
                
                self.stats['lark_records_deleted'] = deleted_count
                return deleted_count
                
        except Exception as e:
            self.logger.error(f"刪除記錄失敗: {e}")
            self.stats['errors'] += 1
            return 0
    
    def clean_processing_logs(self, team: str, table: str, issue_keys: List[str], dry_run: bool = True) -> int:
        """
        清理處理日誌中對應的記錄
        
        Args:
            team: 團隊名稱
            table: 表格名稱
            issue_keys: 要清理的 Issue Key 清單
            dry_run: 是否為乾跑模式
            
        Returns:
            int: 清理的記錄數
        """
        if not issue_keys:
            return 0
        
        try:
            # 取得表格配置
            team_config = self.config_manager.get_team_config(team)
            table_config = team_config['tables'][table]
            table_id = table_config['table_id']
            
            # 取得處理日誌管理器
            log_manager = self.sync_state_manager.get_processing_log_manager(table_id)
            
            if dry_run:
                self.logger.info(f"【乾跑模式】將會清理 {len(issue_keys)} 筆處理日誌記錄")
                return len(issue_keys)
            else:
                self.logger.info(f"開始清理 {len(issue_keys)} 筆處理日誌記錄")
                
                # 批次刪除處理日誌
                cleaned_count = 0
                for issue_key in issue_keys:
                    try:
                        # 直接從資料庫刪除記錄
                        with log_manager._get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute('DELETE FROM processing_log WHERE issue_key = ?', (issue_key,))
                            if cursor.rowcount > 0:
                                cleaned_count += 1
                            conn.commit()
                    except Exception as e:
                        self.logger.error(f"清理處理日誌失敗: {issue_key}, {e}")
                        self.stats['errors'] += 1
                
                self.stats['processing_log_cleaned'] = cleaned_count
                self.logger.info(f"已清理 {cleaned_count} 筆處理日誌記錄")
                return cleaned_count
                
        except Exception as e:
            self.logger.error(f"清理處理日誌失敗: {e}")
            self.stats['errors'] += 1
            return 0
    
    def clean_data(self, team: str, table: str, jql: str, dry_run: bool = True, 
                   confirm: bool = True, clean_processing_log: bool = True) -> Dict:
        """
        執行資料清理
        
        Args:
            team: 團隊名稱
            table: 表格名稱  
            jql: JQL 查詢條件
            dry_run: 是否為乾跑模式
            confirm: 是否需要確認
            clean_processing_log: 是否同時清理處理日誌
            
        Returns:
            Dict: 清理結果統計
        """
        self.logger.info(f"開始資料清理: {team}.{table}")
        self.logger.info(f"JQL 條件: {jql}")
        self.logger.info(f"模式: {'乾跑' if dry_run else '實際執行'}")
        
        # 重置統計
        self.stats = {
            'jira_issues_found': 0,
            'lark_records_found': 0,
            'lark_records_deleted': 0,
            'processing_log_cleaned': 0,
            'errors': 0
        }
        
        # 步驟 1: 使用 JQL 查詢 JIRA Issue Keys
        issue_keys = self.extract_issue_keys_from_jql(jql)
        if not issue_keys:
            self.logger.warning("未找到任何 JIRA Issues，清理作業結束")
            return self.stats
        
        # 步驟 2: 在 Lark 表格中找出對應的記錄
        matching_records = self.find_lark_records_by_issue_keys(team, table, issue_keys)
        if not matching_records:
            self.logger.warning("在 Lark 表格中未找到任何匹配的記錄")
            
            # 即使沒有 Lark 記錄，也可能需要清理處理日誌
            if clean_processing_log:
                self.clean_processing_logs(team, table, issue_keys, dry_run)
            
            return self.stats
        
        # 步驟 3: 安全確認
        if confirm and not dry_run:
            print(f"\n⚠️  即將刪除 {len(matching_records)} 筆 Lark 記錄")
            print(f"團隊: {team}")
            print(f"表格: {table}")
            print(f"JQL: {jql}")
            print(f"匹配的 Issues: {len(issue_keys)} 個")
            
            if clean_processing_log:
                print(f"同時清理對應的處理日誌記錄")
            
            response = input("\n確定要繼續嗎？ (yes/no): ").strip().lower()
            if response not in ('yes', 'y'):
                self.logger.info("使用者取消操作")
                return self.stats
        
        # 步驟 4: 執行刪除
        deleted_count = self.delete_lark_records(team, table, matching_records, dry_run)
        
        # 步驟 5: 清理處理日誌（如果需要）
        if clean_processing_log:
            self.clean_processing_logs(team, table, issue_keys, dry_run)
        
        # 報告結果
        self._print_summary()
        
        return self.stats
    
    def detect_and_clean_duplicates(self, team: str, table: str, 
                                   duplicate_strategy: str = 'keep-latest',
                                   jql_filter: str = None,
                                   dry_run: bool = True,
                                   confirm: bool = True) -> Dict:
        """
        偵測並清理重複記錄
        
        Args:
            team: 團隊名稱
            table: 表格名稱
            duplicate_strategy: 重複處理策略
            jql_filter: 可選的 JQL 過濾條件
            dry_run: 是否為乾跑模式
            confirm: 是否需要確認
            
        Returns:
            Dict: 清理結果統計
        """
        self.logger.info(f"開始重複記錄偵測和清理: {team}.{table}")
        self.logger.info(f"策略: {duplicate_strategy}")
        self.logger.info(f"模式: {'乾跑' if dry_run else '實際執行'}")
        if jql_filter:
            self.logger.info(f"JQL 過濾: {jql_filter}")
        
        # 重置統計
        self.stats = {
            'jira_issues_found': 0,
            'lark_records_found': 0,
            'lark_records_deleted': 0,
            'duplicates_found': 0,
            'duplicate_groups': 0,
            'processing_log_cleaned': 0,
            'errors': 0
        }
        
        # 步驟 1: 偵測重複記錄
        duplicates = self.detect_duplicate_tickets(team, table, jql_filter)
        if not duplicates:
            self.logger.info("未發現重複記錄，清理作業結束")
            return self.stats
        
        # 步驟 2: 根據策略選擇要刪除的記錄
        if duplicate_strategy == 'interactive':
            if dry_run:
                self.logger.warning("互動模式不支援乾跑模式，將改為顯示重複記錄資訊")
                self._display_duplicate_summary(duplicates)
                return self.stats
            else:
                records_to_delete = self.interactive_duplicate_resolution(duplicates)
        else:
            records_to_delete = self.choose_records_to_keep(duplicates, duplicate_strategy)
        
        if not records_to_delete:
            self.logger.info("根據策略沒有需要刪除的記錄")
            return self.stats
        
        self.stats['lark_records_found'] = len(records_to_delete)
        
        # 步驟 3: 安全確認
        if confirm and not dry_run:
            print(f"\n⚠️  即將刪除 {len(records_to_delete)} 筆重複記錄")
            print(f"團隊: {team}")
            print(f"表格: {table}")
            print(f"策略: {duplicate_strategy}")
            print(f"重複組數: {len(duplicates)} 組")
            
            # 顯示將被刪除的記錄摘要
            print(f"\n即將刪除的記錄摘要:")
            for i, record in enumerate(records_to_delete[:5]):  # 顯示前5筆
                issue_key = record.get('_extracted_issue_key', 'Unknown')
                record_id = record.get('record_id', 'Unknown')
                print(f"  {i+1}. {issue_key} (ID: {record_id})")
            if len(records_to_delete) > 5:
                print(f"  ... 還有 {len(records_to_delete) - 5} 筆記錄")
            
            response = input("\n確定要繼續嗎？ (yes/no): ").strip().lower()
            if response not in ('yes', 'y'):
                self.logger.info("使用者取消操作")
                return self.stats
        
        # 步驟 4: 執行刪除
        deleted_count = self.delete_lark_records(team, table, records_to_delete, dry_run)
        
        # 步驟 5: 清理對應的處理日誌（重複記錄的 Issue Keys）
        deleted_issue_keys = [record.get('_extracted_issue_key') for record in records_to_delete 
                             if record.get('_extracted_issue_key')]
        if deleted_issue_keys:
            self.clean_processing_logs(team, table, deleted_issue_keys, dry_run)
        
        # 報告結果
        self._print_duplicate_summary()
        
        return self.stats
    
    def _display_duplicate_summary(self, duplicates: Dict[str, List[Dict]]):
        """
        顯示重複記錄摘要
        
        Args:
            duplicates: 重複記錄分組
        """
        print(f"\n📋 重複記錄摘要:")
        print(f"{'=' * 60}")
        
        for issue_key, records in duplicates.items():
            print(f"\n🔍 Issue Key: {issue_key} ({len(records)} 筆重複)")
            for i, record in enumerate(records, 1):
                record_id = record.get('record_id', 'Unknown')
                created_time = self._format_timestamp(record.get('created_time', 0))
                modified_time = self._format_timestamp(record.get('modified_time', 0))
                print(f"  {i}. ID: {record_id}, 建立: {created_time}, 修改: {modified_time}")
    
    def _print_summary(self):
        """列印清理結果摘要"""
        print(f"\n📊 清理結果摘要:")
        print(f"{'=' * 50}")
        print(f"JIRA Issues 找到: {self.stats['jira_issues_found']}")
        print(f"Lark 記錄找到: {self.stats['lark_records_found']}")
        print(f"Lark 記錄刪除: {self.stats['lark_records_deleted']}")
        print(f"處理日誌清理: {self.stats['processing_log_cleaned']}")
        print(f"錯誤數: {self.stats['errors']}")
        
        if self.stats['errors'] > 0:
            print(f"\n⚠️  執行過程中發生 {self.stats['errors']} 個錯誤，請檢查日誌")
    
    def _print_duplicate_summary(self):
        """列印重複記錄清理結果摘要"""
        print(f"\n📊 重複記錄清理結果摘要:")
        print(f"{'=' * 50}")
        print(f"重複組數: {self.stats['duplicate_groups']}")
        print(f"重複記錄總數: {self.stats['duplicates_found']}")
        print(f"記錄刪除數: {self.stats['lark_records_deleted']}")
        print(f"處理日誌清理: {self.stats['processing_log_cleaned']}")
        print(f"錯誤數: {self.stats['errors']}")
        
        if self.stats['errors'] > 0:
            print(f"\n⚠️  執行過程中發生 {self.stats['errors']} 個錯誤，請檢查日誌")


def main():
    """主程式入口"""
    parser = argparse.ArgumentParser(description='JIRA-Lark 資料清理工具（新架構版本）')
    parser.add_argument('--team', required=True, help='團隊名稱')
    parser.add_argument('--table', required=True, help='表格名稱')
    parser.add_argument('--jql', help='JQL 查詢條件（用於資料清理）')
    parser.add_argument('--dry-run', action='store_true', help='乾跑模式，不實際刪除')
    parser.add_argument('--no-confirm', action='store_true', help='跳過確認提示')
    parser.add_argument('--duplicates', action='store_true', help='偵測並清理重複記錄')
    parser.add_argument('--duplicate-strategy', choices=['keep-latest', 'keep-oldest', 'interactive'], 
                       default='keep-latest', help='重複記錄處理策略')
    parser.add_argument('--jql-filter', help='重複記錄偵測的 JQL 過濾條件')
    parser.add_argument('--config', default='config.yaml', help='配置檔案路徑')
    parser.add_argument('--verbose', '-v', action='store_true', help='詳細輸出')
    
    args = parser.parse_args()
    
    # 設定日誌級別
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        # 建立資料清理器
        cleaner = DataCleaner(args.config)
        
        if args.duplicates:
            # 重複記錄清理模式
            if args.jql:
                print("⚠️  重複記錄模式會忽略 --jql 參數，請使用 --jql-filter")
            
            result = cleaner.detect_and_clean_duplicates(
                team=args.team,
                table=args.table,
                duplicate_strategy=args.duplicate_strategy,
                jql_filter=args.jql_filter,
                dry_run=args.dry_run,
                confirm=not args.no_confirm
            )
        else:
            # 一般資料清理模式
            if not args.jql:
                parser.error("一般清理模式需要 --jql 參數")
            
            result = cleaner.clean_data(
                team=args.team,
                table=args.table,
                jql=args.jql,
                dry_run=args.dry_run,
                confirm=not args.no_confirm
            )
        
        # 檢查結果
        if result['errors'] > 0:
            sys.exit(1)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  操作被用戶中止")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 執行失敗: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()