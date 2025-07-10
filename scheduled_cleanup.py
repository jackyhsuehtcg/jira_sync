#!/usr/bin/env python3
"""
定時清理程式 - 自動清理所有資料表重複項目

功能特性：
1. 讀取 config.yaml 中的所有團隊和表格配置
2. 自動檢測並清理每個表格的重複記錄
3. 採用保留最新記錄策略
4. 支援定期自動執行（每隔N分鐘）
5. 詳細的清理報告和即時狀態顯示

使用方式：
python scheduled_cleanup.py                    # 執行一次清理
python scheduled_cleanup.py --dry-run         # 乾跑模式檢測
python scheduled_cleanup.py --schedule        # 啟動調度器（每30分鐘）
python scheduled_cleanup.py --schedule --interval 15  # 每15分鐘執行一次
"""

import argparse
import sys
import time
import schedule
from typing import Dict, List, Any
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# 導入現有系統組件
from config_manager import ConfigManager
from data_cleaner import DataCleaner
from logger import SyncLogger


class ScheduledCleanup:
    """定時清理系統"""
    
    def __init__(self, config_file: str = 'config.yaml'):
        """
        初始化定時清理系統
        
        Args:
            config_file: 配置檔案路徑
        """
        self.config_file = config_file
        
        # 初始化配置管理器
        self.config_manager = ConfigManager(None, config_file, enable_hot_reload=False)
        
        # 取得全域配置用於日誌初始化
        global_config = self.config_manager.get_global_config()
        
        # 初始化日誌系統
        self.sync_logger = SyncLogger(global_config)
        self.logger = self.sync_logger.get_logger('ScheduledCleanup')
        
        self.logger.info("=" * 60)
        self.logger.info("定時清理系統已初始化")
        self.logger.info(f"配置檔案: {config_file}")
        self.logger.info("=" * 60)
        
        print("🚀 定時清理系統已初始化")
        print(f"📄 配置檔案: {config_file}")
    
    def get_all_tables(self) -> List[Dict[str, Any]]:
        """
        取得所有配置的表格清單
        
        Returns:
            List: 表格配置清單，格式 [{'team': str, 'table': str, 'config': dict}]
        """
        tables = []
        teams_config = self.config_manager.get_teams()
        
        for team_name, team_config in teams_config.items():
            if not team_config.get('tables'):
                continue
                
            for table_name, table_config in team_config['tables'].items():
                if table_config.get('enabled', True):  # 只處理啟用的表格
                    tables.append({
                        'team': team_name,
                        'table': table_name,
                        'config': table_config,
                        'team_config': team_config
                    })
        
        return tables
    
    def cleanup_single_table(self, table_info: Dict[str, Any], 
                           dry_run: bool = False) -> Dict[str, Any]:
        """
        清理單一表格的重複記錄
        
        Args:
            table_info: 表格資訊
            dry_run: 是否為乾跑模式
            
        Returns:
            Dict: 清理結果統計
        """
        team_name = table_info['team']
        table_name = table_info['table']
        
        start_time = time.time()
        
        try:
            # 使用 DataCleaner 進行重複檢測和清理
            cleaner = DataCleaner(self.config_file)
            
            # 先偵測重複記錄以獲得詳細信息
            duplicates = cleaner.detect_duplicate_tickets(team_name, table_name)
            
            # 執行重複記錄清理
            result = cleaner.detect_and_clean_duplicates(
                team=team_name,
                table=table_name,
                duplicate_strategy='keep-latest',  # 固定使用保留最新策略
                dry_run=dry_run,
                confirm=False  # 自動執行，不需要確認
            )
            
            duration = time.time() - start_time
            
            if result:
                deleted_count = result.get('lark_records_deleted', 0)
                duplicate_groups = result.get('duplicate_groups', 0)
                duplicates_found = result.get('duplicates_found', 0)
                
                # 收集重複記錄的 Issue Keys
                duplicate_issue_keys = list(duplicates.keys()) if duplicates else []
                
                return {
                    'status': 'success',
                    'team': team_name,
                    'table': table_name,
                    'deleted_count': deleted_count,
                    'duplicate_groups': duplicate_groups,
                    'duplicates_found': duplicates_found,
                    'duplicate_issue_keys': duplicate_issue_keys,
                    'duration': duration,
                    'table_display_name': table_info['config'].get('table_name', table_name)
                }
            else:
                return {
                    'status': 'success',
                    'team': team_name,
                    'table': table_name,
                    'deleted_count': 0,
                    'duplicate_groups': 0,
                    'duplicates_found': 0,
                    'duplicate_issue_keys': [],
                    'duration': duration,
                    'table_display_name': table_info['config'].get('table_name', table_name)
                }
                
        except Exception as e:
            duration = time.time() - start_time
            return {
                'status': 'error',
                'team': team_name,
                'table': table_name,
                'error': str(e),
                'duration': duration,
                'table_display_name': table_info['config'].get('table_name', table_name)
            }
    
    def run_cleanup(self, dry_run: bool = False, 
                   parallel: bool = True, max_workers: int = 3) -> Dict[str, Any]:
        """
        執行所有表格的清理作業
        
        Args:
            dry_run: 是否為乾跑模式
            parallel: 是否並行處理
            max_workers: 最大並行數
            
        Returns:
            Dict: 總體清理結果
        """
        start_time = datetime.now()
        
        # 取得所有表格
        tables = self.get_all_tables()
        if not tables:
            self.logger.warning("⚠️ 未找到任何配置的表格")
            return {'status': 'no_tables', 'results': []}
        
        results = []
        
        if parallel and len(tables) > 1:
            # 並行處理多個表格
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有清理任務
                future_to_table = {
                    executor.submit(self.cleanup_single_table, table_info, dry_run): table_info
                    for table_info in tables
                }
                
                # 收集結果
                for future in as_completed(future_to_table):
                    table_info = future_to_table[future]
                    try:
                        result = future.result(timeout=300)  # 5分鐘超時
                        results.append(result)
                    except Exception as e:
                        results.append({
                            'status': 'error',
                            'team': table_info['team'],
                            'table': table_info['table'],
                            'error': str(e),
                            'duration': 0,
                            'table_display_name': table_info['config'].get('table_name', table_info['table'])
                        })
        else:
            # 循序處理
            for table_info in tables:
                result = self.cleanup_single_table(table_info, dry_run)
                results.append(result)
        
        # 產生總結報告
        return self._generate_summary_report(results, start_time, dry_run)
    
    def _generate_summary_report(self, results: List[Dict], 
                               start_time: datetime, dry_run: bool) -> Dict[str, Any]:
        """產生清理作業總結報告"""
        end_time = datetime.now()
        total_duration = (end_time - start_time).total_seconds()
        
        # 統計結果
        total_tables = len(results)
        successful_tables = len([r for r in results if r['status'] == 'success'])
        failed_tables = len([r for r in results if r['status'] == 'error'])
        total_deleted = sum(r.get('deleted_count', 0) for r in results)
        total_groups = sum(r.get('duplicate_groups', 0) for r in results)
        
        # 控制台輸出總結報告
        print("=" * 70)
        print("📋 定時清理作業總結報告")
        print("=" * 70)
        print(f"⏰ 執行時間: {start_time.strftime('%Y-%m-%d %H:%M:%S')} - {end_time.strftime('%H:%M:%S')}")
        print(f"⏱️ 總耗時: {total_duration:.2f} 秒")
        print(f"🔍 處理模式: {'乾跑模式' if dry_run else '實際清理'}")
        print(f"📊 處理表格: {total_tables} 個 (✅ 成功: {successful_tables} / ❌ 失敗: {failed_tables})")
        
        if not dry_run:
            print(f"🗑️ 清理結果: 刪除 {total_deleted} 筆重複記錄 ({total_groups} 組)")
        else:
            print(f"🔍 檢測結果: 發現 {total_deleted} 筆重複記錄 ({total_groups} 組)")
        
        # 詳細的每張表格結果
        if results:
            print("\n📊 各表格清理詳情:")
            print("-" * 70)
            
            for result in results:
                table_display = result.get('table_display_name', result['table'])
                team_name = result['team']
                
                if result['status'] == 'success':
                    deleted_count = result.get('deleted_count', 0)
                    duplicate_groups = result.get('duplicate_groups', 0)
                    duration = result.get('duration', 0)
                    duplicate_issue_keys = result.get('duplicate_issue_keys', [])
                    
                    if deleted_count > 0:
                        action = "檢測到" if dry_run else "清除"
                        print(f"🧹 {team_name} | {table_display}")
                        print(f"   {action} {deleted_count} 筆重複記錄 ({duplicate_groups} 組) | 耗時 {duration:.1f}s")
                        
                        # 顯示重複的 Issue Keys
                        if duplicate_issue_keys:
                            keys_display = ", ".join(duplicate_issue_keys[:5])  # 顯示前5個
                            if len(duplicate_issue_keys) > 5:
                                keys_display += f" ... 等{len(duplicate_issue_keys)}個"
                            print(f"   📋 重複項目: {keys_display}")
                    else:
                        print(f"✨ {team_name} | {table_display}")
                        print(f"   無重複記錄 | 耗時 {duration:.1f}s")
                else:
                    error_msg = result.get('error', 'Unknown error')
                    print(f"❌ {team_name} | {table_display}")
                    print(f"   清理失敗: {error_msg}")
                
                print()  # 空行分隔
        
        print("=" * 70)
        
        # 記錄到日誌（簡化版本）
        self.logger.info(f"清理完成: {total_tables}表格, {successful_tables}成功, {total_deleted}筆刪除, 耗時{total_duration:.1f}s")
        
        return {
            'status': 'completed',
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'total_duration': total_duration,
            'dry_run': dry_run,
            'statistics': {
                'total_tables': total_tables,
                'successful_tables': successful_tables,
                'failed_tables': failed_tables,
                'total_deleted': total_deleted,
                'total_groups': total_groups
            },
            'results': results
        }
    
    def run_scheduler(self, interval_minutes: int = 30):
        """
        啟動調度器模式，每隔指定分鐘執行清理
        
        Args:
            interval_minutes: 執行間隔（分鐘）
        """
        self.logger.info(f"📅 啟動調度器模式，每隔 {interval_minutes} 分鐘執行清理")
        print(f"📅 啟動調度器模式，每隔 {interval_minutes} 分鐘執行清理")
        
        # 設定定期清理任務
        schedule.every(interval_minutes).minutes.do(self._scheduled_cleanup_job)
        
        self.logger.info("⏰ 調度器已啟動，等待執行時間...")
        print("⏰ 調度器已啟動，等待執行時間...")
        print(f"⏭️ 下次執行時間: {(datetime.now() + timedelta(minutes=interval_minutes)).strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(30)  # 每30秒檢查一次
        except KeyboardInterrupt:
            self.logger.info("⏹️ 調度器已停止")
            print("\n⏹️ 調度器已停止")
    
    def _scheduled_cleanup_job(self):
        """調度器執行的清理任務"""
        try:
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n⏰ 定時清理任務開始執行 - {current_time}")
            
            self.run_cleanup(dry_run=False, parallel=True)
            
            # 顯示下次執行時間
            next_run = schedule.next_run()
            if next_run:
                print(f"⏭️ 下次執行時間: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
                
        except Exception as e:
            self.logger.error(f"❌ 定時清理任務執行失敗: {e}")
            print(f"❌ 定時清理任務執行失敗: {e}")


def main():
    """主程式入口"""
    parser = argparse.ArgumentParser(
        description='定時清理程式 - 自動清理所有資料表重複項目',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python scheduled_cleanup.py                    # 執行一次清理
  python scheduled_cleanup.py --dry-run         # 乾跑模式檢測
  python scheduled_cleanup.py --schedule        # 啟動調度器（每30分鐘）
  python scheduled_cleanup.py --schedule --interval 15  # 每15分鐘執行一次
        """
    )
    
    parser.add_argument('--config', 
                       default='config.yaml',
                       help='配置檔案路徑 (預設: config.yaml)')
    
    parser.add_argument('--dry-run', 
                       action='store_true',
                       help='乾跑模式：僅檢測重複記錄，不執行實際清理')
    
    parser.add_argument('--schedule', 
                       action='store_true',
                       help='啟動調度器模式，定期執行清理')
    
    parser.add_argument('--interval', 
                       type=int,
                       default=30,
                       help='調度器執行間隔（分鐘，預設: 30）')
    
    parser.add_argument('--sequential', 
                       action='store_true',
                       help='使用循序處理模式 (預設使用並行處理)')
    
    parser.add_argument('--max-workers', 
                       type=int, default=3,
                       help='並行處理最大線程數 (預設: 3)')
    
    args = parser.parse_args()
    
    try:
        # 初始化清理系統
        cleanup_system = ScheduledCleanup(args.config)
        
        if args.schedule:
            # 調度器模式
            cleanup_system.run_scheduler(args.interval)
        else:
            # 單次執行模式
            result = cleanup_system.run_cleanup(
                dry_run=args.dry_run,
                parallel=not args.sequential,
                max_workers=args.max_workers
            )
            
            # 根據結果設定退出碼
            if result['statistics']['failed_tables'] > 0:
                sys.exit(1)  # 有失敗的表格
            else:
                sys.exit(0)  # 全部成功
                
    except KeyboardInterrupt:
        print("\n🛑 程式已中斷")
        sys.exit(130)
    except Exception as e:
        print(f"❌ 程式執行失敗: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()