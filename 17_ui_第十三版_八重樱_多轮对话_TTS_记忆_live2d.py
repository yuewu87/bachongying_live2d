"""
八重樱角色扮演程序 - 集成TTS语音版本 & Live2D展示
支持流式文本输出、异步语音合成和Live2D模型展示
"""

import sys
import json
import html
import io
import os
import warnings
import threading
import time
import logging
import uuid
import traceback
import re

# 1. 解决编码问题
if sys.platform.startswith('win'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
os.environ['PYTHONIOENCODING'] = 'utf-8'

# 2. 忽略PyQt5的弃用警告
warnings.filterwarnings("ignore", category=DeprecationWarning)

from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QTextEdit, QLineEdit, QPushButton, QWidget, QScrollArea,
                             QLabel, QMessageBox, QDialog, QFrame, QSplitter)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl, PYQT_VERSION_STR, QObject
from PyQt5.QtGui import QFont, QPalette, QColor, QTextCursor, QDesktopServices
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from openai import OpenAI

from TTS_GPT_SoVITS.config import TTS_CONFIG

# 导入Live2D管理器
try:
    from need.live2d_manager import Live2DSidebar
    LIVE2D_AVAILABLE = True
    print("✓ Live2D系统已导入")
except ImportError as e:
    print(f"✗ Live2D系统导入失败: {e}")
    LIVE2D_AVAILABLE = False

# 记忆管理器
# 修改导入，使用简化版本
try:
    from need.sakura_memory_manager import get_memory_manager
    LANGCHAIN_AVAILABLE = True
    print("✓ 记忆系统已导入（简化版）")
except ImportError as e:
    print(f"✗ 记忆系统导入失败: {e}")
    LANGCHAIN_AVAILABLE = False

# 尝试导入TTS客户端
try:
    # 先添加项目路径
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    # 尝试从本地导入
    try:
        from TTS_GPT_SoVITS.tts_websocket_client import TTSWebSocketClient, TTSClientStatus
        TTS_AVAILABLE = True
        print("✓ TTS客户端导入成功")
    except ImportError:
        # 尝试从父目录导入
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.append(parent_dir)
        from TTS_GPT_SoVITS.tts_websocket_client import TTSWebSocketClient, TTSClientStatus
        TTS_AVAILABLE = True
        print("✓ TTS客户端从父目录导入成功")
        
except ImportError as e:
    print(f"✗ TTS客户端导入失败: {e}")
    print("将使用纯文本模式运行")
    TTS_AVAILABLE = False

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Sakura-UI")

class ChatThread(QThread):
    """处理API调用的线程 - 支持流式输出和LangChain"""
    chunk_received = pyqtSignal(str)  # 流式输出片段信号
    response_complete = pyqtSignal(str)  # 完整回复信号
    error_occurred = pyqtSignal(str)
    
    def __init__(self, api_key, base_url, model, history, user_input, use_langchain=False):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.history = history
        self.user_input = user_input
        self.use_langchain = use_langchain
        
    def run(self):
        try:
            if self.use_langchain and LANGCHAIN_AVAILABLE:
                # 使用LangChain生成流式回复
                self.run_langchain_stream()
            else:
                # 原有API调用逻辑
                self.run_direct_api()
                
        except Exception as e:
            error_msg = f"对话错误: {str(e)[:100]}"
            self.error_occurred.emit(error_msg)
    
    def run_direct_api(self):
        """原有直接API调用逻辑"""
        client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
        # 添加用户消息到历史
        temp_history = self.history + [{"role": "user", "content": self.user_input}]
        
        # 调用API，开启流式输出
        stream = client.chat.completions.create(
            model=self.model,
            messages=temp_history,
            stream=True
        )
        
        # 处理流式响应
        full_response = ""
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                content = chunk.choices[0].delta.content
                full_response += content
                self.chunk_received.emit(content)
        
        # 发射完整回复
        self.response_complete.emit(full_response)
    
    def run_langchain_stream(self):
        """简化版记忆系统流式输出"""
        memory_manager = get_memory_manager()
        if not memory_manager:
            self.error_occurred.emit("记忆管理器未初始化")
            return
        
        # 直接使用原有API，但使用记忆管理器构建的历史
        try:
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
            
            # 从记忆管理器获取历史（包含记忆上下文）
            temp_history = memory_manager.get_message_history(for_api=True, include_memory=True)
            # 添加当前用户输入
            temp_history.append({"role": "user", "content": self.user_input})
            
            # 调用API，开启流式输出
            stream = client.chat.completions.create(
                model=self.model,
                messages=temp_history,
                stream=True
            )
            
            # 处理流式响应
            full_response = ""
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    self.chunk_received.emit(content)
            
            # 将对话添加到记忆
            memory_manager.add_conversation(self.user_input, full_response)
            
            self.response_complete.emit(full_response)
            
        except Exception as e:
            error_msg = f"API调用错误: {str(e)[:100]}"
            self.error_occurred.emit(error_msg)

class TTSEventHandler(QObject):
    """处理TTS事件的辅助类"""
    
    # 定义信号
    tts_connected = pyqtSignal(str)
    tts_disconnected = pyqtSignal()
    tts_task_completed = pyqtSignal(str, str, float, dict)  # task_id, audio_url, duration, data
    tts_task_failed = pyqtSignal(str, str, dict)  # task_id, error_msg, data
    tts_error = pyqtSignal(str, str, dict)  # error_code, error_msg, data
    
    def __init__(self):
        super().__init__()
        
    def on_connected(self, client_id):
        """TTS连接成功"""
        self.tts_connected.emit(client_id)
        
    def on_disconnected(self):
        """TTS断开连接"""
        self.tts_disconnected.emit()
        
    def on_task_completed(self, task_id, audio_url, duration, data):
        """TTS任务完成"""
        self.tts_task_completed.emit(task_id, audio_url, duration, data)
        
    def on_task_failed(self, task_id, error_msg, data):
        """TTS任务失败"""
        self.tts_task_failed.emit(task_id, error_msg, data)
        
    def on_error(self, error_code, error_msg, data):
        """TTS错误"""
        self.tts_error.emit(error_code, error_msg, data)

class SakuraWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # 配置
        self.api_key = TTS_CONFIG["api_key"]
        self.url = TTS_CONFIG["base_url"]
        self.model = TTS_CONFIG["model"]
        
        # Live2D配置
        self.live2d_sidebar = None
        self.live2d_model_dir = "E:/Study_Projects/yuewu_bachong/data/live2d_models"  # 根据实际情况修改路径

        # 初始化LangChain记忆管理器
        if LANGCHAIN_AVAILABLE:
            try:
                self.memory_manager = get_memory_manager(self.api_key, self.model)
                if self.memory_manager:
                    # 从记忆管理器获取历史
                    self.history = self.memory_manager.get_message_history(for_api=True)
                    print("✓ json记忆系统已初始化")
                    
                    # 启用记忆管理按钮
                    if hasattr(self, 'memory_button'):
                        self.memory_button.setEnabled(True)
                else:
                    print("⚠ json记忆系统初始化失败，使用传统模式")
                    self.history = [{"role": "system", "content": self.load_prompt()}]
            except Exception as e:
                print(f"⚠ json记忆系统初始化错误: {e}")
                import traceback
                traceback.print_exc()
                self.history = [{"role": "system", "content": self.load_prompt()}]
        else:
            # 降级：从文件加载提示词
            self.history = [{"role": "system", "content": self.load_prompt()}]
            print("⚠ 记忆系统不可用, 使用传统模式")
    
        # 聊天相关
        self.chat_thread = None
        self.is_waiting_response = False
        self.message_count = 0
        self.current_streaming_message_id = None
        self.current_message_content = ""
        
        # TTS客户端相关
        self.tts_client = None
        self.tts_connected = False
        self.tts_event_handler = TTSEventHandler()
        self.pending_tts_tasks = {}  # 任务ID -> 消息ID映射
        self.tts_status_label = None
        
        # 音频播放器
        self.media_player = QMediaPlayer()
        
        # 初始化
        self.init_ui()
        self.init_tts_client()
        
    # 从文件加载提示词
    def load_prompt(self):
        """从文件加载提示词"""
        prompt_file = os.path.join(os.path.dirname(__file__), "need/sakura_prompt.txt")
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            print(f"警告: 提示词文件 '{prompt_file}' 未找到，使用默认提示词")
            return """你是八重樱，500年前八重村的巫女，现今意识存在于圣痕空间。用古典含蓄的语气与用户对话。"""

    # 从文件加载HTML模板
    def load_html_template(self):
        """从文件加载HTML模板"""
        html_file = os.path.join(os.path.dirname(__file__), "need/chat_template.html")
        try:
            with open(html_file, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            print(f"警告: HTML模板文件 '{html_file}' 未找到，使用默认模板")
            return """
            <!DOCTYPE html>
            <html>
            <head><meta charset="UTF-8"><style>body{font-family:'Microsoft YaHei';margin:20px;}</style></head>
            <body>
                <h1>八重樱·圣痕之庭</h1>
                <div id="messages-container"></div>
            </body>
            </html>
            """

    # 文本过滤
    def filter_brackets(self, text):
        """
        过滤括号内的内容（内心独白）
        支持多种括号：()、（）、【】、[]、{}
        """
        if not text:
            return text
            
        # 多种括号模式
        patterns = [
            r'（[^）]*）',     # 中文括号
            r'\([^)]*\)',     # 英文括号
            r'【[^】]*】',     # 实心括号
            r'\[[^\]]*\]',    # 方括号
            r'\{[^}]*\}',     # 花括号
            r'<[^>]*>',       # HTML标签
        ]
        
        original_text = text
        filtered_text = text
        
        for pattern in patterns:
            filtered_text = re.sub(pattern, '', filtered_text)
        
        # 清理文本
        filtered_text = re.sub(r'\s+', ' ', filtered_text)  # 多个空格变一个
        filtered_text = re.sub(r'\s+([，。！？；：,.!?;:])', r'\1', filtered_text)
        filtered_text = filtered_text.strip()
        
        # 记录过滤情况
        if filtered_text != original_text:
            print(f"文本过滤: 移除 {len(original_text)-len(filtered_text)} 字符")
            if filtered_text:
                print(f"过滤后: {filtered_text[:80]}...")
            else:
                print("过滤后文本为空，保留原始文本")
                filtered_text = original_text
        
        return filtered_text
    
    def init_ui(self):
        """初始化UI - 包含Live2D侧边栏"""
        self.setWindowTitle("八重樱·圣痕之庭 - TTS语音版 & Live2D展示")
        self.setGeometry(100, 100, 1500, 800)  # 增加宽度以容纳Live2D侧边栏
        
        # 设置主窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # ==================== 左侧：Live2D展示区域 ====================
        if LIVE2D_AVAILABLE:
            try:
                self.live2d_sidebar = Live2DSidebar(
                    self, 
                    model_dir=self.live2d_model_dir,
                    width=500,
                    live2d_size=(480, 600)
                )
                main_layout.addWidget(self.live2d_sidebar)
                print("✓ Live2D侧边栏已加载")
            except Exception as e:
                print(f"✗ Live2D侧边栏加载失败: {e}")
                # 如果Live2D加载失败，创建占位区域
                placeholder = QWidget()
                placeholder.setFixedWidth(500)
                placeholder.setStyleSheet("""
                    QWidget {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 #ffb7c5, stop:0.5 #ff9aac, stop:1 #ff7b95);
                    }
                """)
                placeholder_label = QLabel("🌸 Live2D 展示区域 🌸")
                placeholder_label.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
                placeholder_label.setStyleSheet("color: white;")
                placeholder_label.setAlignment(Qt.AlignCenter)
                
                placeholder_layout = QVBoxLayout(placeholder)
                placeholder_layout.addWidget(placeholder_label)
                
                main_layout.addWidget(placeholder)
        else:
            # Live2D不可用，创建简单的装饰区域
            decoration_area = QWidget()
            decoration_area.setFixedWidth(500)
            decoration_area.setStyleSheet("""
                QWidget {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #ffb7c5, stop:0.5 #ff9aac, stop:1 #ff7b95);
                }
            """)
            
            decoration_layout = QVBoxLayout(decoration_area)
            
            # 添加一些装饰性元素
            sakura_label = QLabel("🌸 八重樱 🌸")
            sakura_label.setFont(QFont("Microsoft YaHei", 24, QFont.Bold))
            sakura_label.setStyleSheet("color: white; padding: 20px;")
            sakura_label.setAlignment(Qt.AlignCenter)
            
            quote_label = QLabel("樱花飘落的速度\n是每秒五厘米\n而你的话语\n却在我心中久久回荡")
            quote_label.setFont(QFont("Microsoft YaHei", 12))
            quote_label.setStyleSheet("color: white; padding: 20px;")
            quote_label.setAlignment(Qt.AlignCenter)
            quote_label.setWordWrap(True)
            
            decoration_layout.addStretch(1)
            decoration_layout.addWidget(sakura_label)
            decoration_layout.addWidget(quote_label)
            decoration_layout.addStretch(1)
            
            main_layout.addWidget(decoration_area)
        
        # ==================== 右侧：聊天区域 ====================
        chat_container = QWidget()
        chat_container.setStyleSheet("background: #f8f0f3;")
        
        chat_layout = QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)
        
        # 标题栏
        title_widget = QWidget()
        title_widget.setFixedHeight(60)
        title_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #ffb7c5, stop:0.5 #ff9aac, stop:1 #ff7b95);
                border-bottom: 2px solid #ff6b8b;
            }
        """)
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(20, 0, 20, 0)
        
        # 标题和图标
        title_label = QLabel("八重樱·圣痕之庭")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title_label.setStyleSheet("""
            color: white;
            background: none;
        """)
        
        # 添加记忆管理按钮
        self.memory_button = QPushButton("记忆管理")
        self.memory_button.setFixedSize(100, 30)
        self.memory_button.setFont(QFont("Microsoft YaHei", 9))
        self.memory_button.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 12px;
                color: white;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.3);
                border-color: rgba(255, 255, 255, 0.5);
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.4);
            }
            QPushButton:disabled {
                background: rgba(255, 255, 255, 0.1);
                color: rgba(255, 255, 255, 0.5);
            }
        """)
        self.memory_button.setToolTip("查看和管理八重樱的记忆")
        self.memory_button.clicked.connect(self.show_memory_dialog)

        # TTS状态指示器
        self.tts_status_label = QLabel("🔇 TTS未连接")
        self.tts_status_label.setFont(QFont("Microsoft YaHei", 10))
        self.tts_status_label.setToolTip("TTS语音服务状态")
        self.tts_status_label.setStyleSheet("""
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
            background: rgba(0, 0, 0, 0.2);
        """)
        
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        title_layout.addWidget(self.memory_button)  # 添加记忆管理按钮
        title_layout.addWidget(self.tts_status_label)
        
        chat_layout.addWidget(title_widget)
        
        # 聊天显示区域
        self.chat_display = QWebEngineView()
        self.chat_display.setStyleSheet("border: none;")
        # 加载html
        self.chat_display.setHtml(self.load_html_template())
        
        chat_layout.addWidget(self.chat_display, 1)
        
        # 输入区域
        input_widget = QWidget()
        input_widget.setFixedHeight(80)
        input_widget.setStyleSheet("""
            QWidget {
                background: #f8f0f3;
                border-top: 1px solid #e8c3cb;
            }
        """)
        
        input_layout = QHBoxLayout(input_widget)
        input_layout.setContentsMargins(20, 10, 20, 10)
        input_layout.setSpacing(10)
        
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("与八重樱对话... (输入'退出', 'exit', 'quit'或'q'来关闭程序)")
        self.input_field.setFont(QFont("Microsoft YaHei", 10))
        self.input_field.setStyleSheet("""
            QLineEdit {
                border: 2px solid #e8c3cb;
                border-radius: 20px;
                padding: 12px 20px;
                font-size: 14px;
                background: white;
            }
            QLineEdit:focus {
                border-color: #ff6b8b;
                background: #fff5f7;
            }
        """)
        self.input_field.returnPressed.connect(self.send_message)
        
        self.send_button = QPushButton("发送")
        self.send_button.setFixedSize(80, 45)
        self.send_button.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        self.send_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ff9aac, stop:1 #ff7b95);
                border: none;
                border-radius: 20px;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ff8a9e, stop:1 #ff6b8b);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ff7a8e, stop:1 #ff5b7b);
            }
            QPushButton:disabled {
                background: #cccccc;
                color: #666666;
            }
        """)
        self.send_button.clicked.connect(self.send_message)
        
        input_layout.addWidget(self.input_field, 1)
        input_layout.addWidget(self.send_button)
        
        chat_layout.addWidget(input_widget)
        
        # 状态栏
        status_widget = QWidget()
        status_widget.setFixedHeight(30)
        status_widget.setStyleSheet("""
            QWidget {
                background: #f1e4e8;
                border-top: 1px solid #e8c3cb;
            }
        """)
        
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(20, 0, 20, 0)
        
        self.status_label = QLabel("圣痕空间·初始化中...")
        self.status_label.setFont(QFont("Microsoft YaHei", 9))
        self.status_label.setStyleSheet("color: #8a6573;")
        
        # Live2D状态指示器
        if LIVE2D_AVAILABLE and self.live2d_sidebar:
            live2d_status = QLabel("🌸 Live2D已加载")
        else:
            live2d_status = QLabel("🌸 Live2D不可用")
        live2d_status.setFont(QFont("Microsoft YaHei", 9))
        live2d_status.setStyleSheet("color: #8a6573;")
        
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(live2d_status)
        
        chat_layout.addWidget(status_widget)
        
        # 将聊天容器添加到主布局
        main_layout.addWidget(chat_container, 1)  # 1表示聊天区域可以扩展
        
        # 连接TTS事件信号
        if TTS_AVAILABLE:
            self.tts_event_handler.tts_connected.connect(self.on_tts_connected)
            self.tts_event_handler.tts_disconnected.connect(self.on_tts_disconnected)
            self.tts_event_handler.tts_task_completed.connect(self.on_tts_task_completed)
            self.tts_event_handler.tts_task_failed.connect(self.on_tts_task_failed)
            self.tts_event_handler.tts_error.connect(self.on_tts_error)
        

    def init_memory_menu(self):
        """初始化记忆管理菜单"""
        # 添加记忆管理按钮到UI
        memory_button = QPushButton("记忆管理")
        memory_button.setFixedSize(100, 30)
        memory_button.setFont(QFont("Microsoft YaHei", 9))
        memory_button.setStyleSheet("""
            QPushButton {
                background: #ff9aac;
                border: none;
                border-radius: 10px;
                color: white;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background: #ff7b95;
            }
        """)
        memory_button.clicked.connect(self.show_memory_dialog)

    def show_memory_dialog(self):
        """显示记忆管理对话框"""
        if not LANGCHAIN_AVAILABLE or not self.memory_manager:
            QMessageBox.warning(self, "记忆管理", "LangChain记忆系统未启用")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("🌸 八重樱的记忆 🌸")
        dialog.setGeometry(300, 200, 700, 500)
        dialog.setStyleSheet("""
            QDialog {
                background: #fff5f7;
            }
            QLabel {
                color: #5a3a44;
                font-family: 'Microsoft YaHei';
            }
            QTextEdit {
                font-family: 'Microsoft YaHei';
                font-size: 12px;
                background: white;
                border: 1px solid #e8c3cb;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton {
                font-family: 'Microsoft YaHei';
                font-size: 11px;
                padding: 8px 16px;
                border-radius: 15px;
                border: none;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("八重樱的记忆 - 圣痕空间")
        title_label.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        title_label.setStyleSheet("color: #ff6b8b;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("background: #ffb7c5; height: 1px;")
        layout.addWidget(line)
        
        # 记忆查看区域
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setMinimumHeight(300)
        
        # 获取记忆信息
        memory_info = self.get_memory_info()
        text_edit.setText(memory_info)
        
        layout.addWidget(text_edit)
        
        # 操作按钮
        button_layout = QHBoxLayout()
        
        clear_btn = QPushButton("🌸 清空记忆")
        clear_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ff9aac, stop:1 #ff7b95);
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ff8a9e, stop:1 #ff6b8b);
            }
        """)
        clear_btn.clicked.connect(lambda: self.clear_memory(dialog))
        
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setStyleSheet("""
            QPushButton {
                background: #e8c3cb;
                color: #5a3a44;
            }
            QPushButton:hover {
                background: #ffb7c5;
            }
        """)
        refresh_btn.clicked.connect(lambda: text_edit.setText(self.get_memory_info()))
        
        close_btn = QPushButton("❌ 关闭")
        close_btn.setStyleSheet("""
            QPushButton {
                background: #8a6573;
                color: white;
            }
            QPushButton:hover {
                background: #9a7583;
            }
        """)
        close_btn.clicked.connect(dialog.close)
        
        button_layout.addStretch()
        button_layout.addWidget(refresh_btn)
        button_layout.addWidget(clear_btn)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # 显示对话框
        dialog.exec_()

    def get_memory_info(self):
        """获取记忆信息的格式化字符串"""
        if not LANGCHAIN_AVAILABLE or not hasattr(self, 'memory_manager'):
            return "记忆系统未启用"
        
        try:
            memory_manager = get_memory_manager()
            if not memory_manager:
                return "记忆管理器未初始化"
            
            return memory_manager.get_formatted_entities()
            
        except Exception as e:
            return f"获取记忆信息时发生错误:\n{str(e)}"

    def clear_memory(self, dialog):
        """清空记忆"""
        if self.memory_manager:
            self.memory_manager.clear_memory()
            QMessageBox.information(self, "记忆管理", "八重樱的记忆已清空")
            dialog.close()

    def init_tts_client(self):
        """初始化TTS客户端"""
        if not TTS_AVAILABLE:
            self.status_label.setText("圣痕空间·TTS不可用")
            self.tts_status_label.setText("🔇 TTS不可用")
            return
            
        try:
            print("正在初始化TTS客户端...")
            
            # 创建TTS客户端
            self.tts_client = TTSWebSocketClient(
                server_url="ws://localhost:8770",  # 你的WebSocket服务器端口
                http_base_url="http://localhost:8005",  # 你的HTTP服务器端口
                auto_reconnect=True,
                reconnect_interval=5
            )
            
            # 设置回调函数
            self.tts_client.on_connected = self.tts_event_handler.on_connected
            self.tts_client.on_disconnected = self.tts_event_handler.on_disconnected
            self.tts_client.on_task_completed = self.tts_event_handler.on_task_completed
            self.tts_client.on_task_failed = self.tts_event_handler.on_task_failed
            self.tts_client.on_error = self.tts_event_handler.on_error
            
            # 连接服务器
            self.tts_client.connect()
            
            # 等待连接建立
            threading.Thread(target=self._wait_for_tts_connection, daemon=True).start()
            
            print("TTS客户端初始化完成")
            
        except Exception as e:
            print(f"初始化TTS客户端失败: {e}")
            traceback.print_exc()
            self.status_label.setText("圣痕空间·TTS初始化失败")
            self.tts_status_label.setText("🔇 TTS失败")
            
    def _wait_for_tts_connection(self):
        """等待TTS连接建立"""
        for i in range(50):  # 等待5秒
            if self.tts_client and self.tts_client.is_connected():
                self.tts_connected = True
                break
            time.sleep(0.1)
            
        if not self.tts_connected:
            print("TTS客户端连接超时，请确保TTS服务器正在运行")
            
    # ================================================================================================================
    # ==================== TTS回调方法 ===============================================================================
    # ================================================================================================================
    
    def on_tts_connected(self, client_id):
        """TTS连接成功回调"""
        print(f"✓ TTS客户端已连接，ID: {client_id}")
        self.tts_connected = True
        self.status_label.setText("圣痕空间·语音服务已就绪")
        self.tts_status_label.setText("🔊 TTS已连接")
        self.tts_status_label.setStyleSheet("""
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
            background: #4CAF50;
        """)
        
    def on_tts_disconnected(self):
        """TTS断开连接回调"""
        print("⚠ TTS客户端已断开")
        self.tts_connected = False
        self.status_label.setText("圣痕空间·语音服务断开")
        self.tts_status_label.setText("🔇 TTS断开")
        self.tts_status_label.setStyleSheet("""
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
            background: #ff6b8b;
        """)
        
    def on_tts_task_completed(self, task_id, audio_url, duration, data):
        """TTS任务完成回调"""
        print(f"✓ 语音合成完成: {task_id}, 时长: {duration}秒")
        
        # 获取对应的消息ID
        if task_id in self.pending_tts_tasks:
            message_id = self.pending_tts_tasks.pop(task_id)
            
            # 在主线程中更新UI
            QTimer.singleShot(0, lambda: self._show_audio_ready(message_id, audio_url, duration))
        else:
            print(f"⚠ 未找到任务 {task_id} 对应的消息")
            
    def on_tts_task_failed(self, task_id, error_msg, data):
        """TTS任务失败回调"""
        print(f"✗ 语音合成失败: {task_id}, 错误: {error_msg}")
        
        if task_id in self.pending_tts_tasks:
            message_id = self.pending_tts_tasks.pop(task_id)
            
            # 在主线程中显示错误
            QTimer.singleShot(0, lambda: self._show_tts_error(message_id, error_msg))
            
    def on_tts_error(self, error_code, error_msg, data):
        """TTS错误回调"""
        print(f"✗ TTS服务错误: {error_code} - {error_msg}")
        self.status_label.setText(f"语音服务异常: {error_code}")
        
    # ================================================================================================================
    # ==================== 原有UI方法 ===============================================================================
    # ================================================================================================================
    
    def add_message(self, sender, message, is_user=False, is_streaming=False):
        """添加消息到聊天显示区域"""
        self.message_count += 1
        message_id = f"msg-{self.message_count}"
        
        # 在Python中计算需要的变量
        message_type = "user-message" if is_user else "assistant-message"
        bubble_class = "user-bubble" if is_user else "assistant-bubble"
        name_class = "user-name" if is_user else "assistant-name"
        cursor_html = '<span class="cursor"></span>' if is_streaming else ''
        
        # 转义HTML特殊字符
        try:
            escaped_message = html.escape(message).replace('\n', '<br>')
        except Exception as e:
            escaped_message = html.escape(f"消息显示异常: {str(e)[:50]}").replace('\n', '<br>')
        
        # 构建JavaScript代码
        js_code = f"""
            var messagesContainer = document.getElementById('messages-container');
            var messageDiv = document.createElement('div');
            messageDiv.className = 'message-container';
            messageDiv.id = '{message_id}';
            
            messageDiv.innerHTML = `
                <div class="{message_type}">
                    <div class="{name_class}">{sender}</div>
                    <div class="message-bubble {bubble_class}">
                        <div class="message-content" id="content-{message_id}">{escaped_message}{cursor_html}</div>
                        <div class="timestamp" id="timestamp-{message_id}">{self.get_current_time()}</div>
                    </div>
                </div>
            `;
            messagesContainer.appendChild(messageDiv);
            
            // 增强的自动滚动功能
            function scrollToBottom() {{
                // 方法1: 直接滚动到最底部
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
                
                // 方法2: 使用平滑滚动
                messagesContainer.scrollTo({{
                    top: messagesContainer.scrollHeight,
                    behavior: 'smooth'
                }});
                
                // 方法3: 使用锚点滚动
                var lastMessage = messagesContainer.lastElementChild;
                if (lastMessage) {{
                    lastMessage.scrollIntoView({{
                        behavior: 'smooth',
                        block: 'end',
                        inline: 'nearest'
                    }});
                }}
            }}
            
            // 添加一个微小的延迟确保DOM完全渲染
            setTimeout(scrollToBottom, 10);
        """
        
        try:
            self.chat_display.page().runJavaScript(js_code)
        except Exception as e:
            print(f"JavaScript执行错误: {e}")
        
        if is_streaming:
            self.current_streaming_message_id = message_id
            self.current_message_content = escaped_message
            
        return message_id
        
    def update_message(self, message_id, new_content, is_complete=False):
        """更新消息内容（用于流式输出）"""
        # 转义HTML特殊字符
        try:
            escaped_content = html.escape(new_content).replace('\n', '<br>')
        except Exception as e:
            escaped_content = html.escape(f"内容更新异常: {str(e)[:30]}").replace('\n', '<br>')
        
        cursor_html = "" if is_complete else '<span class="cursor"></span>'
        
        js_code = f"""
            var contentElement = document.getElementById('content-{message_id}');
            if (contentElement) {{
                contentElement.innerHTML = `{escaped_content}{cursor_html}`;
            }}
            
            var messagesContainer = document.getElementById('messages-container');
            if (messagesContainer) {{
                // 方法1: 直接滚动到最底部
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
                
                // 方法2: 使用平滑滚动
                messagesContainer.scrollTo({{
                    top: messagesContainer.scrollHeight,
                    behavior: 'smooth'
                }});
                
                // 方法3: 滚动到当前消息
                var messageElement = document.getElementById('{message_id}');
                if (messageElement) {{
                    messageElement.scrollIntoView({{
                        behavior: 'smooth',
                        block: 'end',
                        inline: 'nearest'
                    }});
                }}
            }}
        """
        
        try:
            self.chat_display.page().runJavaScript(js_code)
        except Exception as e:
            print(f"JavaScript更新错误: {e}")
        
    def complete_message(self, message_id, final_content):
        """完成消息（移除光标）"""
        # 转义HTML特殊字符
        try:
            escaped_content = html.escape(final_content).replace('\n', '<br>')
        except Exception as e:
            escaped_content = html.escape(f"消息完成异常: {str(e)[:30]}").replace('\n', '<br>')
        
        js_code = f"""
            var contentElement = document.getElementById('content-{message_id}');
            if (contentElement) {{
                contentElement.innerHTML = `{escaped_content}`;
            }}
            
            // 更新时间戳
            var timestampElement = document.getElementById('timestamp-{message_id}');
            if (timestampElement) {{
                timestampElement.textContent = '{self.get_current_time()}';
            }}
            
            var messagesContainer = document.getElementById('messages-container');
            if (messagesContainer) {{
                // 确保滚动到底部
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
                
                // 添加平滑滚动效果
                setTimeout(function() {{
                    messagesContainer.scrollTo({{
                        top: messagesContainer.scrollHeight,
                        behavior: 'smooth'
                    }});
                }}, 100);
            }}
        """
        
        try:
            self.chat_display.page().runJavaScript(js_code)
        except Exception as e:
            print(f"JavaScript完成错误: {e}")
            
    def get_current_time(self):
        """获取当前时间"""
        from datetime import datetime
        return datetime.now().strftime("%H:%M")
        
    def show_typing_indicator(self):
        """显示打字指示器"""
        js_code = """
            document.getElementById('typing-indicator').style.display = 'block';
            var messagesContainer = document.getElementById('messages-container');
            if (messagesContainer) {
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            }
        """
        try:
            self.chat_display.page().runJavaScript(js_code)
        except Exception as e:
            print(f"显示打字指示器错误: {e}")
            
    def hide_typing_indicator(self):
        """隐藏打字指示器"""
        js_code = """
            document.getElementById('typing-indicator').style.display = 'none';
        """
        try:
            self.chat_display.page().runJavaScript(js_code)
        except Exception as e:
            print(f"隐藏打字指示器错误: {e}")
            
    def send_message(self):
        """发送消息"""
        if self.is_waiting_response:
            return
            
        user_input = self.input_field.text().strip()
        
        if not user_input:
            return
            
        # 检查退出命令
        if user_input.lower() in ['退出', 'exit', 'quit', 'q']:
            self.add_message("旅人", user_input, is_user=True)
            self.add_message("八重樱", "……要离开了吗？愿下次樱花盛开时，我们还能再见。", is_user=False)
            QTimer.singleShot(1000, self.close)
            return
            
        # 显示用户消息
        self.add_message("旅人", user_input, is_user=True)
        
        # 清空输入框并禁用
        self.input_field.clear()
        self.input_field.setEnabled(False)
        self.send_button.setEnabled(False)
        self.is_waiting_response = True
        self.status_label.setText("八重樱正在思考...")
        
        # 显示打字指示器
        self.show_typing_indicator()
        
        # 创建并启动聊天线程
        use_memory_system = LANGCHAIN_AVAILABLE and hasattr(self, 'memory_manager')
        
        self.chat_thread = ChatThread(
            self.api_key, 
            self.url, 
            self.model, 
            [],  # 不再直接传递历史，由记忆管理器处理
            user_input,
            use_langchain=use_memory_system  # 实际使用的是记忆系统
        )
        self.chat_thread.chunk_received.connect(self.handle_stream_chunk)
        self.chat_thread.response_complete.connect(self.handle_response_complete)
        self.chat_thread.error_occurred.connect(self.handle_error)
        self.chat_thread.start()
        
    def handle_stream_chunk(self, chunk):
        """处理流式输出的片段"""
        # 隐藏打字指示器
        self.hide_typing_indicator()
        
        # 如果是第一个片段，创建新的消息
        if self.current_streaming_message_id is None:
            self.current_streaming_message_id = self.add_message(
                "八重樱", chunk, is_user=False, is_streaming=True
            )
        else:
            # 更新当前消息内容
            try:
                self.current_message_content += html.escape(chunk).replace('\n', '<br>')
            except Exception as e:
                self.current_message_content += html.escape(f"[内容片段异常]").replace('\n', '<br>')
            self.update_message(self.current_streaming_message_id, self.current_message_content, is_complete=False)
        
    def handle_response_complete(self, full_response):
        """处理完整回复"""
        # 确保隐藏打字指示器
        self.hide_typing_indicator()
        
        # 如果还没有创建消息，创建一个
        if self.current_streaming_message_id is None:
            message_id = self.add_message("八重樱", full_response, is_user=False)
        else:
            # 完成当前流式消息
            message_id = self.current_streaming_message_id
            self.complete_message(message_id, full_response)
        
        # 添加回复到历史记录（兼容模式）
        if LANGCHAIN_AVAILABLE and self.memory_manager:
            # LangChain模式下，历史由记忆管理器维护
            # 只需要更新UI用的历史记录
            self.history = self.memory_manager.get_message_history(for_api=True)
        else:
            self.history.append({"role": "assistant", "content": full_response})
        
        # 重置流式消息状态
        self.current_streaming_message_id = None
        self.current_message_content = ""
        
        # 发送TTS合成请求
        self._request_tts_synthesis(full_response, message_id)
        
        # 重新启用输入
        self.input_field.setEnabled(True)
        self.send_button.setEnabled(True)
        self.input_field.setFocus()
        self.is_waiting_response = False
        self.status_label.setText("圣痕空间·待机中")
        
    def handle_error(self, error_msg):
        """处理错误"""
        self.hide_typing_indicator()
        
        # 简化的错误信息
        simplified_error = "API调用错误"
        if "key" in error_msg.lower() or "api" in error_msg.lower():
            simplified_error = "API密钥错误或无效"
        elif "network" in error_msg.lower() or "connect" in error_msg.lower():
            simplified_error = "网络连接失败"
        elif "model" in error_msg.lower():
            simplified_error = "模型不可用"
            
        self.add_message("系统", f"圣痕空间发生异常: {simplified_error}", is_user=False)
        self.input_field.setEnabled(True)
        self.send_button.setEnabled(True)
        self.input_field.setFocus()
        self.is_waiting_response = False
        self.current_streaming_message_id = None
        self.current_message_content = ""
        self.status_label.setText("空间异常")
        
    # ================================================================================================================
    # ==================== TTS相关方法 ===============================================================================
    # ================================================================================================================
    
    def _request_tts_synthesis(self, text, message_id):
        """请求TTS合成"""
        if not TTS_AVAILABLE or not self.tts_connected or not self.tts_client:
            print("⚠ TTS客户端未连接，跳过语音合成")
            return
            
        try:
            # 过滤括号内容
            filtered_text = self.filter_brackets(text)
            
            # 发送TTS合成请求
            tts_task_id = self.tts_client.synthesize_speech(
                text=filtered_text,
                ref_audio_path=TTS_CONFIG["default_ref_audio_path"],
                ref_text=TTS_CONFIG["default_ref_text"]
            )
            
            if tts_task_id:
                # 保存任务ID和消息ID的映射
                self.pending_tts_tasks[tts_task_id] = message_id
                
                # 显示TTS合成状态
                self._show_tts_pending(message_id)
                
                print(f"✓ 已发送TTS请求，任务ID: {tts_task_id[:8]}")
            else:
                print("✗ TTS请求发送失败")
                self._show_tts_error(message_id, "请求发送失败")
                
        except Exception as e:
            print(f"✗ TTS请求异常: {e}")
            self._show_tts_error(message_id, str(e))
            
    def _show_tts_pending(self, message_id):
        """显示TTS合成中状态"""
        status_html = '<span class="tts-status tts-pending">🎤 语音合成中...</span>'
        
        js_code = f"""
            var contentElement = document.getElementById('content-{message_id}');
            if (contentElement) {{
                var statusDiv = document.createElement('div');
                statusDiv.id = 'tts-status-{message_id}';
                statusDiv.className = 'tts-status-container';
                statusDiv.innerHTML = `{status_html}`;
                contentElement.appendChild(statusDiv);
            }}
        """
        
        try:
            self.chat_display.page().runJavaScript(js_code)
        except Exception as e:
            print(f"显示TTS状态错误: {e}")
            
    def _show_audio_ready(self, message_id, audio_url, duration):
        """显示音频就绪状态并自动播放（使用Qt媒体播放器）"""
        # 移除等待状态
        remove_js = f"""
            var statusDiv = document.getElementById('tts-status-{message_id}');
            if (statusDiv) {{
                statusDiv.remove();
            }}
        """
        
        # 只显示简单的状态
        status_html = f'<span class="tts-status tts-completed">✓ 语音合成完成({duration:.1f}s)</span>'
        
        js_code = f"""
            {remove_js}
            
            var contentElement = document.getElementById('content-{message_id}');
            if (contentElement) {{
                var statusDiv = document.createElement('div');
                statusDiv.id = 'tts-completed-{message_id}';
                statusDiv.style.marginTop = '8px';
                statusDiv.innerHTML = `{status_html}`;
                contentElement.appendChild(statusDiv);
            }}
        """
        
        try:
            self.chat_display.page().runJavaScript(js_code)
            
            # 使用Qt媒体播放器自动播放
            self.media_player.setMedia(QMediaContent(QUrl(audio_url)))
            self.media_player.play()
            
            # 可选：更新状态显示
            self.status_label.setText("八重樱语音播放中...")
            
            # 监听播放结束
            def on_media_state_changed(state):
                if state == QMediaPlayer.StoppedState:
                    self.status_label.setText("圣痕空间·待机中")
                    
            self.media_player.stateChanged.connect(on_media_state_changed)
            
        except Exception as e:
            print(f"自动播放错误: {e}")
                
    def _show_tts_error(self, message_id, error_msg):
        """显示TTS错误"""
        # 移除等待状态
        remove_js = f"""
            var statusDiv = document.getElementById('tts-status-{message_id}');
            if (statusDiv) {{
                statusDiv.remove();
            }}
        """
        
        # 显示错误状态
        short_error = error_msg[:50] + ("..." if len(error_msg) > 50 else "")
        status_html = f'<span class="tts-status tts-failed">❌ 语音合成失败: {short_error}</span>'
        
        js_code = f"""
            {remove_js}
            
            var contentElement = document.getElementById('content-{message_id}');
            if (contentElement) {{
                var errorDiv = document.createElement('div');
                errorDiv.id = 'tts-error-{message_id}';
                errorDiv.style.marginTop = '8px';
                errorDiv.innerHTML = `{status_html}`;
                contentElement.appendChild(errorDiv);
            }}
        """
        
        try:
            self.chat_display.page().runJavaScript(js_code)
        except Exception as e:
            print(f"显示TTS错误错误: {e}")
            
    def closeEvent(self, event):
        """窗口关闭事件"""
        # 清理TTS客户端
        if self.tts_client:
            try:
                self.tts_client.cleanup()
                print("TTS客户端已清理")
            except:
                pass
                
        # 调用父类方法
        super().closeEvent(event)

if __name__ == "__main__":
    # 打印版本信息
    print("=" * 50)
    print("八重樱·圣痕之庭 - TTS语音版 & Live2D展示")
    print("=" * 50)
    print(f"Python版本: {sys.version.split()[0]}")
    print(f"PyQt5版本: {PYQT_VERSION_STR}")
    print(f"TTS支持: {'可用' if TTS_AVAILABLE else '不可用'}")
    print(f"Live2D支持: {'可用' if LIVE2D_AVAILABLE else '不可用'}")
    print("=" * 50)
    
    # 检查TTS服务器
    if TTS_AVAILABLE:
        print("提示: 请确保TTS服务器正在运行")
        print("  WebSocket服务器: ws://localhost:8770")
        print("  HTTP文件服务器: http://localhost:8005")
        print("=" * 50)
    
    app = QApplication(sys.argv)
    
    # 设置应用程序样式
    app.setStyleSheet("""
        QMainWindow {
            background-color: #f8f0f3;
        }
    """)
    
    window = SakuraWindow()
    window.show()
    
    sys.exit(app.exec_())