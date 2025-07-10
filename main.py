#!/usr/bin/env python3
"""
JIRA-Lark Base 同步系統主程式（新架構版本）
提供命令列介面和定時同步功能
基於新的 6 模組架構，使用 SyncCoordinator 作為核心
"""

import sys
import argparse
import signal
import time
import json
from typing import Dict, Any
from datetime import datetime

# 匯入自定義模組
from logger import setup_logging
from config_manager import ConfigManager
from sync_coordinator import SyncCoordinator


class JiraLarkSyncApp:
    """JIRA-Lark Base 同步應用程式（新架構版本）"""
    
    def __init__(self, config_file: str = 'config.yaml'):
        """
        初始化應用程式
        
        Args:
            config_file: 配置檔案路徑
        """
        self.config_file = config_file
        self.running = False
        self.sync_logger = None
        self.config_manager = None
        self.sync_coordinator = None
        
        # 設定信號處理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """處理中斷信號"""
        print(f"\n收到信號 {signum}，正在優雅關閉...")
        self.running = False
    
    def _interruptible_sleep(self, seconds):
        """可中斷的睡眠，每秒檢查一次 running 狀態"""
        for _ in range(int(seconds)):
            if not self.running:
                break
            time.sleep(1)
        # 處理小數部分
        if self.running and seconds % 1 > 0:
            time.sleep(seconds % 1)
    
    def initialize(self):
        """初始化所有組件"""
        print("正在初始化 JIRA-Lark Base 同步系統（新架構）...")
        
        try:
            # 載入配置
            self.config_manager = ConfigManager(None, self.config_file)
            
            # 設定日誌
            global_config = self.config_manager.get_global_config()
            log_config = {
                'log_level': global_config.get('log_level', 'INFO'),
                'log_file': global_config.get('log_file', 'jira_lark_sync.log'),
                'max_size': global_config.get('log_max_size', '10MB'),
                'backup_count': global_config.get('log_backup_count', 5)
            }
            self.sync_logger = setup_logging(log_config)
            
            # 重新初始化配置管理器（提供日誌器）
            self.config_manager = ConfigManager(self.sync_logger, self.config_file)
            
            # 初始化同步協調器
            self.sync_coordinator = SyncCoordinator(
                config_manager=self.config_manager,
                schema_path=global_config.get('schema_file', 'schema.yaml'),
                base_data_dir=global_config.get('data_directory', 'data'),
                logger=self.sync_logger
            )
            
            print("✅ 系統初始化完成（新架構）")
            
        except Exception as e:
            print(f"❌ 系統初始化失敗: {e}")
            if self.sync_logger:
                self.sync_logger.logger.error(f"系統初始化失敗: {e}")
            raise
    
    def run_once(self, team_name: str = None, table_name: str = None, full_update: bool = False) -> Dict[str, Any]:
        """
        執行一次同步
        
        Args:
            team_name: 指定團隊名稱（可選）
            table_name: 指定表格名稱（可選，需要同時指定團隊）
            full_update: 全量更新模式
            
        Returns:
            Dict: 同步結果
        """
        if not self.sync_coordinator:
            raise RuntimeError("系統尚未初始化")
        
        if team_name and table_name:
            # 同步指定表格
            result = self.sync_coordinator.sync_single_table(team_name, table_name, full_update)
            return {
                'status': 'completed' if result['success'] else 'failed',
                'type': 'single_table',
                'team_name': team_name,
                'table_name': table_name,
                'result': result
            }
            
        elif team_name:
            # 同步指定團隊
            result = self.sync_coordinator.sync_team(team_name, full_update)
            return {
                'status': 'completed' if result['success'] else 'failed',
                'type': 'single_team',
                'team_name': team_name,
                'result': result
            }
            
        else:
            # 同步所有團隊
            result = self.sync_coordinator.sync_all_teams(full_update)
            return {
                'status': 'completed' if result.success else 'failed',
                'type': 'all_teams',
                'result': result,
                'summary': {
                    'total_teams': result.total_teams,
                    'total_tables': result.total_tables,
                    'total_synced': result.successful_tables,
                    'total_errors': result.failed_tables
                }
            }
    
    def rebuild_cache(self, team_name: str = None, table_name: str = None) -> Dict[str, Any]:
        """
        從 Lark 表格重建快取
        
        Args:
            team_name: 指定團隊名稱（可選）
            table_name: 指定表格名稱（可選，需要同時指定團隊）
            
        Returns:
            Dict: 重建結果
        """
        if not self.sync_coordinator:
            raise RuntimeError("系統尚未初始化")
        
        try:
            result = self.sync_coordinator.rebuild_cache_from_lark(team_name, table_name)
            
            if team_name and table_name:
                return {
                    'status': 'completed' if result['success'] else 'failed',
                    'type': 'single_table_cache',
                    'team_name': team_name,
                    'table_name': table_name,
                    'result': result
                }
            elif team_name:
                return {
                    'status': 'completed' if result['success'] else 'failed',
                    'type': 'team_cache',
                    'team_name': team_name,
                    'result': result
                }
            else:
                return {
                    'status': 'completed' if result['success'] else 'failed',
                    'type': 'all_cache',
                    'result': result
                }
                
        except Exception as e:
            self.logger.error(f"快取重建失敗: {e}")
            return {'success': False, 'error': str(e)}
    
    def run_daemon(self):
        """運行定時同步守護程式（支援個別表格間隔）"""
        if not self.sync_coordinator:
            raise RuntimeError("系統尚未初始化")
        
        print("🚀 啟動定時同步守護程式（新架構 - 支援個別表格間隔）")
        print("按 Ctrl+C 停止")
        
        self.running = True
        
        # 初始化每個表格的下次執行時間
        import time
        table_next_sync = {}
        
        # 獲取所有表格的同步間隔
        all_intervals = self.config_manager.get_all_sync_intervals()
        current_time = time.time()
        
        # 初始化每個表格的下次同步時間
        for team_name, team_tables in all_intervals.items():
            for table_name, interval in team_tables.items():
                key = f"{team_name}.{table_name}"
                table_next_sync[key] = current_time  # 立即開始第一次同步
                print(f"📋 {key}: 同步間隔 {interval} 秒")
        
        while self.running:
            try:
                current_time = time.time()
                synced_tables = []
                
                # 檢查哪些表格需要同步
                for team_name, team_tables in all_intervals.items():
                    for table_name, interval in team_tables.items():
                        key = f"{team_name}.{table_name}"
                        
                        if not self.running:
                            break
                        
                        if current_time >= table_next_sync.get(key, 0):
                            try:
                                print(f"\n⏰ 開始表格同步: {key} - {datetime.now().strftime('%H:%M:%S')}")
                                
                                # 同步單一表格
                                result = self.sync_coordinator.sync_single_table(team_name, table_name)
                                
                                if result['success']:
                                    sync_result = result.get('result', {})
                                    if hasattr(sync_result, 'created_records'):
                                        print(f"✅ {key} 同步完成 - "
                                             f"創建: {sync_result.created_records}, "
                                             f"更新: {sync_result.updated_records}, "
                                             f"失敗: {sync_result.failed_operations}")
                                    else:
                                        print(f"✅ {key} 同步完成")
                                else:
                                    print(f"❌ {key} 同步失敗: {result.get('error', '未知錯誤')}")
                                
                                # 設定下次同步時間
                                table_next_sync[key] = current_time + interval
                                synced_tables.append(key)
                                
                            except Exception as e:
                                print(f"❌ 表格 {key} 同步錯誤: {e}")
                                if self.sync_logger:
                                    self.sync_logger.error(f"表格 {key} 同步錯誤: {e}")
                                # 發生錯誤時，60 秒後重試
                                table_next_sync[key] = current_time + 60
                
                # 顯示狀態（如果有表格執行了同步）
                if synced_tables and self.running:
                    print(f"\n📊 下次同步時間:")
                    for team_name, team_tables in all_intervals.items():
                        for table_name, interval in team_tables.items():
                            key = f"{team_name}.{table_name}"
                            next_time = table_next_sync.get(key, 0)
                            remaining = max(0, next_time - time.time())
                            print(f"  {key}: {remaining:.0f} 秒後 ({interval}s 間隔)")
                
                # 短暫等待後再檢查（避免 CPU 過度使用）
                if self.running:
                    self._interruptible_sleep(10)
                
            except KeyboardInterrupt:
                print("\n收到中斷信號，正在停止...")
                break
            except Exception as e:
                print(f"❌ 定時同步錯誤: {e}")
                if self.sync_logger:
                    self.sync_logger.error(f"定時同步錯誤: {e}")
                if self.running:
                    print("💤 等待 60 秒後重試...")
                    self._interruptible_sleep(60)  # 等待後重試
        
        print("🛑 定時同步守護程式已停止")
    
    def sync_issue(self, team_name: str, table_name: str, issue_key: str) -> Dict[str, Any]:
        """
        同步單一 Issue
        
        Args:
            team_name: 團隊名稱
            table_name: 表格名稱
            issue_key: Issue Key
            
        Returns:
            Dict: 同步結果
        """
        if not self.sync_coordinator:
            raise RuntimeError("系統尚未初始化")
        
        result = self.sync_coordinator.sync_single_issue(team_name, table_name, issue_key)
        
        return {
            'status': 'success' if result['success'] else 'failed',
            'operation': 'sync_issue',
            'issue_key': issue_key,
            'team_name': team_name,
            'table_name': table_name,
            'result': result,
            'error': result.get('error') if not result['success'] else None
        }
    
    def show_status(self):
        """顯示系統狀態"""
        if not self.config_manager:
            print("❌ 系統尚未初始化")
            return
        
        print("📊 JIRA-Lark Base 同步系統狀態（新架構）")
        print("=" * 60)
        
        # 顯示配置摘要
        self.config_manager.print_config_summary()
        
        # 顯示系統狀態
        if self.sync_coordinator:
            try:
                system_status = self.sync_coordinator.get_system_status()
                
                print(f"\n🏥 系統健康狀態: {'✅ 正常' if system_status.get('system_healthy') else '❌ 異常'}")
                print(f"📊 總團隊數: {system_status.get('total_teams', 0)}")
                print(f"📁 資料目錄: {system_status.get('data_directory', 'N/A')}")
                print(f"📋 Schema 檔案: {system_status.get('schema_path', 'N/A')}")
                
                # 顯示團隊狀態
                team_statuses = system_status.get('team_statuses', {})
                if team_statuses:
                    print(f"\n📋 團隊狀態詳情:")
                    for team_name, team_status in team_statuses.items():
                        print(f"  {team_name}: {team_status.get('total_tables', 0)} 個表格")
                        
                        table_statuses = team_status.get('table_statuses', {})
                        for table_name, table_status in table_statuses.items():
                            stats = table_status.get('stats', {})
                            is_cold = table_status.get('is_cold_start', True)
                            print(f"    - {table_name}: "
                                 f"{stats.get('total_records', 0)} 筆記錄, "
                                 f"{'🔄 冷啟動' if is_cold else '⚡ 增量同步'}")
                
                # 顯示指標摘要
                metrics_summary = system_status.get('metrics_summary', {})
                if metrics_summary and not metrics_summary.get('error'):
                    session_stats = metrics_summary.get('session_statistics', {})
                    if session_stats.get('total_sessions', 0) > 0:
                        print(f"\n📈 效能指標（最近 7 天）:")
                        print(f"  總同步會話: {session_stats.get('total_sessions', 0)}")
                        print(f"  平均處理時間: {session_stats.get('avg_processing_time', 0):.2f}s")
                        print(f"  平均成功率: {session_stats.get('avg_success_rate', 0):.1f}%")
                        print(f"  總處理記錄: {session_stats.get('total_processed', 0)}")
                
            except Exception as e:
                print(f"\n🔗 系統狀態檢查失敗: {e}")
        else:
            print(f"\n🔗 SyncCoordinator: ❌ 未初始化")


def main():
    """主函數"""
    parser = argparse.ArgumentParser(
        description='JIRA-Lark Base 單向同步系統 (JIRA → Lark) - 新架構版本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  %(prog)s status                               # 顯示系統狀態
  %(prog)s sync                                 # 執行一次全面同步
  %(prog)s sync --team management               # 同步指定團隊
  %(prog)s sync --team management --table tp_table  # 同步指定表格
  %(prog)s sync --full-update                   # 全量更新模式
  %(prog)s daemon                               # 啟動定時同步守護程式
  %(prog)s issue management tp_table TP-3153   # 同步單一 Issue
  %(prog)s cache --rebuild                      # 從 Lark 表格重建所有快取
  %(prog)s cache --rebuild --team management    # 從 Lark 表格重建團隊快取
  %(prog)s cache --rebuild --team management --table tp_table  # 從 Lark 表格重建表格快取
        """
    )
    
    parser.add_argument(
        '--config', 
        default='config.yaml',
        help='配置檔案路徑 (預設: config.yaml)'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # status 命令
    subparsers.add_parser('status', help='顯示系統狀態')
    
    # sync 命令
    sync_parser = subparsers.add_parser('sync', help='執行同步')
    sync_parser.add_argument('--team', help='指定團隊名稱')
    sync_parser.add_argument('--table', help='指定表格名稱')
    sync_parser.add_argument('--full-update', action='store_true', 
                            help='全量更新模式：更新所有現有記錄')
    
    # daemon 命令
    subparsers.add_parser('daemon', help='啟動定時同步守護程式')
    
    # issue 命令
    issue_parser = subparsers.add_parser('issue', help='同步單一 Issue')
    issue_parser.add_argument('team', help='團隊名稱')
    issue_parser.add_argument('table', help='表格名稱')
    issue_parser.add_argument('issue_key', help='Issue Key (如 TP-3153)')
    
    # cache 命令
    cache_parser = subparsers.add_parser('cache', help='快取管理')
    cache_parser.add_argument('--team', help='指定團隊名稱')
    cache_parser.add_argument('--table', help='指定表格名稱')
    cache_parser.add_argument('--rebuild', action='store_true', 
                            help='從 Lark 表格重建快取')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        # 建立應用程式實例
        app = JiraLarkSyncApp(args.config)
        
        # 執行相應命令
        if args.command == 'status':
            app.initialize()
            app.show_status()
            
        elif args.command == 'sync':
            app.initialize()
            
            if hasattr(args, 'full_update') and args.full_update:
                print("🔄 全量更新模式啟用")
            
            print("🚀 開始同步...")
            start_time = datetime.now()
            
            result = app.run_once(args.team, args.table, getattr(args, 'full_update', False))
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            print(f"\n✅ 同步完成，耗時 {duration:.2f} 秒")
            
            # 顯示結果摘要
            if result['status'] == 'completed' and 'summary' in result:
                summary = result['summary']
                print(f"📊 同步統計:")
                print(f"  團隊: {summary['total_teams']} 個")
                print(f"  表格: {summary['total_tables']} 個")
                print(f"  成功: {summary['total_synced']} 個")
                print(f"  失敗: {summary['total_errors']} 個")
            elif result['status'] == 'failed':
                print(f"❌ 同步失敗: {result.get('result', {}).get('error', '未知錯誤')}")
                return 1
            
        elif args.command == 'daemon':
            app.initialize()
            app.run_daemon()
            
        elif args.command == 'issue':
            app.initialize()
            
            print(f"🎯 同步單一 Issue: {args.issue_key}")
            
            result = app.sync_issue(args.team, args.table, args.issue_key)
            
            if result['status'] == 'success':
                print(f"✅ Issue 同步成功: {args.issue_key}")
            else:
                print(f"❌ Issue 同步失敗: {result.get('error', '未知錯誤')}")
                return 1
        
        elif args.command == 'cache':
            app.initialize()
            
            if args.rebuild:
                if args.team and args.table:
                    print(f"🔄 從 Lark 表格重建快取: {args.team}.{args.table}")
                elif args.team:
                    print(f"🔄 從 Lark 表格重建團隊快取: {args.team}")
                else:
                    print("🔄 從 Lark 表格重建所有快取")
                
                start_time = datetime.now()
                result = app.rebuild_cache(args.team, args.table)
                end_time = datetime.now()
                
                if result['status'] == 'completed':
                    print(f"✅ 快取重建完成")
                    print(f"⏱️ 處理時間: {end_time - start_time}")
                    
                    # 顯示詳細結果
                    cache_result = result['result']
                    if args.team and args.table:
                        print(f"  表格: {cache_result['table_name']}")
                        print(f"  總記錄: {cache_result['total_records']}")
                        print(f"  已快取: {cache_result['cached_records']}")
                        print(f"  有效記錄: {cache_result['valid_records']}")
                    elif args.team:
                        print(f"  團隊: {cache_result['team_name']}")
                        print(f"  總表格: {cache_result['total_tables']}")
                        print(f"  成功: {cache_result['successful_tables']}")
                        print(f"  失敗: {cache_result['failed_tables']}")
                        print(f"  總快取: {cache_result['total_cached']} 筆")
                    else:
                        print(f"  總團隊: {cache_result['total_teams']}")
                        print(f"  成功: {cache_result['successful_teams']}")
                        print(f"  失敗: {cache_result['failed_teams']}")
                        print(f"  總快取: {cache_result['total_cached']} 筆")
                        
                elif result['status'] == 'failed':
                    print(f"❌ 快取重建失敗: {result.get('result', {}).get('error', '未知錯誤')}")
                    return 1
            else:
                print("❓ 請指定快取操作，例如: --rebuild")
                return 1
        
        return 0
        
    except KeyboardInterrupt:
        print("\n👋 程式被用戶中斷")
        return 130
    except Exception as e:
        print(f"❌ 程式執行錯誤: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())