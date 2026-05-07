"""
TTS WebSocket 服务器 - 集成GPT-SoVITS版本
"""

import asyncio
import json
import logging
import os
import sys
import traceback
import uuid
from datetime import datetime
from typing import Dict, Optional

import websockets
from websockets.server import WebSocketServerProtocol

# 导入配置和推理器
from config import TTS_CONFIG, setup_directories, validate_model_files
from tts_inferencer import tts_manager, validate_text, format_audio_info

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("TTS-WebSocket-Server")

# 设置目录
setup_directories()

# 客户端连接管理
class ClientManager:
    """管理客户端连接"""
    
    def __init__(self):
        self.clients: Dict[str, WebSocketServerProtocol] = {}
        self.client_info: Dict[str, dict] = {}

    # 添加以下两个方法：
    def add_client_task(self, client_id: str, task_id: str):
        """为客户端添加任务"""
        if client_id in self.client_info:
            if "tasks" not in self.client_info[client_id]:
                self.client_info[client_id]["tasks"] = []
            self.client_info[client_id]["tasks"].append(task_id)
            logger.debug(f"客户端 {client_id} 添加任务: {task_id}")
            
    def remove_client_task(self, client_id: str, task_id: str):
        """移除客户端的任务"""
        if client_id in self.client_info and "tasks" in self.client_info[client_id]:
            if task_id in self.client_info[client_id]["tasks"]:
                self.client_info[client_id]["tasks"].remove(task_id)
                logger.debug(f"客户端 {client_id} 移除任务: {task_id}")
        
    def add_client(self, client_id: str, websocket: WebSocketServerProtocol):
        """添加客户端"""
        self.clients[client_id] = websocket
        self.client_info[client_id] = {
            "connected_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
            "tasks": [],
            "ip": websocket.remote_address[0] if websocket.remote_address else "unknown"
        }
        logger.info(f"客户端 {client_id} 已连接，IP: {self.client_info[client_id]['ip']}")
        
    def remove_client(self, client_id: str):
        """移除客户端"""
        if client_id in self.clients:
            del self.clients[client_id]
        if client_id in self.client_info:
            del self.client_info[client_id]
        logger.info(f"客户端 {client_id} 已断开")
        
    def update_client_activity(self, client_id: str):
        """更新客户端活动时间"""
        if client_id in self.client_info:
            self.client_info[client_id]["last_active"] = datetime.now().isoformat()
            
    async def send_to_client(self, client_id: str, message: dict):
        """向指定客户端发送消息"""
        if client_id in self.clients:
            try:
                await self.clients[client_id].send(json.dumps(message, ensure_ascii=False))
                return True
            except Exception as e:
                logger.error(f"向客户端 {client_id} 发送消息失败: {e}")
        return False

# 任务管理
class TaskManager:
    """管理语音合成任务"""
    
    def __init__(self):
        self.tasks: Dict[str, dict] = {}
        self.active_tasks = set()  # 正在处理的任务
        self.task_history = []  # 任务历史记录
        
    def create_task(self, client_id: str, text: str, params: dict) -> str:
        """创建新的语音合成任务"""
        task_id = str(uuid.uuid4())
        
        self.tasks[task_id] = {
            "task_id": task_id,
            "client_id": client_id,
            "text": text,
            "params": params,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "audio_path": None,
            "audio_url": None,
            "error": None,
            "duration": None,
            "sample_rate": None,
        }
        
        # 添加到历史记录（保留最近1000个任务）
        self.task_history.append(task_id)
        if len(self.task_history) > 1000:
            old_task_id = self.task_history.pop(0)
            if old_task_id in self.tasks:
                del self.tasks[old_task_id]
        
        logger.info(f"创建任务 {task_id[:8]}，客户端: {client_id[:8]}，文本长度: {len(text)}")
        return task_id
        
    def update_task_status(self, task_id: str, status: str, **kwargs):
        """更新任务状态"""
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = status
            
            for key, value in kwargs.items():
                self.tasks[task_id][key] = value
                
            if status == "processing":
                self.tasks[task_id]["started_at"] = datetime.now().isoformat()
                self.active_tasks.add(task_id)
            elif status in ["completed", "failed"]:
                self.tasks[task_id]["completed_at"] = datetime.now().isoformat()
                if task_id in self.active_tasks:
                    self.active_tasks.remove(task_id)
                    
            logger.info(f"任务 {task_id[:8]} 状态更新为: {status}")
            
    def get_task(self, task_id: str) -> Optional[dict]:
        """获取任务信息"""
        return self.tasks.get(task_id)
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务（标记为取消，实际停止需要额外处理）"""
        if task_id in self.tasks and self.tasks[task_id]["status"] in ["pending", "processing"]:
            self.update_task_status(task_id, "cancelled", error="用户取消")
            return True
        return False
    
    def get_active_task_count(self) -> int:
        """获取活动任务数量"""
        return len(self.active_tasks)

# WebSocket 服务器主类
class TTSServer:
    """TTS WebSocket 服务器"""
    
    def __init__(self, host: str = None, port: int = None):
        self.host = host or TTS_CONFIG["websocket_host"]
        self.port = port or TTS_CONFIG["websocket_port"]
        self.client_manager = ClientManager()
        self.task_manager = TaskManager()
        
        # 初始化推理器
        self._init_tts_inferencer()
        
        # 启动任务处理器
        self.task_processor_task = None
        
        logger.info(f"TTS服务器初始化完成，监听地址: {self.host}:{self.port}")
        
    def _init_tts_inferencer(self):
        """初始化TTS推理器"""
        logger.info("正在加载GPT-SoVITS推理器...")
        
        # 验证模型文件
        if not validate_model_files():
            logger.warning("模型文件验证失败，服务器将继续运行但TTS功能可能不可用")
        
        # 初始化推理器
        if not tts_manager.initialize():
            logger.error("GPT-SoVITS推理器初始化失败")
        else:
            logger.info("GPT-SoVITS推理器加载成功")
        
    async def handle_connection(self, websocket: WebSocketServerProtocol):
        """处理客户端连接"""
        client_id = str(uuid.uuid4())
        self.client_manager.add_client(client_id, websocket)
        
        try:
            # 发送连接确认消息
            await self._send_connection_ack(websocket, client_id)
            
            # 处理客户端消息
            async for message in websocket:
                await self.handle_message(client_id, websocket, message)
                
        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"客户端 {client_id} 连接关闭: {e}")
        except Exception as e:
            logger.error(f"处理客户端 {client_id} 连接时发生错误: {e}")
            logger.error(traceback.format_exc())
        finally:
            self.client_manager.remove_client(client_id)
            
    async def _send_connection_ack(self, websocket: WebSocketServerProtocol, client_id: str):
        """发送连接确认消息"""
        ack_message = {
            "type": "connection_ack",
            "client_id": client_id,
            "timestamp": datetime.now().isoformat(),
            "server_info": {
                "name": "TTS-WebSocket-Server",
                "version": "1.0.0",
                "tts_status": "ready" if tts_manager.is_initialized else "not_ready",
                "max_concurrent_tasks": TTS_CONFIG["max_concurrent_tasks"],
                "max_text_length": TTS_CONFIG["max_text_length"],
            }
        }
        await websocket.send(json.dumps(ack_message, ensure_ascii=False))
        
    async def handle_message(self, client_id: str, websocket: WebSocketServerProtocol, message: str):
        """处理客户端消息"""
        try:
            data = json.loads(message)
            message_type = data.get("type")
            
            # 更新客户端活动时间
            self.client_manager.update_client_activity(client_id)
            
            # 根据消息类型路由处理
            if message_type == "ping":
                await self._handle_ping(client_id, websocket, data)
            elif message_type == "synthesize_speech":
                await self._handle_synthesize_speech(client_id, websocket, data)
            elif message_type == "get_task_status":
                await self._handle_get_task_status(client_id, websocket, data)
            elif message_type == "cancel_task":
                await self._handle_cancel_task(client_id, websocket, data)
            elif message_type == "list_tasks":
                await self._handle_list_tasks(client_id, websocket, data)
            elif message_type == "server_status":
                await self._handle_server_status(client_id, websocket, data)
            else:
                await self._send_error(client_id, "unknown_message_type", 
                                      f"未知的消息类型: {message_type}")
                
        except json.JSONDecodeError:
            await self._send_error(client_id, "invalid_json", "消息不是有效的JSON格式")
        except Exception as e:
            logger.error(f"处理客户端 {client_id} 消息时发生错误: {e}")
            await self._send_error(client_id, "internal_error", str(e))
            
    async def _handle_ping(self, client_id: str, websocket: WebSocketServerProtocol, data: dict):
        """处理心跳检测"""
        response = {
            "type": "pong",
            "timestamp": datetime.now().isoformat(),
            "server_time": datetime.now().isoformat(),
            "client_id": client_id,
            "active_tasks": self.task_manager.get_active_task_count(),
        }
        await websocket.send(json.dumps(response, ensure_ascii=False))
        
    async def _handle_synthesize_speech(self, client_id: str, websocket: WebSocketServerProtocol, data: dict):
        """处理语音合成请求"""
        text = data.get("text", "").strip()
        
        # 验证文本
        is_valid, error_msg = validate_text(text)
        if not is_valid:
            await self._send_error(client_id, "invalid_text", error_msg)
            return
        
        # 检查并发任务数
        active_tasks = self.task_manager.get_active_task_count()
        if active_tasks >= TTS_CONFIG["max_concurrent_tasks"]:
            await self._send_error(client_id, "too_many_tasks", 
                                  f"服务器繁忙，当前有 {active_tasks} 个任务正在处理，请稍后重试")
            return
        
        # 【重要】使用客户端提供的task_id，而不是生成新的
        client_task_id = data.get("task_id")  # 获取客户端发送的任务ID
        
        # 如果客户端没有提供task_id，则生成一个新的
        if not client_task_id:
            client_task_id = str(uuid.uuid4())

        # 获取合成参数
        params = {
            "ref_audio_path": data.get("ref_audio_path", TTS_CONFIG["default_ref_audio_path"]),
            "ref_text": data.get("ref_text", TTS_CONFIG["default_ref_text"]),
            "text_lang": data.get("text_lang", TTS_CONFIG["model_params"]["text_lang"]),
            "prompt_lang": data.get("prompt_lang", TTS_CONFIG["model_params"]["prompt_lang"]),
            "top_k": data.get("top_k", TTS_CONFIG["model_params"]["top_k"]),
            "top_p": data.get("top_p", TTS_CONFIG["model_params"]["top_p"]),
            "temperature": data.get("temperature", TTS_CONFIG["model_params"]["temperature"]),
            "text_split_method": data.get("text_split_method", TTS_CONFIG["model_params"]["text_split_method"]),
            "speed_factor": data.get("speed_factor", TTS_CONFIG["model_params"]["speed_factor"]),
            "seed": data.get("seed", TTS_CONFIG["model_params"]["seed"]),
        }
        
        # 创建任务
        task_id = self.task_manager.create_task(client_id, text, params)
        # 确保任务ID是客户端发送的那个
        if client_task_id and client_task_id != task_id:
            # 更新任务ID为客户端发送的那个
            self.task_manager.tasks[client_task_id] = self.task_manager.tasks.pop(task_id)
            self.task_manager.tasks[client_task_id]["task_id"] = client_task_id
            task_id = client_task_id
        self.client_manager.add_client_task(client_id, task_id)
        
        # 立即返回任务ID
        response = {
            "type": "task_created",
            "task_id": task_id,
            "timestamp": datetime.now().isoformat(),
            "status": "pending",
            "text_preview": text[:100] + ("..." if len(text) > 100 else ""),
            "estimated_wait_time": active_tasks * 10,  # 预估等待时间（秒）
        }
        await websocket.send(json.dumps(response, ensure_ascii=False))
        
        # 启动异步任务处理
        asyncio.create_task(self._process_tts_task(task_id))
        
    async def _process_tts_task(self, task_id: str):
        """处理TTS任务"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        
        # 更新状态为处理中
        self.task_manager.update_task_status(task_id, "processing")
        
        try:
            # 调用GPT-SoVITS进行语音合成
            logger.info(f"开始处理任务 {task_id[:8]}: {task['text'][:50]}...")
            
            # 准备任务数据
            task_data = {
                "task_id": task_id,
                "text": task["text"],
                **task["params"]
            }
            
            # 异步调用TTS合成
            result = await tts_manager.synthesize_async(task_data)
            
            if result["success"]:
                # 更新任务状态为完成
                self.task_manager.update_task_status(
                    task_id, 
                    "completed",
                    audio_path=result["audio_path"],
                    audio_url=result["audio_url"],
                    duration=result["duration"],
                    sample_rate=result["sample_rate"],
                )
                
                # 通知客户端
                completion_message = {
                    "type": "task_completed",
                    "task_id": task_id,
                    "timestamp": datetime.now().isoformat(),
                    "status": "completed",
                    "audio_url": result["audio_url"],
                    "duration": result["duration"],
                    "sample_rate": result["sample_rate"],
                    "text_preview": task["text"][:100] + ("..." if len(task["text"]) > 100 else ""),
                }
                
                await self.client_manager.send_to_client(task["client_id"], completion_message)
                logger.info(f"任务 {task_id[:8]} 处理完成，时长: {result['duration']:.2f}秒")
                
            else:
                # 更新任务状态为失败
                self.task_manager.update_task_status(
                    task_id, 
                    "failed",
                    error=result["error"]
                )
                
                # 通知客户端
                error_message = {
                    "type": "task_failed",
                    "task_id": task_id,
                    "timestamp": datetime.now().isoformat(),
                    "status": "failed",
                    "error": result["error"],
                }
                
                await self.client_manager.send_to_client(task["client_id"], error_message)
                logger.error(f"任务 {task_id[:8]} 处理失败: {result['error']}")
                
        except asyncio.CancelledError:
            # 任务被取消
            self.task_manager.update_task_status(task_id, "cancelled", error="任务被取消")
            logger.info(f"任务 {task_id[:8]} 被取消")
            
        except Exception as e:
            # 处理过程中发生异常
            self.task_manager.update_task_status(task_id, "failed", error=str(e))
            
            # 通知客户端
            error_message = {
                "type": "task_failed",
                "task_id": task_id,
                "timestamp": datetime.now().isoformat(),
                "status": "failed",
                "error": f"处理过程中发生异常: {str(e)}",
            }
            
            await self.client_manager.send_to_client(task["client_id"], error_message)
            logger.error(f"任务 {task_id[:8]} 处理异常: {e}")
            logger.error(traceback.format_exc())
            
    async def _handle_get_task_status(self, client_id: str, websocket: WebSocketServerProtocol, data: dict):
        """获取任务状态"""
        task_id = data.get("task_id")
        
        if not task_id:
            await self._send_error(client_id, "missing_task_id", "缺少任务ID")
            return
            
        task = self.task_manager.get_task(task_id)
        
        if not task:
            await self._send_error(client_id, "task_not_found", f"任务 {task_id} 不存在")
            return
            
        # 确保只有任务创建者可以查询
        if task["client_id"] != client_id:
            await self._send_error(client_id, "permission_denied", "无权访问此任务")
            return
        
        # 如果任务已完成且有音频文件，获取详细信息
        audio_info = None
        if task["status"] == "completed" and task.get("audio_path"):
            audio_info = format_audio_info(task["audio_path"])
            
        response = {
            "type": "task_status",
            "task_id": task_id,
            "timestamp": datetime.now().isoformat(),
            "status": task["status"],
            "text": task["text"][:200] + ("..." if len(task["text"]) > 200 else ""),
            "created_at": task["created_at"],
            "started_at": task.get("started_at"),
            "completed_at": task.get("completed_at"),
            "audio_url": task.get("audio_url"),
            "duration": task.get("duration"),
            "error": task.get("error"),
            "audio_info": audio_info,
        }
        
        await websocket.send(json.dumps(response, ensure_ascii=False))
        
    async def _handle_cancel_task(self, client_id: str, websocket: WebSocketServerProtocol, data: dict):
        """取消任务"""
        task_id = data.get("task_id")
        
        if not task_id:
            await self._send_error(client_id, "missing_task_id", "缺少任务ID")
            return
            
        task = self.task_manager.get_task(task_id)
        
        if not task:
            await self._send_error(client_id, "task_not_found", f"任务 {task_id} 不存在")
            return
            
        # 确保只有任务创建者可以取消
        if task["client_id"] != client_id:
            await self._send_error(client_id, "permission_denied", "无权取消此任务")
            return
            
        # 尝试取消任务
        if self.task_manager.cancel_task(task_id):
            response = {
                "type": "task_cancelled",
                "task_id": task_id,
                "timestamp": datetime.now().isoformat(),
                "message": "任务已取消",
            }
        else:
            response = {
                "type": "task_cancelled",
                "task_id": task_id,
                "timestamp": datetime.now().isoformat(),
                "message": "任务无法取消（可能已完成或正在处理）",
            }
            
        await websocket.send(json.dumps(response, ensure_ascii=False))
        
    async def _handle_list_tasks(self, client_id: str, websocket: WebSocketServerProtocol, data: dict):
        """列出客户端的所有任务"""
        client_tasks = []
        
        for task_id, task in self.task_manager.tasks.items():
            if task["client_id"] == client_id:
                client_tasks.append({
                    "task_id": task_id,
                    "status": task["status"],
                    "text_preview": task["text"][:50] + ("..." if len(task["text"]) > 50 else ""),
                    "created_at": task["created_at"],
                    "audio_url": task.get("audio_url"),
                })
        
        response = {
            "type": "task_list",
            "timestamp": datetime.now().isoformat(),
            "tasks": client_tasks,
            "total": len(client_tasks),
        }
        
        await websocket.send(json.dumps(response, ensure_ascii=False))
        
    async def _handle_server_status(self, client_id: str, websocket: WebSocketServerProtocol, data: dict):
        """获取服务器状态"""
        status = {
            "type": "server_status",
            "timestamp": datetime.now().isoformat(),
            "server": {
                "clients_connected": len(self.client_manager.clients),
                "total_tasks": len(self.task_manager.tasks),
                "active_tasks": self.task_manager.get_active_task_count(),
                "tts_ready": tts_manager.is_initialized,
                "max_concurrent_tasks": TTS_CONFIG["max_concurrent_tasks"],
            },
            "client": {
                "client_id": client_id,
                "tasks": len([t for t in self.task_manager.tasks.values() if t["client_id"] == client_id]),
            }
        }
        
        await websocket.send(json.dumps(status, ensure_ascii=False))
        
    async def _send_error(self, client_id: str, error_code: str, error_message: str):
        """发送错误消息"""
        error_response = {
            "type": "error",
            "error_code": error_code,
            "error_message": error_message,
            "timestamp": datetime.now().isoformat()
        }
        await self.client_manager.send_to_client(client_id, error_response)
        
    async def start(self):
        """启动WebSocket服务器"""
        logger.info(f"启动TTS WebSocket服务器，监听 {self.host}:{self.port}")
        logger.info(f"HTTP音频服务地址: http://{TTS_CONFIG['http_host']}:{TTS_CONFIG['http_port']}/audio/")
        
        # 启动WebSocket服务器
        async with websockets.serve(
            self.handle_connection,
            self.host,
            self.port,
            ping_interval=30,
            ping_timeout=60,
            max_size=10 * 1024 * 1024
        ):
            logger.info(f"服务器已启动，等待客户端连接...")
            logger.info(f"按 Ctrl+C 停止服务器")
            
            # 保持服务器运行
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                logger.info("服务器正在关闭...")
            finally:
                # 清理资源
                tts_manager.cleanup()
                logger.info("服务器已关闭")
                
    def stop(self):
        """停止服务器"""
        logger.info("正在停止服务器...")
        if self.task_processor_task:
            self.task_processor_task.cancel()

# 测试客户端
async def test_client():
    """测试WebSocket客户端"""
    import asyncio
    
    async def test_connection():
        uri = f"ws://{TTS_CONFIG['websocket_host']}:{TTS_CONFIG['websocket_port']}"
        try:
            async with websockets.connect(uri) as websocket:
                # 接收连接确认
                response = await websocket.recv()
                print(f"收到连接确认: {response}")
                
                # 发送测试合成请求
                test_text = "旅人，你为何事而来？此处是圣痕空间，寻常人难以踏足。樱花虽美，却也是逝去之物的象征。"
                request = {
                    "type": "synthesize_speech",
                    "text": test_text,
                    "ref_audio_path": TTS_CONFIG["default_ref_audio_path"],
                    "ref_text": TTS_CONFIG["default_ref_text"],
                    "speed_factor": 1.0,
                }
                
                await websocket.send(json.dumps(request, ensure_ascii=False))
                print(f"已发送合成请求: {test_text}")
                
                # 接收响应
                while True:
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=60.0)
                        data = json.loads(response)
                        print(f"收到响应 [{data.get('type')}]: {data}")
                        
                        if data.get("type") == "task_completed":
                            print(f"语音合成完成! 音频URL: {data.get('audio_url')}")
                            print(f"音频时长: {data.get('duration', '未知')}秒")
                            break
                        elif data.get("type") == "task_failed":
                            print(f"语音合成失败: {data.get('error')}")
                            break
                            
                    except asyncio.TimeoutError:
                        print("等待响应超时")
                        break
                        
        except Exception as e:
            print(f"客户端连接失败: {e}")
            import traceback
            traceback.print_exc()
            
    await test_connection()

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="TTS WebSocket服务器")
    parser.add_argument("--host", default=TTS_CONFIG["websocket_host"], help="服务器主机地址")
    parser.add_argument("--port", type=int, default=TTS_CONFIG["websocket_port"], help="服务器端口")
    parser.add_argument("--test", action="store_true", help="运行客户端测试")
    
    args = parser.parse_args()
    
    if args.test:
        # 运行客户端测试
        print("启动客户端测试...")
        asyncio.run(test_client())
    else:
        # 启动服务器
        server = TTSServer(host=args.host, port=args.port)
        
        try:
            asyncio.run(server.start())
        except KeyboardInterrupt:
            print("\n服务器被用户中断")
            server.stop()

if __name__ == "__main__":
    main()