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
from typing import Dict, List, Optional, Tuple, Any
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
    
    def get_table_fields(self, obj_token: str, table_id: str) -> List[Dict[str, Any]]:
        """
        獲取表格的完整欄位結構
        
        Args:
            obj_token: 應用 Token
            table_id: 表格 ID
            
        Returns:
            List[Dict]: 欄位列表，每個欄位包含 field_name, type 等資訊
        """
        try:
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                return []
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/fields"
            response = requests.get(url, headers=headers, timeout=self.timeout)
            
            if response.status_code != 200:
                self.logger.error(f"獲取表格欄位失敗，HTTP {response.status_code}: {response.text}")
                return []
            
            result = response.json()
            if result.get('code') != 0:
                self.logger.error(f"獲取表格欄位失敗: {result.get('msg')}")
                return []
            
            fields = result.get('data', {}).get('items', [])
            self.logger.debug(f"獲取表格 {table_id} 的 {len(fields)} 個欄位")
            return fields
            
        except Exception as e:
            self.logger.error(f"獲取表格欄位異常: {e}")
            return []
    
    def get_available_field_names(self, obj_token: str, table_id: str) -> List[str]:
        """
        獲取表格中所有可用的欄位名稱
        
        Args:
            obj_token: 應用 Token
            table_id: 表格 ID
            
        Returns:
            List[str]: 欄位名稱列表
        """
        fields = self.get_table_fields(obj_token, table_id)
        return [field.get('field_name', '') for field in fields if field.get('field_name')]


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
                error_msg = result.get('msg', 'Unknown error')
                self.logger.error(f"API 請求失敗: {error_msg}")
                # 如果是 FieldNameNotFound 錯誤，嘗試提取更多資訊
                if 'FieldNameNotFound' in error_msg or 'field' in error_msg.lower():
                    self.logger.error(f"API 完整回應: {result}")
                    self.logger.error(f"請求 URL: {url}")
                    self.logger.error(f"請求方法: {method}")
                    if method in ['POST', 'PUT'] and 'json' in kwargs:
                        request_data = kwargs.get('json', {})
                        if 'fields' in request_data:
                            self.logger.error(f"請求的欄位列表: {list(request_data['fields'].keys())}")
                            self.logger.error(f"請求的欄位資料: {request_data['fields']}")
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
    
    def create_record(self, obj_token: str, table_id: str, fields: Dict, sprints_ui_type: Optional[str] = None) -> Optional[str]:
        """創建單筆記錄（優先依據 Sprints 欄位屬性決定格式，必要時才 fallback）"""
        url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records"

        # 檢查是否包含 Sprints 欄位
        sprints_field = None
        sprints_value = None
        for name in ['Sprints', 'Sprint', 'sprints', 'sprint']:
            if name in fields:
                sprints_field = name
                sprints_value = fields[name]
                break

        if sprints_field is None or sprints_value is None:
            # 沒有 Sprints，直接送出
            data = {'fields': fields}
            result = self._make_request('POST', url, json=data)
            if result:
                record = result.get('record', {})
                return record.get('record_id')
            return None

        # 先依據欄位屬性決定應用的格式
        preferred_candidates: List[Any] = []
        if sprints_ui_type == "Number":
            # 目標為數字
            try:
                if isinstance(sprints_value, (int, float)):
                    preferred_candidates.append(sprints_value)
                elif isinstance(sprints_value, str) and sprints_value.strip():
                    preferred_candidates.append(int(float(sprints_value.strip())))
            except Exception:
                pass
            # 次要候選：字串（保險用）
            if isinstance(sprints_value, (int, float)):
                preferred_candidates.append(str(sprints_value))
            elif isinstance(sprints_value, str) and sprints_value.strip():
                preferred_candidates.append(sprints_value.strip())
        elif sprints_ui_type == "SingleSelect":
            # 目標為單選（字串）
            if isinstance(sprints_value, (int, float)):
                preferred_candidates.append(str(sprints_value))
            elif isinstance(sprints_value, str) and sprints_value.strip():
                preferred_candidates.append(sprints_value.strip())
            # 次要候選：數字（保險用）
            try:
                if isinstance(sprints_value, (int, float)):
                    preferred_candidates.append(sprints_value)
                elif isinstance(sprints_value, str) and sprints_value.strip():
                    preferred_candidates.append(int(float(sprints_value.strip())))
            except Exception:
                pass
        else:
            # 若未知欄位型別，沿用原本的雙格式候選
            try:
                if isinstance(sprints_value, (int, float)):
                    preferred_candidates.append(sprints_value)
                elif isinstance(sprints_value, str) and sprints_value.strip():
                    preferred_candidates.append(int(float(sprints_value.strip())))
            except Exception:
                pass
            if isinstance(sprints_value, (int, float)):
                preferred_candidates.append(str(sprints_value))
            elif isinstance(sprints_value, str) and sprints_value.strip():
                preferred_candidates.append(sprints_value.strip())

        # 去重，保留順序
        seen = set()
        candidates = []
        for c in preferred_candidates:
            if (isinstance(c, str), c) not in seen:
                candidates.append(c)
                seen.add((isinstance(c, str), c))

        for idx, cand in enumerate(candidates):
            pf = dict(fields)
            pf[sprints_field] = cand
            data = {'fields': self._preprocess_fields_for_sprints(pf, "new_record", sprints_ui_type)}
            result = self._make_request('POST', url, json=data)
            if result:
                record = result.get('record', {})
                rid = record.get('record_id')
                if rid:
                    if idx > 0:
                        self.logger.info(f"Sprints 依據欄位屬性首選失敗，fallback 第 {idx+1} 次嘗試成功")
                    return rid
        
        # 兩種都失敗，最後用原始值再試一次（保險）
        data = {'fields': self._preprocess_fields_for_sprints(fields, "new_record", sprints_ui_type)}
        result = self._make_request('POST', url, json=data)
        if result:
            record = result.get('record', {})
            return record.get('record_id')
        return None
    
    def update_record(self, obj_token: str, table_id: str, record_id: str, fields: Dict, sprints_ui_type: Optional[str] = None) -> bool:
        """更新單筆記錄（優先依據 Sprints 欄位屬性決定格式，必要時才 fallback）"""
        url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/{record_id}"

        # 檢查是否包含 Sprints 欄位
        sprints_field = None
        sprints_value = None
        for name in ['Sprints', 'Sprint', 'sprints', 'sprint']:
            if name in fields:
                sprints_field = name
                sprints_value = fields[name]
                break

        if sprints_field is None or sprints_value is None:
            data = {'fields': self._preprocess_fields_for_sprints(fields, record_id, sprints_ui_type)}
            result = self._make_request('PUT', url, json=data)
            return result is not None

        preferred_candidates: List[Any] = []
        if sprints_ui_type == "Number":
            try:
                if isinstance(sprints_value, (int, float)):
                    preferred_candidates.append(sprints_value)
                elif isinstance(sprints_value, str) and sprints_value.strip():
                    preferred_candidates.append(int(float(sprints_value.strip())))
            except Exception:
                pass
            if isinstance(sprints_value, (int, float)):
                preferred_candidates.append(str(sprints_value))
            elif isinstance(sprints_value, str) and sprints_value.strip():
                preferred_candidates.append(sprints_value.strip())
        elif sprints_ui_type == "SingleSelect":
            if isinstance(sprints_value, (int, float)):
                preferred_candidates.append(str(sprints_value))
            elif isinstance(sprints_value, str) and sprints_value.strip():
                preferred_candidates.append(sprints_value.strip())
            try:
                if isinstance(sprints_value, (int, float)):
                    preferred_candidates.append(sprints_value)
                elif isinstance(sprints_value, str) and sprints_value.strip():
                    preferred_candidates.append(int(float(sprints_value.strip())))
            except Exception:
                pass
        else:
            try:
                if isinstance(sprints_value, (int, float)):
                    preferred_candidates.append(sprints_value)
                elif isinstance(sprints_value, str) and sprints_value.strip():
                    preferred_candidates.append(int(float(sprints_value.strip())))
            except Exception:
                pass
            if isinstance(sprints_value, (int, float)):
                preferred_candidates.append(str(sprints_value))
            elif isinstance(sprints_value, str) and sprints_value.strip():
                preferred_candidates.append(sprints_value.strip())

        seen = set()
        candidates = []
        for c in preferred_candidates:
            if (isinstance(c, str), c) not in seen:
                candidates.append(c)
                seen.add((isinstance(c, str), c))

        for idx, cand in enumerate(candidates):
            pf = dict(fields)
            pf[sprints_field] = cand
            data = {'fields': self._preprocess_fields_for_sprints(pf, record_id, sprints_ui_type)}
            result = self._make_request('PUT', url, json=data)
            if result is not None:
                if idx > 0:
                    self.logger.info(f"Sprints 依據欄位屬性首選失敗，fallback 第 {idx+1} 次嘗試成功")
                return True

        # 兩種都失敗，最後用原始值再試一次（保險）
        data = {'fields': self._preprocess_fields_for_sprints(fields, record_id, sprints_ui_type)}
        result = self._make_request('PUT', url, json=data)
        return result is not None
    
    def _calculate_dynamic_batch_size(self, records: List[Dict[str, Any]], max_size: int = 500) -> int:
        """
        根據記錄複雜度計算動態批次大小
        
        Args:
            records: 記錄列表
            max_size: 最大批次大小
            
        Returns:
            int: 建議的批次大小
        """
        if not records:
            return max_size
        
        # 計算平均記錄大小（估算）
        sample_size = min(10, len(records))
        total_fields = 0
        total_content_length = 0
        
        for i in range(sample_size):
            record = records[i]
            field_count = len(record)
            content_length = len(str(record))
            
            total_fields += field_count
            total_content_length += content_length
        
        avg_fields = total_fields / sample_size
        avg_content_length = total_content_length / sample_size
        
        # 動態調整批次大小
        if avg_fields > 20 or avg_content_length > 2000:
            # 複雜記錄：減少批次大小
            batch_size = min(200, max_size)
        elif avg_fields > 10 or avg_content_length > 1000:
            # 中等複雜度：適中批次大小
            batch_size = min(350, max_size)
        else:
            # 簡單記錄：使用最大批次大小
            batch_size = max_size
        
        self.logger.debug(f"動態批次大小計算: 平均欄位 {avg_fields:.1f}, 平均長度 {avg_content_length:.0f}, 批次大小 {batch_size}")
        return batch_size

    def _preprocess_updates_for_sprints(self, updates: List[Tuple[str, Dict[str, Any]]], sprints_ui_type: Optional[str] = None) -> List[Tuple[str, Dict[str, Any]]]:
        """
        預處理更新資料，為 Sprints 欄位添加 fallback 支援
        
        Args:
            updates: 原始更新列表 (record_id, fields)
            
        Returns:
            List[Tuple[str, Dict[str, Any]]]: 處理後的更新列表
        """
        processed_updates = []
        
        for record_id, fields in updates:
            processed_fields = fields.copy()
            
            # 檢查是否有 Sprints 欄位需要處理
            sprints_field_names = ['Sprints', 'Sprint', 'sprints', 'sprint']
            sprints_field = None
            sprints_value = None
            
            # 找到 Sprints 欄位
            for field_name in sprints_field_names:
                if field_name in processed_fields:
                    sprints_field = field_name
                    sprints_value = processed_fields[field_name]
                    break
            
            # 如果找到 Sprints 欄位，應用 fallback 邏輯
            if sprints_field and sprints_value is not None:
                processed_sprints_value = self._process_sprints_value_with_fallback(sprints_value, record_id, sprints_ui_type)
                processed_fields[sprints_field] = processed_sprints_value
            
            processed_updates.append((record_id, processed_fields))
        
        return processed_updates
    
    def _process_sprints_value_with_fallback(self, sprints_value: Any, record_id: str, sprints_ui_type: Optional[str] = None) -> Any:
        """
        處理 Sprints 值，支援數字格式和單選格式的 fallback
        單選格式使用與 JIRA Status 相同的字串格式
        
        Args:
            sprints_value: 原始 Sprints 值
            record_id: 記錄 ID（用於日誌）
            
        Returns:
            Any: 處理後的 Sprints 值
        """
        if sprints_value is None or sprints_value == "":
            return sprints_value
            
        # 若指定了欄位型別，優先按照型別轉換
        if sprints_ui_type == "Number":
            try:
                if isinstance(sprints_value, (int, float)):
                    return sprints_value
                if isinstance(sprints_value, str) and sprints_value.strip():
                    return int(float(sprints_value.strip()))
            except Exception:
                pass
        elif sprints_ui_type == "SingleSelect":
            if isinstance(sprints_value, (int, float)):
                return str(sprints_value)
            if isinstance(sprints_value, str) and sprints_value.strip():
                return sprints_value.strip()

        # 方法 1: 嘗試數字格式（未指定型別時）
        try:
            if isinstance(sprints_value, (int, float)):
                numeric_sprints = sprints_value
            elif isinstance(sprints_value, str) and sprints_value.strip():
                numeric_sprints = int(float(sprints_value.strip()))
            else:
                numeric_sprints = None
            
            if numeric_sprints is not None:
                self.logger.debug(f"Sprints 欄位使用數字格式: {record_id} -> {numeric_sprints}")
                return numeric_sprints
                
        except (ValueError, TypeError):
            self.logger.debug(f"Sprints 數字格式轉換失敗，嘗試單選格式: {record_id} -> {sprints_value}")
        
        # 方法 2: 如果數字格式失敗，使用單選格式（字串值）
        try:
            # 單選欄位格式就是簡單的字串值，與 JIRA Status 的 extract_nested 結果相同
            if isinstance(sprints_value, (int, float)):
                single_select_value = str(sprints_value)
            elif isinstance(sprints_value, str) and sprints_value.strip():
                single_select_value = sprints_value.strip()
            else:
                single_select_value = None
            
            if single_select_value:
                self.logger.debug(f"Sprints 欄位使用單選格式: {record_id} -> {single_select_value}")
                return single_select_value
                
        except Exception as e:
            self.logger.warning(f"Sprints 單選格式轉換也失敗: {record_id} -> {sprints_value}, 錯誤: {e}")
        
        # 如果兩種方法都失敗，返回原始值並記錄警告
        self.logger.warning(f"Sprints 欄位兩種格式都失敗，使用原始值: {record_id} -> {sprints_value}")
        return sprints_value

    
    def _preprocess_fields_for_sprints(self, fields: Dict[str, Any], record_id: str, sprints_ui_type: Optional[str] = None) -> Dict[str, Any]:
        """
        為單筆記錄預處理欄位，支援 Sprints 欄位 fallback
        
        Args:
            fields: 原始欄位字典
            record_id: 記錄 ID（用於日誌）
            
        Returns:
            Dict[str, Any]: 處理後的欄位字典
        """
        processed_fields = fields.copy()
        
        # 檢查是否有 Sprints 欄位需要處理
        sprints_field_names = ['Sprints', 'Sprint', 'sprints', 'sprint']
        sprints_field = None
        sprints_value = None
        
        # 找到 Sprints 欄位
        for field_name in sprints_field_names:
            if field_name in processed_fields:
                sprints_field = field_name
                sprints_value = processed_fields[field_name]
                break
        
        # 如果找到 Sprints 欄位，應用 fallback 邏輯
        if sprints_field and sprints_value is not None:
            processed_sprints_value = self._process_sprints_value_with_fallback(sprints_value, record_id, sprints_ui_type)
            processed_fields[sprints_field] = processed_sprints_value
        
        return processed_fields

    def batch_update_records(self, obj_token: str, table_id: str, 
                           updates: List[Tuple[str, Dict[str, Any]]], sprints_ui_type: Optional[str] = None) -> bool:
        """
        批量更新記錄（自動分批處理，支援 Sprints 欄位 fallback）
        
        Args:
            obj_token: App token
            table_id: 表格 ID
            updates: 更新列表，每個元素為 (record_id, fields) 元組
            
        Returns:
            bool: 更新成功返回 True
        """
        if not updates:
            return True
        
        # 預處理更新資料，處理 Sprints 欄位的 fallback
        processed_updates = self._preprocess_updates_for_sprints(updates, sprints_ui_type)
            
        # 動態計算批次大小（基於 fields 部分）
        field_records = [fields for _, fields in processed_updates]
        batch_size = self._calculate_dynamic_batch_size(field_records, max_size=500)
        
        self.logger.info(f"使用動態批次大小 {batch_size} 處理 {len(processed_updates)} 筆更新")
        
        # 分批處理
        for i in range(0, len(processed_updates), batch_size):
            batch = processed_updates[i:i + batch_size]
            
            try:
                token = self.auth_manager.get_tenant_access_token()
                if not token:
                    self.logger.error("無法獲取 Access Token")
                    return False
                
                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                }
                
                # 根據官方範例，使用正確的格式
                payload = {
                    'records': [
                        {
                            'record_id': record_id,
                            'fields': fields
                        }
                        for record_id, fields in batch
                    ]
                }
                
                url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/batch_update"
                response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)

                def _retry_with_sprints_fallback(batch_items: List[Tuple[str, Dict[str, Any]]]) -> bool:
                    fallback_batch: List[Tuple[str, Dict[str, Any]]] = []
                    for record_id, fields in batch_items:
                        new_fields = dict(fields)
                        for name in ['Sprints', 'Sprint', 'sprints', 'sprint']:
                            if name in new_fields:
                                v = new_fields[name]
                                alt = None
                                if isinstance(v, (int, float)):
                                    alt = str(v)
                                elif isinstance(v, str) and v.strip():
                                    try:
                                        alt = int(float(v.strip()))
                                    except Exception:
                                        alt = None
                                if alt is not None:
                                    new_fields[name] = alt
                                break
                        fallback_batch.append((record_id, new_fields))
                    payload_fb = {
                        'records': [
                            {'record_id': rid, 'fields': flds}
                            for rid, flds in fallback_batch
                        ]
                    }
                    resp2 = requests.post(url, json=payload_fb, headers=headers, timeout=self.timeout)
                    if resp2.status_code != 200:
                        self.logger.error(f"批次更新 Fallback 失敗，HTTP {resp2.status_code}: {resp2.text}")
                        return False
                    res2 = resp2.json()
                    if res2.get('code') != 0:
                        self.logger.error(f"批次更新 Fallback 失敗: {res2.get('msg')}")
                        return False
                    self.logger.info("批次更新 Fallback 重試成功")
                    return True

                if response.status_code != 200:
                    self.logger.error(f"批次更新失敗，HTTP {response.status_code}: {response.text}")
                    if not _retry_with_sprints_fallback(batch):
                        return False
                else:
                    result = response.json()
                    if result.get('code') != 0:
                        self.logger.error(f"批次更新失敗: {result.get('msg')}")
                        if not _retry_with_sprints_fallback(batch):
                            return False
                
                self.logger.info(f"批次更新記錄 {i+1}-{i+len(batch)}/{len(processed_updates)} 成功")
                
            except Exception as e:
                self.logger.error(f"批次更新異常: {e}")
                return False
        
        self.logger.info(f"成功批量更新 {len(processed_updates)} 筆記錄")
        return True
    
    def batch_create_records(self, obj_token: str, table_id: str, 
                           records_data: List[Dict], sprints_ui_type: Optional[str] = None) -> Tuple[bool, List[str], List[str]]:
        """批次創建記錄（優先依據 Sprints 欄位屬性決定格式，必要時才 fallback）"""
        if not records_data:
            return True, [], []
        
        # 預處理記錄資料，處理 Sprints fallback
        processed_records_data = []
        for i, record_fields in enumerate(records_data):
            processed_fields = self._preprocess_fields_for_sprints(record_fields, f"new_record_{i}", sprints_ui_type)
            processed_records_data.append(processed_fields)
        
        max_batch_size = 500
        success_ids = []
        error_messages = []
        
        # 分批處理
        for i in range(0, len(processed_records_data), max_batch_size):
            batch_data = processed_records_data[i:i + max_batch_size]
            
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

                def _retry_create_with_sprints_fallback(batch_items: List[Dict]) -> Tuple[bool, List[str]]:
                    fb_items: List[Dict] = []
                    for item in batch_items:
                        flds = dict(item)
                        for name in ['Sprints', 'Sprint', 'sprints', 'sprint']:
                            if name in flds:
                                v = flds[name]
                                alt = None
                                if isinstance(v, (int, float)):
                                    alt = str(v)
                                elif isinstance(v, str) and v.strip():
                                    try:
                                        alt = int(float(v.strip()))
                                    except Exception:
                                        alt = None
                                if alt is not None:
                                    flds[name] = alt
                                break
                        fb_items.append(flds)
                    payload_fb = {'records': [{'fields': x} for x in fb_items]}
                    resp2 = requests.post(url, json=payload_fb, headers=headers, timeout=self.timeout)
                    if resp2.status_code != 200:
                        return False, []
                    res2 = resp2.json()
                    if res2.get('code') != 0:
                        return False, []
                    data_section2 = res2.get('data', {})
                    records2 = data_section2.get('records', [])
                    ids2 = [rec.get('record_id') for rec in records2 if rec.get('record_id')]
                    return True, ids2

                if response.status_code != 200:
                    ok, ids_fb = _retry_create_with_sprints_fallback(batch_data)
                    if ok:
                        success_ids.extend(ids_fb)
                        continue
                    error_msg = f"批次創建失敗，HTTP {response.status_code}"
                    error_messages.append(error_msg)
                    continue
                
                result = response.json()
                if result.get('code') != 0:
                    ok, ids_fb = _retry_create_with_sprints_fallback(batch_data)
                    if ok:
                        success_ids.extend(ids_fb)
                        continue
                    error_msg = f"批次創建失敗: {result.get('msg')}"
                    error_messages.append(error_msg)
                    # 記錄詳細的錯誤資訊，包含實際的欄位資料
                    self.logger.error(f"批次創建失敗詳細資訊 - 錯誤碼: {result.get('code')}, 錯誤訊息: {result.get('msg')}")
                    self.logger.error(f"失敗的資料筆數: {len(batch_data)}")
                    if batch_data and len(batch_data) > 0:
                        self.logger.error(f"第一筆資料的欄位: {list(batch_data[0].keys())}")
                        for i, record_data in enumerate(batch_data[:3]):
                            self.logger.error(f"第 {i+1} 筆資料內容: {record_data}")
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
    
    def batch_delete_records(self, obj_token: str, table_id: str, 
                           record_ids: List[str]) -> bool:
        """批次刪除記錄"""
        if not record_ids:
            return True
        
        max_batch_size = 500
        
        # 分批處理
        for i in range(0, len(record_ids), max_batch_size):
            batch_ids = record_ids[i:i + max_batch_size]
            
            try:
                token = self.auth_manager.get_tenant_access_token()
                if not token:
                    self.logger.error("無法獲取 Access Token")
                    return False
                
                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                }
                
                # 準備批次刪除數據
                data = {'records': batch_ids}
                
                url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/batch_delete"
                response = requests.post(url, json=data, headers=headers, timeout=self.timeout)
                
                if response.status_code != 200:
                    self.logger.error(f"批次刪除失敗，HTTP {response.status_code}")
                    return False
                
                result = response.json()
                if result.get('code') != 0:
                    self.logger.error(f"批次刪除失敗: {result.get('msg')}")
                    return False
                
            except Exception as e:
                self.logger.error(f"批次刪除異常: {e}")
                return False
        
        self.logger.info(f"批次刪除完成，共刪除 {len(record_ids)} 筆記錄")
        return True
    
    def check_record_exists(self, obj_token: str, table_id: str, record_id: str) -> bool:
        """
        檢查記錄是否存在
        
        Args:
            obj_token: App token
            table_id: 表格 ID
            record_id: 記錄 ID
            
        Returns:
            bool: 記錄是否存在
        """
        try:
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                self.logger.error("無法獲取 Access Token")
                return False
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            # 嘗試獲取單一記錄來檢查是否存在
            url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/{record_id}"
            response = requests.get(url, headers=headers, timeout=self.timeout)
            
            if response.status_code == 200:
                result = response.json()
                return result.get('code') == 0
            elif response.status_code == 404:
                # 記錄不存在
                return False
            else:
                self.logger.warning(f"檢查記錄存在性失敗，HTTP {response.status_code}")
                return False
                
        except Exception as e:
            self.logger.error(f"檢查記錄存在性異常: {e}")
            return False


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
            
            url = f"{self.base_url}/contact/v3/users/batch_get_id"
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
                user_id = user_info.get('user_id')
                
                if not user_id:
                    return None
                
                # 轉換為統一格式，與 user_mapper.py 保持一致
                result = {
                    'id': user_id,
                    'name': user_info.get('name', email.split('@')[0]),
                    'email': email
                }
                
                # 快取結果
                with self._cache_lock:
                    self._user_cache[email] = result
                return result
            
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
    
    def _get_field_ui_type(self, obj_token: str, table_id: str, field_name: str) -> Optional[str]:
        fields = self.table_manager.get_table_fields(obj_token, table_id)
        for f in fields:
            if f.get('field_name') == field_name:
                return f.get('ui_type')
        return None

    def create_record(self, table_id: str, fields: Dict, wiki_token: str = None) -> Optional[str]:
        """創建單筆記錄（先判斷 Sprints 欄位屬性，再決定格式）"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return None

        sprints_ui_type = None
        for name in ['Sprints', 'Sprint', 'sprints', 'sprint']:
            if name in fields:
                sprints_ui_type = self._get_field_ui_type(obj_token, table_id, name)
                break
        
        return self.record_manager.create_record(obj_token, table_id, fields, sprints_ui_type)
    
    def update_record(self, table_id: str, record_id: str, fields: Dict,
                     wiki_token: str = None) -> bool:
        """更新單筆記錄（先判斷 Sprints 欄位屬性，再決定格式）"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False

        sprints_ui_type = None
        for name in ['Sprints', 'Sprint', 'sprints', 'sprint']:
            if name in fields:
                sprints_ui_type = self._get_field_ui_type(obj_token, table_id, name)
                break
        
        return self.record_manager.update_record(obj_token, table_id, record_id, fields, sprints_ui_type)
    
    def get_table_fields(self, table_id: str, wiki_token: str = None) -> List[Dict[str, Any]]:
        """
        獲取表格的完整欄位結構
        
        Args:
            table_id: 表格 ID
            wiki_token: Wiki Token（可選，使用預設值）
            
        Returns:
            List[Dict]: 欄位列表，每個欄位包含 field_name, type 等資訊
        """
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return []
        
        return self.table_manager.get_table_fields(obj_token, table_id)
    
    def get_available_field_names(self, table_id: str, wiki_token: str = None) -> List[str]:
        """
        獲取表格中所有可用的欄位名稱
        
        Args:
            table_id: 表格 ID
            wiki_token: Wiki Token（可選，使用預設值）
            
        Returns:
            List[str]: 欄位名稱列表
        """
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return []
        
        return self.table_manager.get_available_field_names(obj_token, table_id)
    
    def batch_create_records(self, table_id: str, records: List[Dict],
                           wiki_token: str = None) -> Tuple[bool, List[str], List[str]]:
        """批次創建記錄（先判斷 Sprints 欄位屬性，再決定格式）"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False, [], ['無法獲取 Obj Token']

        # 嘗試從第一筆含有 Sprints 的資料判斷欄位型別
        sprints_ui_type = None
        for rec in records:
            for name in ['Sprints', 'Sprint', 'sprints', 'sprint']:
                if name in rec:
                    sprints_ui_type = self._get_field_ui_type(obj_token, table_id, name)
                    break
            if sprints_ui_type:
                break
        
        return self.record_manager.batch_create_records(obj_token, table_id, records, sprints_ui_type)
    
    def batch_delete_records(self, table_id: str, record_ids: List[str],
                           wiki_token: str = None) -> bool:
        """批次刪除記錄"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False
        
        return self.record_manager.batch_delete_records(obj_token, table_id, record_ids)
    
    def batch_update_records(self, table_id: str, updates: List[Tuple[str, Dict]],
                           wiki_token: str = None) -> bool:
        """批次更新記錄（先判斷 Sprints 欄位屬性，再決定格式）"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False

        # 嘗試從第一筆含有 Sprints 的更新判斷欄位型別
        sprints_ui_type = None
        for _, fields in updates:
            for name in ['Sprints', 'Sprint', 'sprints', 'sprint']:
                if name in fields:
                    sprints_ui_type = self._get_field_ui_type(obj_token, table_id, name)
                    break
            if sprints_ui_type:
                break
        
        return self.record_manager.batch_update_records(obj_token, table_id, updates, sprints_ui_type)
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """根據 Email 獲取用戶資訊"""
        return self.user_manager.get_user_by_email(email)
    
    def check_record_exists(self, table_id: str, record_id: str, wiki_token: str = None) -> bool:
        """
        檢查記錄是否存在
        
        Args:
            table_id: 表格 ID
            record_id: 記錄 ID
            wiki_token: Wiki Token（可選）
            
        Returns:
            bool: 記錄是否存在
        """
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False
        
        return self.record_manager.check_record_exists(obj_token, table_id, record_id)
    
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
