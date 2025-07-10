#!/usr/bin/env python3
"""
YAML 工具函數
支援保留註解的 YAML 讀寫操作，適用於 schema.yaml 和 config.yaml
"""

import os
from typing import Dict, Any
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString


def load_yaml_with_comments(yaml_file: str) -> Dict[str, Any]:
    """
    載入 YAML 文件，保留註解
    
    Args:
        yaml_file: YAML 檔案路徑
        
    Returns:
        Dict: YAML 數據
    """
    if not os.path.exists(yaml_file):
        raise FileNotFoundError(f"YAML 檔案不存在: {yaml_file}")
    
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096  # 避免長行被折行
    
    with open(yaml_file, 'r', encoding='utf-8') as f:
        return yaml.load(f)


def save_yaml_with_comments(yaml_file: str, data: Dict[str, Any]):
    """
    保存 YAML 文件，保留註解和格式
    
    Args:
        yaml_file: YAML 檔案路徑
        data: 要保存的數據
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096  # 避免長行被折行
    yaml.indent(mapping=2, sequence=4, offset=2)
    
    with open(yaml_file, 'w', encoding='utf-8') as f:
        yaml.dump(data, f)


# 向後相容的函數別名
def load_schema_with_comments(schema_file: str) -> Dict[str, Any]:
    """載入 schema.yaml 文件，保留註解（向後相容）"""
    return load_yaml_with_comments(schema_file)


def save_schema_with_comments(schema_file: str, data: Dict[str, Any]):
    """保存 schema.yaml 文件，保留註解和格式（向後相容）"""
    save_yaml_with_comments(schema_file, data)


def add_field_mapping_with_comments(schema_file: str, jira_field: str, lark_field: str, processor: str = 'extract_simple', **kwargs):
    """
    向 schema.yaml 添加新的欄位映射，保留註解
    
    Args:
        schema_file: schema 檔案路徑
        jira_field: JIRA 欄位名稱
        lark_field: Lark 欄位名稱
        processor: 處理器類型
        **kwargs: 其他配置參數（如 nested_path, field_type）
    """
    # 載入現有數據
    data = load_schema_with_comments(schema_file)
    
    # 確保 field_mappings 存在
    if 'field_mappings' not in data:
        data['field_mappings'] = {}
    
    # 創建新的欄位配置
    field_config = {
        'lark_field': lark_field,
        'processor': processor
    }
    
    # 添加其他配置
    for key, value in kwargs.items():
        if value:  # 只添加非空值
            field_config[key] = value
    
    # 添加到 field_mappings
    data['field_mappings'][jira_field] = field_config
    
    # 保存文件
    save_schema_with_comments(schema_file, data)


def update_field_mappings_with_comments(schema_file: str, field_mappings: Dict[str, Dict[str, Any]]):
    """
    批量更新 field_mappings，保留註解
    
    Args:
        schema_file: schema 檔案路徑
        field_mappings: 欄位映射字典
    """
    # 載入現有數據
    data = load_schema_with_comments(schema_file)
    
    # 更新 field_mappings
    data['field_mappings'] = field_mappings
    
    # 保存文件
    save_schema_with_comments(schema_file, data)


def update_config_with_comments(config_file: str, config_updates: Dict[str, Any]):
    """
    更新 config.yaml 文件，保留註解
    
    Args:
        config_file: config 檔案路徑
        config_updates: 要更新的配置字典
    """
    # 載入現有數據
    data = load_yaml_with_comments(config_file)
    
    # 遞歸更新配置
    def deep_update(target: Dict[str, Any], source: Dict[str, Any]):
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                deep_update(target[key], value)
            else:
                target[key] = value
    
    deep_update(data, config_updates)
    
    # 保存文件
    save_yaml_with_comments(config_file, data)


def update_config_section_with_comments(config_file: str, section: str, section_data: Dict[str, Any]):
    """
    更新 config.yaml 中的特定區段，保留註解
    
    Args:
        config_file: config 檔案路徑
        section: 區段名稱（如 'global', 'jira', 'lark_base'）
        section_data: 區段數據
    """
    # 載入現有數據
    data = load_yaml_with_comments(config_file)
    
    # 更新指定區段
    if section in data:
        data[section].update(section_data)
    else:
        data[section] = section_data
    
    # 保存文件
    save_yaml_with_comments(config_file, data)


# 使用範例
if __name__ == '__main__':
    # 測試載入和保存
    schema_file = 'schema.yaml'
    
    try:
        # 測試載入
        data = load_schema_with_comments(schema_file)
        print(f"載入成功，包含 {len(data.get('field_mappings', {}))} 個欄位映射")
        
        # 測試添加新欄位
        add_field_mapping_with_comments(
            schema_file,
            'test_field',
            'Test Field',
            'extract_simple'
        )
        print("測試欄位添加成功")
        
        # 驗證添加結果
        updated_data = load_schema_with_comments(schema_file)
        if 'test_field' in updated_data.get('field_mappings', {}):
            print("✓ 測試欄位已成功添加")
        else:
            print("✗ 測試欄位添加失敗")
            
    except Exception as e:
        print(f"測試失敗: {e}")