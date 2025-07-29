#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JIRA-Lark 同步系統 Web 介面
專注於配置管理和工具功能，採用 Gmail 風格的雙欄式佈局
"""

import os
import shutil
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

# 導入現有系統模組
from config_manager import ConfigManager
from logger import setup_logging
from user_id_fixer import UserIdFixer
from lark_client import LarkClient


def mask_user_id(user_id):
    """遮蔽 User ID 的中間15位字符以保護隱私"""
    if not user_id or len(user_id) < 20:
        return user_id
    
    # 格式: ou_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx (35字符總長度)
    # 顯示: ou_xxxxx***************xxxxx (前10碼 + 15個* + 後10碼)
    prefix = user_id[:10]
    suffix = user_id[-10:]
    masked = prefix + '***************' + suffix
    
    return masked

app = Flask(__name__)

# 全局變量
config_manager = None
yaml_handler = None
logger = None
user_fixer = None
lark_client = None

# 文件鎖，防止多人同時編輯
config_lock = threading.Lock()


class YAMLHandler:
    """YAML 配置檔案處理器，保留註解和格式"""
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.backup_dir = 'config_backup'
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.width = 4096
        self.yaml.indent(mapping=2, sequence=4, offset=2)
        
        # 確保備份目錄存在
        os.makedirs(self.backup_dir, exist_ok=True)
    
    def load_config(self):
        """載入配置檔案，保留註解和格式"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return self.yaml.load(f)
        except Exception as e:
            if logger:
                logger.logger.error(f"載入配置檔案失敗: {e}")
            return None
    
    def backup_config(self):
        """創建配置檔案備份"""
        try:
            if not os.path.exists(self.config_path):
                return None
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_filename = f'config_{timestamp}.yaml'
            backup_path = os.path.join(self.backup_dir, backup_filename)
            
            shutil.copy2(self.config_path, backup_path)
            
            if logger:
                logger.logger.info(f"配置檔案已備份至: {backup_path}")
            
            return backup_path
        except Exception as e:
            if logger:
                logger.logger.error(f"備份配置檔案失敗: {e}")
            return None
    
    def save_config(self, config_data):
        """保存配置檔案，保留註解和格式"""
        try:
            # 保存前先備份
            backup_path = self.backup_config()
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                self.yaml.dump(config_data, f)
            
            if logger and backup_path:
                logger.logger.info(f"配置檔案已更新，備份位置: {backup_path}")
            
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


def init_user_management():
    """初始化用戶管理組件"""
    global user_fixer, lark_client, config_manager, logger
    
    try:
        if not config_manager:
            init_app()
        
        # 獲取 Lark 配置
        lark_config = config_manager.get_lark_base_config()
        
        # 初始化 Lark 客戶端
        lark_client = LarkClient(lark_config['app_id'], lark_config['app_secret'])
        
        # 初始化用戶 ID 修復器
        user_fixer = UserIdFixer('data/user_mapping_cache.db', lark_client)
        
        logger.logger.info("用戶管理組件初始化完成")
        return True
        
    except Exception as e:
        if logger:
            logger.logger.error(f"用戶管理組件初始化失敗: {e}")
        return False


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


@app.route('/user_management')
def user_management():
    """人員對應管理頁面"""
    return render_template('user_management.html')


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


# 用戶管理 API 路由

@app.route('/api/users/mapped')
def api_get_mapped_users():
    """獲取已對應用戶列表 API"""
    try:
        if not init_user_management():
            return jsonify({'error': '用戶管理組件初始化失敗'}), 500
        
        # 獲取所有有 email 的用戶
        all_users = user_fixer.get_users_with_email()
        
        # 過濾出已有 lark_user_id 的用戶並遮蔽 User ID
        mapped_users = []
        for user in all_users:
            if user.get('lark_user_id') and user['lark_user_id'].strip():
                # 創建用戶副本並遮蔽 User ID
                masked_user = user.copy()
                masked_user['lark_user_id'] = mask_user_id(user['lark_user_id'])
                mapped_users.append(masked_user)
        
        return jsonify(mapped_users)
        
    except Exception as e:
        logger.logger.error(f"獲取已對應用戶失敗: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/unmapped')
def api_get_unmapped_users():
    """獲取未對應用戶列表 API（所有沒有 lark_user_id 的用戶）"""
    try:
        if not init_user_management():
            return jsonify({'error': '用戶管理組件初始化失敗'}), 500
        
        # 直接查詢數據庫獲取所有沒有 lark_user_id 的用戶
        import sqlite3
        unmapped_users = []
        
        with sqlite3.connect('data/user_mapping_cache.db') as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT username, lark_email, lark_name
                FROM user_mappings 
                WHERE username IS NOT NULL 
                  AND (lark_user_id IS NULL OR lark_user_id = '')
                ORDER BY username
            """)
            
            columns = ['username', 'lark_email', 'lark_name']
            unmapped_users = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        return jsonify(unmapped_users)
        
    except Exception as e:
        logger.logger.error(f"獲取未對應用戶失敗: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/query', methods=['POST'])
def api_query_user():
    """查詢 Lark 用戶 API"""
    try:
        if not init_user_management():
            return jsonify({'error': '用戶管理組件初始化失敗'}), 500
        
        data = request.get_json()
        if not data or not data.get('email'):
            return jsonify({'error': '請提供 email 地址'}), 400
        
        email = data['email'].strip()
        if not email:
            return jsonify({'error': 'Email 地址不能為空'}), 400
        
        # 查詢 Lark 用戶
        user_info = user_fixer.query_lark_user_by_email(email)
        
        if user_info:
            # 遮蔽返回的 User ID
            masked_user_info = user_info.copy()
            masked_user_info['user_id'] = mask_user_id(user_info['user_id'])
            
            return jsonify({
                'success': True,
                'user_info': masked_user_info,
                'original_user_id': user_info['user_id']  # 保留原始 ID 供內部使用
            })
        else:
            return jsonify({
                'success': False,
                'message': f'在 Lark 中找不到 email: {email}'
            })
            
    except Exception as e:
        logger.logger.error(f"查詢用戶失敗: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/create', methods=['POST'])
def api_create_user_mapping():
    """創建用戶對應 API"""
    try:
        if not init_user_management():
            return jsonify({'error': '用戶管理組件初始化失敗'}), 500
        
        data = request.get_json()
        if not data:
            return jsonify({'error': '請提供用戶數據'}), 400
        
        username = data.get('username', '').strip()
        user_id = data.get('user_id', '').strip()
        original_user_id = data.get('original_user_id', '').strip()
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        
        # 使用原始 User ID 進行操作，如果沒有則使用傳入的 user_id
        actual_user_id = original_user_id if original_user_id else user_id
        
        if not username or not actual_user_id:
            return jsonify({'error': '用戶名和用戶 ID 不能為空'}), 400
        
        # 創建用戶對應（實際執行，非 dry_run）
        success = user_fixer.update_user_id(username, actual_user_id, name, email, dry_run=False)
        
        if success:
            masked_id = mask_user_id(actual_user_id)
            logger.logger.info(f"成功創建用戶對應: {username} -> {masked_id}")
            return jsonify({
                'success': True,
                'message': '用戶對應創建成功'
            })
        else:
            return jsonify({
                'success': False,
                'error': '創建用戶對應失敗'
            }), 500
            
    except Exception as e:
        logger.logger.error(f"創建用戶對應失敗: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # 初始化應用程式
    init_app()
    
    # 確保必要目錄存在
    os.makedirs('static', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('data', exist_ok=True)
    os.makedirs('config_backup', exist_ok=True)
    
    logger.logger.info("🚀 JIRA-Lark 同步系統 Web 介面啟動中...")
    logger.logger.info("🎨 Gmail 風格的雙欄式佈局")
    logger.logger.info("🌐 訪問 http://localhost:8889 查看")
    logger.logger.info("📋 可用頁面:")
    logger.logger.info("   • 團隊配置: / (預設頁面)")
    logger.logger.info("✨ 特色功能:")
    logger.logger.info("   • 配置檔案管理（保留註解和格式）")
    logger.logger.info("   • 多人編輯防衝突")
    
    app.run(debug=True, host='0.0.0.0', port=8888)