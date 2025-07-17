#!/usr/bin/env python3
"""
JIRA-Lark 同步系統 Web 介面啟動腳本
"""

import os
import sys

# 確保必要的目錄存在
os.makedirs('static/css', exist_ok=True)
os.makedirs('templates', exist_ok=True)
os.makedirs('data', exist_ok=True)

# 檢查必要檔案是否存在
required_files = [
    'web_app.py',
    'templates/base.html',
    'templates/teams.html',
    'static/css/style.css'
]

missing_files = []
for file_path in required_files:
    if not os.path.exists(file_path):
        missing_files.append(file_path)

if missing_files:
    print("❌ 缺少必要檔案:")
    for file_path in missing_files:
        print(f"   - {file_path}")
    print("\n請先完成 web 介面檔案的建立")
    sys.exit(1)

# 檢查配置檔案
if not os.path.exists('config.yaml'):
    print("⚠️  警告: 找不到 config.yaml，某些功能可能無法正常運作")

print("🚀 啟動 JIRA-Lark 同步系統 Web 介面...")
print("🌐 服務將在 http://localhost:8888 啟動")
print("📋 可用功能:")
print("   • 團隊配置管理")
print()

# 啟動 Flask 應用
try:
    from web_app import app, init_app
    
    # 初始化應用
    init_app()
    
    # 啟動服務
    app.run(debug=True, host='0.0.0.0', port=8888)
    
except ImportError as e:
    print(f"❌ 模組導入失敗: {e}")
    print("請確保所有依賴模組都已正確安裝")
    sys.exit(1)
except Exception as e:
    print(f"❌ 啟動失敗: {e}")
    sys.exit(1)