#!/usr/bin/env python3
"""
父子記錄關係更新程式

基於 JIRA sub-task 關係自動更新 Lark 資料表中的父子記錄關係

功能:
1. 讀取 Lark 資料表全表記錄，獲取單號並確認父子記錄欄位
2. 從 JIRA 獲取每個單號的 sub-task 關係
3. 比對並確認上層 ticket 是否存在於資料表中
4. 批次更新 Lark 資料表的父子關係

使用方法:
1. 預覽模式 (不實際寫入):
python parent_child_relationship_updater.py --url "https://example.larksuite.com/wiki/xxxxx" \
    --preview --parent-field "Parent Tickets"

2. Dry-run 模式 (模擬執行):
python parent_child_relationship_updater.py --url "https://example.larksuite.com/wiki/xxxxx" \
    --dry-run --parent-field "父記錄"

3. 實際執行:
python parent_child_relationship_updater.py --url "https://example.larksuite.com/wiki/xxxxx" \
    --parent-field "Parent Tickets" --execute
"""

import argparse
import json
import sys
import yaml
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from pathlib import Path
import requests
import re
from urllib.parse import urlparse, parse_qs

# 添加專案根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from jira_client import JiraClient
import sqlite3


class ParentChildRelationshipUpdater:
    """父子記錄關係更新器"""
    
    def __init__(self, config_path: Optional[str] = None):
        """初始化更新器"""
        self.config = self._load_config(config_path)
        
        # Lark 配置
        lark_config = self.config.get('lark_base', {})
        self.app_id = lark_config.get('app_id')
        self.app_secret = lark_config.get('app_secret')
        self.access_token = None
        self.base_url = "https://open.larksuite.com/open-apis"
        
        # JIRA 配置
        jira_config = self.config.get('jira', {})
        self.jira_client = JiraClient(jira_config)
        
        # 統計資訊
        self.stats = {
            'total_records': 0,
            'valid_tickets': 0,
            'tickets_with_parents': 0,
            'parent_tickets_found': 0,
            'relationships_to_update': 0,
            'successful_updates': 0,
            'failed_updates': 0
        }
        
    def _load_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """載入配置檔案"""
        if not config_path:
            config_path = project_root / "config.yaml"
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"✗ 載入配置檔案失敗: {e}")
            sys.exit(1)
    
    def _get_access_token(self) -> bool:
        """獲取 Lark 訪問令牌"""
        try:
            url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
            headers = {"Content-Type": "application/json"}
            data = {
                "app_id": self.app_id,
                "app_secret": self.app_secret
            }
            
            response = requests.post(url, json=data, headers=headers)
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    self.access_token = result["tenant_access_token"]
                    print(f"✓ 成功獲取 Lark access token")
                    return True
            
            print(f"✗ 獲取 access token 失敗")
            return False
                
        except Exception as e:
            print(f"✗ 獲取 access token 異常: {e}")
            return False
    
    def parse_lark_url(self, url: str) -> Dict[str, str]:
        """解析 Lark Base 網址"""
        result = {"wiki_token": "", "table_id": ""}
        
        try:
            parsed_url = urlparse(url)
            
            # 提取 wiki token
            path_match = re.search(r'/(wiki|base)/([a-zA-Z0-9]+)', parsed_url.path)
            if path_match:
                result["wiki_token"] = path_match.group(2)
                print(f"✓ 提取 wiki token: {result['wiki_token']}")
            
            # 提取 table ID
            query_params = parse_qs(parsed_url.query)
            if 'table' in query_params:
                result["table_id"] = query_params['table'][0]
            elif 'tbl' in query_params:
                result["table_id"] = query_params['tbl'][0]
            
            if not result["table_id"]:
                table_match = re.search(r'/(tbl[a-zA-Z0-9]+)', parsed_url.path)
                if table_match:
                    result["table_id"] = table_match.group(1)
            
            if not result["table_id"] and parsed_url.fragment:
                fragment_match = re.search(r'(tbl[a-zA-Z0-9]+)', parsed_url.fragment)
                if fragment_match:
                    result["table_id"] = fragment_match.group(1)
            
            if result["table_id"]:
                print(f"✓ 提取 table ID: {result['table_id']}")
                
        except Exception as e:
            print(f"✗ 解析 URL 失敗: {e}")
            
        return result
    
    def get_obj_token(self, wiki_token: str) -> Optional[str]:
        """從 Wiki Token 獲取 Obj Token"""
        try:
            url = f"{self.base_url}/wiki/v2/spaces/get_node?token={wiki_token}"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    obj_token = result.get("data", {}).get("node", {}).get("obj_token")
                    if obj_token:
                        print(f"✓ 成功獲取 obj token: {obj_token}")
                        return obj_token
                        
            print(f"✗ 獲取 obj token 失敗")
            return None
                
        except Exception as e:
            print(f"✗ 獲取 obj token 異常: {e}")
            return None
    
    def get_all_lark_records(self, obj_token: str, table_id: str, 
                           field_names: List[str] = None) -> List[Dict[str, Any]]:
        """獲取 Lark 資料表所有記錄"""
        if field_names:
            print(f"\n--- 步驟 1: 讀取 Lark 資料表全表記錄 (僅取得欄位: {', '.join(field_names)}) ---")
        else:
            print(f"\n--- 步驟 1: 讀取 Lark 資料表全表記錄 ---")
        
        try:
            all_records = []
            page_token = None
            
            while True:
                url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records"
                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                }
                
                params = {"page_size": 500}
                if page_token:
                    params["page_token"] = page_token
                
                # 如果指定了欄位，只取得這些欄位 (提升效能)
                if field_names:
                    params["fields"] = field_names
                
                response = requests.get(url, headers=headers, params=params)
                if response.status_code == 200:
                    result = response.json()
                    if result.get("code") == 0:
                        data = result.get("data", {})
                        records = data.get("items", [])
                        all_records.extend(records)
                        
                        if data.get("has_more", False):
                            page_token = data.get("page_token")
                            print(f"  已獲取 {len(all_records)} 筆記錄，繼續...")
                        else:
                            break
                    else:
                        print(f"✗ 獲取記錄失敗: {result.get('msg', 'Unknown error')}")
                        break
                else:
                    print(f"✗ HTTP 錯誤: {response.status_code}")
                    break
            
            self.stats['total_records'] = len(all_records)
            print(f"✓ 總共獲取 {len(all_records)} 筆記錄")
            return all_records
            
        except Exception as e:
            print(f"✗ 獲取記錄異常: {e}")
            return []
    
    def get_table_fields(self, obj_token: str, table_id: str) -> List[Dict[str, Any]]:
        """獲取表格欄位資訊"""
        try:
            url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/fields"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    fields = result.get("data", {}).get("items", [])
                    print(f"✓ 成功獲取 {len(fields)} 個欄位")
                    return fields
                else:
                    print(f"✗ 獲取欄位失敗: {result.get('msg', 'Unknown error')}")
                    return []
                    
            print(f"✗ 獲取欄位失敗: HTTP {response.status_code}")
            return []
                
        except Exception as e:
            print(f"✗ 獲取欄位異常: {e}")
            return []
    
    def get_primary_field_info(self, table_fields: List[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
        """獲取第一欄(主要欄位)的名稱和ID"""
        for field in table_fields:
            if field.get("is_primary", False):
                field_name = field.get("field_name", "")
                field_id = field.get("field_id", "")
                print(f"✓ 找到第一欄(主要欄位): {field_name} (ID: {field_id})")
                return field_name, field_id
        
        print("✗ 未找到主要欄位")
        return None
    
    def get_cache_db_path(self, table_id: str) -> str:
        """獲取指定表格的 processing_log cache 檔案路徑"""
        data_dir = project_root / "data"
        cache_file = data_dir / f"processing_log_{table_id}.db"
        return str(cache_file)
    
    def get_tickets_from_cache(self, table_id: str) -> Dict[str, str]:
        """從 processing_log cache 中讀取票據號碼和記錄ID對應關係"""
        print(f"\n--- 步驟 1: 從 Cache 讀取票據記錄 ---")
        
        cache_db_path = self.get_cache_db_path(table_id)
        if not Path(cache_db_path).exists():
            print(f"✗ Cache 檔案不存在: {cache_db_path}")
            return {}
        
        print(f"✓ 使用 Cache 檔案: {cache_db_path}")
        
        try:
            ticket_to_record = {}
            
            with sqlite3.connect(cache_db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # 查詢所有有 lark_record_id 的記錄
                cursor.execute("""
                    SELECT issue_key, lark_record_id 
                    FROM processing_log 
                    WHERE lark_record_id IS NOT NULL 
                    AND lark_record_id != ''
                    ORDER BY issue_key
                """)
                
                records = cursor.fetchall()
                
                for record in records:
                    issue_key = record['issue_key']
                    record_id = record['lark_record_id']
                    ticket_to_record[issue_key] = record_id
                
                print(f"✓ 從 Cache 讀取到 {len(ticket_to_record)} 個票據記錄")
                
                # 顯示前幾個範例
                if ticket_to_record:
                    sample_items = list(ticket_to_record.items())[:5]
                    print(f"  範例記錄:")
                    for ticket, record_id in sample_items:
                        print(f"    {ticket} -> {record_id}")
                    if len(ticket_to_record) > 5:
                        print(f"    ... 還有 {len(ticket_to_record) - 5} 筆")
                
                return ticket_to_record
                
        except Exception as e:
            print(f"✗ 從 Cache 讀取失敗: {e}")
            return {}
    
    def extract_ticket_numbers(self, records: List[Dict[str, Any]], 
                             ticket_field_name: str) -> Tuple[Dict[str, str], Dict[str, Any]]:
        """從記錄中提取票據號碼，同時保存原始票據值用於寫入"""
        ticket_to_record = {}
        record_to_ticket_data = {}  # 保存原始票據資料
        
        for record in records:
            record_id = record.get("record_id")
            fields = record.get("fields", {})
            
            # 提取票據號碼 (支援文字和超連結格式)
            ticket_field = fields.get(ticket_field_name)
            ticket_number = ""
            
            if ticket_field:
                if isinstance(ticket_field, list) and len(ticket_field) > 0:
                    # 處理陣列格式
                    first_item = ticket_field[0]
                    if isinstance(first_item, dict):
                        # 文字格式: {"text": "TCG-123", "type": "text"}
                        # 超連結格式: {"text": "TCG-123", "link": "https://...", "type": "url"}
                        ticket_number = first_item.get("text", "")
                    elif isinstance(first_item, str):
                        ticket_number = first_item
                elif isinstance(ticket_field, str):
                    # 直接字串格式
                    ticket_number = ticket_field
                elif isinstance(ticket_field, dict):
                    # 單一物件格式
                    ticket_number = ticket_field.get("text", "")
                
                if ticket_number:
                    ticket_to_record[ticket_number] = record_id
                    # 保存原始票據資料供寫入時使用
                    record_to_ticket_data[record_id] = ticket_field
        
        self.stats['valid_tickets'] = len(ticket_to_record)
        print(f"✓ 提取到 {len(ticket_to_record)} 個有效票據號碼")
        return ticket_to_record, record_to_ticket_data
    
    def get_jira_parent_relationships(self, ticket_numbers: List[str]) -> Dict[str, str]:
        """從 JIRA 批次獲取票據的父子關係 (每批50筆)"""
        print(f"\n--- 步驟 2: 從 JIRA 批次獲取 {len(ticket_numbers)} 個票據的父子關係 ---")
        
        parent_relationships = {}
        batch_size = 50
        total_batches = (len(ticket_numbers) + batch_size - 1) // batch_size
        
        try:
            for batch_num in range(total_batches):
                start_idx = batch_num * batch_size
                end_idx = min(start_idx + batch_size, len(ticket_numbers))
                batch_tickets = ticket_numbers[start_idx:end_idx]
                
                print(f"  處理批次 {batch_num + 1}/{total_batches} ({len(batch_tickets)} 筆票據)")
                
                # 構建 JQL 查詢這批票據
                jql = f"key in ({','.join(batch_tickets)})"
                
                # 批次獲取票據資訊，只需要 parent 欄位
                issues_data = self.jira_client.search_issues(jql, ['parent'])
                
                # 處理這批票據的父子關係
                for ticket_key, issue_data in issues_data.items():
                    parent_issue = issue_data.get('fields', {}).get('parent')
                    
                    if parent_issue:
                        parent_key = parent_issue.get('key')
                        if parent_key:
                            parent_relationships[ticket_key] = parent_key
                            print(f"    ✓ {ticket_key} -> {parent_key}")
                
                print(f"    批次 {batch_num + 1} 完成，找到 {len([k for k in issues_data.keys() if k in parent_relationships])} 個子票據")
            
            self.stats['tickets_with_parents'] = len(parent_relationships)
            print(f"✓ 找到 {len(parent_relationships)} 個具有父票據關係的 sub-task")
            return parent_relationships
            
        except Exception as e:
            print(f"✗ 批次獲取 JIRA 資料失敗: {e}")
            return {}
    
    def filter_valid_relationships(self, parent_relationships: Dict[str, str], 
                                 ticket_to_record: Dict[str, str]) -> List[Dict[str, str]]:
        """篩選有效的父子關係"""
        print(f"\n--- 步驟 3: 篩選有效的父子關係 ---")
        
        valid_updates = []
        parent_tickets_found = set()
        
        for child_ticket, parent_ticket in parent_relationships.items():
            # 檢查父票據是否存在於資料表中
            if parent_ticket in ticket_to_record:
                child_record_id = ticket_to_record.get(child_ticket)
                parent_record_id = ticket_to_record.get(parent_ticket)
                
                if child_record_id and parent_record_id:
                    valid_updates.append({
                        'child_ticket': child_ticket,
                        'child_record_id': child_record_id,
                        'parent_ticket': parent_ticket,
                        'parent_record_id': parent_record_id
                    })
                    parent_tickets_found.add(parent_ticket)
                    print(f"  ✓ {child_ticket} ({child_record_id}) -> {parent_ticket} ({parent_record_id})")
            else:
                print(f"  ✗ 父票據不存在於資料表: {child_ticket} -> {parent_ticket}")
        
        self.stats['parent_tickets_found'] = len(parent_tickets_found)
        self.stats['relationships_to_update'] = len(valid_updates)
        print(f"✓ 篩選出 {len(valid_updates)} 個有效的父子關係更新")
        return valid_updates
    
    def preview_updates(self, valid_updates: List[Dict[str, str]], parent_field: str):
        """預覽將要執行的更新"""
        print(f"\n=== 更新預覽 (父子關係欄位: {parent_field}) ===")
        
        if not valid_updates:
            print("沒有需要更新的記錄")
            return
        
        print(f"將要更新 {len(valid_updates)} 筆記錄的父子關係:")
        print(f"{'序號':<4} {'子票據':<15} {'父票據':<15} {'子記錄ID':<15} {'父記錄ID':<15}")
        print("-" * 80)
        
        for i, update in enumerate(valid_updates, 1):
            print(f"{i:<4} {update['child_ticket']:<15} {update['parent_ticket']:<15} "
                  f"{update['child_record_id']:<15} {update['parent_record_id']:<15}")
    
    def batch_update_relationships(self, obj_token: str, table_id: str,
                                 valid_updates: List[Dict[str, str]], 
                                 parent_field: str, ticket_field_name: str,
                                 record_to_ticket_data: Dict[str, Any], 
                                 dry_run: bool = False) -> bool:
        """批次更新父子關係"""
        mode_name = "模擬執行" if dry_run else "實際執行"
        print(f"\n--- 步驟 4: {mode_name}更新 Lark 資料表 ---")
        
        if not valid_updates:
            print("沒有需要更新的記錄")
            return True
        
        # 準備批次更新資料
        batch_updates = []
        for update in valid_updates:
            # 準備更新欄位
            update_fields = {parent_field: [update['parent_record_id']]}
            
            # 自動帶入票據號碼 (保持原格式)
            child_record_id = update['child_record_id']
            if child_record_id in record_to_ticket_data:
                original_ticket_data = record_to_ticket_data[child_record_id]
                update_fields[ticket_field_name] = original_ticket_data
                
            batch_updates.append((child_record_id, update_fields))
        
        if dry_run:
            print(f"✓ 模擬執行: 將更新 {len(batch_updates)} 筆記錄")
            print(f"  欄位: {parent_field}")
            print(f"  更新資料範例:")
            for i, (record_id, fields) in enumerate(batch_updates[:3]):
                print(f"    記錄 {record_id}: {fields}")
                if i == 2 and len(batch_updates) > 3:
                    print(f"    ... 還有 {len(batch_updates) - 3} 筆")
            self.stats['successful_updates'] = len(batch_updates)
            return True
        
        # 實際執行批次更新
        try:
            # 分批處理，每批最多 500 筆
            batch_size = 500
            total_batches = (len(batch_updates) + batch_size - 1) // batch_size
            
            for batch_num in range(total_batches):
                start_idx = batch_num * batch_size
                end_idx = min(start_idx + batch_size, len(batch_updates))
                current_batch = batch_updates[start_idx:end_idx]
                
                print(f"  處理批次 {batch_num + 1}/{total_batches} ({len(current_batch)} 筆記錄)")
                
                success = self._execute_batch_update(obj_token, table_id, current_batch)
                if success:
                    self.stats['successful_updates'] += len(current_batch)
                    print(f"    ✓ 批次 {batch_num + 1} 更新成功")
                else:
                    self.stats['failed_updates'] += len(current_batch)
                    print(f"    ✗ 批次 {batch_num + 1} 更新失敗")
                    return False
            
            print(f"✓ 所有批次更新完成，成功更新 {self.stats['successful_updates']} 筆記錄")
            return True
            
        except Exception as e:
            print(f"✗ 批次更新異常: {e}")
            return False
    
    def _execute_batch_update(self, obj_token: str, table_id: str, 
                            batch_updates: List[Tuple[str, Dict]]) -> bool:
        """執行單一批次的更新"""
        try:
            url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/batch_update"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            records = []
            for record_id, fields in batch_updates:
                records.append({
                    "record_id": record_id,
                    "fields": fields
                })
            
            data = {"records": records}
            
            response = requests.post(url, json=data, headers=headers)
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    return True
                else:
                    print(f"    ✗ 批次更新 API 失敗: {result.get('msg', 'Unknown error')}")
                    return False
            else:
                print(f"    ✗ HTTP 錯誤: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"    ✗ 批次更新異常: {e}")
            return False
    
    def validate_parent_field(self, table_fields: List[Dict[str, Any]], 
                            parent_field: str) -> bool:
        """驗證父子關係欄位是否存在且為連結欄位"""
        for field in table_fields:
            if field.get("field_name") == parent_field:
                field_type = field.get("ui_type")
                if field_type in ["SingleLink", "DuplexLink"]:
                    print(f"✓ 找到父子關係欄位: {parent_field} ({field_type})")
                    return True
                else:
                    print(f"✗ 欄位 {parent_field} 不是連結欄位 (類型: {field_type})")
                    return False
        
        print(f"✗ 未找到欄位: {parent_field}")
        print(f"  可用欄位: {', '.join([f.get('field_name', '') for f in table_fields])}")
        return False
    
    def print_statistics(self):
        """列印統計資訊"""
        print(f"\n=== 執行統計 ===")
        print(f"總記錄數: {self.stats['total_records']}")
        print(f"有效票據數: {self.stats['valid_tickets']}")
        print(f"具有父票據的子票據數: {self.stats['tickets_with_parents']}")
        print(f"找到的父票據數: {self.stats['parent_tickets_found']}")
        print(f"需要更新的關係數: {self.stats['relationships_to_update']}")
        print(f"成功更新數: {self.stats['successful_updates']}")
        print(f"失敗更新數: {self.stats['failed_updates']}")
    
    def save_result(self, result: Dict[str, Any], filename: str):
        """保存結果到檔案"""
        try:
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            print(f"✓ 結果已保存到: {filename}")
            
        except Exception as e:
            print(f"✗ 保存檔案失敗: {e}")
    
    def run(self, lark_url: str, parent_field: str, 
            preview: bool = False, dry_run: bool = False, execute: bool = False) -> Dict[str, Any]:
        """執行父子記錄關係更新"""
        start_time = datetime.now()
        
        # 初始化
        print(f"=== 父子記錄關係更新程式 ===")
        print(f"開始時間: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"目標欄位: {parent_field}")
        
        if preview:
            print(f"執行模式: 預覽模式")
        elif dry_run:
            print(f"執行模式: 模擬執行")
        elif execute:
            print(f"執行模式: 實際執行")
        
        # 初始化連接
        if not self._get_access_token():
            return {"success": False, "error": "無法獲取 Lark access token"}
        
        url_info = self.parse_lark_url(lark_url)
        if not url_info["wiki_token"] or not url_info["table_id"]:
            return {"success": False, "error": "無法解析 Lark URL"}
        
        obj_token = self.get_obj_token(url_info["wiki_token"])
        if not obj_token:
            return {"success": False, "error": "無法獲取 obj token"}
        
        # 驗證欄位
        table_fields = self.get_table_fields(obj_token, url_info["table_id"])
        if not self.validate_parent_field(table_fields, parent_field):
            return {"success": False, "error": f"父子關係欄位 {parent_field} 驗證失敗"}
        
        # 自動識別第一欄(票據號碼欄位)
        field_info = self.get_primary_field_info(table_fields)
        if not field_info:
            return {"success": False, "error": "無法識別第一欄(票據號碼欄位)"}
        
        ticket_field_name, ticket_field_id = field_info
        
        try:
            # 步驟 1: 讀取 Lark 記錄 (只取得票據號碼欄位，提升速度)
            lark_records = self.get_all_lark_records(obj_token, url_info["table_id"], [ticket_field_id])
            if not lark_records:
                return {"success": False, "error": "無法獲取 Lark 記錄"}
            
            # 提取票據號碼
            ticket_to_record, record_to_ticket_data = self.extract_ticket_numbers(lark_records, ticket_field_name)
            if not ticket_to_record:
                return {"success": False, "error": "未找到有效的票據號碼"}
            
            # 步驟 2: 從 JIRA 獲取父子關係
            parent_relationships = self.get_jira_parent_relationships(list(ticket_to_record.keys()))
            
            # 步驟 3: 篩選有效關係
            valid_updates = self.filter_valid_relationships(parent_relationships, ticket_to_record)
            
            # 步驟 4: 執行更新
            if preview:
                self.preview_updates(valid_updates, parent_field)
                success = True
            else:
                self.preview_updates(valid_updates, parent_field)
                success = self.batch_update_relationships(
                    obj_token, url_info["table_id"], valid_updates, parent_field, 
                    ticket_field_name, record_to_ticket_data, dry_run
                )
            
            # 統計和結果
            end_time = datetime.now()
            duration = end_time - start_time
            
            self.print_statistics()
            print(f"\n執行完成時間: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"總耗時: {duration.total_seconds():.2f} 秒")
            
            result = {
                "success": success,
                "execution_mode": "preview" if preview else ("dry_run" if dry_run else "execute"),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": duration.total_seconds(),
                "statistics": self.stats,
                "valid_updates": valid_updates if preview or dry_run else [],
                "parent_field": parent_field,
                "lark_url": lark_url
            }
            
            return result
            
        except Exception as e:
            print(f"\n✗ 執行過程中發生錯誤: {e}")
            return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="父子記錄關係更新程式")
    parser.add_argument("--url", required=True, help="Lark Base 網址")
    parser.add_argument("--parent-field", required=True, help="父子關係欄位名稱 (如: Parent Tickets, 父記錄)")
    parser.add_argument("--config", help="配置檔案路徑")
    
    # 執行模式
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--preview", action="store_true", help="預覽模式 (不執行任何更新)")
    mode_group.add_argument("--dry-run", action="store_true", help="模擬執行 (不實際更新)")
    mode_group.add_argument("--execute", action="store_true", help="實際執行更新")
    
    # 其他參數
    parser.add_argument("--output", help="輸出檔案名稱")
    parser.add_argument("--ticket-field", default="Ticket Number", help="票據號碼欄位名稱")
    
    args = parser.parse_args()
    
    # 創建更新器
    updater = ParentChildRelationshipUpdater(args.config)
    
    # 執行更新
    result = updater.run(
        args.url, 
        args.parent_field,
        preview=args.preview,
        dry_run=args.dry_run,
        execute=args.execute
    )
    
    # 保存結果
    output_file = args.output
    if not output_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode = "preview" if args.preview else ("dry_run" if args.dry_run else "execute")
        output_file = f"study_tools/parent_child_update_{mode}_{timestamp}.json"
    
    updater.save_result(result, output_file)
    
    # 顯示結果
    if result["success"]:
        if args.preview:
            print(f"\n🔍 預覽完成！")
        elif args.dry_run:
            print(f"\n🧪 模擬執行完成！")
        else:
            print(f"\n🎉 更新執行完成！")
        print(f"詳細結果已保存到: {output_file}")
    else:
        print(f"\n❌ 執行失敗: {result.get('error', '未知錯誤')}")
        sys.exit(1)


if __name__ == "__main__":
    main()