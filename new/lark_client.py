#!/usr/bin/env python3
"""
Lark Base Client

專注於高效的全表掃描功能：
- 快速獲取所有記錄
- 批次操作
- 用戶管理
"""

import logging
import requests
import threading
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta


class LarkAuthManager:
    """Lark 認證管理器"""
    
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        
        # Token 快取
        self._tenant_access_token = None
        self._token_expire_time = None
        self._token_lock = threading.Lock()
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.LarkAuthManager")
        
        # API 配置
        self.auth_url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
        self.timeout = 30
    
    def get_tenant_access_token(self, force_refresh: bool = False) -> Optional[str]:
        """獲取 Tenant Access Token"""
        with self._token_lock:
            # 檢查是否需要刷新
            if (not force_refresh and 
                self._tenant_access_token and 
                self._token_expire_time and 
                datetime.now() < self._token_expire_time):
                return self._tenant_access_token
            
            # 獲取新 Token
            try:
                response = requests.post(
                    self.auth_url,
                    json={
                        "app_id": self.app_id,
                        "app_secret": self.app_secret
                    },
                    timeout=self.timeout
                )
                
                if response.status_code != 200:
                    self.logger.error(f"Token 獲取失敗，HTTP {response.status_code}")
                    return None
                
                result = response.json()
                
                if result.get('code') != 0:
                    self.logger.error(f"Token 獲取失敗: {result.get('msg')}")
                    return None
                
                # 快取 Token
                self._tenant_access_token = result['tenant_access_token']
                expire_seconds = result.get('expire', 7200)
                self._token_expire_time = datetime.now() + timedelta(seconds=expire_seconds - 300)
                
                return self._tenant_access_token
                
            except Exception as e:
                self.logger.error(f"Token 獲取異常: {e}")
                return None
    
    def is_token_valid(self) -> bool:
        """檢查 Token 是否有效"""
        return (self._tenant_access_token is not None and 
                self._token_expire_time is not None and 
                datetime.now() < self._token_expire_time)


class LarkTableManager:
    """Lark 表格管理器"""
    
    def __init__(self, auth_manager: LarkAuthManager):
        self.auth_manager = auth_manager
        
        # 快取
        self._obj_tokens = {}     # wiki_token -> obj_token
        self._cache_lock = threading.Lock()
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.LarkTableManager")
        
        # API 配置
        self.base_url = "https://open.larksuite.com/open-apis"
        self.timeout = 30
    
    def get_obj_token(self, wiki_token: str) -> Optional[str]:
        """從 Wiki Token 獲取 Obj Token"""
        with self._cache_lock:
            if wiki_token in self._obj_tokens:
                return self._obj_tokens[wiki_token]
        
        try:
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                return None
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            url = f"{self.base_url}/wiki/v2/spaces/get_node?token={wiki_token}"
            response = requests.get(url, headers=headers, timeout=self.timeout)
            
            if response.status_code != 200:
                self.logger.error(f"Wiki Token 解析失敗，HTTP {response.status_code}")
                return None
            
            result = response.json()
            if result.get('code') != 0:
                self.logger.error(f"Wiki Token 解析失敗: {result.get('msg')}")
                return None
            
            obj_token = result['data']['node']['obj_token']
            
            # 快取結果
            with self._cache_lock:
                self._obj_tokens[wiki_token] = obj_token
            
            return obj_token
            
        except Exception as e:
            self.logger.error(f"Wiki Token 解析異常: {e}")
            return None


class LarkRecordManager:
    """Lark 記錄管理器 - 專注於全表掃描"""
    
    def __init__(self, auth_manager: LarkAuthManager):
        self.auth_manager = auth_manager
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.LarkRecordManager")
        
        # API 配置
        self.base_url = "https://open.larksuite.com/open-apis"
        self.timeout = 60
        self.max_page_size = 500
    
    def _make_request(self, method: str, url: str, **kwargs) -> Optional[Dict]:
        """統一的 HTTP 請求方法"""
        try:
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                self.logger.error("無法獲取 Access Token")
                return None
            
            headers = kwargs.pop('headers', {})
            headers.update({
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            })
            
            response = requests.request(
                method, url, 
                headers=headers, 
                timeout=self.timeout,
                **kwargs
            )
            
            if response.status_code != 200:
                self.logger.error(f"API 請求失敗，HTTP {response.status_code}: {response.text}")
                return None
            
            result = response.json()
            
            if result.get('code') != 0:
                self.logger.error(f"API 請求失敗: {result.get('msg', 'Unknown error')}")
                return None
            
            return result.get('data', {})
            
        except Exception as e:
            self.logger.error(f"API 請求異常: {e}")
            return None
    
    def get_all_records(self, obj_token: str, table_id: str) -> List[Dict]:
        """
        獲取表格所有記錄（高效全表掃描）
        
        Args:
            obj_token: Obj Token
            table_id: 表格 ID
            
        Returns:
            記錄列表
        """
        url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records"
        
        all_records = []
        page_token = None
        
        while True:
            params = {'page_size': self.max_page_size}
            if page_token:
                params['page_token'] = page_token
            
            result = self._make_request('GET', url, params=params)
            if not result:
                break
            
            records = result.get('items', [])
            all_records.extend(records)
            
            # 檢查是否還有更多記錄
            page_token = result.get('page_token')
            if not page_token or not result.get('has_more', False):
                break
        
        self.logger.info(f"全表掃描完成，共獲取 {len(all_records)} 筆記錄")
        return all_records
    
    def create_record(self, obj_token: str, table_id: str, fields: Dict) -> Optional[str]:
        """創建單筆記錄"""
        url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records"
        
        data = {'fields': fields}
        result = self._make_request('POST', url, json=data)
        
        if result:
            record = result.get('record', {})
            return record.get('record_id')
        return None
    
    def update_record(self, obj_token: str, table_id: str, record_id: str, fields: Dict) -> bool:
        """更新單筆記錄"""
        url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/{record_id}"
        
        data = {'fields': fields}
        result = self._make_request('PUT', url, json=data)
        return result is not None
    
    def batch_create_records(self, obj_token: str, table_id: str, 
                           records_data: List[Dict]) -> Tuple[bool, List[str], List[str]]:
        """批次創建記錄"""
        if not records_data:
            return True, [], []
        
        max_batch_size = 500
        success_ids = []
        error_messages = []
        
        # 分批處理
        for i in range(0, len(records_data), max_batch_size):
            batch_data = records_data[i:i + max_batch_size]
            
            try:
                token = self.auth_manager.get_tenant_access_token()
                if not token:
                    error_messages.append("無法獲取 Access Token")
                    continue
                
                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                }
                
                # 準備批次數據
                records = [{'fields': fields} for fields in batch_data]
                data = {'records': records}
                
                url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/batch_create"
                response = requests.post(url, json=data, headers=headers, timeout=self.timeout)
                
                if response.status_code != 200:
                    error_msg = f"批次創建失敗，HTTP {response.status_code}"
                    error_messages.append(error_msg)
                    continue
                
                result = response.json()
                if result.get('code') != 0:
                    error_msg = f"批次創建失敗: {result.get('msg')}"
                    error_messages.append(error_msg)
                    continue
                
                # 提取成功創建的記錄 ID
                data_section = result.get('data', {})
                records = data_section.get('records', [])
                batch_ids = [record.get('record_id') for record in records if record.get('record_id')]
                success_ids.extend(batch_ids)
                
            except Exception as e:
                error_messages.append(f"批次創建異常: {e}")
        
        overall_success = len(error_messages) == 0
        self.logger.info(f"批次創建完成，成功: {len(success_ids)}, 失敗: {len(error_messages)}")
        
        return overall_success, success_ids, error_messages


class LarkUserManager:
    """Lark 用戶管理器"""
    
    def __init__(self, auth_manager: LarkAuthManager):
        self.auth_manager = auth_manager
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.LarkUserManager")
        
        # API 配置
        self.base_url = "https://open.larksuite.com/open-apis"
        self.timeout = 30
        
        # 用戶快取
        self._user_cache = {}  # email -> user_info
        self._cache_lock = threading.Lock()
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """根據 Email 獲取用戶資訊"""
        with self._cache_lock:
            if email in self._user_cache:
                return self._user_cache[email]
        
        try:
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                return None
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            url = f"{self.base_url}/contact/v3/users/batch_get_id?user_id_type=user_id"
            data = {'emails': [email]}
            
            response = requests.post(url, json=data, headers=headers, timeout=self.timeout)
            
            if response.status_code != 200:
                return None
            
            result = response.json()
            if result.get('code') != 0:
                return None
            
            # 提取用戶資訊
            data_section = result.get('data', {})
            user_list = data_section.get('user_list', [])
            
            if user_list:
                user_info = user_list[0]
                # 快取結果
                with self._cache_lock:
                    self._user_cache[email] = user_info
                return user_info
            
            return None
                
        except Exception as e:
            self.logger.error(f"用戶查詢異常: {e}")
            return None


class LarkClient:
    """
    Lark Base Client
    
    專注於高效的全表掃描功能
    """
    
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.LarkClient")
        
        # 初始化管理器
        self.auth_manager = LarkAuthManager(app_id, app_secret)
        self.table_manager = LarkTableManager(self.auth_manager)
        self.record_manager = LarkRecordManager(self.auth_manager)
        self.user_manager = LarkUserManager(self.auth_manager)
        
        # 當前 Wiki Token
        self._current_wiki_token = None
        self._current_obj_token = None
        
        self.logger.info("Lark Client 初始化完成")
    
    def set_wiki_token(self, wiki_token: str) -> bool:
        """設定當前使用的 Wiki Token"""
        self._current_wiki_token = wiki_token
        
        # 立即解析 Obj Token
        obj_token = self.table_manager.get_obj_token(wiki_token)
        if obj_token:
            self._current_obj_token = obj_token
            self.logger.info(f"Wiki Token 設定成功")
            return True
        else:
            self.logger.error(f"Wiki Token 設定失敗")
            return False
    
    def test_connection(self, wiki_token: str = None) -> bool:
        """測試連接"""
        try:
            # 測試認證
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                return False
            
            # 如果提供了 wiki_token，測試 Obj Token 解析
            if wiki_token:
                obj_token = self.table_manager.get_obj_token(wiki_token)
                if not obj_token:
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"連接測試異常: {e}")
            return False
    
    def get_all_records(self, table_id: str, wiki_token: str = None) -> List[Dict]:
        """
        獲取表格所有記錄（主要功能）
        
        Args:
            table_id: 表格 ID
            wiki_token: Wiki Token（可選，使用預設值）
            
        Returns:
            記錄列表
        """
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return []
        
        return self.record_manager.get_all_records(obj_token, table_id)
    
    def create_record(self, table_id: str, fields: Dict, wiki_token: str = None) -> Optional[str]:
        """創建單筆記錄"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return None
        
        return self.record_manager.create_record(obj_token, table_id, fields)
    
    def update_record(self, table_id: str, record_id: str, fields: Dict,
                     wiki_token: str = None) -> bool:
        """更新單筆記錄"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False
        
        return self.record_manager.update_record(obj_token, table_id, record_id, fields)
    
    def batch_create_records(self, table_id: str, records: List[Dict],
                           wiki_token: str = None) -> Tuple[bool, List[str], List[str]]:
        """批次創建記錄"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False, [], ['無法獲取 Obj Token']
        
        return self.record_manager.batch_create_records(obj_token, table_id, records)
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """根據 Email 獲取用戶資訊"""
        return self.user_manager.get_user_by_email(email)
    
    def _get_obj_token(self, wiki_token: str = None) -> Optional[str]:
        """獲取 Obj Token（內部方法）"""
        if wiki_token:
            return self.table_manager.get_obj_token(wiki_token)
        elif self._current_obj_token:
            return self._current_obj_token
        elif self._current_wiki_token:
            obj_token = self.table_manager.get_obj_token(self._current_wiki_token)
            if obj_token:
                self._current_obj_token = obj_token
            return obj_token
        else:
            self.logger.error("沒有可用的 Wiki Token")
            return None
    
    def get_performance_stats(self) -> Dict:
        """獲取效能統計資訊"""
        return {
            'auth_token_valid': self.auth_manager.is_token_valid(),
            'obj_token_cache_size': len(self.table_manager._obj_tokens),
            'user_cache_size': len(self.user_manager._user_cache),
            'client_type': 'LarkClient',
            'features': ['全表掃描', '批次操作', '用戶管理']
        }
    
    def clear_caches(self):
        """清理所有快取"""
        with self.table_manager._cache_lock:
            self.table_manager._obj_tokens.clear()
        
        with self.user_manager._cache_lock:
            self.user_manager._user_cache.clear()
        
        self.logger.info("所有快取已清理")


# 向後相容
LarkBaseClient = LarkClient