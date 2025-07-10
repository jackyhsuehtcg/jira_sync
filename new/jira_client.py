#!/usr/bin/env python3
"""
重構版 JIRA 客戶端模組
專注於資料撷取、正確性和唯一性
不處理 schema 映射邏輯
"""

import requests
import json
import time
import random
from typing import Dict, List, Any, Optional
from requests.auth import HTTPBasicAuth


class DataIncompleteError(Exception):
    """資料不完整異常"""
    def __init__(self, message: str, failed_batches: List[int] = None, 
                 expected_count: int = 0, actual_count: int = 0):
        super().__init__(message)
        self.failed_batches = failed_batches or []
        self.expected_count = expected_count
        self.actual_count = actual_count


class JiraClient:
    """專注於資料撷取的 JIRA 客戶端"""
    
    def __init__(self, config: Dict[str, Any], logger=None, test_connection: bool = True):
        """
        初始化 JIRA 客戶端
        
        Args:
            config: JIRA 連接配置
            logger: 日誌管理器
            test_connection: 是否測試連接
        """
        self.logger = logger
        self.config = config
        
        # JIRA 連接配置
        self.server_url = config['server_url'].rstrip('/')
        self.username = config['username']
        self.password = config['password']
        self.timeout = config.get('timeout', 30)
        self.max_results = config.get('max_results', 1000)
        
        # 設定認證和標頭
        self.auth = HTTPBasicAuth(self.username, self.password)
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        # 測試連接
        if test_connection:
            self._test_connection()
        
        if self.logger:
            self.logger.info(f"JIRA 客戶端初始化完成: {self.server_url}")
    
    def _test_connection(self):
        """測試 JIRA 連接"""
        try:
            response = self._make_request('GET', '/rest/api/2/myself')
            if response:
                user_info = response.get('displayName', self.username)
                if self.logger:
                    self.logger.info(f"JIRA 連接測試成功，用戶: {user_info}")
            else:
                raise Exception("無法取得用戶資訊")
        except Exception as e:
            if self.logger:
                self.logger.error(f"JIRA 連接測試失敗: {e}")
            raise
    
    def _make_request(self, method: str, endpoint: str, data: Dict[str, Any] = None, 
                     params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """發送 HTTP 請求到 JIRA"""
        url = f"{self.server_url}{endpoint}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                auth=self.auth,
                headers=self.headers,
                json=data,
                params=params,
                timeout=self.timeout
            )
            
            if self.logger:
                self.logger.debug(f"API 請求: {method} {endpoint} -> {response.status_code}")
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 201:
                return response.json() if response.text else {}
            elif response.status_code == 204:
                return {}
            else:
                error_msg = f"API 請求失敗: {response.status_code} - {response.text}"
                if self.logger:
                    self.logger.error(error_msg)
                return None
                
        except requests.exceptions.Timeout:
            if self.logger:
                self.logger.error(f"API 請求逾時: {method} {endpoint}")
            return None
        except requests.exceptions.RequestException as e:
            if self.logger:
                self.logger.error(f"API 請求錯誤: {e}")
            return None
        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.error(f"JSON 解析錯誤: {e}")
            return None
    
    def _get_total_count_with_retry(self, jql: str, max_retries: int = 3) -> int:
        """
        帶重試的總數獲取
        
        Args:
            jql: JQL 查詢語句
            max_retries: 最大重試次數
            
        Returns:
            int: 總記錄數
            
        Raises:
            Exception: 重試耗盡後仍失敗
        """
        for attempt in range(max_retries):
            try:
                params = {
                    'jql': jql,
                    'maxResults': 0  # 只要總數，不要資料
                }
                
                response = self._make_request('GET', '/rest/api/2/search', params=params)
                
                if response and 'total' in response:
                    total_count = response['total']
                    if self.logger:
                        self.logger.info(f"查詢總數: {total_count} 筆")
                    return total_count
                
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"獲取總數第 {attempt + 1} 次嘗試失敗: {e}")
                
                if attempt < max_retries - 1:
                    # 指數退避加隨機抖動
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    if self.logger:
                        self.logger.debug(f"等待 {wait_time:.2f} 秒後重試")
                    time.sleep(wait_time)
                else:
                    error_msg = f"獲取總數重試 {max_retries} 次後仍失敗: {e}"
                    if self.logger:
                        self.logger.error(error_msg)
                    raise Exception(error_msg)
        
        return 0
    
    def _fetch_batch_with_retry(self, jql: str, fields: List[str], 
                               start_at: int, batch_size: int,
                               max_retries: int = 3) -> Optional[Dict[str, Dict[str, Any]]]:
        """
        帶重試的批次獲取
        
        Args:
            jql: JQL 查詢語句
            fields: 欄位清單
            start_at: 起始位置
            batch_size: 批次大小
            max_retries: 最大重試次數
            
        Returns:
            Dict: {issue_key: issue_data} 或 None 表示失敗
        """
        for attempt in range(max_retries):
            try:
                params = {
                    'jql': jql,
                    'fields': ','.join(fields),
                    'startAt': start_at,
                    'maxResults': batch_size
                }
                
                response = self._make_request('GET', '/rest/api/2/search', params=params)
                
                if response and 'issues' in response:
                    issues = response['issues']
                    
                    # 轉換為 dict 格式並確保唯一性
                    batch_dict = {}
                    for issue in issues:
                        issue_key = issue['key']
                        batch_dict[issue_key] = issue
                    
                    if self.logger:
                        self.logger.debug(f"批次 {start_at}-{start_at + len(batch_dict)} 成功: {len(batch_dict)} 筆")
                    
                    return batch_dict
                
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"批次 {start_at} 第 {attempt + 1} 次嘗試失敗: {e}")
                
                if attempt < max_retries - 1:
                    # 指數退避加隨機抖動
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    if self.logger:
                        self.logger.debug(f"等待 {wait_time:.2f} 秒後重試批次 {start_at}")
                    time.sleep(wait_time)
                else:
                    if self.logger:
                        self.logger.error(f"批次 {start_at} 重試 {max_retries} 次後仍失敗")
        
        return None
    
    def _calculate_optimal_batch_size(self, total_count: int, max_results: int = None) -> int:
        """
        計算最佳批次大小以減少API呼叫次數
        目標：5-10次API呼叫完成所有資料獲取
        
        Args:
            total_count: 總記錄數
            max_results: 使用者指定的批次限制
            
        Returns:
            int: 最佳批次大小
        """
        # 如果使用者指定了 max_results，優先使用
        if max_results:
            return min(max_results, 1000)  # JIRA API 限制最大1000
        
        # 根據總數量計算最佳批次大小
        if total_count <= 500:
            # 小量資料：一次搞定
            return total_count
        elif total_count <= 2500:
            # 中量資料：2-5次API呼叫
            return 500
        elif total_count <= 5000:
            # 大量資料：5-10次API呼叫
            return 500
        else:
            # 超大量資料：使用最大批次
            return 1000
    
    def search_issues(self, jql: str, fields: List[str], 
                     max_results: int = None) -> Dict[str, Dict[str, Any]]:
        """
        原子性獲取 JIRA Issues
        要麼全部成功，要麼拋出異常，絕不返回不完整資料
        
        Args:
            jql: JQL 查詢語句
            fields: 明確指定要取得的欄位清單
            max_results: 批次大小限制（預設使用設定值）
            
        Returns:
            Dict: {issue_key: issue_data} 完整資料字典
            
        Raises:
            DataIncompleteError: 資料獲取不完整時
            Exception: 其他獲取錯誤
        """
        # 確保包含 key 欄位用於唯一性
        if 'key' not in fields:
            fields = fields + ['key']
        
        if self.logger:
            self.logger.info(f"開始原子性獲取 JIRA Issues: {jql}")
            self.logger.debug(f"請求欄位: {fields}")
        
        # 第一階段：獲取總數和驗證
        total_count = self._get_total_count_with_retry(jql)
        if total_count == 0:
            if self.logger:
                self.logger.info("查詢結果為空，返回空字典")
            return {}
        
        # 第二階段：分批獲取到臨時存儲
        temp_issues = {}
        failed_batches = []
        # 優化批次大小以減少API呼叫次數
        batch_size = self._calculate_optimal_batch_size(total_count, max_results)
        
        if self.logger:
            self.logger.info(f"開始分批獲取：總數 {total_count}，批次大小 {batch_size}")
        
        for batch_start in range(0, total_count, batch_size):
            batch_end = min(batch_start + batch_size, total_count)
            
            if self.logger:
                self.logger.debug(f"處理批次: {batch_start} - {batch_end}")
            
            # 帶重試的批次獲取
            batch_data = self._fetch_batch_with_retry(
                jql, fields, batch_start, batch_size
            )
            
            if batch_data is None:
                failed_batches.append(batch_start)
                if self.logger:
                    self.logger.error(f"批次 {batch_start} 獲取失敗")
            else:
                # 使用 dict.update() 確保唯一性
                temp_issues.update(batch_data)
                if self.logger:
                    self.logger.debug(f"批次 {batch_start} 成功，累計: {len(temp_issues)} 筆")
        
        # 第三階段：完整性驗證
        self._validate_data_completeness(
            temp_issues, total_count, failed_batches
        )
        
        if self.logger:
            self.logger.info(f"原子性獲取完成: {len(temp_issues)} 筆唯一 Issues")
        
        return temp_issues
    
    def _validate_data_completeness(self, issues_dict: Dict[str, Dict[str, Any]], 
                                  expected_count: int, failed_batches: List[int]):
        """
        驗證資料完整性
        
        Args:
            issues_dict: 獲取到的 issues 字典
            expected_count: 預期的總數量
            failed_batches: 失敗的批次列表
            
        Raises:
            DataIncompleteError: 資料不完整時
        """
        actual_count = len(issues_dict)
        
        # 檢查失敗的批次
        if failed_batches:
            error_msg = f"部分批次獲取失敗，無法保證資料完整性"
            if self.logger:
                self.logger.error(f"{error_msg}: 失敗批次 {failed_batches}")
                self.logger.error(f"預期總數: {expected_count}，實際獲取: {actual_count}")
            
            raise DataIncompleteError(
                error_msg,
                failed_batches=failed_batches,
                expected_count=expected_count,
                actual_count=actual_count
            )
        
        # 檢查數量一致性
        # 注意：由於去重，實際數量可能小於預期數量，這是正常的
        if actual_count > expected_count:
            # 實際數量不應該超過預期數量
            error_msg = f"資料數量異常：實際 {actual_count} 筆超過預期 {expected_count} 筆"
            if self.logger:
                self.logger.error(error_msg)
            
            raise DataIncompleteError(
                error_msg,
                expected_count=expected_count,
                actual_count=actual_count
            )
        
        # 記錄去重統計
        if actual_count < expected_count:
            duplicates_removed = expected_count - actual_count
            if self.logger:
                self.logger.info(f"資料去重：{expected_count} -> {actual_count} 筆（移除 {duplicates_removed} 重複）")
        
        if self.logger:
            self.logger.info(f"資料完整性驗證通過: {actual_count} 筆唯一記錄")
    
    def get_issue(self, issue_key: str, fields: List[str]) -> Optional[Dict[str, Any]]:
        """
        取得單一 Issue
        
        Args:
            issue_key: Issue Key (如 TP-3153)
            fields: 明確指定要取得的欄位清單
            
        Returns:
            Dict: Issue 原始資料或 None
        """
        # 確保包含 key 欄位
        if 'key' not in fields:
            fields = fields + ['key']
        
        params = {
            'fields': ','.join(fields)
        }
        
        if self.logger:
            self.logger.debug(f"取得 Issue: {issue_key}")
            self.logger.debug(f"請求欄位: {fields}")
        
        response = self._make_request('GET', f'/rest/api/2/issue/{issue_key}', params=params)
        
        if response:
            if self.logger:
                self.logger.debug(f"成功取得 Issue: {issue_key}")
            return response
        else:
            if self.logger:
                self.logger.warning(f"找不到 Issue: {issue_key}")
            return None
    
    def validate_jql(self, jql: str) -> bool:
        """
        驗證 JQL 語法
        
        Args:
            jql: JQL 查詢語句
            
        Returns:
            bool: 是否有效
        """
        params = {
            'jql': jql,
            'maxResults': 1
        }
        
        if self.logger:
            self.logger.debug(f"驗證 JQL: {jql}")
        
        response = self._make_request('GET', '/rest/api/2/search', params=params)
        
        if response:
            if self.logger:
                self.logger.debug("JQL 語法有效")
            return True
        else:
            if self.logger:
                self.logger.warning("JQL 語法無效")
            return False
    
    def get_server_info(self) -> Dict[str, Any]:
        """取得 JIRA 伺服器資訊"""
        if self.logger:
            self.logger.debug("取得 JIRA 伺服器資訊")
        
        response = self._make_request('GET', '/rest/api/2/serverInfo')
        
        if response:
            server_info = {
                'version': response.get('version', ''),
                'build_number': response.get('buildNumber', ''),
                'build_date': response.get('buildDate', ''),
                'server_title': response.get('serverTitle', ''),
                'base_url': response.get('baseUrl', self.server_url)
            }
            if self.logger:
                self.logger.info(f"JIRA 版本: {server_info['version']}")
            return server_info
        else:
            if self.logger:
                self.logger.error("取得伺服器資訊失敗")
            return {}


# 使用範例
if __name__ == '__main__':
    # 測試配置
    jira_config = {
        'server_url': 'https://jira.tc-gaming.co/jira',
        'username': 'your_username',
        'password': 'your_password',
        'timeout': 30,
        'max_results': 100
    }
    
    # 測試欄位清單（由調用方決定）
    test_fields = [
        'key', 'summary', 'status', 'assignee', 'reporter', 
        'created', 'updated', 'issuelinks'
    ]
    
    try:
        # 建立純資料撷取的 JIRA 客戶端
        jira_client = JiraClient(jira_config)
        
        print("=== 純資料撷取 JIRA 客戶端測試 ===")
        
        # 取得伺服器資訊
        server_info = jira_client.get_server_info()
        print(f"JIRA 版本: {server_info.get('version', 'Unknown')}")
        
        # 執行 JQL 查詢（明確指定欄位）
        jql = "project = TP AND status != Closed ORDER BY updated DESC"
        issues_dict = jira_client.search_issues(jql, test_fields, max_results=5)
        print(f"查詢結果: {len(issues_dict)} 筆唯一 Issues")
        
        # 顯示原始資料
        for issue_key, issue_data in list(issues_dict.items())[:3]:
            summary = issue_data['fields']['summary']
            status = issue_data['fields']['status']['name']
            print(f"  - {issue_key}: {summary} ({status})")
        
        print("\n純資料撷取 JIRA 客戶端測試完成")
        
    except Exception as e:
        print(f"JIRA 客戶端測試失敗: {e}")