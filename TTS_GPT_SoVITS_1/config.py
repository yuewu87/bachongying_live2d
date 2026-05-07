"""
TTS WebSocket服务器配置文件
"""

import os

# 基础路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# GPT-SoVITS模型配置
TTS_CONFIG = {
    # api-key
    "api_key": "sk-9a0ff400d4fc4c07b13c483748590113", 

    # url
    "base_url": "https://api.deepseek.com",

    # 模型参数
    "model": "deepseek-chat",

    # live2d模型路径
    "live2d_path": "E:/Study_Projects/yuewu_bachong/data/live2d_models/八重樱",
    
    # GPT模型路径
    "gpt_model_path": "E:/Study_Projects/yuewu_bachong/data/TTS_models/GPT_weights_v2/八重樱-e10.ckpt",
    
    # SoVITS模型路径
    "sovits_model_path": "E:/Study_Projects/yuewu_bachong/data/TTS_models/SoVITS_weights_v2/八重樱_e10_s200.pth",
    
    # 默认参考音频
    "default_ref_audio_path": "E:/Study_Projects/yuewu_bachong/data/example_audio/八重樱/此时此刻，唯有你和我，共赏这轮明月。.wav",
    
    # 默认参考文本
    "default_ref_text": "此时此刻，唯有你和我，共赏这轮明月。",
    
    # 输出目录
    "output_dir": os.path.join(BASE_DIR, "tts_output"),
    
    # 服务器配置
    "websocket_host": "localhost",
    "websocket_port": 8770,
    "http_host": "localhost",
    "http_port": 8005,
    
    # 模型参数
    "model_params": {
        "text_lang": "中文",
        "prompt_lang": "中文",
        "top_k": 5,
        "top_p": 1.0,
        "temperature": 1.0,
        "text_split_method": "按标点符号切",
        "speed_factor": 1.0,
        "seed": -1,
    },
    
    # 性能配置
    "max_text_length": 1000,  # 最大文本长度
    "max_concurrent_tasks": 2,  # 最大并发任务数（GPU内存限制）
    "task_timeout": 300,  # 任务超时时间（秒）
}

# 检查并创建必要的目录
def setup_directories():
    """创建必要的目录"""
    directories = [
        TTS_CONFIG["output_dir"],
        os.path.join(TTS_CONFIG["output_dir"]),
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"确保目录存在: {directory}")

# 验证模型文件是否存在
def validate_model_files():
    """验证模型文件是否存在"""
    missing_files = []
    
    if not os.path.exists(TTS_CONFIG["gpt_model_path"]):
        missing_files.append(TTS_CONFIG["gpt_model_path"])
    
    if not os.path.exists(TTS_CONFIG["sovits_model_path"]):
        missing_files.append(TTS_CONFIG["sovits_model_path"])
    
    if not os.path.exists(TTS_CONFIG["default_ref_audio_path"]):
        missing_files.append(TTS_CONFIG["default_ref_audio_path"])
    
    if missing_files:
        print("警告: 以下文件不存在:")
        for file in missing_files:
            print(f"  - {file}")
        return False
    
    print("模型文件验证通过")
    return True

if __name__ == "__main__":
    setup_directories()
    validate_model_files()