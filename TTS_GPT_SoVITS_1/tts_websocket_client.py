"""
TTS WebSocket客户端模块
用于连接TTS服务器进行异步语音合成
"""

import asyncio
import json
import logging
import threading
import queue
import time
import websockets
from datetime import datetime
from typing import Optional, Callable, Any
from enum import Enum

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("TTS-Client")

class TTSClientStatus(Enum):
    """客户端状态枚举"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"

class TTSWebSocketClient:
    """TTS WebSocket客户端"""
    
    def __init__(self, 
                 server_url: str = "ws://localhost:8765",
                 http_base_url: str = "http://localhost:8000",
                 auto_reconnect: bool = True,
                 reconnect_interval: int = 5):
        """
        初始化TTS客户端
        
        Args:
            server_url: WebSocket服务器地址
            http_base_url: HTTP文件服务器地址
            auto_reconnect: 是否自动重连
            reconnect_interval: 重连间隔(秒)
        """
        self.server_url = server_url
        self.http_base_url = http_base_url
        self.auto_reconnect = auto_reconnect
        self.reconnect_interval = reconnect_interval
        
        # 状态管理
        self.status = TTSClientStatus.DISCONNECTED
        self.client_id = None
        self.websocket = None
        self.loop = None
        self.thread = None
        
        # 任务管理
        self.pending_tasks = {}  # task_id -> 任务信息
        self.task_callbacks = {}  # task_id -> 回调函数
        
        # 消息队列
        self.message_queue = queue.Queue()
        
        # 回调函数
        self.on_connected = None
        self.on_disconnected = None
        self.on_error = None
        self.on_task_started = None
        self.on_task_completed = None
        self.on_task_failed = None
        
        # 异步事件
        self.stop_event = threading.Event()
        
        logger.info(f"初始化TTS客户端，服务器: {server_url}")
        
    def connect(self):
        """连接服务器（线程安全）"""
        if self.status == TTSClientStatus.CONNECTED:
            logger.warning("客户端已连接，无需重复连接")
            return True
            
        if self.thread and self.thread.is_alive():
            logger.warning("客户端线程已在运行")
            return True
            
        self.status = TTSClientStatus.CONNECTING
        self.stop_event.clear()
        
        # 启动异步线程
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()
        
        # 等待连接建立
        for _ in range(50):  # 等待5秒
            if self.status == TTSClientStatus.CONNECTED:
                return True
            time.sleep(0.1)
            
        return self.status == TTSClientStatus.CONNECTED
    
    def _run_async_loop(self):
        """运行异步事件循环"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        try:
            self.loop.run_until_complete(self._async_connect())
        except Exception as e:
            logger.error(f"异步循环运行失败: {e}")
        finally:
            self.loop.close()
            self.loop = None
            
    async def _async_connect(self):
        """异步连接服务器"""
        import websockets
        
        while not self.stop_event.is_set():
            try:
                logger.info(f"正在连接TTS服务器: {self.server_url}")
                
                # 连接WebSocket服务器
                async with websockets.connect(self.server_url, ping_interval=30, ping_timeout=60) as ws:
                    self.websocket = ws
                    
                    # 接收连接确认
                    ack_message = await ws.recv()
                    ack_data = json.loads(ack_message)
                    
                    if ack_data.get("type") == "connection_ack":
                        self.client_id = ack_data.get("client_id")
                        self.status = TTSClientStatus.CONNECTED
                        
                        logger.info(f"已连接到TTS服务器，客户端ID: {self.client_id}")
                        
                        # 调用连接回调
                        if self.on_connected:
                            self._safe_callback(self.on_connected, self.client_id)
                        
                        # 处理消息循环
                        await self._message_loop()
                        
                    else:
                        logger.error(f"收到非预期的连接响应: {ack_data}")
                        
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"连接关闭: {e}")
                self.status = TTSClientStatus.DISCONNECTED
                
            except ConnectionRefusedError:
                logger.error(f"连接被拒绝，请检查服务器是否运行: {self.server_url}")
                self.status = TTSClientStatus.ERROR
                
            except Exception as e:
                logger.error(f"连接异常: {e}")
                self.status = TTSClientStatus.ERROR
                
            finally:
                self.websocket = None
                
                # 调用断开连接回调
                if self.status != TTSClientStatus.CONNECTED and self.on_disconnected:
                    self._safe_callback(self.on_disconnected)
                
                # 自动重连
                if self.auto_reconnect and not self.stop_event.is_set():
                    logger.info(f"{self.reconnect_interval}秒后尝试重连...")
                    await asyncio.sleep(self.reconnect_interval)
                    
    async def _message_loop(self):
        """处理消息循环"""
        try:
            async for message in self.websocket:
                await self._handle_message(message)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket连接已关闭")
            
    async def _handle_message(self, message: str):
        """处理服务器消息"""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            logger.debug(f"收到服务器消息: {msg_type}")
            
            # 根据消息类型处理
            if msg_type == "pong":
                pass  # 心跳响应，无需处理
                
            elif msg_type == "task_created":
                task_id = data.get("task_id")
                if task_id in self.pending_tasks:
                    self.pending_tasks[task_id]["server_task_id"] = task_id
                    self.pending_tasks[task_id]["status"] = "processing"
                    
                    # 调用任务开始回调
                    if self.on_task_started:
                        self._safe_callback(self.on_task_started, task_id, data)
                        
            elif msg_type == "task_completed":
                task_id = data.get("task_id")
                audio_url = data.get("audio_url")
                duration = data.get("duration")
                
                logger.info(f"任务完成: {task_id}, 音频URL: {audio_url}")
                
                # 更新任务状态
                if task_id in self.pending_tasks:
                    self.pending_tasks[task_id]["status"] = "completed"
                    self.pending_tasks[task_id]["audio_url"] = audio_url
                    self.pending_tasks[task_id]["duration"] = duration
                    self.pending_tasks[task_id]["completed_at"] = datetime.now().isoformat()
                    
                    # 调用任务完成回调
                    if self.on_task_completed:
                        self._safe_callback(
                            self.on_task_completed, 
                            task_id, 
                            audio_url, 
                            duration,
                            data
                        )
                        
                    # 调用自定义回调
                    if task_id in self.task_callbacks:
                        callback = self.task_callbacks.pop(task_id)
                        self._safe_callback(callback, audio_url, duration, data)
                        
            elif msg_type == "task_failed":
                task_id = data.get("task_id")
                error_msg = data.get("error")
                
                logger.error(f"任务失败: {task_id}, 错误: {error_msg}")
                
                # 更新任务状态
                if task_id in self.pending_tasks:
                    self.pending_tasks[task_id]["status"] = "failed"
                    self.pending_tasks[task_id]["error"] = error_msg
                    
                    # 调用任务失败回调
                    if self.on_task_failed:
                        self._safe_callback(self.on_task_failed, task_id, error_msg, data)
                        
            elif msg_type == "error":
                error_code = data.get("error_code")
                error_msg = data.get("error_message")
                
                logger.error(f"服务器错误: {error_code} - {error_msg}")
                
                # 调用错误回调
                if self.on_error:
                    self._safe_callback(self.on_error, error_code, error_msg, data)
                    
        except json.JSONDecodeError:
            logger.error(f"消息JSON解析失败: {message[:100]}")
        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            
    def _safe_callback(self, callback: Callable, *args, **kwargs):
        """安全执行回调函数"""
        try:
            if callback:
                callback(*args, **kwargs)
        except Exception as e:
            logger.error(f"回调函数执行失败: {e}")
            
    def synthesize_speech(self, 
                         text: str,
                         ref_audio_path: str = None,
                         ref_text: str = None,
                         callback: Callable = None) -> Optional[str]:
        """
        发起语音合成请求
        
        Args:
            text: 要合成的文本
            ref_audio_path: 参考音频路径
            ref_text: 参考文本
            callback: 合成完成后的回调函数
            
        Returns:
            任务ID或None
        """
        if self.status != TTSClientStatus.CONNECTED:
            logger.error("客户端未连接，无法发送请求")
            if self.auto_reconnect:
                self.connect()
                # 等待连接
                for _ in range(30):
                    if self.status == TTSClientStatus.CONNECTED:
                        break
                    time.sleep(0.1)
                    
            if self.status != TTSClientStatus.CONNECTED:
                return None
        
        # 生成任务ID
        import uuid
        task_id = str(uuid.uuid4())
        
        # 准备请求数据
        request = {
            "type": "synthesize_speech",
            "task_id": task_id,  # 【重要】发送任务ID给服务器
            "text": text,
            "ref_audio_path": ref_audio_path,
            "ref_text": ref_text,
        }
        
        # 移除空值
        request = {k: v for k, v in request.items() if v is not None}
        
        # 保存任务信息
        self.pending_tasks[task_id] = {
            "task_id": task_id,
            "text": text,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "audio_url": None,
            "duration": None,
            "error": None,
        }
        
        # 保存回调函数
        if callback:
            self.task_callbacks[task_id] = callback
            
        # 发送请求
        try:
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._send_request(task_id, request),
                    self.loop
                )
                logger.info(f"已发送语音合成请求，任务ID: {task_id}")
                return task_id
            else:
                logger.error("事件循环未运行")
                return None
                
        except Exception as e:
            logger.error(f"发送请求失败: {e}")
            return None
            
    async def _send_request(self, task_id: str, request: dict):
        """发送请求到服务器"""
        try:
            await self.websocket.send(json.dumps(request, ensure_ascii=False))
            
            # 将任务ID添加到请求中，用于服务器跟踪
            self.pending_tasks[task_id]["server_request_sent"] = True
            
        except Exception as e:
            logger.error(f"发送WebSocket消息失败: {e}")
            if task_id in self.pending_tasks:
                self.pending_tasks[task_id]["error"] = str(e)
                self.pending_tasks[task_id]["status"] = "failed"
                
    def get_task_status(self, task_id: str) -> dict:
        """获取任务状态"""
        return self.pending_tasks.get(task_id, {"error": "任务不存在"})
    
    def disconnect(self):
        """断开连接"""
        logger.info("正在断开TTS客户端连接...")
        self.stop_event.set()
        
        if self.loop and self.loop.is_running():
            # 发送关闭信号
            asyncio.run_coroutine_threadsafe(
                self._async_disconnect(),
                self.loop
            )
            
        if self.thread:
            self.thread.join(timeout=2)
            
        self.status = TTSClientStatus.DISCONNECTED
        logger.info("TTS客户端已断开")
        
    async def _async_disconnect(self):
        """异步断开连接"""
        if self.websocket:
            await self.websocket.close()
            
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self.status == TTSClientStatus.CONNECTED
    
    def get_client_id(self) -> Optional[str]:
        """获取客户端ID"""
        return self.client_id
    
    def cleanup(self):
        """清理资源"""
        self.disconnect()
        self.pending_tasks.clear()
        self.task_callbacks.clear()
        
    def __del__(self):
        """析构函数"""
        self.cleanup()