"""
启动TTS WebSocket服务器和HTTP文件服务器
"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path

def start_http_server():
    """启动HTTP文件服务器"""
    print("启动HTTP文件服务器...")
    http_process = subprocess.Popen([
        sys.executable, "http_file_server.py",
        "--host", "localhost",
        "--port", "8005"
    ])
    
    time.sleep(2)  # 给HTTP服务器启动时间
    return http_process

def start_websocket_server():
    """启动WebSocket服务器"""
    print("启动WebSocket服务器...")
    ws_process = subprocess.Popen([
        sys.executable, "tts_websocket_server.py",
        "--host", "localhost",
        "--port", "8770"
    ])
    
    time.sleep(3)  # 给WebSocket服务器启动时间
    return ws_process

def main():
    """主函数"""
    print("=" * 50)
    print("TTS服务器启动器")
    print("=" * 50)
    
    try:
        # 启动HTTP服务器
        http_process = start_http_server()
        
        # 启动WebSocket服务器
        ws_process = start_websocket_server()
        
        print("\n服务器启动完成!")
        print(f"HTTP文件服务器: http://localhost:8005")
        print(f"WebSocket服务器: ws://localhost:8765")
        print(f"音频文件目录: ./tts_output")
        print("\n按 Ctrl+C 停止所有服务器")
        
        # 等待用户中断
        try:
            http_process.wait()
            ws_process.wait()
        except KeyboardInterrupt:
            print("\n正在停止服务器...")
            http_process.terminate()
            ws_process.terminate()
            http_process.wait()
            ws_process.wait()
            print("所有服务器已停止")
            
    except Exception as e:
        print(f"启动服务器时发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()