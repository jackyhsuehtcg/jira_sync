#!/usr/bin/env python3
"""
JIRA-Lark Base 同步系統 Web API（新架構版本）
提供 REST API 介面供前端調用
"""

import time
import threading
import signal
import sys
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# 匯入新架構模組
from config_manager import ConfigManager
from jira_client import JiraClient
from lark_client import LarkClient
from field_processor import FieldProcessor
from sync_workflow_manager import SyncWorkflowManager
from sync_state_manager import SyncStateManager

class SyncSystemAPI:
    """同步系統 API 類別（新架構版本）"""
    
    def __init__(self, config_file: str = 'config.yaml'):
        """初始化 API"""
        self.config_file = config_file
        self.daemon_thread = None
        self.daemon_running = False
        self.start_time = datetime.now()
        self.sync_stats = {
            'total_syncs': 0,
            'success_count': 0,
            'error_count': 0,
            'last_sync_time': None,
            'total_sync_time': 0,
            'today_syncs': 0,
            'last_reset_date': datetime.now().date()
        }
        self.team_status = {}
        
        # 初始化系統元件
        self.config_manager = None
        self.jira_client = None
        self.lark_client = None
        self.field_processor = None
        self.sync_workflow_manager = None
        self.sync_state_manager = None
        self.logger = None
        
        # 初始化同步系統
        self._initialize_system()
    
    def _initialize_system(self):
        """初始化同步系統元件"""
        try:
            # 設定日誌
            self.logger = logging.getLogger(f"{__name__}.SyncSystemAPI")
            
            # 初始化配置管理器
            self.config_manager = ConfigManager(None, self.config_file)
            
            # 初始化 JIRA 客戶端
            jira_config = self.config_manager.get_jira_config()
            self.jira_client = JiraClient(config=jira_config, logger=self.logger)
            
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
            
            # 初始化欄位處理器
            self.field_processor = FieldProcessor(
                schema_path=self.config_manager.get_global_config().get('schema_file', 'schema.yaml'),
                jira_server_url=jira_config['server_url'],
                logger=self.logger
            )
            
            # 初始化同步工作流程管理器
            self.sync_workflow_manager = SyncWorkflowManager(
                jira_client=self.jira_client,
                lark_client=self.lark_client,
                field_processor=self.field_processor,
                sync_state_manager=self.sync_state_manager,
                logger=self.logger
            )
            
            print("✅ 同步系統初始化完成")
            
        except Exception as e:
            print(f"❌ 同步系統初始化失敗: {e}")
            self.logger.error(f"系統初始化失敗: {e}")
            self.config_manager = None
    
    def _update_daily_stats(self):
        """更新每日統計（重置今日計數）"""
        today = datetime.now().date()
        if today != self.sync_stats['last_reset_date']:
            self.sync_stats['today_syncs'] = 0
            self.sync_stats['last_reset_date'] = today
    
    def _record_sync_result(self, result: Dict[str, Any], duration: float):
        """記錄同步結果統計"""
        self._update_daily_stats()
        
        self.sync_stats['total_syncs'] += 1
        self.sync_stats['today_syncs'] += 1
        self.sync_stats['last_sync_time'] = datetime.now()
        self.sync_stats['total_sync_time'] += duration
        
        if result.get('status') == 'completed':
            self.sync_stats['success_count'] += 1
        else:
            self.sync_stats['error_count'] += 1
    
    def get_system_status(self) -> Dict[str, Any]:
        """獲取系統狀態"""
        if not self.config_manager:
            return {
                'status': 'error',
                'message': '系統未初始化'
            }
        
        self._update_daily_stats()
        
        # 計算運行時間
        uptime = datetime.now() - self.start_time
        uptime_str = f"{uptime.days}天 {uptime.seconds // 3600}小時"
        
        # 獲取團隊狀態
        teams = self.config_manager.get_teams()
        active_teams = len([t for t, status in self.team_status.items() 
                           if status.get('active', False)])
        
        # 計算成功率
        total_attempts = self.sync_stats['success_count'] + self.sync_stats['error_count']
        success_rate = (self.sync_stats['success_count'] / total_attempts * 100) if total_attempts > 0 else 0
        
        # 計算平均同步時間
        avg_sync_time = (self.sync_stats['total_sync_time'] / self.sync_stats['total_syncs']) if self.sync_stats['total_syncs'] > 0 else 0
        
        # 檢查真正的守護程序狀態
        import subprocess
        daemon_is_running = False
        try:
            result = subprocess.run(['pgrep', '-f', 'python main.py daemon'], capture_output=True, text=True)
            daemon_is_running = result.returncode == 0 and result.stdout.strip()
        except:
            pass
        
        return {
            'status': 'running' if daemon_is_running else 'stopped',
            'uptime': uptime_str,
            'daemon_status': daemon_is_running,
            'teams': {
                'total': len(teams),
                'active': active_teams
            },
            'stats': {
                'total_syncs': self.sync_stats['total_syncs'],
                'success_count': self.sync_stats['success_count'],
                'error_count': self.sync_stats['error_count'],
                'success_rate': round(success_rate, 1),
                'today_syncs': self.sync_stats['today_syncs'],
                'avg_sync_time': round(avg_sync_time, 2),
                'last_sync': self.sync_stats['last_sync_time'].isoformat() if self.sync_stats['last_sync_time'] else None
            }
        }
    
    def get_teams_status(self) -> Dict[str, Any]:
        """獲取所有團隊狀態"""
        if not self.config_manager:
            return {'error': '系統未初始化'}
        
        teams = self.config_manager.get_teams()
        result = {}
        
        for team_name, team_config in teams.items():
            tables = team_config.get('tables', {})
            team_status = self.team_status.get(team_name, {})
            
            result[team_name] = {
                'name': team_name,
                'active': team_status.get('active', False),
                'table_count': len(tables),
                'last_sync': team_status.get('last_sync'),
                'next_sync': team_status.get('next_sync'),
                'sync_interval': team_config.get('sync_interval', 300),
                'tables': {
                    table_name: {
                        'name': table_config.get('name', table_name),
                        'enabled': table_config.get('enabled', True),
                        'table_id': table_config.get('table_id'),
                        'sync_interval': table_config.get('sync_interval', 300)
                    }
                    for table_name, table_config in tables.items()
                }
            }
        
        return result
    
    def start_all_sync(self) -> Dict[str, Any]:
        """開始所有同步"""
        if not self.config_manager:
            return {'status': 'error', 'message': '系統未初始化'}
        
        try:
            import subprocess
            import os
            
            # 檢查是否已經有守護程序在運行
            result = subprocess.run(['pgrep', '-f', 'python main.py daemon'], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                return {'status': 'warning', 'message': '同步已在運行中'}
            
            # 啟動 main.py daemon
            process = subprocess.Popen(
                ['python', 'main.py', 'daemon'],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            
            # 等待一下確保程序啟動
            time.sleep(2)
            
            # 驗證程序是否成功啟動
            if process.poll() is None:
                self.daemon_running = True
                return {'status': 'success', 'message': '同步守護程序已啟動'}
            else:
                return {'status': 'error', 'message': '守護程序啟動失敗'}
            
        except Exception as e:
            return {'status': 'error', 'message': f'啟動失敗: {str(e)}'}
    
    def stop_all_sync(self) -> Dict[str, Any]:
        """停止所有同步"""
        try:
            import subprocess
            import signal
            
            # 查找 main.py daemon 進程
            result = subprocess.run(['pgrep', '-f', 'python main.py daemon'], capture_output=True, text=True)
            daemon_pid = None
            
            if result.returncode == 0 and result.stdout.strip():
                daemon_pid = int(result.stdout.strip().split('\n')[0])
            
            if daemon_pid:
                # 發送 SIGTERM 信號停止守護程序
                import os
                os.kill(daemon_pid, signal.SIGTERM)
                
                # 等待一下確保程序停止
                time.sleep(2)
                
                # 驗證程序是否已停止
                try:
                    os.kill(daemon_pid, 0)  # 測試進程是否還存在
                    return {'status': 'warning', 'message': '守護程序可能仍在運行'}
                except OSError:
                    self.daemon_running = False
                    return {'status': 'success', 'message': '同步守護程序已停止'}
            else:
                self.daemon_running = False
                return {'status': 'warning', 'message': '同步未在運行'}
                
        except Exception as e:
            return {'status': 'error', 'message': f'停止失敗: {str(e)}'}
    
    def full_update_all(self) -> Dict[str, Any]:
        """執行全量更新"""
        if not self.config_manager:
            return {'status': 'error', 'message': '系統未初始化'}
        
        try:
            import subprocess
            import os
            
            start_time = time.time()
            
            # 執行 main.py sync --full-update
            result = subprocess.run(
                ['python', 'main.py', 'sync', '--full-update'],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                capture_output=True,
                text=True,
                timeout=300  # 5分鐘超時
            )
            
            duration = time.time() - start_time
            
            if result.returncode == 0:
                return {
                    'status': 'success',
                    'message': '全量更新已完成',
                    'duration': round(duration, 2),
                    'output': result.stdout
                }
            else:
                return {
                    'status': 'error',
                    'message': f'全量更新失敗: {result.stderr}',
                    'duration': round(duration, 2)
                }
            
        except subprocess.TimeoutExpired:
            return {'status': 'error', 'message': '全量更新超時（5分鐘）'}
        except Exception as e:
            return {'status': 'error', 'message': f'全量更新失敗: {str(e)}'}
    
    def sync_team(self, team_name: str, full_update: bool = False) -> Dict[str, Any]:
        """同步指定團隊"""
        if not self.config_manager:
            return {'status': 'error', 'message': '系統未初始化'}
        
        try:
            import subprocess
            import os
            
            start_time = time.time()
            
            # 構建命令
            cmd = ['python', 'main.py', 'sync', '--team', team_name]
            if full_update:
                cmd.append('--full-update')
            
            # 執行 main.py sync --team
            result = subprocess.run(
                cmd,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                capture_output=True,
                text=True,
                timeout=300  # 5分鐘超時
            )
            
            duration = time.time() - start_time
            
            if result.returncode == 0:
                return {
                    'status': 'success',
                    'message': f'團隊 {team_name} 同步完成',
                    'duration': round(duration, 2),
                    'output': result.stdout
                }
            else:
                return {
                    'status': 'error',
                    'message': f'同步團隊失敗: {result.stderr}',
                    'duration': round(duration, 2)
                }
            
        except subprocess.TimeoutExpired:
            return {'status': 'error', 'message': '同步團隊超時（5分鐘）'}
        except Exception as e:
            return {'status': 'error', 'message': f'同步團隊失敗: {str(e)}'}
    
    def sync_table(self, team_name: str, table_name: str, full_update: bool = False) -> Dict[str, Any]:
        """同步指定表格"""
        if not self.config_manager:
            return {'status': 'error', 'message': '系統未初始化'}
        
        try:
            import subprocess
            import os
            
            start_time = time.time()
            
            # 構建命令
            cmd = ['python', 'main.py', 'sync', '--team', team_name, '--table', table_name]
            if full_update:
                cmd.append('--full-update')
            
            # 執行 main.py sync --team --table
            result = subprocess.run(
                cmd,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                capture_output=True,
                text=True,
                timeout=300  # 5分鐘超時
            )
            
            duration = time.time() - start_time
            
            if result.returncode == 0:
                return {
                    'status': 'success',
                    'message': f'表格 {table_name} 同步完成',
                    'duration': round(duration, 2),
                    'output': result.stdout
                }
            else:
                return {
                    'status': 'error',
                    'message': f'同步表格失敗: {result.stderr}',
                    'duration': round(duration, 2)
                }
            
        except subprocess.TimeoutExpired:
            return {'status': 'error', 'message': '同步表格超時（5分鐘）'}
        except Exception as e:
            return {'status': 'error', 'message': f'同步表格失敗: {str(e)}'}
    
    def sync_all_teams(self) -> Dict[str, Any]:
        """同步所有團隊"""
        try:
            teams = self.config_manager.get_teams()
            results = {}
            
            for team_name in teams.keys():
                try:
                    result = self.sync_single_team(team_name)
                    results[team_name] = result
                except Exception as e:
                    results[team_name] = {'status': 'error', 'message': str(e)}
            
            return {'status': 'completed', 'teams': results}
            
        except Exception as e:
            return {'status': 'error', 'message': f'同步所有團隊失敗: {str(e)}'}
    
    def sync_single_team(self, team_name: str) -> Dict[str, Any]:
        """同步單一團隊"""
        try:
            team_config = self.config_manager.get_team_config(team_name)
            if not team_config:
                return {'status': 'error', 'message': f'找不到團隊: {team_name}'}
            
            tables = team_config.get('tables', {})
            results = {}
            
            for table_name, table_config in tables.items():
                if table_config.get('enabled', True):
                    try:
                        result = self.sync_single_table(team_name, table_name)
                        results[table_name] = result
                    except Exception as e:
                        results[table_name] = {'status': 'error', 'message': str(e)}
            
            return {'status': 'completed', 'tables': results}
            
        except Exception as e:
            return {'status': 'error', 'message': f'同步團隊失敗: {str(e)}'}
    
    def sync_single_table(self, team_name: str, table_name: str) -> Dict[str, Any]:
        """同步單一表格"""
        try:
            # 獲取團隊和表格配置
            team_config = self.config_manager.get_team_config(team_name)
            if not team_config:
                return {'status': 'error', 'message': f'找不到團隊: {team_name}'}
            
            table_config = team_config.get('tables', {}).get(table_name)
            if not table_config:
                return {'status': 'error', 'message': f'找不到表格: {table_name}'}
            
            # 設定 Wiki Token
            wiki_token = team_config.get('wiki_token')
            if not wiki_token:
                return {'status': 'error', 'message': '缺少 wiki_token'}
            
            self.lark_client.set_wiki_token(wiki_token)
            
            # 創建同步工作流配置
            from sync_workflow_manager import SyncWorkflowConfig
            sync_config = SyncWorkflowConfig(
                table_id=table_config.get('table_id'),
                jql_query=table_config.get('jql_query'),
                ticket_field_name=table_config.get('ticket_field', 'TCG Tickets'),
                batch_size=team_config.get('sync_settings', {}).get('batch_size', 100),
                max_retries=team_config.get('sync_settings', {}).get('max_retries', 3),
                retry_delay=team_config.get('sync_settings', {}).get('retry_delay', 1.0)
            )
            
            # 執行同步工作流程
            result = self.sync_workflow_manager.execute_sync_workflow(sync_config)
            
            return {
                'status': 'completed',
                'team': team_name,
                'table': table_name,
                'result': result.__dict__
            }
            
        except Exception as e:
            return {'status': 'error', 'message': f'同步表格失敗: {str(e)}'}
    
    def rebuild_cache(self, team_name: str = None, table_name: str = None) -> Dict[str, Any]:
        """重建快取"""
        if not self.config_manager:
            return {'status': 'error', 'message': '系統未初始化'}
        
        try:
            import subprocess
            import os
            
            start_time = time.time()
            
            # 構建命令
            cmd = ['python', 'main.py', 'cache', '--rebuild']
            if team_name:
                cmd.extend(['--team', team_name])
            if table_name:
                cmd.extend(['--table', table_name])
            
            # 執行 main.py cache --rebuild
            result = subprocess.run(
                cmd,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                capture_output=True,
                text=True,
                timeout=600  # 10分鐘超時
            )
            
            duration = time.time() - start_time
            
            if result.returncode == 0:
                return {
                    'status': 'success',
                    'message': '快取重建完成',
                    'duration': round(duration, 2),
                    'output': result.stdout
                }
            else:
                return {
                    'status': 'error',
                    'message': f'快取重建失敗: {result.stderr}',
                    'duration': round(duration, 2)
                }
            
        except subprocess.TimeoutExpired:
            return {'status': 'error', 'message': '快取重建超時（10分鐘）'}
        except Exception as e:
            return {'status': 'error', 'message': f'快取重建失敗: {str(e)}'}
    
    def test_jira_connection(self) -> Dict[str, Any]:
        """測試 JIRA 連線"""
        if not self.jira_client:
            return {'status': 'error', 'message': 'JIRA 客戶端未初始化'}
        
        try:
            server_info = self.jira_client.get_server_info()
            return {
                'status': 'success',
                'message': 'JIRA 連線正常',
                'server_info': server_info
            }
        except Exception as e:
            return {'status': 'error', 'message': f'JIRA 連線失敗: {str(e)}'}
    
    def test_lark_connection(self, wiki_token: str = None) -> Dict[str, Any]:
        """測試 Lark Base 連線"""
        if not self.lark_client:
            return {'status': 'error', 'message': 'Lark Base 客戶端未初始化'}
        
        try:
            # 使用第一個團隊的 wiki_token 進行測試（如果未提供）
            test_wiki_token = wiki_token
            test_table_id = None
            
            if not test_wiki_token:
                teams = self.config_manager.get_teams()
                if teams:
                    first_team = next(iter(teams.values()))
                    test_wiki_token = first_team.get('wiki_token')
                    
                    # 取得第一個啟用的表格 ID 進行測試
                    tables = first_team.get('tables', {})
                    for table_name, table_config in tables.items():
                        if table_config.get('enabled', True):
                            test_table_id = table_config.get('table_id')
                            break
            
            if not test_wiki_token:
                return {'status': 'error', 'message': '未找到有效的 wiki_token'}
            
            # 執行實際連線測試
            connection_success = self.lark_client.test_connection(test_wiki_token)
            
            if connection_success:
                return {
                    'status': 'success',
                    'message': 'Lark Base 連線正常',
                    'details': {
                        'wiki_token': test_wiki_token[:20] + '...' if len(test_wiki_token) > 20 else test_wiki_token,
                        'test_table_id': test_table_id
                    }
                }
            else:
                return {'status': 'error', 'message': 'Lark Base 連線測試失敗'}
            
        except Exception as e:
            return {'status': 'error', 'message': f'Lark Base 連線失敗: {str(e)}'}
    
    def test_jira_connection_with_config(self, jira_config: Dict[str, Any]) -> Dict[str, Any]:
        """使用指定配置測試 JIRA 連線"""
        try:
            from jira_client import JiraClient
            
            # 合併當前配置與表單配置
            current_jira_config = self.config_manager.get_jira_config()
            test_config = current_jira_config.copy()
            
            # 只更新非敏感欄位
            if 'server_url' in jira_config:
                test_config['server_url'] = jira_config['server_url']
            if 'username' in jira_config:
                test_config['username'] = jira_config['username']
            # 密碼使用配置檔中的值，不從表單獲取
            
            # 建立臨時 JIRA 客戶端（不自動測試連線）
            temp_jira_client = JiraClient(config=test_config, logger=self.logger, test_connection=False)
            
            # 測試連線
            server_info = temp_jira_client.get_server_info()
            if server_info:
                return {
                    'status': 'success',
                    'message': 'JIRA 連線正常',
                    'server_info': server_info
                }
            else:
                return {'status': 'error', 'message': 'JIRA 連線失敗：無法獲取伺服器資訊'}
                
        except Exception as e:
            return {'status': 'error', 'message': f'JIRA 連線失敗: {str(e)}'}
    
    def test_lark_connection_with_config(self, lark_config: Dict[str, Any]) -> Dict[str, Any]:
        """使用指定配置測試 Lark Base 連線"""
        try:
            from lark_client import LarkClient
            
            # 合併當前配置與表單配置
            current_lark_config = self.config_manager.get_lark_base_config()
            test_config = current_lark_config.copy()
            
            # 只更新非敏感欄位
            if 'app_id' in lark_config:
                test_config['app_id'] = lark_config['app_id']
            if 'base_url' in lark_config:
                test_config['base_url'] = lark_config['base_url']
            # app_secret 使用配置檔中的值，不從表單獲取
            
            # 建立臨時 Lark Base 客戶端
            temp_lark_client = LarkClient(
                app_id=test_config['app_id'],
                app_secret=test_config['app_secret']
            )
            
            # 使用第一個團隊的 wiki_token 進行測試
            teams = self.config_manager.get_teams()
            test_wiki_token = None
            test_table_id = None
            
            if teams:
                first_team = next(iter(teams.values()))
                test_wiki_token = first_team.get('wiki_token')
                
                # 取得第一個啟用的表格 ID 進行測試
                tables = first_team.get('tables', {})
                for table_name, table_config in tables.items():
                    if table_config.get('enabled', True):
                        test_table_id = table_config.get('table_id')
                        break
            
            if not test_wiki_token:
                return {'status': 'error', 'message': '未找到有效的 wiki_token'}
            
            # 執行實際連線測試
            connection_success = temp_lark_client.test_connection(test_wiki_token)
            
            if connection_success:
                return {
                    'status': 'success',
                    'message': 'Lark Base 連線正常',
                    'details': {
                        'wiki_token': test_wiki_token[:20] + '...' if len(test_wiki_token) > 20 else test_wiki_token,
                        'test_table_id': test_table_id
                    }
                }
            else:
                return {'status': 'error', 'message': 'Lark Base 連線測試失敗'}
                
        except Exception as e:
            return {'status': 'error', 'message': f'Lark Base 連線失敗: {str(e)}'}
    
    def validate_jql(self, jql_query: str) -> Dict[str, Any]:
        """驗證 JQL 語法"""
        if not self.jira_client:
            return {'status': 'error', 'message': 'JIRA 客戶端未初始化'}
        
        try:
            # 嘗試執行 JQL 查詢（限制結果數量）
            issues_dict = self.jira_client.search_issues(
                jql=jql_query,
                fields=['key'],
                max_results=1  # 只取1筆結果進行驗證
            )
            
            return {
                'status': 'success',
                'message': 'JQL 語法正確',
                'total_results': len(issues_dict)
            }
            
        except Exception as e:
            return {'status': 'error', 'message': f'JQL 語法錯誤: {str(e)}'}
    
    def test_jql_query(self, jql_query: str, max_results: int = 10) -> Dict[str, Any]:
        """測試 JQL 查詢並返回結果"""
        if not self.jira_client:
            return {'status': 'error', 'message': 'JIRA 客戶端未初始化'}
        
        try:
            issues_dict = self.jira_client.search_issues(
                jql=jql_query,
                fields=['key', 'summary', 'status', 'assignee', 'priority', 'updated'],
                max_results=max_results
            )
            
            # 格式化結果
            formatted_issues = []
            for issue_key, issue in issues_dict.items():
                fields = issue.get('fields', {})
                
                # 安全地取得欄位值
                assignee = None
                if fields.get('assignee'):
                    assignee = fields['assignee'].get('displayName') or fields['assignee'].get('name')
                
                priority = None
                if fields.get('priority'):
                    priority = fields['priority'].get('name')
                
                status = None
                if fields.get('status'):
                    status = fields['status'].get('name')
                
                # 構建 JIRA Issue URL
                issue_url = f"{self.config_manager.get_jira_config()['server_url']}/browse/{issue_key}" if issue_key != 'N/A' else '#'
                
                formatted_issues.append({
                    'key': issue_key,
                    'url': issue_url,
                    'summary': fields.get('summary', 'N/A'),
                    'status': status or 'N/A',
                    'assignee': assignee or 'Unassigned',
                    'priority': priority or 'N/A',
                    'updated': fields.get('updated', 'N/A')
                })
            
            return {
                'status': 'success',
                'message': f'查詢成功，找到 {len(issues_dict)} 筆記錄',
                'total': len(issues_dict),
                'issues': formatted_issues
            }
            
        except Exception as e:
            return {'status': 'error', 'message': f'查詢失敗: {str(e)}'}
    
    def _run_daemon_wrapper(self):
        """守護程式包裝器"""
        try:
            self.daemon_running = True
            
            # 基本的守護程序循環
            while self.daemon_running:
                try:
                    # 執行一次全部同步
                    result = self.sync_all_teams()
                    
                    # 記錄統計
                    duration = 5.0  # 估計持續時間
                    self._record_sync_result(result, duration)
                    
                    # 等待一段時間再執行下一次同步
                    time.sleep(300)  # 5分鐘間隔
                    
                except Exception as e:
                    self.logger.error(f"守護程序同步錯誤: {e}")
                    time.sleep(60)  # 錯誤後等待1分鐘
                    
        except KeyboardInterrupt:
            print("\n守護程式收到中斷信號，正在停止...")
        except Exception as e:
            print(f"守護程式錯誤: {e}")
            if self.logger:
                self.logger.error(f"守護程序錯誤: {e}")
        finally:
            self.daemon_running = False


# 全域變數用於信號處理
api = None
app = None

def signal_handler(signum, frame):
    """處理中斷信號"""
    print(f"\n收到信號 {signum}，正在優雅關閉...")
    
    if api:
        # 停止所有同步
        api.stop_all_sync()
        
        # 停止守護程式
        if api.daemon_running:
            api.daemon_running = False
    
    print("API 服務器已停止")
    sys.exit(0)

# 註冊信號處理器
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# 創建 Flask 應用
app = Flask(__name__)
CORS(app)  # 允許跨域請求

# 初始化 API 實例
api = SyncSystemAPI()

@app.route('/')
def serve_index():
    """提供主頁面"""
    return send_from_directory('templates', 'index.html')

@app.route('/templates/<path:filename>')
def serve_templates(filename):
    """提供模板檔案"""
    return send_from_directory('templates', filename)

@app.route('/api/status')
def get_status():
    """獲取系統狀態"""
    return jsonify(api.get_system_status())

@app.route('/api/teams')
def get_teams():
    """獲取所有團隊狀態"""
    return jsonify(api.get_teams_status())

@app.route('/api/config/teams')
def get_teams_config():
    """獲取團隊配置用於生成側邊欄"""
    if not api.config_manager:
        return jsonify({'error': '系統未初始化'})
    
    teams = api.config_manager.get_teams()
    result = {}
    
    for team_name, team_config in teams.items():
        tables = team_config.get('tables', {})
        
        result[team_name] = {
            'name': team_name,
            'display_name': team_config.get('display_name', team_name.upper()),
            'tables': {}
        }
        
        for table_name, table_config in tables.items():
            if table_config.get('enabled', True):
                result[team_name]['tables'][table_name] = {
                    'name': table_config.get('name', table_name),
                    'display_name': table_config.get('name', table_name),
                    'enabled': table_config.get('enabled', True)
                }
    
    return jsonify(result)

@app.route('/api/sync/start', methods=['POST'])
def start_sync():
    """開始所有同步"""
    return jsonify(api.start_all_sync())

@app.route('/api/sync/stop', methods=['POST'])
def stop_sync():
    """停止所有同步"""
    return jsonify(api.stop_all_sync())

@app.route('/api/sync/full-update', methods=['POST'])
def full_update():
    """執行全量更新"""
    return jsonify(api.full_update_all())

@app.route('/api/cache/rebuild', methods=['POST'])
def rebuild_cache():
    """重建快取"""
    data = request.get_json() if request.is_json else {}
    team_name = data.get('team_name')
    table_name = data.get('table_name')
    return jsonify(api.rebuild_cache(team_name, table_name))

@app.route('/api/cache/rebuild/<team_name>', methods=['POST'])
def rebuild_team_cache(team_name):
    """重建團隊快取"""
    return jsonify(api.rebuild_cache(team_name))

@app.route('/api/cache/rebuild/<team_name>/<table_name>', methods=['POST'])
def rebuild_table_cache(team_name, table_name):
    """重建表格快取"""
    return jsonify(api.rebuild_cache(team_name, table_name))

@app.route('/api/sync/team/<team_name>', methods=['POST'])
def sync_team_endpoint(team_name):
    """同步指定團隊"""
    full_update = request.json.get('full_update', False) if request.json else False
    return jsonify(api.sync_team(team_name, full_update))

@app.route('/api/sync/table/<team_name>/<table_name>', methods=['POST'])
def sync_table_endpoint(team_name, table_name):
    """同步指定表格"""
    full_update = request.json.get('full_update', False) if request.json else False
    return jsonify(api.sync_table(team_name, table_name, full_update))

@app.route('/api/test/jira', methods=['GET', 'POST'])
def test_jira():
    """測試 JIRA 連線"""
    if request.method == 'POST' and request.json:
        # 使用提供的配置進行測試
        jira_config = request.json
        return jsonify(api.test_jira_connection_with_config(jira_config))
    else:
        # 使用當前系統配置進行測試
        return jsonify(api.test_jira_connection())

@app.route('/api/test/lark', methods=['POST'])
def test_lark():
    """測試 Lark Base 連線"""
    try:
        # 確保請求有 JSON 內容類型
        if not request.is_json:
            return jsonify({
                'status': 'error',
                'message': 'Content-Type 必須是 application/json'
            }), 400
            
        # 取得 JSON 資料
        json_data = request.get_json(force=True)
        
        if json_data and 'app_id' in json_data:
            # 使用提供的配置進行測試
            lark_config = json_data
            return jsonify(api.test_lark_connection_with_config(lark_config))
        else:
            # 使用當前系統配置進行測試
            wiki_token = json_data.get('wiki_token') if json_data else None
            return jsonify(api.test_lark_connection(wiki_token))
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Lark 連線測試錯誤: {str(e)}'
        }), 500

@app.route('/api/jql/validate', methods=['POST'])
def validate_jql():
    """驗證 JQL 語法"""
    if not request.json or 'jql' not in request.json:
        return jsonify({'status': 'error', 'message': '請提供 JQL 查詢語句'})
    
    jql_query = request.json['jql']
    return jsonify(api.validate_jql(jql_query))

@app.route('/api/jql/test', methods=['POST'])
def test_jql():
    """測試 JQL 查詢"""
    if not request.json or 'jql' not in request.json:
        return jsonify({'status': 'error', 'message': '請提供 JQL 查詢語句'})
    
    jql_query = request.json['jql']
    max_results = request.json.get('max_results', 10)
    return jsonify(api.test_jql_query(jql_query, max_results))

# 配置管理 API 端點
@app.route('/api/config/system', methods=['GET'])
def get_system_config():
    """獲取系統配置"""
    try:
        config_manager = api.config_manager
        
        # 獲取各項配置
        global_config = config_manager.get_global_config()
        jira_config = config_manager.get_jira_config()
        lark_config = config_manager.get_lark_base_config()
        
        # 從 field_processor 獲取欄位對應
        field_mappings = {}
        if api.field_processor:
            # 返回完整的欄位對應配置，包含 processor 資訊
            raw_mappings = api.field_processor.field_mappings
            
            # 轉換為前端期待的格式，保留完整配置
            jira_to_lark = {}
            for jira_field, config in raw_mappings.items():
                jira_to_lark[jira_field] = config
            
            field_mappings = {
                'jira_to_lark': jira_to_lark,
                'ticket_fields': []  # 在新架構中不使用 ticket_fields
            }
        
        # 隱藏敏感資訊
        jira_config_safe = jira_config.copy()
        if 'password' in jira_config_safe:
            jira_config_safe['password'] = '*' * 8
            
        lark_config_safe = lark_config.copy()
        if 'app_secret' in lark_config_safe:
            lark_config_safe['app_secret'] = '*' * 20
        
        return jsonify({
            'status': 'success',
            'config': {
                'global': global_config,
                'jira': jira_config_safe,
                'lark_base': lark_config_safe,
                'field_mappings': field_mappings
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'獲取系統配置失敗: {str(e)}'
        }), 500

@app.route('/api/config/system', methods=['POST'])
def update_system_config():
    """更新系統配置"""
    try:
        if not request.json:
            return jsonify({
                'status': 'error',
                'message': '請提供配置資料'
            }), 400
        
        config_data = request.json
        config_manager = api.config_manager
        
        # 取得期望的配置版本（如果前端提供）
        # expected_version = config_data.get('_config_version')
        
        # 讀取當前配置
        current_config = config_manager.get_config()
        
        # 更新各項配置
        if 'global' in config_data:
            current_config['global'].update(config_data['global'])
            
        if 'jira' in config_data:
            # 如果密碼是 ******** 格式，保持原值
            jira_update = config_data['jira'].copy()
            if jira_update.get('password', '').startswith('*'):
                jira_update.pop('password', None)
            current_config['jira'].update(jira_update)
            
        if 'lark_base' in config_data:
            # 如果 app_secret 是 ******* 格式，保持原值
            lark_update = config_data['lark_base'].copy()
            if lark_update.get('app_secret', '').startswith('*'):
                lark_update.pop('app_secret', None)
            current_config['lark_base'].update(lark_update)
            
        if 'field_mappings' in config_data:
            # 處理 jira_to_lark 欄位對應，更新到 schema.yaml
            if 'jira_to_lark' in config_data['field_mappings']:
                jira_to_lark = config_data['field_mappings']['jira_to_lark']
                
                # 更新 schema.yaml 文件，保留註解
                try:
                    global_config = config_manager.get_global_config()
                    schema_file = global_config.get('schema_file', 'schema.yaml')
                    
                    from schema_utils import update_field_mappings_with_comments
                    update_field_mappings_with_comments(schema_file, jira_to_lark)
                    
                    print(f"✅ 已更新 schema.yaml 的 field_mappings（保留註解）")
                    
                except Exception as e:
                    print(f"❌ 更新 schema.yaml 失敗: {e}")
                    return jsonify({
                        'status': 'error',
                        'message': f'更新欄位映射失敗: {str(e)}'
                    }), 500
        
        # 配置寫入
        try:
            config_manager.save_config(current_config)
            
            # 重新初始化 field_processor 以載入新的配置
            if api.field_processor:
                try:
                    api.field_processor._load_schema()
                except Exception as e:
                    print(f"重新載入 field_processor schema 失敗: {e}")
            
            return jsonify({
                'status': 'success',
                'message': '配置已更新'
            })
        except Exception as e:
            return jsonify({
                'status': 'error',
                'message': f'配置更新失敗: {str(e)}'
            }), 500
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'更新系統配置失敗: {str(e)}'
        }), 500

@app.route('/api/config/validate', methods=['POST'])
def validate_config():
    """驗證配置有效性"""
    try:
        if not request.json:
            return jsonify({
                'status': 'error',
                'message': '請提供配置資料'
            }), 400
        
        # 這裡可以添加配置驗證邏輯
        config_data = request.json
        errors = []
        
        # 驗證全域配置
        if 'global' in config_data:
            global_config = config_data['global']
            if 'poll_interval' in global_config:
                if not isinstance(global_config['poll_interval'], int) or global_config['poll_interval'] < 60:
                    errors.append('輪詢間隔必須是大於等於 60 的整數')
        
        # 驗證 JIRA 配置
        if 'jira' in config_data:
            jira_config = config_data['jira']
            if 'server_url' in jira_config and not jira_config['server_url'].startswith('http'):
                errors.append('JIRA 伺服器 URL 必須以 http 或 https 開頭')
        
        if errors:
            return jsonify({
                'status': 'error',
                'message': '配置驗證失敗',
                'errors': errors
            }), 400
        
        return jsonify({
            'status': 'success',
            'message': '配置驗證通過'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'配置驗證失敗: {str(e)}'
        }), 500

# 表格配置管理 API 端點
@app.route('/api/config/table/<team_name>/<table_name>', methods=['GET'])
def get_table_config(team_name, table_name):
    """獲取表格配置"""
    try:
        config_manager = api.config_manager
        
        # 獲取團隊配置
        team_config = config_manager.get_team_config(team_name)
        if not team_config:
            return jsonify({
                'status': 'error',
                'message': f'找不到團隊: {team_name}'
            }), 404
        
        # 獲取表格配置
        tables = team_config.get('tables', {})
        if table_name not in tables:
            return jsonify({
                'status': 'error',
                'message': f'找不到表格: {table_name}'
            }), 404
        
        table_config = tables[table_name].copy()
        
        return jsonify({
            'status': 'success',
            'config': {
                'team_name': team_name,
                'table_name': table_name,
                'team_config': {
                    'wiki_token': team_config.get('wiki_token', ''),
                    'sync_interval': team_config.get('sync_interval', config_manager.get_global_config().get('default_sync_interval', 300))
                },
                'table_config': table_config
            }
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'獲取表格配置失敗: {str(e)}'
        }), 500

@app.route('/api/config/table/<team_name>/<table_name>', methods=['POST'])
def update_table_config(team_name, table_name):
    """更新表格配置"""
    try:
        if not request.json:
            return jsonify({
                'status': 'error',
                'message': '請提供配置資料'
            }), 400
        
        config_data = request.json
        config_manager = api.config_manager
        
        # 取得期望的配置版本
        # expected_version = config_data.get('_config_version')
        
        # 讀取當前配置
        current_config = config_manager.get_config()
        
        # 確保團隊和表格存在
        if 'teams' not in current_config:
            current_config['teams'] = {}
        if team_name not in current_config['teams']:
            current_config['teams'][team_name] = {'tables': {}}
        if 'tables' not in current_config['teams'][team_name]:
            current_config['teams'][team_name]['tables'] = {}
        
        # 更新團隊配置
        if 'team_config' in config_data:
            team_update = config_data['team_config']
            current_config['teams'][team_name].update(team_update)
        
        # 更新表格配置
        if 'table_config' in config_data:
            table_update = config_data['table_config']
            current_config['teams'][team_name]['tables'][table_name] = table_update
        
        # 儲存配置
        config_manager.save_config(current_config)
        
        return jsonify({
            'status': 'success',
            'message': '表格配置已更新'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'更新表格配置失敗: {str(e)}'
        }), 500

@app.route('/api/teams', methods=['GET'])
def get_all_teams():
    """獲取所有團隊和表格列表"""
    try:
        config_manager = api.config_manager
        teams = config_manager.get_teams()
        
        teams_data = {}
        for team_name, team_config in teams.items():
            tables = team_config.get('tables', {})
            tables_info = {}
            
            for table_name, table_config in tables.items():
                tables_info[table_name] = {
                    'name': table_config.get('name', table_name),
                    'enabled': table_config.get('enabled', False),
                    'dry_run': table_config.get('dry_run', False),
                    'table_id': table_config.get('table_id', '')
                }
            
            teams_data[team_name] = {
                'wiki_token': team_config.get('wiki_token', ''),
                'sync_interval': team_config.get('sync_interval'),
                'tables': tables_info
            }
        
        return jsonify({
            'status': 'success',
            'teams': teams_data
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'獲取團隊列表失敗: {str(e)}'
        }), 500

@app.route('/api/config/team/<team_name>', methods=['GET'])
def get_team_config(team_name):
    """獲取團隊配置"""
    try:
        config_manager = api.config_manager
        
        # 獲取團隊配置
        team_config = config_manager.get_team_config(team_name)
        if not team_config:
            return jsonify({
                'status': 'error',
                'message': f'找不到團隊: {team_name}'
            }), 404
        
        # 新增團隊名稱到配置中
        team_config['name'] = team_name
        
        return jsonify({
            'status': 'success',
            'config': team_config
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'獲取團隊配置失敗: {str(e)}'
        }), 500

@app.route('/api/config/team/<team_name>', methods=['POST'])
def update_team_config(team_name):
    """更新團隊配置"""
    try:
        if not request.json:
            return jsonify({
                'status': 'error',
                'message': '請提供配置資料'
            }), 400
        
        config_data = request.json
        config_manager = api.config_manager
        
        # 取得期望的配置版本
        # expected_version = config_data.get('_config_version')
        
        # 讀取當前配置
        current_config = config_manager.get_config()
        
        # 確保團隊存在
        if 'teams' not in current_config:
            current_config['teams'] = {}
        if team_name not in current_config['teams']:
            current_config['teams'][team_name] = {'tables': {}}
        
        # 更新團隊配置（保留現有的 tables）
        tables_backup = current_config['teams'][team_name].get('tables', {})
        current_config['teams'][team_name].update(config_data)
        current_config['teams'][team_name]['tables'] = tables_backup
        
        # 儲存配置
        config_manager.save_config(current_config)
        
        return jsonify({
            'status': 'success',
            'message': '團隊配置已更新'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'更新團隊配置失敗: {str(e)}'
        }), 500

@app.route('/api/config/table/<team_name>/<table_name>', methods=['DELETE'])
def delete_table_config(team_name, table_name):
    """刪除表格配置"""
    try:
        config_manager = api.config_manager
        
        # 讀取當前配置
        current_config = config_manager.get_config()
        
        # 檢查團隊和表格是否存在
        if ('teams' not in current_config or 
            team_name not in current_config['teams'] or
            'tables' not in current_config['teams'][team_name] or
            table_name not in current_config['teams'][team_name]['tables']):
            return jsonify({
                'status': 'error',
                'message': f'找不到表格: {team_name}/{table_name}'
            }), 404
        
        # 刪除表格配置
        del current_config['teams'][team_name]['tables'][table_name]
        
        # 儲存配置
        config_manager.save_config(current_config)
        
        return jsonify({
            'status': 'success',
            'message': f'表格 {table_name} 已刪除'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'刪除表格配置失敗: {str(e)}'
        }), 500

# 配置版本資訊 API 端點
@app.route('/api/config/version', methods=['GET'])
def get_config_version():
    """獲取配置檔案版本資訊"""
    try:
        import os
        from datetime import datetime
        
        config_file = api.config_file
        
        # 獲取檔案修改時間
        if os.path.exists(config_file):
            stat = os.stat(config_file)
            last_modified = datetime.fromtimestamp(stat.st_mtime)
        else:
            last_modified = None
        
        return jsonify({
            'status': 'success',
            'version': f"v1.0.0",
            'last_modified': last_modified.isoformat() if last_modified else None,
            'config_file': config_file
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'獲取配置版本失敗: {str(e)}'
        }), 500

# 配置檔案直接編輯 API 端點
@app.route('/api/config/raw', methods=['GET'])
def get_raw_config():
    """獲取原始配置檔案內容"""
    try:
        config_manager = api.config_manager
        config_file_path = config_manager.config_file
        
        # 讀取原始配置檔案
        with open(config_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({
            'status': 'success',
            'content': content,
            'file_path': config_file_path
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'讀取配置檔案失敗: {str(e)}'
        }), 500

@app.route('/api/config/raw', methods=['POST'])
def update_raw_config():
    """更新原始配置檔案內容"""
    try:
        if not request.json or 'content' not in request.json:
            return jsonify({
                'status': 'error',
                'message': '請提供配置檔案內容'
            }), 400
        
        content = request.json['content']
        # expected_version = request.json.get('_config_version')
        config_manager = api.config_manager
        
        try:
            # 驗證 YAML 語法並解析內容
            import yaml
            new_config = yaml.safe_load(content)
            
            # 儲存配置
            config_manager.save_config(new_config)
            
            # 重新初始化 field_processor 以更新欄位對應
            if api.field_processor:
                try:
                    api.field_processor._load_schema()
                except Exception as e:
                    print(f"重新載入 field_processor schema 失敗: {e}")
            
            return jsonify({
                'status': 'success',
                'message': '配置已更新'
            })
                    
        except yaml.YAMLError as e:
            return jsonify({
                'status': 'error',
                'message': f'YAML 語法錯誤: {str(e)}'
            }), 400
            
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'更新配置檔案失敗: {str(e)}'
        }), 500

# 日誌查看 API 端點
@app.route('/api/logs', methods=['GET'])
def get_logs():
    """獲取系統日誌內容"""
    try:
        config_manager = api.config_manager
        global_config = config_manager.get_global_config()
        log_file_path = global_config.get('log_file', 'jira_lark_sync.log')
        
        # 取得查詢參數
        lines = request.args.get('lines', 500, type=int)  # 預設顯示最後 500 行
        
        import os
        if not os.path.exists(log_file_path):
            return jsonify({
                'status': 'success',
                'content': '',
                'message': '日誌檔案不存在',
                'file_path': log_file_path,
                'total_lines': 0
            })
        
        # 讀取日誌檔案
        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
            
            # 取得最後 N 行
            if lines > 0:
                displayed_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            else:
                displayed_lines = all_lines
            
            content = ''.join(displayed_lines)
            
            return jsonify({
                'status': 'success',
                'content': content,
                'file_path': log_file_path,
                'total_lines': len(all_lines),
                'displayed_lines': len(displayed_lines),
                'file_size': os.path.getsize(log_file_path)
            })
            
        except UnicodeDecodeError:
            # 嘗試使用其他編碼
            with open(log_file_path, 'r', encoding='latin-1') as f:
                all_lines = f.readlines()
            
            if lines > 0:
                displayed_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            else:
                displayed_lines = all_lines
            
            content = ''.join(displayed_lines)
            
            return jsonify({
                'status': 'success',
                'content': content,
                'file_path': log_file_path,
                'total_lines': len(all_lines),
                'displayed_lines': len(displayed_lines),
                'file_size': os.path.getsize(log_file_path),
                'encoding': 'latin-1'
            })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'讀取日誌檔案失敗: {str(e)}'
        }), 500

@app.route('/api/lark/table-fields/<team_name>/<table_name>', methods=['GET'])
def get_lark_table_fields(team_name, table_name):
    """獲取指定 Lark 表格的欄位清單"""
    try:
        config_manager = api.config_manager
        lark_client = api.lark_client
        
        # 獲取團隊和表格配置
        team_config = config_manager.get_team_config(team_name)
        if not team_config:
            return jsonify({
                'status': 'error',
                'message': f'找不到團隊: {team_name}'
            }), 404
        
        tables = team_config.get('tables', {})
        if table_name not in tables:
            return jsonify({
                'status': 'error',
                'message': f'找不到表格: {table_name}'
            }), 404
        
        table_config = tables[table_name]
        table_id = table_config.get('table_id')
        
        if not table_id:
            return jsonify({
                'status': 'error',
                'message': '表格配置中缺少 table_id'
            }), 400
        
        # 設定 wiki_token
        wiki_token = team_config.get('wiki_token')
        if not wiki_token:
            return jsonify({
                'status': 'error',
                'message': '團隊配置中缺少 wiki_token'
            }), 400
        
        lark_client.set_wiki_token(wiki_token)
        
        # 獲取表格欄位
        available_fields = lark_client.get_available_field_names(table_id)
        
        return jsonify({
            'status': 'success',
            'table_fields': available_fields,
            'table_id': table_id,
            'table_name': table_config.get('name', table_name)
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'獲取表格欄位失敗: {str(e)}'
        }), 500

# 智慧新增欄位流程 API 端點
@app.route('/api/smart-field/get-issue/<ticket_key>', methods=['GET'])
def get_jira_issue_fields(ticket_key):
    """步驟2：取得指定 ticket 的 JIRA 資料並返回所有欄位"""
    try:
        if not api.jira_client:
            return jsonify({
                'status': 'error',
                'message': 'JIRA 客戶端未初始化'
            }), 500
        
        # 透過 JIRA API 取得單一 Issue，取得所有欄位
        issues_dict = api.jira_client.search_issues(jql=f'key = {ticket_key}', fields=['*all'], max_results=1)
        
        if not issues_dict:
            return jsonify({
                'status': 'error',
                'message': f'找不到 ticket: {ticket_key}'
            }), 404
        
        issue = list(issues_dict.values())[0]
        fields = issue.get('fields', {})
        
        # 整理欄位清單，包含欄位路徑、類型和範例值
        field_list = []
        
        # 處理所有欄位
        for field_key, field_value in fields.items():
            if field_value is None:
                continue
                
            field_info = {
                'field_path': field_key,
                'field_type': type(field_value).__name__,
                'sample_value': field_value,
                'is_nested': False,
                'is_array': False,
                'nested_paths': []
            }
            
            # 檢查是否為嵌套物件
            if isinstance(field_value, dict):
                field_info['is_nested'] = True
                field_info['nested_paths'] = list(field_value.keys())
                
                # 為嵌套欄位添加具體路徑選項
                for nested_key in field_value.keys():
                    nested_field = {
                        'field_path': f'{field_key}.{nested_key}',
                        'field_type': type(field_value[nested_key]).__name__,
                        'sample_value': field_value[nested_key],
                        'is_nested': False,
                        'is_array': False,
                        'nested_paths': [],
                        'parent_field': field_key
                    }
                    field_list.append(nested_field)
            
            # 檢查是否為陣列
            elif isinstance(field_value, list) and len(field_value) > 0:
                field_info['is_array'] = True
                field_info['array_length'] = len(field_value)
                
                # 分析陣列第一個元素
                first_item = field_value[0]
                if isinstance(first_item, dict):
                    field_info['array_item_keys'] = list(first_item.keys())
                    
                    # 為陣列元素添加路徑選項
                    for item_key in first_item.keys():
                        array_field = {
                            'field_path': f'{field_key}[0].{item_key}',
                            'field_type': type(first_item[item_key]).__name__,
                            'sample_value': first_item[item_key],
                            'is_nested': False,
                            'is_array': False,
                            'nested_paths': [],
                            'parent_field': field_key,
                            'is_array_item': True
                        }
                        field_list.append(array_field)
            
            field_list.append(field_info)
        
        # 按欄位路徑排序
        field_list.sort(key=lambda x: x['field_path'])
        
        return jsonify({
            'status': 'success',
            'issue_key': ticket_key,
            'issue_summary': fields.get('summary', 'N/A'),
            'fields': field_list,
            'total_fields': len(field_list)
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'取得 JIRA Issue 失敗: {str(e)}'
        }), 500

@app.route('/api/smart-field/check-existing', methods=['POST'])
def check_existing_field():
    """步驟3：檢查欄位是否已存在於配置中"""
    try:
        if not request.json:
            return jsonify({
                'status': 'error',
                'message': '缺少請求資料'
            }), 400
        
        field_path = request.json.get('field_path')
        if not field_path:
            return jsonify({
                'status': 'error',
                'message': '缺少 field_path 參數'
            }), 400
        
        # 檢查是否已存在於 field_processor 的 field_mappings 中
        if api.field_processor:
            field_mappings = api.field_processor.field_mappings
            
            if field_path in field_mappings:
                mapping_config = field_mappings[field_path]
                return jsonify({
                    'status': 'warning',
                    'exists': True,
                    'message': f'欄位 {field_path} 已存在',
                    'current_mapping': {
                        'jira_field': field_path,
                        'lark_field': mapping_config.get('lark_field', ''),
                        'processor': mapping_config.get('processor', 'extract_simple')
                    }
                })
        
        return jsonify({
            'status': 'success',
            'exists': False,
            'message': '欄位不存在，可以新增'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'檢查欄位失敗: {str(e)}'
        }), 500

@app.route('/api/smart-field/get-field-categories', methods=['GET'])
def get_field_categories():
    """步驟4：取得可用的欄位分類（從 config 檔的 field_processing_rules）"""
    try:
        config_manager = api.config_manager
        current_config = config_manager.get_config()
        
        processing_rules = current_config.get('field_mappings', {}).get('field_processing_rules', {})
        
        categories = []
        
        # 基本欄位分類
        for rule_name, rule_config in processing_rules.items():
            if rule_name != 'array_fields':  # array_fields 單獨處理
                categories.append({
                    'id': rule_name,
                    'name': rule_name,
                    'processor': rule_config.get('processor', 'extract_simple'),
                    'description': _get_category_description(rule_name),
                    'patterns': rule_config.get('patterns', [])
                })
        
        # 陣列欄位分類
        array_fields = processing_rules.get('array_fields', {})
        for field_name, field_config in array_fields.items():
            categories.append({
                'id': f'array_{field_name}',
                'name': f'陣列欄位 - {field_name}',
                'processor': field_config.get('processor', 'extract_simple'),
                'description': f'特殊陣列處理: {field_name}',
                'is_array_specific': True,
                'target_field': field_name
            })
        
        return jsonify({
            'status': 'success',
            'categories': categories
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'取得欄位分類失敗: {str(e)}'
        }), 500

def _get_category_description(category_name):
    """取得分類描述"""
    descriptions = {
        'user_fields': '人員欄位，將提取用戶資訊',
        'datetime_fields': '時間欄位，將轉換為 Lark 時間戳格式',
        'nested_fields': '嵌套物件欄位，提取指定路徑的值',
        'simple_fields': '簡單文字或數值欄位，直接使用值'
    }
    return descriptions.get(category_name, '自定義欄位分類')

@app.route('/api/config/field-mapping/add', methods=['POST'])
def add_field_mapping():
    """添加新的欄位對應到配置檔案"""
    try:
        if not request.json:
            return jsonify({
                'status': 'error',
                'message': '缺少請求資料'
            }), 400
        
        mapping_config = request.json.get('mapping_config')
        # expected_version = request.json.get('_config_version')
        
        if not mapping_config:
            return jsonify({
                'status': 'error',
                'message': '缺少 mapping_config 參數'
            }), 400
        
        # 在新架構中，欄位映射應該保存到 schema.yaml 文件中
        config_manager = api.config_manager
        
        # 合併新的欄位對應到 schema.yaml，保留註解
        if 'jira_to_lark' in mapping_config:
            try:
                global_config = config_manager.get_global_config()
                schema_file = global_config.get('schema_file', 'schema.yaml')
                
                from schema_utils import add_field_mapping_with_comments
                
                # 添加新的欄位對應
                for jira_field, lark_field in mapping_config['jira_to_lark'].items():
                    add_field_mapping_with_comments(
                        schema_file,
                        jira_field,
                        lark_field,
                        'extract_simple'  # 預設處理器
                    )
                
                print(f"✅ 已將新欄位對應添加到 schema.yaml（保留註解）")
                
            except Exception as e:
                print(f"❌ 更新 schema.yaml 失敗: {e}")
                return jsonify({
                    'status': 'error',
                    'message': f'更新欄位映射失敗: {str(e)}'
                }), 500
        
        # 在新架構中，處理規則已包含在 schema.yaml 的 field_mappings 中
        # 不再需要單獨的 field_processing_rules
        
        # 重新初始化 field_processor 以更新欄位對應
        if api.field_processor:
            try:
                api.field_processor._load_schema()
            except Exception as e:
                print(f"重新載入 field_processor schema 失敗: {e}")
        
        return jsonify({
            'status': 'success',
            'message': '欄位對應已成功添加到配置檔'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'添加欄位對應失敗: {str(e)}'
        }), 500


@app.errorhandler(404)
def not_found(error):
    return jsonify({'status': 'error', 'message': 'API 端點不存在'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'status': 'error', 'message': '內部伺服器錯誤'}), 500

def run_server():
    """啟動服務器"""
    try:
        print("🌐 啟動 JIRA-Lark 同步系統 Web API...")
        print("📡 API 端點:")
        print("  GET  /api/status          - 獲取系統狀態")
        print("  GET  /api/teams           - 獲取團隊狀態")
        print("  POST /api/sync/start      - 開始所有同步")
        print("  POST /api/sync/stop       - 停止所有同步")
        print("  POST /api/sync/full-update - 執行全量更新")
        print("  GET  /api/test/jira       - 測試 JIRA 連線")
        print("  POST /api/test/lark       - 測試 Lark 連線")
        print("  POST /api/jql/validate    - 驗證 JQL 語法")
        print("  POST /api/jql/test        - 測試 JQL 查詢")
        print("  GET  /api/config/raw      - 取得原始配置檔案")
        print("  POST /api/config/raw      - 更新原始配置檔案")
        print("  GET  /api/logs            - 查看系統日誌")
        print("\n🌍 Web 介面: http://localhost:8888")
        print("📋 按 Ctrl+C 停止服務器\n")
        
        # 關閉 Flask 的自動重載功能以避免信號處理問題
        app.run(
            host='0.0.0.0', 
            port=8888, 
            debug=False,  # 關閉 debug 模式避免信號衝突
            use_reloader=False,  # 關閉自動重載
            threaded=True  # 啟用多線程支援
        )
        
    except KeyboardInterrupt:
        print("\n收到鍵盤中斷，正在停止...")
    except Exception as e:
        print(f"服務器啟動錯誤: {e}")
    finally:
        print("服務器已關閉")

if __name__ == '__main__':
    run_server()