#!/usr/bin/env python3
"""
停止 JIRA-Lark 同步系統 Web 服務的腳本
當 Ctrl+C 無效時使用
"""

import subprocess
import sys
import platform

def find_and_kill_process():
    """查找並終止使用 port 8888 的進程"""
    system = platform.system().lower()
    
    try:
        if system == 'windows':
            # Windows 系統
            print("正在查找使用 port 8888 的進程...")
            result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
            lines = result.stdout.split('\n')
            
            for line in lines:
                if ':8888' in line and 'LISTENING' in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        print(f"找到進程 PID: {pid}")
                        
                        # 終止進程
                        subprocess.run(['taskkill', '/F', '/PID', pid])
                        print(f"已終止進程 {pid}")
                        return True
        
        else:
            # macOS/Linux 系統
            print("正在查找使用 port 8888 的進程...")
            result = subprocess.run(['lsof', '-i', ':8888'], capture_output=True, text=True)
            lines = result.stdout.split('\n')[1:]  # 跳過標題行
            
            for line in lines:
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        pid = parts[1]
                        print(f"找到進程 PID: {pid}")
                        
                        # 終止進程
                        subprocess.run(['kill', '-9', pid])
                        print(f"已終止進程 {pid}")
                        return True
        
        print("未找到使用 port 8888 的進程")
        return False
        
    except subprocess.CalledProcessError as e:
        print(f"執行命令時發生錯誤: {e}")
        return False
    except Exception as e:
        print(f"發生未預期的錯誤: {e}")
        return False

def main():
    """主函數"""
    print("🛑 JIRA-Lark 同步系統 Web 服務停止工具")
    print("=" * 50)
    
    if find_and_kill_process():
        print("✅ Web 服務已成功停止")
    else:
        print("❌ 未能停止 Web 服務")
        print("\n手動停止方法:")
        if platform.system().lower() == 'windows':
            print("1. 開啟任務管理器")
            print("2. 尋找 Python 進程")
            print("3. 結束相關的 Python 進程")
        else:
            print("1. 開啟終端")
            print("2. 執行: ps aux | grep python")
            print("3. 尋找 web_api.py 或 start_web.py 相關進程")
            print("4. 執行: kill -9 <PID>")

if __name__ == '__main__':
    main()