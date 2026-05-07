"""
GPT-SoVITS 直接推理脚本 - 修复torchaudio依赖问题
使用soundfile替代torchaudio读取音频
"""

import os
import sys
import torch
import logging
import random
import numpy as np
import soundfile as sf
import traceback

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 添加当前目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
print("当前目录:", current_dir)
now_dir = os.getcwd()
print("当前工作目录:", now_dir)
sys.path.append(now_dir)
sys.path.append(current_dir)
sys.path.append(os.path.join(current_dir, "GPT_SoVITS"))

# 设置环境变量
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = '1'

# 减少不必要的日志
for log_name in ["markdown_it", "urllib3", "httpcore", "httpx", "asyncio", 
                 "charset_normalizer", "torchaudio._extension"]:
    logging.getLogger(log_name).setLevel(logging.ERROR)


class GPTSoVITSInferencer:
    """GPT-SoVITS 推理器"""
    
    def __init__(self, 
                 gpt_model_path: str,
                 sovits_model_path: str,
                 cnhubert_path: str = None,
                 bert_path: str = None,
                 device: str = None,
                 use_half: bool = True,
                 version: str = "v2"):
        """
        初始化推理器
        """
        self.gpt_model_path = gpt_model_path
        self.sovits_model_path = sovits_model_path
        self.cnhubert_path = cnhubert_path
        self.bert_path = bert_path
        self.version = version
        
        # 自动检测设备
        if device is None:
            if torch.cuda.is_available():
                device = "cuda"
                self.is_half = use_half and torch.cuda.is_available()
            else:
                device = "cpu"
                self.is_half = False
        else:
            self.is_half = use_half and device == "cuda"
        
        self.device = device
        
        logger.info(f"初始化GPT-SoVITS推理器")
        logger.info(f"设备: {device}, 半精度: {self.is_half}")
        
        # 语言映射
        self._init_language_mapping()
        
        # 初始化TTS管道
        self._init_tts_pipeline()
        
        logger.info("GPT-SoVITS推理器初始化完成")
    
    def _init_language_mapping(self):
        """初始化语言映射"""
        self.dict_language_v2 = {
            "中文": "all_zh",
            "英文": "en",
            "日文": "all_ja",
            "粤语": "all_yue",
            "韩文": "all_ko",
            "中英混合": "zh",
            "日英混合": "ja",
            "粤英混合": "yue",
            "韩英混合": "ko",
            "多语种混合": "auto",
            "多语种混合(粤语)": "auto_yue",
        }
        
        self.dict_language = self.dict_language_v2
        
        # 切分方法映射
        self.cut_method = {
            "不切": "cut0",
            "凑四句一切": "cut1",
            "凑50字一切": "cut2",
            "按中文句号。切": "cut3",
            "按英文句号.切": "cut4",
            "按标点符号切": "cut5",
        }
    
    def _init_tts_pipeline(self):
        """初始化TTS管道"""
        try:
            from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config
            
            # 创建配置
            tts_config = TTS_Config("GPT_SoVITS/configs/tts_infer.yaml")
            tts_config.device = self.device
            tts_config.is_half = self.is_half
            tts_config.update_version(self.version)
            tts_config.t2s_weights_path = self.gpt_model_path
            tts_config.vits_weights_path = self.sovits_model_path
            
            if self.cnhubert_path is not None:
                tts_config.cnhuhbert_base_path = self.cnhubert_path
            if self.bert_path is not None:
                tts_config.bert_base_path = self.bert_path
            
            # 创建TTS实例
            self.tts_pipeline = TTS(tts_config)
            
        except Exception as e:
            logger.error(f"初始化TTS管道失败: {e}")
            raise
    
    def _load_audio_with_soundfile(self, audio_path):
        """
        使用soundfile加载音频文件
        替代torchaudio.load，避免FFmpeg依赖
        """
        try:
            # 使用soundfile读取音频
            audio_data, sample_rate = sf.read(audio_path, dtype='float32')
            
            # 转换为单声道（如果需要）
            if len(audio_data.shape) > 1 and audio_data.shape[1] > 1:
                audio_data = np.mean(audio_data, axis=1)
            
            # 转换为torch tensor
            audio_tensor = torch.from_numpy(audio_data).float()
            
            # 添加批次维度
            audio_tensor = audio_tensor.unsqueeze(0)
            
            return audio_tensor, sample_rate
            
        except Exception as e:
            logger.error(f"加载音频文件失败: {e}")
            raise
    
    def _patch_torchaudio_load(self):
        """
        临时补丁: 替换torchaudio.load为soundfile版本
        """
        try:
            import torchaudio
            # 保存原始的torchaudio.load
            original_load = torchaudio.load
            
            # 定义新的加载函数
            def patched_load(filepath, **kwargs):
                return self._load_audio_with_soundfile(filepath)
            
            # 替换torchaudio.load
            torchaudio.load = patched_load
            logger.info("已应用torchaudio.load补丁，使用soundfile替代")
            
        except Exception as e:
            logger.warning(f"应用torchaudio补丁失败: {e}")
    
    def _process_tts_output(self, generator):
        """
        处理TTS输出的生成器，提取音频数据
        """
        audio_data = None
        last_valid_item = None
        
        for item in generator:
            # 尝试提取音频数据
            if isinstance(item, tuple):
                if len(item) == 2:
                    item1, item2 = item
                    if isinstance(item1, np.ndarray) and isinstance(item2, (int, float)):
                        audio_data = item
                        break
                    elif isinstance(item2, np.ndarray) and isinstance(item1, (int, float)):
                        audio_data = (item2, item1)
                        break
                last_valid_item = item
            elif isinstance(item, np.ndarray):
                audio_data = (item, 24000)
                break
            else:
                last_valid_item = item
        
        # 如果没有找到标准的音频数据，尝试使用最后一个非数值项
        if audio_data is None and last_valid_item is not None:
            if isinstance(last_valid_item, tuple):
                for elem in last_valid_item:
                    if isinstance(elem, np.ndarray):
                        audio_data = (elem, 24000)
                        break
        
        return audio_data
    
    def infer(self,
              text: str,
              ref_audio_path: str,
              ref_text: str = "",
              output_path: str = "output.wav",
              text_lang: str = "中文",
              prompt_lang: str = "中文",
              top_k: int = 5,
              top_p: float = 1.0,
              temperature: float = 1.0,
              text_split_method: str = "不切",
              speed_factor: float = 1.0,
              seed: int = -1):
        """
        推理方法
        
        Args:
            text: 待合成文本
            ref_audio_path: 参考音频路径
            ref_text: 参考文本
            output_path: 输出音频路径
            text_lang: 文本语言
            prompt_lang: 提示语言
            top_k: top_k参数
            top_p: top_p参数
            temperature: 温度参数
            text_split_method: 文本切分方法
            speed_factor: 语速因子
            seed: 随机种子
            
        Returns:
            dict: 包含音频信息的字典，或None表示失败
        """
        # 检查文件是否存在
        if not os.path.exists(ref_audio_path):
            logger.error(f"参考音频文件不存在: {ref_audio_path}")
            return None
        
        # 设置随机种子
        actual_seed = seed if seed != -1 else random.randint(0, 2**32 - 1)
        
        # 尝试应用补丁以避免FFmpeg依赖
        self._patch_torchaudio_load()
        
        # 准备输入参数
        inputs = {
            "text": text,
            "text_lang": self.dict_language[text_lang],
            "ref_audio_path": ref_audio_path,
            "aux_ref_audio_paths": [],
            "prompt_text": ref_text,
            "prompt_lang": self.dict_language[prompt_lang],
            "top_k": top_k,
            "top_p": top_p,
            "temperature": temperature,
            "text_split_method": self.cut_method[text_split_method],
            "batch_size": 20,
            "speed_factor": float(speed_factor),
            "split_bucket": True,
            "return_fragment": False,
            "fragment_interval": 0,
            "seed": actual_seed,
            "parallel_infer": True,
            "repetition_penalty": 1.35,
            "sample_steps": 32,
            "super_sampling": False,
        }
        
        logger.info(f"开始语音合成: {text}")
        
        try:
            # 执行推理
            generator = self.tts_pipeline.run(inputs)
            
            # 处理输出
            audio_data = self._process_tts_output(generator)
            
            if audio_data is None:
                logger.error("未能提取音频数据")
                return None
            
            # 解包音频数据
            samples, sample_rate = audio_data
            
            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            # 保存音频文件
            sf.write(output_path, samples, int(sample_rate))
            
            # 计算音频信息
            duration = len(samples) / sample_rate
            
            logger.info(f"语音合成完成: {output_path}")
            logger.info(f"时长: {duration:.2f} 秒")
            
            return {
                "path": output_path,
                "sample_rate": sample_rate,
                "duration": duration,
                "shape": samples.shape,
                "seed": actual_seed,
            }
                
        except Exception as e:
            logger.error(f"推理过程中发生错误: {e}")
            logger.error(traceback.format_exc())
            
            # 如果是torchcodec错误，提示安装FFmpeg
            if "torchcodec" in str(e).lower() or "ffmpeg" in str(e).lower():
                logger.error("\n" + "="*60)
                logger.error("FFmpeg依赖问题解决方法:")
                logger.error("1. 安装FFmpeg（推荐）:")
                logger.error("   conda install ffmpeg -c conda-forge")
                logger.error("2. 或从 https://www.gyan.dev/ffmpeg/builds/ 下载")
                logger.error("="*60)
            
            return None
    
    def simple_infer(self,
                     text: str,
                     ref_audio_path: str,
                     ref_text: str = "",
                     output_path: str = "output.wav"):
        """
        简化版推理接口
        """
        return self.infer(
            text=text,
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            output_path=output_path
        )


def simple_inference_example(text):
    """
    简化版推理示例
    """
    
    # 配置参数 - 请根据实际情况修改
    config = {
        "gpt_model": "E:/Study_Projects/yuewu_bachong/data/TTS_models/GPT_weights_v2/八重樱-e10.ckpt",
        "sovits_model": "E:/Study_Projects/yuewu_bachong/data/TTS_models/SoVITS_weights_v2/八重樱_e10_s200.pth",
        "ref_audio": "E:/Study_Projects/yuewu_bachong/data/example_audio/八重樱/此时此刻，唯有你和我，共赏这轮明月。.wav",
        "ref_text": "此时此刻，唯有你和我，共赏这轮明月。",
        "text": text,
        "output_path": "output.wav",
    }
    
    # 创建推理器
    inferencer = GPTSoVITSInferencer(
        gpt_model_path=config["gpt_model"],
        sovits_model_path=config["sovits_model"]
    )
    
    # 执行推理
    result = inferencer.simple_infer(
        text=config["text"],
        ref_audio_path=config["ref_audio"],
        ref_text=config["ref_text"],
        output_path=config["output_path"]
    )
    
    if result:
        print(f"\n语音合成成功!")
        print(f"音频文件: {result['path']}")
        print(f"采样率: {result['sample_rate']} Hz")
        print(f"时长: {result['duration']:.2f} 秒")
    else:
        print("\n语音合成失败!")
    
    return result


if __name__ == "__main__":
    print("=" * 50)
    print("GPT-SoVITS 直接推理脚本")
    print("=" * 50)
    
    # 运行简单推理示例
    text = "此乃静谧之地, 旅人若无要事, 还请回吧"
    result = simple_inference_example(text)
    
    if result:
        print("=" * 50)
        print("推理成功完成!")
        print("=" * 50)
    else:
        print("=" * 50)
        print("推理失败!")
        print("=" * 50)