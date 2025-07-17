#!/usr/bin/env python3
"""
欄位處理器模組
基於 schema 配置將 JIRA 原始資料轉換為 Lark Base 格式
專注於欄位轉換，不處理資料撷取或寫入
"""

import yaml
import re
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path


class FieldProcessorError(Exception):
    """欄位處理異常"""
    def __init__(self, message: str, field_name: str = "", issue_key: str = ""):
        super().__init__(message)
        self.field_name = field_name
        self.issue_key = issue_key


class FieldProcessor:
    """基於 Schema 的欄位處理器"""
    
    def __init__(self, schema_path: str = "schema.yaml", jira_server_url: str = "", logger=None, user_mapper=None, config_path: str = "config.yaml"):
        """
        初始化欄位處理器
        
        Args:
            schema_path: schema 配置檔案路徑
            jira_server_url: JIRA 伺服器 URL，用於生成連結
            logger: 日誌管理器
            user_mapper: 用戶映射器（可選）
            config_path: 主配置檔案路徑，用於載入 issue link 規則
        """
        self.logger = logger
        self.schema_path = schema_path
        self.config_path = config_path
        self.jira_server_url = jira_server_url.rstrip('/')
        self.field_mappings = {}
        self.user_mapper = user_mapper
        self.issue_link_rules = {}
        
        # 載入 schema 配置
        self._load_schema()
        
        # 載入 issue link 過濾規則
        self._load_issue_link_rules()
        
        if self.logger:
            self.logger.info(f"欄位處理器初始化完成，支援 {len(self.field_mappings)} 個欄位轉換")
            if self.user_mapper:
                self.logger.info("用戶映射器已整合，將進行非阻塞用戶映射")
            if self.issue_link_rules:
                self.logger.info(f"Issue Link 過濾規則已載入，支援 {len(self.issue_link_rules)} 種前綴規則")
    
    def _load_schema(self):
        """載入 schema 配置"""
        try:
            schema_file = Path(self.schema_path)
            if not schema_file.exists():
                raise FileNotFoundError(f"Schema 檔案不存在: {self.schema_path}")
            
            with open(schema_file, 'r', encoding='utf-8') as f:
                schema = yaml.safe_load(f)
            
            self.field_mappings = schema.get('field_mappings', {})
            
            if self.logger:
                self.logger.debug(f"載入 schema 配置: {len(self.field_mappings)} 個欄位對應")
                
        except Exception as e:
            error_msg = f"載入 schema 配置失敗: {e}"
            if self.logger:
                self.logger.error(error_msg)
            raise FieldProcessorError(error_msg)
    
    def _load_issue_link_rules(self):
        """載入 issue link 過濾規則配置"""
        try:
            config_file = Path(self.config_path)
            if not config_file.exists():
                if self.logger:
                    self.logger.warning(f"配置檔案不存在: {self.config_path}，使用預設 issue link 規則")
                self.issue_link_rules = {}
                return
            
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            self.issue_link_rules = config.get('issue_link_rules', {})
            
            if self.logger:
                self.logger.debug(f"載入 issue link 規則配置: {len(self.issue_link_rules)} 個前綴規則")
                
        except Exception as e:
            error_msg = f"載入 issue link 規則配置失敗: {e}"
            if self.logger:
                self.logger.warning(error_msg)
            self.issue_link_rules = {}  # 使用空規則作為後備
    
    def process_issues(self, raw_issues_dict: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        將 JIRA 原始資料批次轉換為 Lark Base 格式
        
        Args:
            raw_issues_dict: JIRA Client 提供的原始資料字典 {issue_key: issue_data}
            
        Returns:
            Dict: 轉換後的 Lark 格式資料 {issue_key: processed_data}
            
        Raises:
            FieldProcessorError: 處理失敗時
        """
        return self.process_issues_with_mappings(raw_issues_dict, self.field_mappings)
    
    def process_issues_with_mappings(self, raw_issues_dict: Dict[str, Dict[str, Any]], field_mappings: Dict[str, Any], excluded_fields: List[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        使用指定的欄位映射批次轉換 JIRA 原始資料為 Lark Base 格式
        
        Args:
            raw_issues_dict: JIRA Client 提供的原始資料字典 {issue_key: issue_data}
            field_mappings: 欄位映射配置
            excluded_fields: 排除不同步的欄位清單
            
        Returns:
            Dict: 轉換後的 Lark 格式資料 {issue_key: processed_data}
            
        Raises:
            FieldProcessorError: 處理失敗時
        """
        if self.logger:
            self.logger.info(f"開始處理 {len(raw_issues_dict)} 筆 Issue 的欄位轉換")
        
        
        processed_issues = {}
        failed_issues = []
        
        for issue_key, raw_issue in raw_issues_dict.items():
            try:
                processed_issue = self._process_single_issue_with_mappings(issue_key, raw_issue, field_mappings, excluded_fields)
                processed_issues[issue_key] = processed_issue
                
                if self.logger:
                    self.logger.debug(f"Issue {issue_key} 處理完成")
                    
            except Exception as e:
                failed_issues.append(issue_key)
                if self.logger:
                    self.logger.error(f"Issue {issue_key} 處理失敗: {e}")
        
        # 檢查是否有失敗的 issue
        if failed_issues:
            error_msg = f"部分 Issue 處理失敗: {failed_issues}"
            if self.logger:
                self.logger.error(error_msg)
            raise FieldProcessorError(error_msg)
        
        if self.logger:
            self.logger.info(f"欄位轉換完成: {len(processed_issues)} 筆 Issue")
        
        return processed_issues
    
    def process_issues_with_dynamic_ticket_field(self, raw_issues_dict: Dict[str, Dict[str, Any]], 
                                                 field_mappings: Dict[str, Any], 
                                                 available_fields: List[str],
                                                 excluded_fields: List[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        使用動態多選欄位處理 Issue
        
        Args:
            raw_issues_dict: JIRA 原始資料字典
            field_mappings: 欄位映射配置
            available_fields: Lark 表格中可用的欄位列表
            excluded_fields: 排除不同步的欄位清單
            
        Returns:
            Dict: 處理後的 Lark 格式資料
        """
        # 創建修改後的映射配置
        modified_mappings = {}
        
        for jira_field, config in field_mappings.items():
            lark_field = config.get('lark_field')
            
            # 如果 lark_field 是數組，找到第一個在 available_fields 中的欄位
            if isinstance(lark_field, list):
                matched_field = None
                for possible_field in lark_field:
                    if possible_field in available_fields:
                        matched_field = possible_field
                        break
                
                if matched_field:
                    # 找到匹配的欄位，使用它
                    modified_mappings[jira_field] = {
                        'lark_field': matched_field,
                        'processor': config.get('processor', 'extract_simple')
                    }
                    if self.logger:
                        self.logger.info(f"動態選擇欄位: {jira_field} -> {matched_field}")
                # 如果沒找到匹配的欄位，跳過這個映射
            else:
                # 單一欄位，正常處理
                if lark_field in available_fields:
                    modified_mappings[jira_field] = config
        
        return self.process_issues_with_mappings(raw_issues_dict, modified_mappings, excluded_fields)
    
    
    def _process_single_issue(self, issue_key: str, raw_issue: Dict[str, Any]) -> Dict[str, Any]:
        """
        處理單一 Issue 的欄位轉換
        
        Args:
            issue_key: Issue Key
            raw_issue: JIRA 原始資料
            
        Returns:
            Dict: 處理後的 Lark 格式資料
        """
        return self._process_single_issue_with_mappings(issue_key, raw_issue, self.field_mappings)
    
    def _process_single_issue_with_mappings(self, issue_key: str, raw_issue: Dict[str, Any], field_mappings: Dict[str, Any], excluded_fields: List[str] = None) -> Dict[str, Any]:
        """
        使用指定映射處理單一 Issue 的欄位轉換
        
        Args:
            issue_key: Issue Key
            raw_issue: JIRA 原始資料
            field_mappings: 欄位映射配置
            excluded_fields: 排除不同步的欄位清單
            
        Returns:
            Dict: 處理後的 Lark 格式資料
        """
        processed_data = {}
        issue_fields = raw_issue.get('fields', {})
        excluded_fields = excluded_fields or []
        
        # 處理每個配置的欄位對應
        for jira_field, config in field_mappings.items():
            # 檢查是否在排除清單中
            if jira_field in excluded_fields:
                if self.logger:
                    self.logger.debug(f"Issue {issue_key} 跳過排除欄位: {jira_field}")
                continue
            lark_field = config['lark_field']
            processor = config['processor']
            
            try:
                # 從 JIRA 資料中提取原始值
                # 特殊處理 key 欄位，它在 raw_issue 頂層而不在 fields 中
                if jira_field == 'key':
                    raw_value = raw_issue.get('key')
                else:
                    raw_value = self._extract_raw_value(issue_fields, jira_field, issue_key)
                
                # 根據 processor 類型處理資料
                processed_value = self._apply_processor(processor, raw_value, jira_field, issue_key, config)
                
                # 設定到 Lark 欄位
                processed_data[lark_field] = processed_value
                
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Issue {issue_key} 欄位 {jira_field} 處理失敗: {e}")
                # 設定為 None 而不是拋出異常
                processed_data[lark_field] = None
        
        return processed_data
    
    def _extract_raw_value(self, issue_fields: Dict[str, Any], jira_field: str, issue_key: str) -> Any:
        """
        從 JIRA issue fields 中提取原始值
        
        Args:
            issue_fields: JIRA issue 的 fields 物件
            jira_field: JIRA 欄位路徑（如 "status.name"）
            issue_key: Issue Key（用於錯誤訊息）
            
        Returns:
            Any: 提取的原始值
        """
        try:
            # 處理嵌套欄位（如 status.name）
            if '.' in jira_field:
                parts = jira_field.split('.')
                value = issue_fields
                for part in parts:
                    if value is None:
                        return None
                    if isinstance(value, dict):
                        value = value.get(part)
                    else:
                        # 如果當前值不是字典，無法繼續嵌套取值
                        return None
                return value
            else:
                # 直接欄位
                return issue_fields.get(jira_field)
                
        except Exception as e:
            if self.logger:
                self.logger.debug(f"提取欄位 {jira_field} 失敗 (Issue: {issue_key}): {e}")
            return None
    
    def _apply_processor(self, processor: str, raw_value: Any, jira_field: str, issue_key: str, config: Dict[str, Any] = None) -> Any:
        """
        根據 processor 類型處理資料
        
        Args:
            processor: 處理器類型
            raw_value: 原始值
            jira_field: JIRA 欄位名稱
            issue_key: Issue Key（用於錯誤訊息）
            config: 欄位配置（可選）
            
        Returns:
            Any: 處理後的值
        """
        if raw_value is None:
            return None
        
        
        try:
            if processor == "extract_simple":
                return self._extract_simple(raw_value)
            elif processor == "extract_nested":
                return self._extract_nested(raw_value, config)
            elif processor == "extract_user":
                return self._extract_user(raw_value)
            elif processor == "convert_datetime":
                return self._convert_datetime(raw_value)
            elif processor == "extract_components":
                return self._extract_components(raw_value, config)
            elif processor == "extract_versions":
                return self._extract_versions(raw_value, config)
            elif processor == "extract_links":
                return self._extract_links(raw_value, config)
            elif processor == "extract_links_filtered":
                return self._extract_links_filtered(raw_value, issue_key, config)
            elif processor == "extract_ticket_link":
                return self._extract_ticket_link(raw_value)
            else:
                if self.logger:
                    self.logger.warning(f"未知的處理器類型: {processor}，使用 extract_simple")
                return self._extract_simple(raw_value)
                
        except Exception as e:
            raise FieldProcessorError(
                f"處理器 {processor} 處理失敗: {e}",
                field_name=jira_field,
                issue_key=issue_key
            )
    
    # === Processor 實作 ===
    
    def _extract_simple(self, value: Any) -> Any:
        """
        直接提取值，適用於字串和數字欄位
        
        Args:
            value: 原始值
            
        Returns:
            處理後的值，符合 field_processing.md 安全訪問原則
        """
        # 明確處理 None 值
        if value is None:
            return None
        
        # 處理基本資料類型
        if isinstance(value, (str, int, float, bool)):
            return value
        
        # 處理字典物件
        elif isinstance(value, dict):
            # 字典物件轉為 JSON 字串
            import json
            try:
                return json.dumps(value)
            except (TypeError, ValueError):
                return str(value)
        
        # 處理其他類型
        else:
            # 嘗試轉換為字串
            try:
                return str(value)
            except Exception:
                return None
    
    def _extract_nested(self, value: Any, config: Dict[str, Any] = None) -> Optional[str]:
        """
        提取嵌套物件的值
        
        Args:
            value: 原始值
            config: 欄位配置，包含 nested_path
            
        Returns:
            str: 提取的值，符合 field_processing.md 安全訪問原則
            對於嵌套欄位，None 值返回空字符串 ''，保持與舊版本一致
        """
        # 如果有 nested_path 配置，使用它來提取值
        if config and config.get('nested_path'):
            nested_path = config['nested_path']
            
            # 處理 None 值 - 返回空字符串以保持與舊版本一致
            if value is None:
                return ''
                
            # 確保 value 是字典才進行嵌套訪問
            if isinstance(value, dict):
                # 使用 get() 方法安全訪問，默認返回空字符串
                result = value.get(nested_path, '')
                # 如果結果是 None，返回空字符串
                return result if result is not None else ''
            else:
                # 如果不是字典，無法嵌套訪問，返回空字符串
                return ''
        
        # 否則直接返回值
        return self._extract_simple(value)
    
    def _extract_user(self, user_obj: Any) -> Optional[list]:
        """
        提取用戶資訊並進行映射
        
        Args:
            user_obj: JIRA 用戶物件
            
        Returns:
            list: Lark Base 人員欄位格式的列表，未找到則返回空陣列
        """
        if user_obj is None:
            return []
        
        # 如果有 UserMapper，使用非阻塞映射
        if self.user_mapper:
            try:
                # 使用 UserMapper 進行用戶映射
                lark_user_list = self.user_mapper.map_jira_user_to_lark(user_obj)
                return lark_user_list if lark_user_list is not None else []
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"用戶映射失敗: {e}")
                return []
        
        # 如果沒有 UserMapper，返回空陣列（Lark Base 人員欄位要求）
        # 統一返回空陣列，避免欄位格式問題
        return []
    
    def _convert_datetime(self, datetime_str: Any) -> Optional[int]:
        """
        轉換 JIRA 時間格式為 Lark 時間戳（毫秒）
        
        Args:
            datetime_str: JIRA 時間字串（ISO 8601 格式）
            
        Returns:
            int: Unix 時間戳（毫秒）或 None
        """
        if not datetime_str:
            return None
        
        if isinstance(datetime_str, str):
            try:
                # JIRA 時間格式: "2025-01-08T03:45:23.000+0000"
                # 移除毫秒和時區資訊進行解析
                clean_datetime = re.sub(r'\.\d{3}[+-]\d{4}$', '', datetime_str)
                if clean_datetime.endswith('Z'):
                    clean_datetime = clean_datetime[:-1]
                
                # 解析時間
                dt = datetime.fromisoformat(clean_datetime.replace('T', ' '))
                
                # 轉換為毫秒時間戳
                return int(dt.timestamp() * 1000)
                
            except Exception as e:
                if self.logger:
                    self.logger.debug(f"時間轉換失敗: {datetime_str} -> {e}")
                return None
        
        return None
    
    def _extract_components(self, components_array: Any, config: Dict[str, Any] = None) -> Any:
        """
        提取組件資訊
        
        Args:
            components_array: JIRA 組件陣列
            config: 欄位配置，包含 field_type
            
        Returns:
            list: 組件名稱列表（多選欄位）或 str: 組件名稱列表（逗號分隔）
        """
        if not components_array:
            # 根據欄位類型返回適當的空值
            if config and config.get('field_type') == 'multiselect':
                return []
            return None
        
        if isinstance(components_array, list):
            component_names = []
            for component in components_array:
                if isinstance(component, dict):
                    name = component.get('name')
                    if name:
                        component_names.append(name)
                elif isinstance(component, str):
                    component_names.append(component)
            
            # 根據配置的欄位類型返回適當格式
            if config and config.get('field_type') == 'multiselect':
                return component_names  # 返回列表用於多選欄位
            else:
                return ', '.join(component_names) if component_names else None
        
        # 對於非列表類型，根據欄位類型返回適當格式
        if config and config.get('field_type') == 'multiselect':
            return [str(components_array)]
        return str(components_array)
    
    def _extract_versions(self, versions_array: Any, config: Dict[str, Any] = None) -> Any:
        """
        提取版本資訊
        
        Args:
            versions_array: JIRA 版本陣列
            config: 欄位配置，包含 field_type
            
        Returns:
            list: 版本名稱列表（多選欄位）或 str: 版本名稱列表（逗號分隔）
        """
        if not versions_array:
            # 根據欄位類型返回適當的空值
            if config and config.get('field_type') == 'multiselect':
                return []
            return None
        
        if isinstance(versions_array, list):
            version_names = []
            for version in versions_array:
                if isinstance(version, dict):
                    name = version.get('name')
                    if name:
                        version_names.append(name)
                elif isinstance(version, str):
                    version_names.append(version)
            
            # 根據配置的欄位類型返回適當格式
            if config and config.get('field_type') == 'multiselect':
                return version_names  # 返回列表用於多選欄位
            else:
                return ', '.join(version_names) if version_names else None
        
        # 對於非列表類型，根據欄位類型返回適當格式
        if config and config.get('field_type') == 'multiselect':
            return [str(versions_array)]
        return str(versions_array)
    
    def _extract_links(self, links_array: Any, config: Dict[str, Any] = None) -> Any:
        """
        提取關聯連結資訊，並格式化為 "link_type: JIRA_URL" 形式
        
        Args:
            links_array: JIRA issuelinks 陣列
            config: 欄位配置，包含 field_type
            
        Returns:
            list: 格式化後的關聯 Issue 列表（多選欄位）或 str: 格式化後的關聯 Issue 列表（換行符分隔）
        """
        if not links_array or not self.jira_server_url:
            # 根據欄位類型返回適當的空值
            if config and config.get('field_type') == 'multiselect':
                return []
            return None
        
        if isinstance(links_array, list):
            if config and config.get('field_type') == 'multiselect':
                # 多選欄位模式：返回 issue keys 列表
                issue_keys = []
                for link in links_array:
                    if isinstance(link, dict):
                        outward = link.get('outwardIssue', {})
                        inward = link.get('inwardIssue', {})
                        
                        # 處理 outward 連結
                        if outward and outward.get('key'):
                            issue_keys.append(outward['key'])
                        
                        # 處理 inward 連結
                        if inward and inward.get('key'):
                            issue_keys.append(inward['key'])
                
                return issue_keys
            else:
                # 文字欄位模式：返回格式化的連結字串
                formatted_links = []
                for link in links_array:
                    if isinstance(link, dict):
                        type_info = link.get('type', {})
                        outward = link.get('outwardIssue', {})
                        inward = link.get('inwardIssue', {})
                        
                        # 處理 outward 連結
                        if outward and outward.get('key') and type_info.get('outward'):
                            issue_key = outward['key']
                            link_type = type_info['outward']
                            jira_url = f"{self.jira_server_url}/browse/{issue_key}"
                            formatted_links.append(f"{link_type}: {jira_url}")
                        
                        # 處理 inward 連結
                        if inward and inward.get('key') and type_info.get('inward'):
                            issue_key = inward['key']
                            link_type = type_info['inward']
                            jira_url = f"{self.jira_server_url}/browse/{issue_key}"
                            formatted_links.append(f"{link_type}: {jira_url}")
                
                return '\n'.join(formatted_links) if formatted_links else None
        
        # 對於非列表類型，根據欄位類型返回適當格式
        if config and config.get('field_type') == 'multiselect':
            return [str(links_array)]
        return str(links_array)
    
    def _extract_links_filtered(self, links_array: Any, issue_key: str, config: Dict[str, Any] = None) -> Any:
        """
        根據配置規則過濾並提取關聯連結資訊
        
        Args:
            links_array: JIRA issuelinks 陣列
            issue_key: 當前 issue 的 key，用於決定適用的過濾規則
            config: 欄位配置，包含 field_type
            
        Returns:
            list: 過濾後格式化的關聯 Issue 列表（多選欄位）或 str: 過濾後格式化的關聯 Issue 列表（換行符分隔）
        """
        if not links_array or not self.jira_server_url:
            # 根據欄位類型返回適當的空值
            if config and config.get('field_type') == 'multiselect':
                return []
            return None
        
        # 取得當前 issue 的前綴
        current_prefix = self._get_issue_key_prefix(issue_key)
        
        # 根據前綴找到適用規則
        rules = self.issue_link_rules.get(current_prefix, self.issue_link_rules.get('default', {}))
        
        # 如果規則未啟用，返回原始結果
        if not rules.get('enabled', True):
            return self._extract_links(links_array, config)
        
        # 獲取允許顯示的前綴列表
        allowed_prefixes = rules.get('display_link_prefixes', [])
        if not allowed_prefixes:  # 空陣列表示顯示所有
            return self._extract_links(links_array, config)
        
        # 過濾並格式化連結
        if isinstance(links_array, list):
            filtered_links = []
            for link in links_array:
                if isinstance(link, dict):
                    allowed_keys = self._format_single_link_if_allowed(link, allowed_prefixes)
                    filtered_links.extend(allowed_keys)
            
            # 根據配置的欄位類型返回適當格式
            if config and config.get('field_type') == 'multiselect':
                return filtered_links  # 返回列表用於多選欄位（issue keys）
            else:
                # 對於文字欄位，需要重新格式化為 "link_type: URL" 格式
                formatted_text_links = []
                for link in links_array:
                    if isinstance(link, dict):
                        type_info = link.get('type', {})
                        outward = link.get('outwardIssue', {})
                        inward = link.get('inwardIssue', {})
                        
                        # 處理 outward 連結
                        if outward and outward.get('key') and type_info.get('outward'):
                            issue_key = outward['key']
                            linked_prefix = self._get_issue_key_prefix(issue_key)
                            if linked_prefix in allowed_prefixes:
                                link_type = type_info['outward']
                                jira_url = f"{self.jira_server_url}/browse/{issue_key}"
                                formatted_text_links.append(f"{link_type}: {jira_url}")
                        
                        # 處理 inward 連結
                        if inward and inward.get('key') and type_info.get('inward'):
                            issue_key = inward['key']
                            linked_prefix = self._get_issue_key_prefix(issue_key)
                            if linked_prefix in allowed_prefixes:
                                link_type = type_info['inward']
                                jira_url = f"{self.jira_server_url}/browse/{issue_key}"
                                formatted_text_links.append(f"{link_type}: {jira_url}")
                
                return '\n'.join(formatted_text_links) if formatted_text_links else None
        
        return str(links_array)
    
    def _get_issue_key_prefix(self, issue_key: str) -> str:
        """
        提取 Issue Key 的前綴（例如 TCG-108387 → TCG）
        
        Args:
            issue_key: JIRA Issue Key
            
        Returns:
            str: Issue Key 前綴，如果無法提取則返回空字串
        """
        if not issue_key or not isinstance(issue_key, str):
            return ""
        
        # 使用正則表達式匹配前綴
        match = re.match(r'^([A-Z]+)-', issue_key.strip().upper())
        return match.group(1) if match else ""
    
    def _format_single_link_if_allowed(self, link: Dict, allowed_prefixes: List[str]) -> List[str]:
        """
        格式化單個連結，如果其前綴在允許列表中，返回 issue key 列表
        
        Args:
            link: 單個 issue link 字典
            allowed_prefixes: 允許顯示的前綴列表
            
        Returns:
            List[str]: 允許顯示的 issue key 列表
        """
        result_keys = []
        outward = link.get('outwardIssue', {})
        inward = link.get('inwardIssue', {})
        
        # 處理 outward 連結
        if outward and outward.get('key'):
            issue_key = outward['key']
            linked_prefix = self._get_issue_key_prefix(issue_key)
            if linked_prefix in allowed_prefixes:
                result_keys.append(issue_key)
        
        # 處理 inward 連結
        if inward and inward.get('key'):
            issue_key = inward['key']
            linked_prefix = self._get_issue_key_prefix(issue_key)
            if linked_prefix in allowed_prefixes:
                result_keys.append(issue_key)
        
        return result_keys
    
    def _extract_ticket_link(self, value: Any) -> Optional[str]:
        """
        將 JIRA Issue Key 轉換為超連結格式，支援多種輸入格式
        
        Args:
            value: JIRA Issue Key 或包含 Issue Key 的任何格式
            
        Returns:
            Optional[str]: 超連結格式的字串，如果輸入無效則返回 None
        """
        if not value:
            return None
        
        # 處理不同類型的輸入
        issue_key = None
        
        if isinstance(value, str):
            # 直接是字串
            issue_key = value.strip()
        elif isinstance(value, dict):
            # 可能是 JIRA 物件，嘗試取得 key
            issue_key = value.get('key') or value.get('id') or str(value)
        elif isinstance(value, list) and len(value) > 0:
            # 可能是陣列，取第一個元素
            first_item = value[0]
            if isinstance(first_item, dict):
                issue_key = first_item.get('key') or first_item.get('id') or str(first_item)
            else:
                issue_key = str(first_item)
        else:
            # 其他類型，轉為字串
            issue_key = str(value).strip()
        
        if not issue_key or issue_key == 'None':
            return None
        
        # 產生 JIRA 超連結
        jira_url = f"{self.jira_server_url}/browse/{issue_key}"
        
        # 返回 Lark Base 期望的超連結格式
        # 嘗試多種可能的格式
        return {
            "text": issue_key,
            "link": jira_url
        }
    
    def get_supported_processors(self) -> List[str]:
        """取得支援的處理器清單"""
        return [
            "extract_simple",
            "extract_nested", 
            "extract_user",
            "convert_datetime",
            "extract_components",
            "extract_versions",
            "extract_links",
            "extract_links_filtered",
            "extract_ticket_link"
        ]
    
    def get_required_jira_fields(self) -> List[str]:
        """
        獲取 schema 中定義的所有 JIRA 欄位
        用於優化 JIRA 查詢性能，只獲取需要的欄位
        
        Returns:
            List[str]: JIRA 欄位清單
        """
        # 從 field_mappings 中提取所有 JIRA 欄位
        jira_fields = list(self.field_mappings.keys())
        
        # 添加基本必需欄位
        essential_fields = ['key', 'id', 'self']
        
        # 合併並去重
        all_fields = list(set(jira_fields + essential_fields))
        
        if self.logger:
            self.logger.info(f"優化 JIRA 查詢：只獲取 {len(all_fields)} 個必要欄位")
            self.logger.debug(f"必要欄位列表: {sorted(all_fields)}")
        
        return all_fields
    
    def validate_schema(self) -> bool:
        """
        驗證 schema 配置的正確性
        
        Returns:
            bool: 是否有效
        """
        try:
            # 檢查 field_mappings 結構
            if not isinstance(self.field_mappings, dict):
                if self.logger:
                    self.logger.error("field_mappings 必須是字典格式")
                return False
            
            supported_processors = self.get_supported_processors()
            
            for jira_field, config in self.field_mappings.items():
                # 檢查配置結構
                if not isinstance(config, dict):
                    if self.logger:
                        self.logger.error(f"欄位 {jira_field} 配置必須是字典格式")
                    return False
                
                # 檢查必要欄位
                if 'lark_field' not in config:
                    if self.logger:
                        self.logger.error(f"欄位 {jira_field} 缺少 lark_field 配置")
                    return False
                
                if 'processor' not in config:
                    if self.logger:
                        self.logger.error(f"欄位 {jira_field} 缺少 processor 配置")
                    return False
                
                # 檢查 processor 是否支援
                processor = config['processor']
                if processor not in supported_processors:
                    if self.logger:
                        self.logger.warning(f"欄位 {jira_field} 使用未知的處理器: {processor}")
            
            if self.logger:
                self.logger.info("Schema 配置驗證通過")
            return True
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Schema 驗證失敗: {e}")
            return False


# 使用範例
if __name__ == '__main__':
    # 建立欄位處理器
    processor = FieldProcessor()
    
    # 驗證 schema
    if processor.validate_schema():
        print("✓ Schema 配置有效")
    else:
        print("✗ Schema 配置有問題")
    
    # 模擬 JIRA 原始資料
    mock_jira_data = {
        'TP-001': {
            'key': 'TP-001',
            'fields': {
                'summary': 'Test Issue 1',
                'status': {'name': 'Open'},
                'assignee': {'displayName': 'John Doe', 'name': 'john.doe'},
                'created': '2025-01-08T03:45:23.000+0000',
                'components': [{'name': 'Backend'}, {'name': 'API'}],
                'issuelinks': [
                    {'outwardIssue': {'key': 'TP-002'}},
                    {'inwardIssue': {'key': 'TP-003'}}
                ]
            }
        }
    }
    
    try:
        # 處理資料
        processed_data = processor.process_issues(mock_jira_data)
        print(f"✓ 處理完成: {len(processed_data)} 筆")
        
        # 顯示處理結果
        for key, data in processed_data.items():
            print(f"\n{key}:")
            for field, value in data.items():
                print(f"  {field}: {value}")
                
    except Exception as e:
        print(f"✗ 處理失敗: {e}")