#!/usr/bin/env python3
"""
Lark 記錄分析工具

獨立的研究工具，用於：
1. 解析 Lark Base 網址，提取 wiki token 和 table ID
2. 獲取指定票據的記錄
3. 格式化顯示完整記錄內容
4. 輸出結果到檔案

使用方法:
python lark_record_analyzer.py --url "https://example.larksuite.com/wiki/xxxxx" --ticket "TP-123"
"""

import argparse
import json
import re
import sys
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse, parse_qs
import requests
from datetime import datetime
import os

class LarkRecordAnalyzer:
    """Lark 記錄分析器"""
    
    def __init__(self):
        """
        初始化分析器
        
        使用 config.yaml 中的 Lark 配置
        """
        # 直接使用 config.yaml 中的配置
        self.app_id = "cli_a8d1077685be102f"
        self.app_secret = "kS35CmIAjP5tVib1LpPIqUkUJjuj3pIt"
        self.access_token = None
        self.base_url = "https://open.larksuite.com/open-apis"
        
    def _get_access_token(self) -> bool:
        """獲取訪問令牌"""
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
                    print(f"✓ 成功獲取 tenant access token")
                    return True
                else:
                    print(f"✗ 獲取 tenant access token 失敗: {result.get('msg', 'Unknown error')}")
                    return False
            else:
                print(f"✗ HTTP 錯誤: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"✗ 獲取 tenant access token 異常: {e}")
            return False
    
    def parse_lark_url(self, url: str) -> Dict[str, str]:
        """
        解析 Lark Base 網址，提取 wiki token 和 table ID
        
        Args:
            url: Lark Base 網址
            
        Returns:
            包含 wiki_token 和 table_id 的字典
        """
        result = {"wiki_token": "", "table_id": ""}
        
        try:
            # 解析 URL
            parsed_url = urlparse(url)
            
            # 提取 wiki token - 通常在路徑中
            # 格式: /wiki/xxx 或 /base/xxx
            path_match = re.search(r'/(wiki|base)/([a-zA-Z0-9]+)', parsed_url.path)
            if path_match:
                result["wiki_token"] = path_match.group(2)
                print(f"✓ 提取 wiki token: {result['wiki_token']}")
            
            # 提取 table ID - 可能在查詢參數中或路徑中
            # 從查詢參數中提取
            query_params = parse_qs(parsed_url.query)
            if 'table' in query_params:
                result["table_id"] = query_params['table'][0]
            elif 'tbl' in query_params:
                result["table_id"] = query_params['tbl'][0]
            
            # 從路徑中提取 table ID
            if not result["table_id"]:
                table_match = re.search(r'/(tbl[a-zA-Z0-9]+)', parsed_url.path)
                if table_match:
                    result["table_id"] = table_match.group(1)
            
            # 從 fragment 中提取
            if not result["table_id"] and parsed_url.fragment:
                fragment_match = re.search(r'(tbl[a-zA-Z0-9]+)', parsed_url.fragment)
                if fragment_match:
                    result["table_id"] = fragment_match.group(1)
            
            if result["table_id"]:
                print(f"✓ 提取 table ID: {result['table_id']}")
            else:
                print("⚠ 未能從 URL 中提取 table ID")
                
        except Exception as e:
            print(f"✗ 解析 URL 失敗: {e}")
            
        return result
    
    def get_obj_token(self, wiki_token: str) -> Optional[str]:
        """
        從 Wiki Token 獲取 Obj Token
        
        Args:
            wiki_token: Wiki Token
            
        Returns:
            Obj Token 或 None
        """
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
                    else:
                        print(f"✗ 無法從回應中提取 obj token")
                        print(f"  回應資料: {result}")
                        return None
                else:
                    print(f"✗ 獲取 obj token 失敗: {result.get('msg', 'Unknown error')}")
                    print(f"  詳細錯誤: {result}")
                    return None
            else:
                print(f"✗ HTTP 錯誤: {response.status_code}")
                print(f"  請求 URL: {url}")
                print(f"  回應內容: {response.text}")
                return None
                
        except Exception as e:
            print(f"✗ 獲取 obj token 異常: {e}")
            return None
    
    def get_table_fields(self, obj_token: str, table_id: str) -> List[Dict[str, Any]]:
        """
        獲取表格欄位資訊
        
        Args:
            obj_token: Obj Token
            table_id: 表格 ID
            
        Returns:
            欄位資訊列表
        """
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
                    print(f"  詳細錯誤: {result}")
                    return []
            else:
                print(f"✗ HTTP 錯誤: {response.status_code}")
                print(f"  請求 URL: {url}")
                print(f"  回應內容: {response.text}")
                return []
                
        except Exception as e:
            print(f"✗ 獲取欄位異常: {e}")
            return []
    
    def search_records_by_ticket(self, obj_token: str, table_id: str, 
                                ticket_value: str, ticket_field_name: str = None) -> List[Dict[str, Any]]:
        """
        根據票據欄位搜尋記錄
        
        Args:
            obj_token: Obj Token
            table_id: 表格 ID
            ticket_value: 票據值
            ticket_field_name: 票據欄位名稱（可選，預設使用第一欄）
            
        Returns:
            匹配的記錄列表
        """
        try:
            # 如果沒有指定票據欄位，先獲取欄位資訊找到主要欄位
            if not ticket_field_name:
                fields = self.get_table_fields(obj_token, table_id)
                if fields:
                    # 找到主要欄位（is_primary: true）
                    primary_field = next((f for f in fields if f.get('is_primary', False)), None)
                    if primary_field:
                        ticket_field_name = primary_field.get('field_name', '')
                        print(f"✓ 使用主要欄位: {ticket_field_name}")
                    else:
                        # 如果沒有主要欄位，使用第一個欄位
                        first_field = fields[0] if fields else None
                        if first_field:
                            ticket_field_name = first_field.get('field_name', '')
                            print(f"✓ 使用第一欄位: {ticket_field_name}")
                        else:
                            print("✗ 無法找到可用欄位")
                            return []
                else:
                    print("✗ 無法獲取欄位資訊")
                    return []
            
            # 搜尋記錄
            url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/search"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            # 構建搜尋條件
            data = {
                "filter": {
                    "conditions": [
                        {
                            "field_name": ticket_field_name,
                            "operator": "is",
                            "value": [ticket_value]
                        }
                    ],
                    "conjunction": "and"
                }
            }
            
            response = requests.post(url, json=data, headers=headers)
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    records = result.get("data", {}).get("items", [])
                    print(f"✓ 找到 {len(records)} 筆記錄")
                    return records
                else:
                    print(f"✗ 搜尋記錄失敗: {result.get('msg', 'Unknown error')}")
                    print(f"  詳細錯誤: {result}")
                    return []
            else:
                print(f"✗ HTTP 錯誤: {response.status_code}")
                print(f"  請求 URL: {url}")
                print(f"  請求資料: {data}")
                print(f"  回應內容: {response.text}")
                return []
                
        except Exception as e:
            print(f"✗ 搜尋記錄異常: {e}")
            return []
    
    def get_all_records(self, obj_token: str, table_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        獲取所有記錄
        
        Args:
            obj_token: Obj Token
            table_id: 表格 ID
            limit: 每次請求的記錄數限制
            
        Returns:
            所有記錄列表
        """
        try:
            all_records = []
            page_token = None
            
            while True:
                url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records"
                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                }
                
                params = {"page_size": limit}
                if page_token:
                    params["page_token"] = page_token
                
                response = requests.get(url, headers=headers, params=params)
                if response.status_code == 200:
                    result = response.json()
                    if result.get("code") == 0:
                        data = result.get("data", {})
                        records = data.get("items", [])
                        all_records.extend(records)
                        
                        # 檢查是否還有更多記錄
                        if data.get("has_more", False):
                            page_token = data.get("page_token")
                            print(f"✓ 已獲取 {len(all_records)} 筆記錄，繼續獲取...")
                        else:
                            break
                    else:
                        print(f"✗ 獲取記錄失敗: {result.get('msg', 'Unknown error')}")
                        break
                else:
                    print(f"✗ HTTP 錯誤: {response.status_code}")
                    break
            
            print(f"✓ 總共獲取 {len(all_records)} 筆記錄")
            return all_records
            
        except Exception as e:
            print(f"✗ 獲取記錄異常: {e}")
            return []
    
    def format_record(self, record: Dict[str, Any], fields: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        格式化記錄顯示
        
        Args:
            record: 記錄資料
            fields: 欄位資訊（可選）
            
        Returns:
            格式化後的記錄
        """
        formatted = {
            "record_id": record.get("record_id", ""),
            "created_time": record.get("created_time", ""),
            "last_modified_time": record.get("last_modified_time", ""),
            "fields": {}
        }
        
        # 創建欄位名稱映射
        field_name_map = {}
        if fields:
            for field in fields:
                field_name_map[field.get("field_id", "")] = field.get("field_name", "")
        
        # 格式化欄位
        record_fields = record.get("fields", {})
        for field_id, field_value in record_fields.items():
            field_name = field_name_map.get(field_id, field_id)
            formatted["fields"][field_name] = field_value
        
        return formatted
    
    def save_to_file(self, data: Any, filename: str):
        """
        保存資料到檔案
        
        Args:
            data: 要保存的資料
            filename: 檔案名稱
        """
        try:
            # 確保目錄存在
            os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else '.', exist_ok=True)
            
            # 保存為 JSON 格式
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"✓ 資料已保存到: {filename}")
            
        except Exception as e:
            print(f"✗ 保存檔案失敗: {e}")
    
    def analyze_records(self, wiki_token: str, table_id: str, 
                       ticket_values: List[str] = None, 
                       output_file: str = None) -> Dict[str, Any]:
        """
        分析記錄
        
        Args:
            wiki_token: Wiki Token
            table_id: 表格 ID
            ticket_values: 要搜尋的票據值列表（可選）
            output_file: 輸出檔案名稱（可選）
            
        Returns:
            分析結果
        """
        # 先獲取 obj_token
        obj_token = self.get_obj_token(wiki_token)
        if not obj_token:
            print("✗ 無法獲取 obj token")
            return {
                "timestamp": datetime.now().isoformat(),
                "wiki_token": wiki_token,
                "table_id": table_id,
                "error": "無法獲取 obj token",
                "fields": [],
                "records": []
            }
        
        # 獲取欄位資訊
        fields = self.get_table_fields(obj_token, table_id)
        
        analysis_result = {
            "timestamp": datetime.now().isoformat(),
            "wiki_token": wiki_token,
            "table_id": table_id,
            "fields": fields,
            "records": []
        }
        
        if ticket_values:
            # 搜尋特定票據
            for ticket_value in ticket_values:
                print(f"\n--- 搜尋票據: {ticket_value} ---")
                records = self.search_records_by_ticket(obj_token, table_id, ticket_value)
                
                for record in records:
                    formatted_record = self.format_record(record, fields)
                    analysis_result["records"].append(formatted_record)
                    
                    print(f"\n記錄 ID: {formatted_record['record_id']}")
                    print(f"創建時間: {formatted_record['created_time']}")
                    print(f"修改時間: {formatted_record['last_modified_time']}")
                    print("欄位內容:")
                    for field_name, field_value in formatted_record["fields"].items():
                        print(f"  {field_name}: {field_value}")
        else:
            # 獲取所有記錄
            print(f"\n--- 獲取所有記錄 ---")
            records = self.get_all_records(obj_token, table_id)
            
            for record in records:
                formatted_record = self.format_record(record, fields)
                analysis_result["records"].append(formatted_record)
        
        # 輸出統計資訊
        print(f"\n=== 分析結果 ===")
        print(f"表格 ID: {table_id}")
        print(f"欄位數量: {len(fields)}")
        print(f"記錄數量: {len(analysis_result['records'])}")
        
        # 保存到檔案
        if output_file:
            self.save_to_file(analysis_result, output_file)
        
        return analysis_result


def main():
    parser = argparse.ArgumentParser(description="Lark 記錄分析工具")
    parser.add_argument("--url", required=True, help="Lark Base 網址")
    parser.add_argument("--ticket", nargs="*", help="要搜尋的票據值（多個值用空格分隔）")
    parser.add_argument("--all", action="store_true", help="獲取所有記錄")
    parser.add_argument("--output", help="輸出檔案名稱")
    
    args = parser.parse_args()
    
    # 創建分析器（使用 config.yaml 中的配置）
    analyzer = LarkRecordAnalyzer()
    
    # 獲取 access token
    if not analyzer._get_access_token():
        sys.exit(1)
    
    # 解析 URL
    url_info = analyzer.parse_lark_url(args.url)
    if not url_info["wiki_token"] or not url_info["table_id"]:
        print("✗ 錯誤: 無法從 URL 中解析出必要資訊")
        print("  請檢查 URL 格式是否正確")
        sys.exit(1)
    
    # 分析記錄
    ticket_values = None
    if args.ticket:
        ticket_values = args.ticket
    elif not args.all:
        print("⚠ 未指定 --ticket 或 --all，將獲取所有記錄")
        ticket_values = None
    
    # 生成輸出檔案名稱
    output_file = args.output
    if not output_file and (args.ticket or args.all):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if args.ticket:
            ticket_str = "_".join(args.ticket)
            output_file = f"study_tools/lark_analysis_{ticket_str}_{timestamp}.json"
        else:
            output_file = f"study_tools/lark_analysis_all_{timestamp}.json"
    
    # 執行分析
    try:
        analyzer.analyze_records(
            url_info["wiki_token"],
            url_info["table_id"],
            ticket_values,
            output_file
        )
        print("\n✓ 分析完成")
    except Exception as e:
        print(f"\n✗ 分析失敗: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()