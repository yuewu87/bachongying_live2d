"""
简单的HTTP文件服务器 - 使用配置版本
"""
import argparse
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import uvicorn

from config import TTS_CONFIG

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("HTTP-File-Server")

# 创建FastAPI应用
app = FastAPI(
    title="TTS音频文件服务器",
    description="提供GPT-SoVITS生成的音频文件访问",
    version="1.0.0"
)

# 音频目录
AUDIO_DIR = Path(TTS_CONFIG["output_dir"])

@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "TTS Audio File Server",
        "version": "1.0.0",
        "endpoints": {
            "/audio/{filename}": "获取音频文件",
            "/list": "列出所有音频文件",
            "/health": "健康检查",
            "/stats": "服务器统计信息"
        },
        "audio_dir": str(AUDIO_DIR.absolute()),
        "websocket_server": f"ws://{TTS_CONFIG['websocket_host']}:{TTS_CONFIG['websocket_port']}"
    }

@app.get("/audio/{filename}")
async def get_audio_file(filename: str):
    """获取音频文件"""
    file_path = AUDIO_DIR / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件 {filename} 不存在")
    
    # 安全检查：确保文件在音频目录内
    try:
        file_path.relative_to(AUDIO_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="禁止访问")
    
    # 检查文件扩展名
    valid_extensions = ['.wav', '.mp3', '.ogg', '.flac', '.m4a']
    if file_path.suffix.lower() not in valid_extensions:
        raise HTTPException(status_code=400, detail="不支持的文件类型")
    
    logger.info(f"提供音频文件: {filename}")
    
    # 根据文件类型设置媒体类型
    media_types = {
        '.wav': 'audio/wav',
        '.mp3': 'audio/mpeg',
        '.ogg': 'audio/ogg',
        '.flac': 'audio/flac',
        '.m4a': 'audio/mp4'
    }
    
    media_type = media_types.get(file_path.suffix.lower(), 'application/octet-stream')
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=3600",  # 缓存1小时
            "Access-Control-Allow-Origin": "*"  # 允许跨域访问
        }
    )

@app.get("/list")
async def list_audio_files():
    """列出所有音频文件"""
    if not AUDIO_DIR.exists():
        return {"files": []}
    
    audio_files = []
    for ext in ['*.wav', '*.mp3', '*.ogg', '*.flac', '*.m4a']:
        for file_path in AUDIO_DIR.glob(ext):
            stat = file_path.stat()
            audio_files.append({
                "name": file_path.name,
                "size": stat.st_size,
                "size_human": f"{stat.st_size / 1024:.1f} KB",
                "modified": stat.st_mtime,
                "url": f"/audio/{file_path.name}"
            })
    
    # 按修改时间排序（最新的在前）
    audio_files.sort(key=lambda x: x["modified"], reverse=True)
    
    return {
        "count": len(audio_files),
        "files": audio_files[:100]  # 只返回前100个文件
    }

@app.get("/stats")
async def server_stats():
    """服务器统计信息"""
    import os
    
    if not AUDIO_DIR.exists():
        return {
            "total_files": 0,
            "total_size": 0,
            "total_size_human": "0 KB"
        }
    
    total_files = 0
    total_size = 0
    
    for ext in ['*.wav', '*.mp3', '*.ogg', '*.flac', '*.m4a']:
        for file_path in AUDIO_DIR.glob(ext):
            total_files += 1
            total_size += file_path.stat().st_size
    
    return {
        "total_files": total_files,
        "total_size": total_size,
        "total_size_human": f"{total_size / (1024*1024):.2f} MB",
        "audio_dir": str(AUDIO_DIR.absolute()),
        "server_url": f"http://{TTS_CONFIG['http_host']}:{TTS_CONFIG['http_port']}"
    }

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "audio_dir": str(AUDIO_DIR.absolute()),
        "directory_exists": AUDIO_DIR.exists(),
        "websocket_server": f"ws://{TTS_CONFIG['websocket_host']}:{TTS_CONFIG['websocket_port']}"
    }

@app.get("/cleanup")
async def cleanup_old_files(days: int = 7):
    """清理旧文件（仅供调试使用）"""
    import time
    import os
    
    cutoff_time = time.time() - (days * 24 * 60 * 60)
    deleted_files = []
    
    if AUDIO_DIR.exists():
        for file_path in AUDIO_DIR.glob("*.*"):
            if file_path.stat().st_mtime < cutoff_time:
                try:
                    file_path.unlink()
                    deleted_files.append(file_path.name)
                except Exception as e:
                    logger.error(f"删除文件失败 {file_path}: {e}")
    
    return {
        "deleted_files": deleted_files,
        "count": len(deleted_files),
        "older_than_days": days
    }

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="HTTP音频文件服务器")
    parser.add_argument("--host", default=TTS_CONFIG["http_host"], help="服务器主机地址")
    parser.add_argument("--port", type=int, default=TTS_CONFIG["http_port"], help="服务器端口")
    
    args = parser.parse_args()
    
    # 确保目录存在
    AUDIO_DIR.mkdir(exist_ok=True, parents=True)
    
    logger.info(f"启动HTTP文件服务器，监听 {args.host}:{args.port}")
    logger.info(f"音频文件目录: {AUDIO_DIR.absolute()}")
    logger.info(f"WebSocket服务器: ws://{TTS_CONFIG['websocket_host']}:{TTS_CONFIG['websocket_port']}")
    
    # 启动服务器
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info"
    )

if __name__ == "__main__":
    main()