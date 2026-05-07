"""
GPT-SoVITS 推理器模块 - WebSocket服务器专用
"""

import os
import sys
import traceback
import asyncio
import logging
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor

# 添加GPT-SoVITS到系统路径
sys.path.append(os.path.join(os.path.dirname(__file__), "GPT_SoVITS"))

from config import TTS_CONFIG

logger = logging.getLogger("TTS-Inferencer")

class GPTSoVITSManager:
    """管理GPT-SoVITS推理器的单例类"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GPTSoVITSManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._initialized = True
            self.inferencer = None
            self.thread_pool = ThreadPoolExecutor(max_workers=1)  # 限制并发，避免GPU内存溢出
            self.is_initialized = False
            
    def initialize(self):
        """初始化推理器"""
        if self.is_initialized:
            return True
            
        try:
            logger.info("正在初始化GPT-SoVITS推理器...")
            
            # 动态导入，避免启动时立即加载所有依赖
            from start import GPTSoVITSInferencer
            
            # 创建推理器实例
            self.inferencer = GPTSoVITSInferencer(
                gpt_model_path=TTS_CONFIG["gpt_model_path"],
                sovits_model_path=TTS_CONFIG["sovits_model_path"],
                device="cuda"  # 假设使用CUDA，可以根据实际情况调整
            )
            
            self.is_initialized = True
            logger.info("GPT-SoVITS推理器初始化成功")
            return True
            
        except Exception as e:
            logger.error(f"初始化GPT-SoVITS推理器失败: {e}")
            logger.error(traceback.format_exc())
            return False
    
    async def synthesize_async(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        异步语音合成
        使用线程池避免阻塞事件循环
        """
        if not self.is_initialized:
            if not self.initialize():
                return {"success": False, "error": "推理器初始化失败"}
        
        loop = asyncio.get_event_loop()
        
        try:
            # 在线程池中运行同步的TTS合成
            result = await loop.run_in_executor(
                self.thread_pool,
                self._synthesize_sync,
                task_data
            )
            
            return result
            
        except Exception as e:
            logger.error(f"异步语音合成失败: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "error": str(e)}
    
    def _synthesize_sync(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """同步语音合成（在线程池中运行）"""
        try:
            # 准备输出路径
            output_filename = f"{task_data['task_id']}.wav"
            output_path = os.path.join(TTS_CONFIG["output_dir"], output_filename)
            
            # 使用参考音频路径
            ref_audio_path = task_data.get("ref_audio_path", TTS_CONFIG["default_ref_audio_path"])
            
            # 调用推理器
            result = self.inferencer.infer(
                text=task_data["text"],
                ref_audio_path=ref_audio_path,
                ref_text=task_data.get("ref_text", TTS_CONFIG["default_ref_text"]),
                output_path=output_path,
                text_lang=task_data.get("text_lang", TTS_CONFIG["model_params"]["text_lang"]),
                prompt_lang=task_data.get("prompt_lang", TTS_CONFIG["model_params"]["prompt_lang"]),
                top_k=task_data.get("top_k", TTS_CONFIG["model_params"]["top_k"]),
                top_p=task_data.get("top_p", TTS_CONFIG["model_params"]["top_p"]),
                temperature=task_data.get("temperature", TTS_CONFIG["model_params"]["temperature"]),
                text_split_method=task_data.get("text_split_method", TTS_CONFIG["model_params"]["text_split_method"]),
                speed_factor=task_data.get("speed_factor", TTS_CONFIG["model_params"]["speed_factor"]),
                seed=task_data.get("seed", TTS_CONFIG["model_params"]["seed"]),
            )
            
            if result is None:
                return {"success": False, "error": "GPT-SoVITS推理返回None"}
            
            # 构建音频URL（假设HTTP服务器运行在配置的端口）
            audio_url = f"http://{TTS_CONFIG['http_host']}:{TTS_CONFIG['http_port']}/audio/{output_filename}"
            
            return {
                "success": True,
                "task_id": task_data["task_id"],
                "audio_path": output_path,
                "audio_url": audio_url,
                "duration": result.get("duration", 0),
                "sample_rate": result.get("sample_rate", 24000),
                "seed": result.get("seed", "unknown"),
            }
            
        except Exception as e:
            logger.error(f"同步语音合成失败: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "error": str(e)}
    
    def cleanup(self):
        """清理资源"""
        if self.thread_pool:
            self.thread_pool.shutdown(wait=True)
            logger.info("线程池已关闭")
        
        self.is_initialized = False
        self.inferencer = None
        logger.info("GPT-SoVITS管理器已清理")

# 全局实例
tts_manager = GPTSoVITSManager()

# 工具函数
def format_audio_info(audio_path: str) -> Dict[str, Any]:
    """获取音频文件信息"""
    import wave
    import os
    
    if not os.path.exists(audio_path):
        return {"error": "文件不存在"}
    
    try:
        with wave.open(audio_path, 'rb') as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            duration = frames / float(rate)
            
            return {
                "channels": wav_file.getnchannels(),
                "sample_width": wav_file.getsampwidth(),
                "frame_rate": rate,
                "frames": frames,
                "duration": duration,
                "file_size": os.path.getsize(audio_path),
            }
    except Exception as e:
        return {"error": str(e)}

def validate_text(text: str) -> tuple[bool, str]:
    """验证文本"""
    if not text or not text.strip():
        return False, "文本不能为空"
    
    if len(text.strip()) > TTS_CONFIG["max_text_length"]:
        return False, f"文本长度超过限制 ({TTS_CONFIG['max_text_length']}字符)"
    
    # 可以添加更多验证规则
    return True, "验证通过"