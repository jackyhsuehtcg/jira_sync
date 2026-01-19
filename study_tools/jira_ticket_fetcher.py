#!/usr/bin/env python3
"""
JIRA 票據取得工具

用於獲取 JIRA 特定票據的完整資訊

使用方法:
1. 單一票據:
python jira_ticket_fetcher.py --ticket TCG-108387

2. 多個票據:
python jira_ticket_fetcher.py --ticket TCG-108387 --ticket TCG-88819

3. 輸出到 JSON 檔案:
python jira_ticket_fetcher.py --ticket TCG-108387 --output ticket_info.json

4. 只顯示特定欄位:
python jira_ticket_fetcher.py --ticket TCG-108387 --fields summary,status,assignee
"""

import argparse
import json
import sys
from typing import Dict, List, Any, Optional
from datetime import datetime
import os
import requests
from requests.auth import HTTPBasicAuth
import yaml

try:
    from tls_utils import build_ca_bundle
except ModuleNotFoundError:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from tls_utils import build_ca_bundle


class JiraTicketFetcher:
    """JIRA 票據取得工具"""
    
    def __init__(self):
        """
        初始化工具
        
        使用 config.yaml 中的 JIRA 配置
        """
        # 從 config.yaml 載入配置
        try:
            config_path = os.path.abspath('config.yaml')
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            jira_config = config.get('jira', {})
            self.server_url = jira_config.get('server_url', '').rstrip('/')
            self.username = jira_config.get('username', '')
            self.password = jira_config.get('password', '')
            self.ca_cert_path = jira_config.get('ca_cert_path')
            
            if not all([self.server_url, self.username, self.password]):
                raise ValueError("JIRA 配置不完整")
                
            print(f"✓ 成功載入 JIRA 配置: {self.server_url}")
            
            if self.ca_cert_path:
                self.ca_cert_path = os.path.expanduser(str(self.ca_cert_path))
                if not os.path.isabs(self.ca_cert_path):
                    config_dir = os.path.dirname(config_path)
                    self.ca_cert_path = os.path.abspath(os.path.join(config_dir, self.ca_cert_path))
            
        except Exception as e:
            print(f"✗ 載入 config.yaml 失敗: {e}")
            sys.exit(1)
        
        # 設定認證和標頭
        self.auth = HTTPBasicAuth(self.username, self.password)
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        self.timeout = 30
        self.verify = True
        if self.ca_cert_path:
            self.verify = build_ca_bundle(self.ca_cert_path) or self.ca_cert_path
            if self.verify == self.ca_cert_path:
                print("✓ 使用自訂 CA 憑證進行 TLS 驗證")
            else:
                print("✓ 使用系統 CA + 自訂 CA 憑證進行 TLS 驗證")
        
        # 測試連接
        self._test_connection()
    
    def _test_connection(self):
        """測試 JIRA 連接"""
        try:
            response = self._make_request('GET', '/rest/api/2/myself')
            if response:
                user_info = response.get('displayName', self.username)
                print(f"✓ JIRA 連接測試成功，用戶: {user_info}")
            else:
                raise Exception("無法取得用戶資訊")
        except Exception as e:
            print(f"✗ JIRA 連接測試失敗: {e}")
            sys.exit(1)
    
    def _make_request(self, method: str, endpoint: str, params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """發送 HTTP 請求到 JIRA"""
        url = f"{self.server_url}{endpoint}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                auth=self.auth,
                headers=self.headers,
                params=params,
                timeout=self.timeout,
                verify=self.verify
            )
            
            print(f"API 請求: {method} {endpoint} -> {response.status_code}")
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                print(f"✗ 票據不存在: {endpoint}")
                return None
            else:
                print(f"✗ API 請求失敗: {response.status_code}")
                print(f"  錯誤內容: {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"✗ 請求異常: {e}")
            return None
    
    def get_ticket(self, ticket_key: str, fields: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """
        獲取單一票據資訊
        
        Args:
            ticket_key: 票據編號 (如 TCG-108387)
            fields: 指定要獲取的欄位列表，None 表示獲取所有欄位
            
        Returns:
            票據資訊或 None
        """
        print(f"\n--- 獲取票據: {ticket_key} ---")
        
        # 建立請求參數
        params = {}
        if fields:
            # 如果指定了欄位，只獲取指定欄位
            params['fields'] = ','.join(fields)
            print(f"指定欄位: {', '.join(fields)}")
        else:
            # 獲取所有欄位
            params['expand'] = 'names,schema,operations,versionedRepresentations,renderedFields,editmeta,changelog,transitions'
            print("獲取所有欄位")
        
        # 發送請求
        endpoint = f"/rest/api/2/issue/{ticket_key}"
        response = self._make_request('GET', endpoint, params)
        
        if response:
            print(f"✓ 成功獲取票據: {ticket_key}")
            return response
        else:
            print(f"✗ 獲取票據失敗: {ticket_key}")
            return None
    
    def get_multiple_tickets(self, ticket_keys: List[str], fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        獲取多個票據資訊
        
        Args:
            ticket_keys: 票據編號列表
            fields: 指定要獲取的欄位列表，None 表示獲取所有欄位
            
        Returns:
            包含所有票據資訊的字典
        """
        print(f"\n--- 獲取多個票據: {len(ticket_keys)} 個 ---")
        
        results = {
            'success': [],
            'failed': [],
            'tickets': {}
        }
        
        for ticket_key in ticket_keys:
            ticket_info = self.get_ticket(ticket_key, fields)
            if ticket_info:
                results['success'].append(ticket_key)
                results['tickets'][ticket_key] = ticket_info
            else:
                results['failed'].append(ticket_key)
        
        print(f"\n✓ 成功獲取: {len(results['success'])} 個票據")
        if results['failed']:
            print(f"✗ 失敗票據: {', '.join(results['failed'])}")
        
        return results
    
    def format_ticket_summary(self, ticket_info: Dict[str, Any]) -> str:
        """
        格式化票據摘要資訊
        
        Args:
            ticket_info: 票據資訊
            
        Returns:
            格式化的摘要字串
        """
        try:
            fields = ticket_info.get('fields', {})
            
            # 基本資訊
            key = ticket_info.get('key', 'Unknown')
            summary = fields.get('summary', 'No summary')
            
            # 處理狀態資訊
            status = fields.get('status', {})
            status_name = status.get('name', 'Unknown') if status else 'Unknown'
            
            # 處理問題類型
            issue_type = fields.get('issuetype', {})
            issue_type_name = issue_type.get('name', 'Unknown') if issue_type else 'Unknown'
            
            # 指派人
            assignee = fields.get('assignee')
            assignee_name = assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned'
            
            # 優先級
            priority = fields.get('priority')
            priority_name = priority.get('name', 'Unknown') if priority else 'Unknown'
            
            # 建立時間 - 處理不同的日期格式
            created = fields.get('created', '')
            if created:
                if 'T' in created:
                    created_date = created.split('T')[0]
                else:
                    created_date = created
            else:
                created_date = 'Unknown'
            
            # 更新時間 - 處理不同的日期格式
            updated = fields.get('updated', '')
            if updated:
                if 'T' in updated:
                    updated_date = updated.split('T')[0]
                else:
                    updated_date = updated
            else:
                updated_date = 'Unknown'
            
            # 報告人
            reporter = fields.get('reporter')
            reporter_name = reporter.get('displayName', 'Unknown') if reporter else 'Unknown'
            
            # 專案
            project = fields.get('project', {})
            project_name = project.get('name', 'Unknown') if project else 'Unknown'
            
            summary_text = f"""
票據編號: {key}
標題: {summary}
專案: {project_name}
類型: {issue_type_name}
狀態: {status_name}
優先級: {priority_name}
指派人: {assignee_name}
報告人: {reporter_name}
建立日期: {created_date}
更新日期: {updated_date}
"""
            
            return summary_text.strip()
            
        except Exception as e:
            return f"格式化票據摘要時發生錯誤: {e}"
    
    def save_to_json(self, data: Dict[str, Any], filename: str):
        """
        將資料保存為 JSON 檔案
        
        Args:
            data: 要保存的資料
            filename: 檔案名稱
        """
        try:
            import os
            os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else '.', exist_ok=True)
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"✓ 資料已保存到: {filename}")
            
        except Exception as e:
            print(f"✗ 保存檔案失敗: {e}")


def main():
    parser = argparse.ArgumentParser(description="JIRA 票據取得工具")
    parser.add_argument("--ticket", action="append", required=True, help="票據編號（可重複使用獲取多個票據）")
    parser.add_argument("--fields", help="指定要獲取的欄位，用逗號分隔（如: summary,status,assignee）")
    parser.add_argument("--output", help="輸出 JSON 檔案名稱")
    parser.add_argument("--summary", action="store_true", help="顯示票據摘要資訊")
    
    args = parser.parse_args()
    
    # 建立工具
    fetcher = JiraTicketFetcher()
    
    # 處理欄位參數
    fields = None
    if args.fields:
        fields = [field.strip() for field in args.fields.split(',')]
        print(f"指定欄位: {', '.join(fields)}")
    
    # 獲取票據
    if len(args.ticket) == 1:
        # 單一票據
        ticket_info = fetcher.get_ticket(args.ticket[0], fields)
        if not ticket_info:
            sys.exit(1)
        
        result = {
            'timestamp': datetime.now().isoformat(),
            'ticket_count': 1,
            'ticket': ticket_info
        }
        
        # 顯示摘要
        if args.summary:
            print("\n=== 票據摘要 ===")
            print(fetcher.format_ticket_summary(ticket_info))
        
    else:
        # 多個票據
        results = fetcher.get_multiple_tickets(args.ticket, fields)
        
        result = {
            'timestamp': datetime.now().isoformat(),
            'ticket_count': len(results['success']),
            'success_tickets': results['success'],
            'failed_tickets': results['failed'],
            'tickets': results['tickets']
        }
        
        # 顯示摘要
        if args.summary:
            print("\n=== 票據摘要 ===")
            for ticket_key, ticket_info in results['tickets'].items():
                print(f"\n{ticket_key}:")
                print(fetcher.format_ticket_summary(ticket_info))
        
        # 如果有失敗的票據，以非零狀態碼結束
        if results['failed']:
            sys.exit(1)
    
    # 保存到 JSON 檔案
    if args.output:
        fetcher.save_to_json(result, args.output)
    else:
        # 如果沒有指定輸出檔案，使用預設名稱
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if len(args.ticket) == 1:
            default_filename = f"study_tools/jira_ticket_{args.ticket[0].replace('-', '_')}_{timestamp}.json"
        else:
            default_filename = f"study_tools/jira_tickets_{timestamp}.json"
        
        fetcher.save_to_json(result, default_filename)
    
    print(f"\n🎉 票據獲取完成！")


if __name__ == "__main__":
    main()
