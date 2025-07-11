#!/usr/bin/env python3
"""
父子記錄管理工具

用於在 Lark Base 中創建和更新具有父子關係的記錄

使用方法:
1. 創建父子記錄:
python parent_child_record_creator.py --url "https://example.larksuite.com/wiki/xxxxx" \
    --create --parent-story "Story-ARD-00010" --parent-feature "用戶管理" \
    --child-story "Story-ARD-00011" --child-feature "用戶管理 - 新增用戶"

2. 更新父子關係:
python parent_child_record_creator.py --url "https://example.larksuite.com/wiki/xxxxx" \
    --update --child-story "Story-ARD-00011" --new-parent-story "Story-ARD-00001"

3. 刪除父記錄關係:
python parent_child_record_creator.py --url "https://example.larksuite.com/wiki/xxxxx" \
    --remove-parent --child-story "Story-ARD-00011"

4. 從 JSON 文件讀取並更新:
python parent_child_record_creator.py --url "https://example.larksuite.com/wiki/xxxxx" \
    --update-from-json "creation_result.json" --child-story "Story-ARD-00011" --new-parent-story "Story-ARD-00001"
"""

import argparse
import json
import sys
from typing import Dict, List, Optional, Any
from datetime import datetime
import requests

class ParentChildRecordManager:
    """父子記錄管理器"""
    
    def __init__(self):
        """
        初始化管理器
        
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
        import re
        from urllib.parse import urlparse, parse_qs
        
        result = {"wiki_token": "", "table_id": ""}
        
        try:
            # 解析 URL
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
                        return None
                else:
                    print(f"✗ 獲取 obj token 失敗: {result.get('msg', 'Unknown error')}")
                    return None
            else:
                print(f"✗ HTTP 錯誤: {response.status_code}")
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
                    return []
            else:
                print(f"✗ HTTP 錯誤: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"✗ 獲取欄位異常: {e}")
            return []
    
    def search_record_by_story(self, obj_token: str, table_id: str, story_no: str) -> Optional[Dict[str, Any]]:
        """
        根據 Story.No 搜尋記錄
        
        Args:
            obj_token: Obj Token
            table_id: 表格 ID
            story_no: Story.No 值
            
        Returns:
            找到的記錄或 None
        """
        try:
            url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/search"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            data = {
                "filter": {
                    "conditions": [
                        {
                            "field_name": "Story.No",
                            "operator": "is",
                            "value": [story_no]
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
                    if records:
                        print(f"✓ 找到記錄: {story_no}")
                        return records[0]
                    else:
                        print(f"✗ 未找到記錄: {story_no}")
                        return None
                else:
                    print(f"✗ 搜尋記錄失敗: {result.get('msg', 'Unknown error')}")
                    return None
            else:
                print(f"✗ HTTP 錯誤: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"✗ 搜尋記錄異常: {e}")
            return None
    
    def create_record(self, obj_token: str, table_id: str, fields: Dict[str, Any]) -> Optional[str]:
        """
        創建單筆記錄
        
        Args:
            obj_token: Obj Token
            table_id: 表格 ID
            fields: 欄位資料
            
        Returns:
            新創建的記錄 ID 或 None
        """
        try:
            url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            data = {
                "fields": fields
            }
            
            response = requests.post(url, json=data, headers=headers)
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    record_id = result.get("data", {}).get("record", {}).get("record_id")
                    print(f"✓ 成功創建記錄: {record_id}")
                    return record_id
                else:
                    print(f"✗ 創建記錄失敗: {result.get('msg', 'Unknown error')}")
                    print(f"  詳細錯誤: {result}")
                    return None
            else:
                print(f"✗ HTTP 錯誤: {response.status_code}")
                print(f"  回應內容: {response.text}")
                return None
                
        except Exception as e:
            print(f"✗ 創建記錄異常: {e}")
            return None
    
    def update_record(self, obj_token: str, table_id: str, record_id: str, fields: Dict[str, Any]) -> bool:
        """
        更新記錄
        
        Args:
            obj_token: Obj Token
            table_id: 表格 ID
            record_id: 記錄 ID
            fields: 要更新的欄位資料
            
        Returns:
            是否成功
        """
        try:
            url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/{record_id}"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            data = {
                "fields": fields
            }
            
            response = requests.put(url, json=data, headers=headers)
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    print(f"✓ 成功更新記錄: {record_id}")
                    return True
                else:
                    print(f"✗ 更新記錄失敗: {result.get('msg', 'Unknown error')}")
                    print(f"  詳細錯誤: {result}")
                    return False
            else:
                print(f"✗ HTTP 錯誤: {response.status_code}")
                print(f"  回應內容: {response.text}")
                return False
                
        except Exception as e:
            print(f"✗ 更新記錄異常: {e}")
            return False
    
    def create_parent_child_records(self, obj_token: str, table_id: str, table_fields: List[Dict[str, Any]],
                                  parent_story: str, parent_feature: str, parent_criteria: str,
                                  child_story: str, child_feature: str, child_criteria: str) -> Dict[str, Any]:
        """
        創建父子記錄
        
        Args:
            obj_token: Obj Token
            table_id: 表格 ID
            table_fields: 表格欄位資訊
            parent_story: 父記錄的 Story.No
            parent_feature: 父記錄的 Features
            parent_criteria: 父記錄的 Criteria
            child_story: 子記錄的 Story.No
            child_feature: 子記錄的 Features
            child_criteria: 子記錄的 Criteria
            
        Returns:
            創建結果
        """
        # 建立欄位名稱到 ID 的映射
        field_map = {}
        parent_link_field_id = None
        
        for field in table_fields:
            field_name = field.get("field_name", "")
            field_id = field.get("field_id", "")
            field_map[field_name] = field_id
            
            # 找到父記錄欄位
            if field_name == "父記錄" and field.get("ui_type") == "SingleLink":
                parent_link_field_id = field_id
        
        if not parent_link_field_id:
            print("✗ 未找到父記錄欄位")
            return {"success": False, "error": "未找到父記錄欄位"}
        
        print(f"✓ 找到父記錄欄位 ID: {parent_link_field_id}")
        
        # 步驟 1: 創建父記錄
        print(f"\n--- 創建父記錄: {parent_story} ---")
        parent_fields = {}
        
        # 添加 Story.No
        if "Story.No" in field_map:
            parent_fields["Story.No"] = parent_story
        
        # 添加 Features
        if "Features" in field_map and parent_feature:
            parent_fields["Features"] = parent_feature
        
        # 添加 Criteria
        if "Criteria" in field_map and parent_criteria:
            parent_fields["Criteria"] = parent_criteria
        
        print(f"父記錄欄位資料: {parent_fields}")
        parent_record_id = self.create_record(obj_token, table_id, parent_fields)
        
        if not parent_record_id:
            return {"success": False, "error": "創建父記錄失敗"}
        
        # 步驟 2: 創建子記錄（含父記錄連結）
        print(f"\n--- 創建子記錄: {child_story} ---")
        child_fields = {}
        
        # 添加 Story.No
        if "Story.No" in field_map:
            child_fields["Story.No"] = child_story
        
        # 添加 Features
        if "Features" in field_map and child_feature:
            child_fields["Features"] = child_feature
        
        # 添加 Criteria
        if "Criteria" in field_map and child_criteria:
            child_fields["Criteria"] = child_criteria
        
        # 添加父記錄連結
        child_fields["父記錄"] = [parent_record_id]
        
        print(f"子記錄欄位資料: {child_fields}")
        child_record_id = self.create_record(obj_token, table_id, child_fields)
        
        if not child_record_id:
            return {"success": False, "error": "創建子記錄失敗", "parent_record_id": parent_record_id}
        
        # 創建成功
        result = {
            "success": True,
            "parent_record": {
                "record_id": parent_record_id,
                "story_no": parent_story,
                "features": parent_feature,
                "criteria": parent_criteria
            },
            "child_record": {
                "record_id": child_record_id,
                "story_no": child_story,
                "features": child_feature,
                "criteria": child_criteria,
                "parent_record_id": parent_record_id
            }
        }
        
        print(f"\n✓ 父子記錄創建成功！")
        print(f"  父記錄: {parent_story} (ID: {parent_record_id})")
        print(f"  子記錄: {child_story} (ID: {child_record_id})")
        
        return result
    
    def update_parent_child_relationship(self, obj_token: str, table_id: str, 
                                       child_story: str, new_parent_story: str) -> Dict[str, Any]:
        """
        更新父子關係
        
        Args:
            obj_token: Obj Token
            table_id: 表格 ID
            child_story: 子記錄的 Story.No
            new_parent_story: 新父記錄的 Story.No
            
        Returns:
            更新結果
        """
        print(f"\n--- 更新父子關係 ---")
        print(f"子記錄: {child_story}")
        print(f"新父記錄: {new_parent_story}")
        
        # 步驟 1: 找到子記錄
        child_record = self.search_record_by_story(obj_token, table_id, child_story)
        if not child_record:
            return {"success": False, "error": f"未找到子記錄: {child_story}"}
        
        child_record_id = child_record.get("record_id")
        print(f"✓ 找到子記錄 ID: {child_record_id}")
        
        # 步驟 2: 找到新父記錄
        new_parent_record = self.search_record_by_story(obj_token, table_id, new_parent_story)
        if not new_parent_record:
            return {"success": False, "error": f"未找到新父記錄: {new_parent_story}"}
        
        new_parent_record_id = new_parent_record.get("record_id")
        print(f"✓ 找到新父記錄 ID: {new_parent_record_id}")
        
        # 步驟 3: 更新子記錄的父記錄欄位
        update_fields = {
            "父記錄": [new_parent_record_id]
        }
        
        print(f"更新欄位資料: {update_fields}")
        success = self.update_record(obj_token, table_id, child_record_id, update_fields)
        
        if success:
            result = {
                "success": True,
                "child_record": {
                    "record_id": child_record_id,
                    "story_no": child_story,
                    "old_parent_record_id": child_record.get("fields", {}).get("父記錄", {}).get("link_record_ids", [None])[0],
                    "new_parent_record_id": new_parent_record_id
                },
                "new_parent_record": {
                    "record_id": new_parent_record_id,
                    "story_no": new_parent_story
                }
            }
            
            print(f"\n✓ 父子關係更新成功！")
            print(f"  子記錄: {child_story} (ID: {child_record_id})")
            print(f"  新父記錄: {new_parent_story} (ID: {new_parent_record_id})")
            
            return result
        else:
            return {"success": False, "error": "更新父子關係失敗"}
    
    def remove_parent_relationship(self, obj_token: str, table_id: str, child_story: str) -> Dict[str, Any]:
        """
        刪除父記錄關係，使記錄變成獨立的父記錄
        
        Args:
            obj_token: Obj Token
            table_id: 表格 ID
            child_story: 子記錄的 Story.No
            
        Returns:
            刪除結果
        """
        print(f"\n--- 刪除父記錄關係 ---")
        print(f"目標記錄: {child_story}")
        
        # 步驟 1: 找到目標記錄
        target_record = self.search_record_by_story(obj_token, table_id, child_story)
        if not target_record:
            return {"success": False, "error": f"未找到目標記錄: {child_story}"}
        
        target_record_id = target_record.get("record_id")
        print(f"✓ 找到目標記錄 ID: {target_record_id}")
        
        # 檢查是否有父記錄
        current_parent = target_record.get("fields", {}).get("父記錄", {})
        current_parent_ids = current_parent.get("link_record_ids", [])
        
        if not current_parent_ids:
            print(f"⚠ 記錄 {child_story} 目前沒有父記錄，無需刪除")
            return {
                "success": True,
                "message": f"記錄 {child_story} 已經是獨立記錄",
                "target_record": {
                    "record_id": target_record_id,
                    "story_no": child_story
                }
            }
        
        old_parent_id = current_parent_ids[0]
        print(f"✓ 找到當前父記錄 ID: {old_parent_id}")
        
        # 步驟 2: 清空父記錄欄位
        update_fields = {
            "父記錄": []  # 設置為空陣列
        }
        
        print(f"更新欄位資料: {update_fields}")
        success = self.update_record(obj_token, table_id, target_record_id, update_fields)
        
        if success:
            result = {
                "success": True,
                "target_record": {
                    "record_id": target_record_id,
                    "story_no": child_story,
                    "old_parent_record_id": old_parent_id,
                    "new_parent_record_id": None
                }
            }
            
            print(f"\n✓ 父記錄關係刪除成功！")
            print(f"  記錄: {child_story} (ID: {target_record_id})")
            print(f"  原父記錄 ID: {old_parent_id}")
            print(f"  現在是獨立記錄")
            
            return result
        else:
            return {"success": False, "error": "刪除父記錄關係失敗"}
    
    def load_json_file(self, filename: str) -> Optional[Dict[str, Any]]:
        """
        載入 JSON 檔案
        
        Args:
            filename: 檔案名稱
            
        Returns:
            JSON 資料或 None
        """
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"✓ 成功載入 JSON 檔案: {filename}")
            return data
        except Exception as e:
            print(f"✗ 載入 JSON 檔案失敗: {e}")
            return None
    
    def save_result(self, result: Dict[str, Any], filename: str):
        """
        保存結果到檔案
        
        Args:
            result: 結果資料
            filename: 檔案名稱
        """
        try:
            import os
            os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else '.', exist_ok=True)
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            print(f"✓ 結果已保存到: {filename}")
            
        except Exception as e:
            print(f"✗ 保存檔案失敗: {e}")


def main():
    parser = argparse.ArgumentParser(description="父子記錄管理工具")
    parser.add_argument("--url", required=True, help="Lark Base 網址")
    
    # 操作類型
    operation_group = parser.add_mutually_exclusive_group(required=True)
    operation_group.add_argument("--create", action="store_true", help="創建父子記錄")
    operation_group.add_argument("--update", action="store_true", help="更新父子關係")
    operation_group.add_argument("--remove-parent", action="store_true", help="刪除父記錄關係")
    operation_group.add_argument("--update-from-json", help="從 JSON 檔案載入資料並更新")
    
    # 創建記錄參數
    parser.add_argument("--parent-story", help="父記錄的 Story.No")
    parser.add_argument("--parent-feature", help="父記錄的 Features")
    parser.add_argument("--parent-criteria", default="", help="父記錄的 Criteria")
    parser.add_argument("--child-story", help="子記錄的 Story.No")
    parser.add_argument("--child-feature", help="子記錄的 Features")
    parser.add_argument("--child-criteria", default="", help="子記錄的 Criteria")
    
    # 更新關係參數
    parser.add_argument("--new-parent-story", help="新父記錄的 Story.No")
    
    # 輸出參數
    parser.add_argument("--output", help="輸出檔案名稱")
    
    args = parser.parse_args()
    
    # 創建工具
    manager = ParentChildRecordManager()
    
    # 獲取 access token
    if not manager._get_access_token():
        sys.exit(1)
    
    # 解析 URL
    url_info = manager.parse_lark_url(args.url)
    if not url_info["wiki_token"] or not url_info["table_id"]:
        print("✗ 錯誤: 無法從 URL 中解析出必要資訊")
        sys.exit(1)
    
    # 獲取 obj_token
    obj_token = manager.get_obj_token(url_info["wiki_token"])
    if not obj_token:
        print("✗ 錯誤: 無法獲取 obj token")
        sys.exit(1)
    
    # 獲取表格欄位資訊
    table_fields = manager.get_table_fields(obj_token, url_info["table_id"])
    if not table_fields:
        print("✗ 錯誤: 無法獲取表格欄位資訊")
        sys.exit(1)
    
    # 執行操作
    if args.create:
        # 創建父子記錄
        if not args.parent_story or not args.child_story:
            print("✗ 錯誤: 創建記錄需要 --parent-story 和 --child-story 參數")
            sys.exit(1)
        
        result = manager.create_parent_child_records(
            obj_token, url_info["table_id"], table_fields,
            args.parent_story, args.parent_feature or "", args.parent_criteria,
            args.child_story, args.child_feature or "", args.child_criteria
        )
        
    elif args.update:
        # 更新父子關係
        if not args.child_story or not args.new_parent_story:
            print("✗ 錯誤: 更新關係需要 --child-story 和 --new-parent-story 參數")
            sys.exit(1)
        
        result = manager.update_parent_child_relationship(
            obj_token, url_info["table_id"], args.child_story, args.new_parent_story
        )
        
    elif args.remove_parent:
        # 刪除父記錄關係
        if not args.child_story:
            print("✗ 錯誤: 刪除父記錄關係需要 --child-story 參數")
            sys.exit(1)
        
        result = manager.remove_parent_relationship(
            obj_token, url_info["table_id"], args.child_story
        )
        
    elif args.update_from_json:
        # 從 JSON 檔案載入並更新
        json_data = manager.load_json_file(args.update_from_json)
        if not json_data:
            sys.exit(1)
        
        if not args.child_story or not args.new_parent_story:
            print("✗ 錯誤: 更新關係需要 --child-story 和 --new-parent-story 參數")
            sys.exit(1)
        
        print(f"原始 JSON 資料: {json_data}")
        
        result = manager.update_parent_child_relationship(
            obj_token, url_info["table_id"], args.child_story, args.new_parent_story
        )
        
        # 將原始 JSON 資料加入結果
        if result["success"]:
            result["original_json"] = json_data
    
    # 保存結果
    output_file = args.output
    if not output_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if args.create:
            output_file = f"study_tools/parent_child_creation_{timestamp}.json"
        elif args.remove_parent:
            output_file = f"study_tools/parent_child_remove_{timestamp}.json"
        else:
            output_file = f"study_tools/parent_child_update_{timestamp}.json"
    
    manager.save_result(result, output_file)
    
    # 顯示結果
    if result["success"]:
        if args.create:
            print(f"\n🎉 父子記錄創建完成！")
        elif args.remove_parent:
            print(f"\n🎉 父記錄關係刪除完成！")
        else:
            print(f"\n🎉 父子關係更新完成！")
        print(f"詳細結果已保存到: {output_file}")
    else:
        print(f"\n❌ 操作失敗: {result.get('error', '未知錯誤')}")
        sys.exit(1)


if __name__ == "__main__":
    main()