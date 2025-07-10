#!/usr/bin/env python3
"""
JIRA-Lark 同步系統 Web 服務啟動腳本
提供更好的信號處理和優雅關閉功能
"""

import signal
import sys
import threading
import time
from web_api import app, api

class WebServerManager:
    """Web 服務器管理器"""
    
    def __init__(self):
        self.running = True
        self.setup_signal_handlers()
    
    def setup_signal_handlers(self):
        """設置信號處理器"""
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Windows 支援
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, self.signal_handler)
    
    def signal_handler(self, signum, _frame):
        """處理中斷信號"""
        print(f"\n收到信號 {signum}，正在優雅關閉...")
        self.running = False
        
        # 停止同步服務
        if api:
            try:
                print("停止所有同步服務...")
                api.stop_all_sync()
                
                if api.daemon_running:
                    api.daemon_running = False
                        
                print("同步服務已停止")
            except Exception as e:
                print(f"停止同步服務時發生錯誤: {e}")
        
        print("Web 服務器正在關閉...")
        
        # 優雅退出，不使用 os._exit
        sys.exit(0)
    
    def run(self):
        """運行服務器"""
        try:
            print("🌐 啟動 JIRA-Lark 同步系統 Web API...")
            print("📡 API 端點:")
            print("  GET  /api/status          - 獲取系統狀態")
            print("  GET  /api/teams           - 獲取團隊狀態")
            print("  POST /api/sync/start      - 開始所有同步")
            print("  POST /api/sync/stop       - 停止所有同步")
            print("  POST /api/sync/full-update - 執行全量更新")
            print("  GET  /api/test/jira       - 測試 JIRA 連線")
            print("  POST /api/test/lark       - 測試 Lark 連線")
            print("  POST /api/jql/validate    - 驗證 JQL 語法")
            print("  POST /api/jql/test        - 測試 JQL 查詢")
            print("\n🌍 Web 介面: http://localhost:8888")
            print("📋 按 Ctrl+C 停止服務器")
            print("💡 如果 Ctrl+C 無效，請嘗試 Ctrl+Break 或關閉終端視窗\n")
            
            # 在單獨線程中運行 Flask
            flask_thread = threading.Thread(
                target=self.run_flask,
                daemon=True  # 設為守護線程，主程序結束時自動結束
            )
            flask_thread.start()
            
            # 主線程監控運行狀態
            while self.running:
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\n收到鍵盤中斷")
        except Exception as e:
            print(f"啟動錯誤: {e}")
        finally:
            self.cleanup()
    
    def run_flask(self):
        """運行 Flask 應用"""
        try:
            app.run(
                host='0.0.0.0',
                port=8888,
                debug=False,
                use_reloader=False,
                threaded=True
            )
        except Exception as e:
            print(f"Flask 運行錯誤: {e}")
            self.running = False
    
    def cleanup(self):
        """清理資源"""
        print("正在清理資源...")
        self.running = False
        
        if api:
            try:
                api.stop_all_sync()
            except:
                pass
        
        print("資源清理完成，服務器已關閉")

def main():
    """主函數"""
    manager = WebServerManager()
    manager.run()

if __name__ == '__main__':
    main()