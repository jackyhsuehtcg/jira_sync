#!/usr/bin/env python3
"""
JIRA-Lark 重複票據偵測工具（定時版本）

基於現有的 data_cleaner.py 建立，專門用於定時偵測重複票據
支援所有 config_prod.yaml 中的團隊和表格，提供 dry run 模式安全預覽

使用範例:
python duplicate_checker.py --dry-run                    # 檢查所有啟用的表格
python duplicate_checker.py --team management --dry-run  # 檢查特定團隊
python duplicate_checker.py --schedule                   # 定時模式
"""

import argparse
import sys
import time
import schedule
import logging
from datetime import datetime
from typing import Dict, List, Tuple
from pathlib import Path

# 導入現有的資料清理器
from data_cleaner import DataCleaner


class DuplicateChecker:
    """重複票據偵測器 - 基於 DataCleaner 擴展"""
    
    def __init__(self, config_file: str = 'config_prod.yaml'):
        """
        初始化重複票據偵測器
        
        Args:
            config_file: 配置檔案路徑
        """
        self.config_file = config_file
        self.logger = logging.getLogger(f"{__name__}.DuplicateChecker")
        
        # 使用現有的 DataCleaner
        self.cleaner = DataCleaner(config_file)
        
        # 統計資訊
        self.total_stats = {
            'teams_checked': 0,
            'tables_checked': 0,
            'duplicate_groups_found': 0,
            'duplicate_records_found': 0,
            'errors': 0,
            'check_time': None
        }
        
        self.logger.info(f"重複票據偵測器初始化完成，配置檔案: {config_file}")
    
    def get_all_enabled_tables(self) -> List[Dict]:
        """
        從配置檔案中取得所有啟用的表格
        
        Returns:
            List[Dict]: 表格資訊列表，每個包含 team, table, config 等資訊
        """
        enabled_tables = []
        
        try:
            config = self.cleaner.config_manager.config
            teams = config.get('teams', {})
            
            for team_name, team_config in teams.items():
                if not team_config.get('enabled', False):
                    continue
                
                tables = team_config.get('tables', {})
                for table_name, table_config in tables.items():
                    if table_config.get('enabled', False):
                        enabled_tables.append({
                            'team': team_name,
                            'table': table_name,
                            'display_name': team_config.get('display_name', team_name),
                            'table_display_name': table_config.get('name', table_name),
                            'table_id': table_config.get('table_id'),
                            'ticket_field': table_config.get('ticket_field', 'Issue Key'),
                            'jql_query': table_config.get('jql_query', '')
                        })
            
            self.logger.info(f"發現 {len(enabled_tables)} 個啟用的表格")
            return enabled_tables
            
        except Exception as e:
            self.logger.error(f"讀取配置失敗: {e}")
            return []
    
    def check_table_duplicates(self, team: str, table: str) -> Dict:
        """
        檢查單一表格的重複票據
        
        Args:
            team: 團隊名稱
            table: 表格名稱
            
        Returns:
            Dict: 檢查結果統計
        """
        self.logger.info(f"開始檢查表格重複票據: {team}.{table}")
        
        try:
            # 使用 DataCleaner 的重複偵測功能
            duplicates = self.cleaner.detect_duplicate_tickets(team, table)
            
            result = {
                'team': team,
                'table': table,
                'duplicate_groups': len(duplicates),
                'duplicate_records': sum(len(records) for records in duplicates.values()),
                'duplicates_detail': duplicates,
                'success': True,
                'error': None
            }
            
            if duplicates:
                self.logger.warning(f"發現重複票據: {team}.{table} - {len(duplicates)} 組，共 {result['duplicate_records']} 筆")
            else:
                self.logger.info(f"表格 {team}.{table} 無重複票據")
            
            return result
            
        except Exception as e:
            self.logger.error(f"檢查表格 {team}.{table} 失敗: {e}")
            return {
                'team': team,
                'table': table,
                'duplicate_groups': 0,
                'duplicate_records': 0,
                'duplicates_detail': {},
                'success': False,
                'error': str(e)
            }
    
    def check_all_tables(self, team_filter: str = None) -> List[Dict]:
        """
        檢查所有啟用表格的重複票據
        
        Args:
            team_filter: 可選的團隊過濾條件
            
        Returns:
            List[Dict]: 所有表格的檢查結果
        """
        self.logger.info("開始檢查所有表格的重複票據")
        
        # 重置統計
        self.total_stats = {
            'teams_checked': 0,
            'tables_checked': 0,
            'duplicate_groups_found': 0,
            'duplicate_records_found': 0,
            'errors': 0,
            'check_time': datetime.now()
        }
        
        # 取得所有啟用的表格
        enabled_tables = self.get_all_enabled_tables()
        
        if team_filter:
            enabled_tables = [t for t in enabled_tables if t['team'] == team_filter]
            self.logger.info(f"過濾團隊: {team_filter}，剩餘 {len(enabled_tables)} 個表格")
        
        if not enabled_tables:
            self.logger.warning("沒有找到任何啟用的表格")
            return []
        
        # 檢查每個表格
        results = []
        teams_checked = set()
        
        for table_info in enabled_tables:
            team = table_info['team']
            table = table_info['table']
            
            # 檢查重複票據
            result = self.check_table_duplicates(team, table)
            results.append(result)
            
            # 更新統計
            teams_checked.add(team)
            self.total_stats['tables_checked'] += 1
            
            if result['success']:
                self.total_stats['duplicate_groups_found'] += result['duplicate_groups']
                self.total_stats['duplicate_records_found'] += result['duplicate_records']
            else:
                self.total_stats['errors'] += 1
            
            # 短暫休息避免 API 過載
            time.sleep(0.5)
        
        self.total_stats['teams_checked'] = len(teams_checked)
        
        # 生成報告
        self.generate_summary_report(results)
        
        return results
    
    def generate_summary_report(self, results: List[Dict]):
        """
        生成總結報告
        
        Args:
            results: 所有表格的檢查結果
        """
        print(f"\n{'='*70}")
        print(f"🔍 重複票據偵測報告")
        print(f"{'='*70}")
        print(f"檢查時間: {self.total_stats['check_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"團隊數量: {self.total_stats['teams_checked']}")
        print(f"表格數量: {self.total_stats['tables_checked']}")
        print(f"重複組數: {self.total_stats['duplicate_groups_found']}")
        print(f"重複記錄: {self.total_stats['duplicate_records_found']}")
        print(f"錯誤數量: {self.total_stats['errors']}")
        
        # 詳細結果
        if self.total_stats['duplicate_groups_found'] > 0:
            print(f"\n📋 重複票據詳細資訊:")
            print(f"{'-'*70}")
            
            for result in results:
                if result['success'] and result['duplicate_groups'] > 0:
                    team = result['team']
                    table = result['table']
                    groups = result['duplicate_groups']
                    records = result['duplicate_records']
                    
                    print(f"\n⚠️  {team}.{table}:")
                    print(f"   重複組數: {groups}")
                    print(f"   重複記錄: {records}")
                    
                    # 顯示前5組重複的詳細資訊
                    duplicates = result['duplicates_detail']
                    for i, (issue_key, dup_records) in enumerate(list(duplicates.items())[:5]):
                        print(f"   - {issue_key}: {len(dup_records)} 筆重複")
                    
                    if len(duplicates) > 5:
                        print(f"   ... 還有 {len(duplicates)-5} 組重複")
        
        # 錯誤資訊
        if self.total_stats['errors'] > 0:
            print(f"\n❌ 錯誤表格:")
            print(f"{'-'*70}")
            
            for result in results:
                if not result['success']:
                    print(f"   {result['team']}.{result['table']}: {result['error']}")
        
        if self.total_stats['duplicate_groups_found'] == 0:
            print(f"\n✅ 所有表格都沒有重複票據！")
        
        print(f"\n{'='*70}")
    
    def generate_detailed_report(self, results: List[Dict], output_file: str = None):
        """
        生成詳細報告並儲存到檔案
        
        Args:
            results: 所有表格的檢查結果
            output_file: 輸出檔案路徑
        """
        if not output_file:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"duplicate_check_report_{timestamp}.txt"
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"JIRA-Lark 重複票據偵測報告\n")
                f.write(f"{'='*70}\n")
                f.write(f"檢查時間: {self.total_stats['check_time'].strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"配置檔案: {self.config_file}\n")
                f.write(f"團隊數量: {self.total_stats['teams_checked']}\n")
                f.write(f"表格數量: {self.total_stats['tables_checked']}\n")
                f.write(f"重複組數: {self.total_stats['duplicate_groups_found']}\n")
                f.write(f"重複記錄: {self.total_stats['duplicate_records_found']}\n")
                f.write(f"錯誤數量: {self.total_stats['errors']}\n\n")
                
                # 詳細結果
                for result in results:
                    f.write(f"表格: {result['team']}.{result['table']}\n")
                    f.write(f"{'-'*50}\n")
                    
                    if result['success']:
                        f.write(f"狀態: 成功\n")
                        f.write(f"重複組數: {result['duplicate_groups']}\n")
                        f.write(f"重複記錄: {result['duplicate_records']}\n")
                        
                        if result['duplicates_detail']:
                            f.write(f"重複詳情:\n")
                            for issue_key, dup_records in result['duplicates_detail'].items():
                                f.write(f"  - {issue_key}: {len(dup_records)} 筆重複\n")
                                for i, record in enumerate(dup_records, 1):
                                    record_id = record.get('record_id', 'Unknown')
                                    created_time = record.get('created_time', 0)
                                    modified_time = record.get('modified_time', 0)
                                    f.write(f"    {i}. ID: {record_id}, 建立: {created_time}, 修改: {modified_time}\n")
                        else:
                            f.write(f"無重複記錄\n")
                    else:
                        f.write(f"狀態: 失敗\n")
                        f.write(f"錯誤: {result['error']}\n")
                    
                    f.write(f"\n")
            
            self.logger.info(f"詳細報告已儲存到: {output_file}")
            print(f"\n📄 詳細報告已儲存到: {output_file}")
            
        except Exception as e:
            self.logger.error(f"儲存報告失敗: {e}")
    
    def scheduled_check(self):
        """定時檢查函數"""
        self.logger.info("執行定時重複票據檢查")
        
        try:
            results = self.check_all_tables()
            
            # 如果發現重複，產生詳細報告
            if self.total_stats['duplicate_groups_found'] > 0:
                self.generate_detailed_report(results)
            
            self.logger.info("定時檢查完成")
            
        except Exception as e:
            self.logger.error(f"定時檢查失敗: {e}")
    
    def run_scheduler(self, interval_hours: int = 6):
        """
        執行定時排程
        
        Args:
            interval_hours: 檢查間隔（小時）
        """
        self.logger.info(f"啟動定時排程，每 {interval_hours} 小時檢查一次")
        
        # 設定排程
        schedule.every(interval_hours).hours.do(self.scheduled_check)
        
        # 立即執行一次
        print(f"🚀 立即執行第一次檢查...")
        self.scheduled_check()
        
        # 開始定時循環
        print(f"⏰ 定時排程已啟動，每 {interval_hours} 小時檢查一次")
        print(f"   下次檢查時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   按 Ctrl+C 停止排程")
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # 每分鐘檢查一次排程
        except KeyboardInterrupt:
            self.logger.info("定時排程被用戶中止")
            print(f"\n⏹️  定時排程已停止")


def main():
    """主程式入口"""
    parser = argparse.ArgumentParser(description='JIRA-Lark 重複票據偵測工具')
    parser.add_argument('--config', default='config_prod.yaml', help='配置檔案路徑')
    parser.add_argument('--team', help='指定檢查的團隊 (management, aid_trm, wsd)')
    parser.add_argument('--dry-run', action='store_true', help='乾跑模式（預設啟用）')
    parser.add_argument('--schedule', action='store_true', help='定時模式')
    parser.add_argument('--interval', type=int, default=6, help='定時檢查間隔（小時，預設6小時）')
    parser.add_argument('--report', help='儲存詳細報告到指定檔案')
    parser.add_argument('--verbose', '-v', action='store_true', help='詳細輸出')
    
    args = parser.parse_args()
    
    # 設定日誌級別
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 檢查配置檔案
    if not Path(args.config).exists():
        print(f"❌ 配置檔案不存在: {args.config}")
        sys.exit(1)
    
    try:
        # 建立重複票據偵測器
        checker = DuplicateChecker(args.config)
        
        if args.schedule:
            # 定時模式
            checker.run_scheduler(args.interval)
        else:
            # 單次檢查模式
            print(f"🔍 開始重複票據偵測...")
            if args.team:
                print(f"   限定團隊: {args.team}")
            print(f"   配置檔案: {args.config}")
            print(f"   模式: 乾跑預覽")
            
            results = checker.check_all_tables(args.team)
            
            # 儲存詳細報告
            if args.report:
                checker.generate_detailed_report(results, args.report)
            elif checker.total_stats['duplicate_groups_found'] > 0:
                checker.generate_detailed_report(results)
        
    except KeyboardInterrupt:
        print(f"\n\n⚠️  操作被用戶中止")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 執行失敗: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()