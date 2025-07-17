#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JIRA-Lark 同步系統 Web 介面
專注於配置管理和工具功能，採用 Gmail 風格的雙欄式佈局
"""

import os
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

# 導入現有系統模組
from config_manager import ConfigManager
from logger import setup_logging

app = Flask(__name__)

# 全局變量
config_manager = None
yaml_handler = None
logger = None

# 文件鎖，防止多人同時編輯
config_lock = threading.Lock()


class YAMLHandler:
    """YAML 配置檔案處理器，保留註解和格式"""
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.width = 4096
        self.yaml.indent(mapping=2, sequence=4, offset=2)
    
    def load_config(self):
        """載入配置檔案，保留註解和格式"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return self.yaml.load(f)
        except Exception as e:
            if logger:
                logger.logger.error(f"載入配置檔案失敗: {e}")
            return None
    
    def save_config(self, config_data):
        """保存配置檔案，保留註解和格式"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                self.yaml.dump(config_data, f)
            return True
        except Exception as e:
            if logger:
                logger.logger.error(f"保存配置檔案失敗: {e}")
            return False




def init_app():
    """初始化應用程式"""
    global config_manager, yaml_handler, logger
    
    # 初始化日誌系統
    log_config = {
        'log_level': 'INFO',
        'log_file': 'web_app.log',
        'max_size': '10MB',
        'backup_count': 3
    }
    logger = setup_logging(log_config)
    
    # 初始化配置管理器
    config_manager = ConfigManager(logger, 'config.yaml')
    yaml_handler = YAMLHandler('config.yaml')
    
    logger.logger.info("Web 應用程式初始化完成")


@app.route('/')
def index():
    """首頁 - 重定向到團隊配置"""
    from flask import redirect, url_for
    return redirect(url_for('teams'))


@app.route('/teams')
def teams():
    """團隊配置管理頁面"""
    config_data = yaml_handler.load_config()
    teams_config = config_data.get('teams', {}) if config_data else {}
    
    # 統計資料
    stats = {
        'total_teams': len(teams_config),
        'total_tables': sum(len(team.get('tables', {})) for team in teams_config.values()),
        'config_file': 'config.yaml',
        'last_modified': datetime.fromtimestamp(os.path.getmtime('config.yaml')).strftime('%Y-%m-%d %H:%M:%S') if os.path.exists('config.yaml') else 'N/A'
    }
    
    return render_template('teams.html', teams=teams_config, stats=stats)








# API 路由

@app.route('/api/config/teams', methods=['GET'])
def api_get_teams():
    """獲取團隊配置 API"""
    try:
        config_data = yaml_handler.load_config()
        teams = config_data.get('teams', {}) if config_data else {}
        
        # 轉換為列表格式，便於前端處理
        teams_list = []
        for team_name, team_config in teams.items():
            team_info = {
                'name': team_name,
                'config': team_config,
                'tables': list(team_config.get('tables', {}).keys()) if isinstance(team_config.get('tables'), dict) else []
            }
            teams_list.append(team_info)
        
        return jsonify({'teams': teams_list})
    
    except Exception as e:
        logger.logger.error(f"獲取團隊配置失敗: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/teams/<team_name>', methods=['PUT'])
def api_update_team(team_name):
    """更新團隊配置 API"""
    try:
        with config_lock:
            config_data = yaml_handler.load_config()
            if not config_data:
                return jsonify({'error': '無法載入配置檔案'}), 500
            
            team_config = request.json
            
            # 更新團隊配置
            if 'teams' not in config_data:
                config_data['teams'] = CommentedMap()
            
            # 保留現有的 wiki_token 如果存在
            if team_name in config_data['teams'] and 'wiki_token' in config_data['teams'][team_name]:
                team_config['wiki_token'] = config_data['teams'][team_name]['wiki_token']
            
            config_data['teams'][team_name] = team_config
            
            # 保存配置
            if yaml_handler.save_config(config_data):
                logger.logger.info(f"團隊 {team_name} 配置已更新")
                return jsonify({'message': '配置更新成功'})
            else:
                return jsonify({'error': '配置保存失敗'}), 500
    
    except Exception as e:
        logger.logger.error(f"更新團隊配置失敗: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/teams/<team_name>', methods=['DELETE'])
def api_delete_team(team_name):
    """刪除團隊配置 API"""
    try:
        with config_lock:
            config_data = yaml_handler.load_config()
            if not config_data:
                return jsonify({'error': '無法載入配置檔案'}), 500
            
            teams = config_data.get('teams', {})
            if team_name in teams:
                del teams[team_name]
                
                if yaml_handler.save_config(config_data):
                    logger.logger.info(f"團隊 {team_name} 已刪除")
                    return jsonify({'message': '團隊刪除成功'})
                else:
                    return jsonify({'error': '配置保存失敗'}), 500
            else:
                return jsonify({'error': '團隊不存在'}), 404
    
    except Exception as e:
        logger.logger.error(f"刪除團隊配置失敗: {e}")
        return jsonify({'error': str(e)}), 500









if __name__ == '__main__':
    # 初始化應用程式
    init_app()
    
    # 確保必要目錄存在
    os.makedirs('static', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('data', exist_ok=True)
    
    logger.logger.info("🚀 JIRA-Lark 同步系統 Web 介面啟動中...")
    logger.logger.info("🎨 Gmail 風格的雙欄式佈局")
    logger.logger.info("🌐 訪問 http://localhost:8889 查看")
    logger.logger.info("📋 可用頁面:")
    logger.logger.info("   • 團隊配置: / (預設頁面)")
    logger.logger.info("✨ 特色功能:")
    logger.logger.info("   • 配置檔案管理（保留註解和格式）")
    logger.logger.info("   • 多人編輯防衝突")
    
    app.run(debug=True, host='0.0.0.0', port=8888)