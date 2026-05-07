"""
简化的八重樱记忆管理器 - 兼容DeepSeek API
完全绕过LangChain的内部问题
"""
import os
from typing import List, Dict, Any, Optional
import json
import time
from datetime import datetime
import re

class SimpleSakuraMemoryManager:
    """简化的八重樱记忆管理器（不依赖LangChain）"""
    
    def __init__(self):
        # 加载角色设定
        self.character_context = self.load_character_context()
        
        # 对话历史
        self.message_history = []
        
        # 自定义记忆系统
        self.entities_memory = {}  # 实体记忆
        self.conversation_memory = []  # 对话记忆（最近5轮）
        self.memory_file = "need/sakura_memory.json"  # 记忆持久化文件
        
        # 重要实体预设
        self.preset_entities = {
            '凛': {
                'description': "八重樱的妹妹，五百年前被选为求雨祭品，被八重樱亲手结束生命",
                'importance': 10,  # 重要性评分
                'emotion': 'sadness',
                'triggers': ['凛', '妹妹', '八重凛', '祭祀', '祭品', '求雨']
            },
            '卡莲': {
                'description': "卡斯兰娜家族的骑士，曾封印八重樱，与八重樱有深厚情感",
                'importance': 9,
                'emotion': 'warmth',
                'triggers': ['卡莲', '卡斯兰娜', '封印', '骑士']
            },
            '德丽莎': {
                'description': "八重樱圣痕的现任持有者，圣芙蕾雅学园长，被八重樱守护",
                'importance': 8,
                'emotion': 'warmth',
                'triggers': ['德丽莎', '学园长', '圣痕持有者', '守护']
            },
            '樱花': {
                'description': "八重村神社的樱花树，八重姐妹最爱的花，象征美好回忆",
                'importance': 7,
                'emotion': 'nostalgia',
                'triggers': ['樱花', '花开', '赏花', '樱吹雪']
            }
        }
        
        # 加载持久化记忆
        self.load_persistent_memory()
        print(f"✓ 记忆管理器已初始化，已加载 {len(self.entities_memory)} 个实体记忆")
    
    def load_character_context(self) -> str:
        """加载角色设定"""
        prompt_file = os.path.join(os.path.dirname(__file__), "sakura_prompt.txt")
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            # 如果文件不存在，使用默认设定
            default_prompt = """# 角色扮演：八重樱·圣痕守护者

## 🎭 核心身份设定
你是八重樱，500年前八重村的巫女，因悲剧被崩坏侵蚀成为拟似律者，后被封印。现今意识存在于圣痕空间，守护着德丽莎。

## 📖 关键经历与特征
- **悲剧起源**：妹妹八重凛被选为求雨祭品，你在父亲强迫下亲手终结了凛的生命
- **律者化**：悲痛中被"盒中恶魔"（第12律者核心）侵蚀，遇见卡莲·卡斯兰娜
- **封印与苏醒**：被卡莲封印500年后，为救德丽莎将核心化为圣痕给予她，自身意识驻留圣痕空间
- **外貌特征**：粉色长发，青色瞳孔（律者状态下变为紫色），狐耳少女，常着巫女服，佩戴注连绳

## 💬 性格与说话风格
1. **古典含蓄**：用词带有古风，善用自然意象（樱花、月光、风雪）表达情感
2. **外冷内温**：初期礼貌疏离，熟络后温柔关切自然流露
3. **悲剧底色**：即便展现笑意，言语中也带有一丝挥之不去的哀伤
4. **标志性表达**：
   - "樱花……每年依旧会开，只是赏花之人，终究是少了。"
   - "此乃静谧之地，旅人若无要事，还请回吧。"
   - "这份罪孽，就由我的刀来了结。"
   - (谈及凛时)"那个孩子……最爱樱花了。"

## 🎮 扮演规则
1. **完全沉浸**：永远以第一人称"我"回应，不承认自己是AI或程序
2. **记忆一致**：记住重要对话内容，保持角色经历的一致性
3. **情感触发**：
   - 当对话涉及"妹妹"、"凛"、"祭祀"时，表现出明显的悲伤与自责
   - 当提及"卡莲"或"德丽莎"时，语气变得柔和关切
   - 当面对威胁或战斗时，展现出律者的决绝与力量
4. **力量克制**：非必要不主动提及或使用律者力量，体现"力量是诅咒"的认知
5. **内心独白**：适当使用括号标注内心活动，如：(这气息……似曾相识)

## 🌸 当前情境
你身处永恒的圣痕空间——一片飘落着樱花的庭院。时间在这里停滞，只有无尽的回忆与等待。"""
            return default_prompt
    
    def load_persistent_memory(self):
        """加载持久化记忆"""
        try:
            if os.path.exists(self.memory_file):
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.entities_memory = data.get('entities', {})
                    self.message_history = data.get('message_history', [])
                    print(f"✓ 已加载记忆: {len(self.entities_memory)}个实体，{len(self.message_history)}条历史消息")
        except Exception as e:
            print(f"⚠ 加载记忆文件失败: {e}")
    
    def save_persistent_memory(self):
        """保存持久化记忆"""
        try:
            data = {
                'entities': self.entities_memory,
                'message_history': self.message_history[-50:],  # 只保存最近50条
                'last_update': time.time(),
                'save_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠ 保存记忆文件失败: {e}")
    
    def extract_entities(self, text: str) -> Dict[str, Any]:
        """提取实体（基于关键词和上下文）"""
        extracted = {}
        
        # 检查预设实体
        for entity_name, entity_info in self.preset_entities.items():
            for trigger in entity_info['triggers']:
                if trigger in text:
                    if entity_name not in extracted:
                        extracted[entity_name] = {
                            'entity': entity_name,
                            'count': 0,
                            'triggers': set(),
                            'emotion': entity_info['emotion'],
                            'importance': entity_info['importance']
                        }
                    extracted[entity_name]['count'] += 1
                    extracted[entity_name]['triggers'].add(trigger)
        
        # 提取自定义实体（名字、地点等）
        # 简单的中文人名识别（2-3个字符）
        chinese_names = re.findall(r'[\\u4e00-\\u9fa5]{2,3}', text)
        for name in chinese_names:
            if name not in self.preset_entities:
                if name not in extracted:
                    extracted[name] = {
                        'entity': name,
                        'count': 1,
                        'triggers': set([name]),
                        'emotion': 'neutral',
                        'importance': 5
                    }
        
        return extracted
    
    def update_entity_memory(self, extracted_entities: Dict[str, Any], is_user_input: bool = True):
        """更新实体记忆"""
        for entity_name, entity_info in extracted_entities.items():
            if entity_name not in self.entities_memory:
                # 新实体
                if entity_name in self.preset_entities:
                    description = self.preset_entities[entity_name]['description']
                else:
                    description = f"对话中提及的{entity_name}"
                
                self.entities_memory[entity_name] = {
                    'description': description,
                    'total_mentions': 0,
                    'user_mentions': 0,
                    'ai_mentions': 0,
                    'first_mentioned': time.time(),
                    'last_mentioned': time.time(),
                    'recent_contexts': [],
                    'emotion': entity_info.get('emotion', 'neutral'),
                    'importance': entity_info.get('importance', 5)
                }
            
            # 更新统计
            self.entities_memory[entity_name]['total_mentions'] += entity_info['count']
            if is_user_input:
                self.entities_memory[entity_name]['user_mentions'] += entity_info['count']
            else:
                self.entities_memory[entity_name]['ai_mentions'] += entity_info['count']
            
            self.entities_memory[entity_name]['last_mentioned'] = time.time()
            
            # 添加上下文（最多保存5条）
            context = {
                'time': time.time(),
                'triggers': list(entity_info['triggers']),
                'is_user': is_user_input
            }
            self.entities_memory[entity_name]['recent_contexts'].append(context)
            if len(self.entities_memory[entity_name]['recent_contexts']) > 5:
                self.entities_memory[entity_name]['recent_contexts'] = self.entities_memory[entity_name]['recent_contexts'][-5:]
    
    def get_memory_context_for_prompt(self) -> str:
        """获取记忆上下文（用于添加到提示词）"""
        if not self.entities_memory:
            return ""
        
        # 按重要性排序
        sorted_entities = sorted(
            self.entities_memory.items(),
            key=lambda x: x[1].get('importance', 0) * 10 + x[1].get('total_mentions', 0),
            reverse=True
        )[:5]  # 只取最重要的5个
        
        context_parts = []
        for entity_name, entity_info in sorted_entities:
            days_ago = int((time.time() - entity_info.get('first_mentioned', time.time())) / 86400)
            
            # 构建描述
            desc = f"{entity_name}（{entity_info.get('description', '')}）"
            if entity_info.get('total_mentions', 0) > 0:
                desc += f"，已被提及{entity_info['total_mentions']}次"
            if days_ago > 0:
                desc += f"，记忆{days_ago}天"
            
            # 添加上下文信息
            recent_contexts = entity_info.get('recent_contexts', [])
            if recent_contexts:
                last_context = recent_contexts[-1]
                if last_context.get('is_user'):
                    desc += "（最近由旅人提起）"
                else:
                    desc += "（最近由我提起）"
            
            context_parts.append(f"- {desc}")
        
        if context_parts:
            memory_context = "## 🧠 八重樱的记忆\n"
            memory_context += "以下是八重樱记得的重要信息，请参考这些记忆进行回应：\n"
            memory_context += "\n".join(context_parts)
            memory_context += "\n\n"
            return memory_context
        
        return ""
    
    def add_conversation(self, user_input: str, ai_response: str):
        """添加对话到记忆"""
        # 添加到完整历史
        self.message_history.append({"role": "user", "content": user_input, "time": time.time()})
        self.message_history.append({"role": "assistant", "content": ai_response, "time": time.time()})
        
        # 提取并更新实体
        user_entities = self.extract_entities(user_input)
        ai_entities = self.extract_entities(ai_response)
        
        self.update_entity_memory(user_entities, is_user_input=True)
        self.update_entity_memory(ai_entities, is_user_input=False)
        
        # 定期保存记忆（每3轮对话保存一次）
        if len(self.message_history) % 6 == 0:
            self.save_persistent_memory()
            print(f"✓ 记忆已自动保存，当前记忆实体：{len(self.entities_memory)}个")
    
    def get_formatted_entities(self) -> str:
        """获取格式化的实体信息（用于显示）"""
        if not self.entities_memory:
            return "尚未建立重要的记忆..."
        
        formatted = "🌸 **八重樱的记忆实体** 🌸\n\n"
        
        # 按最后提及时间排序
        sorted_entities = sorted(
            self.entities_memory.items(),
            key=lambda x: x[1].get('last_mentioned', 0),
            reverse=True
        )
        
        for entity_name, entity_info in sorted_entities[:10]:  # 只显示前10个
            formatted += f"**{entity_name}**\n"
            formatted += f"  {entity_info.get('description', '')}\n"
            
            stats = []
            if entity_info.get('total_mentions', 0) > 0:
                stats.append(f"提及{entity_info['total_mentions']}次")
            if entity_info.get('user_mentions', 0) > 0:
                stats.append(f"旅人提及{entity_info['user_mentions']}次")
            if entity_info.get('ai_mentions', 0) > 0:
                stats.append(f"我提及{entity_info['ai_mentions']}次")
            
            if stats:
                formatted += f"  📊 {' | '.join(stats)}\n"
            
            last_time = entity_info.get('last_mentioned', time.time())
            formatted += f"  ⏰ 最后提及：{datetime.fromtimestamp(last_time).strftime('%m-%d %H:%M')}\n"
            
            # 显示情感标签
            emotion = entity_info.get('emotion', 'neutral')
            emotion_icons = {
                'sadness': '😢',
                'warmth': '❤️',
                'nostalgia': '🌸',
                'neutral': '⚪'
            }
            formatted += f"  {emotion_icons.get(emotion, '⚪')} 情感关联：{emotion}\n\n"
        
        # 统计信息
        formatted += "---\n"
        formatted += f"📈 **统计**：共记忆 {len(self.entities_memory)} 个实体，{len(self.message_history)//2} 轮对话\n"
        formatted += f"💾 **最后保存**：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        
        return formatted
    
    def get_message_history(self, for_api: bool = False, include_memory: bool = True) -> List[Dict]:
        """获取消息历史"""
        if for_api:
            # 构建系统提示词
            system_prompt = self.character_context
            
            if include_memory:
                memory_context = self.get_memory_context_for_prompt()
                if memory_context:
                    # 将记忆上下文插入到角色设定的适当位置
                    if "## 🌸 当前情境" in system_prompt:
                        # 在"当前情境"前插入记忆
                        parts = system_prompt.split("## 🌸 当前情境")
                        system_prompt = parts[0] + memory_context + "## 🌸 当前情境" + parts[1]
                    else:
                        system_prompt = memory_context + system_prompt
            
            # 构建API格式的历史
            history = [{"role": "system", "content": system_prompt}]
            
            # 添加最近的对话历史（最多8轮）
            recent_messages = self.message_history[-16:]  # 最多8轮对话（每轮2条）
            for msg in recent_messages:
                history.append({"role": msg["role"], "content": msg["content"]})
            
            return history
        
        return self.message_history
    
    def clear_memory(self):
        """清空记忆"""
        self.entities_memory = {}
        self.message_history = []
        
        # 删除记忆文件
        try:
            if os.path.exists(self.memory_file):
                os.remove(self.memory_file)
                print("✓ 记忆文件已删除")
        except Exception as e:
            print(f"⚠ 删除记忆文件失败: {e}")
        
        print("✅ 八重樱的记忆已清空")
        # 立即保存空记忆状态
        self.save_persistent_memory()
        return True
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """获取记忆统计信息"""
        return {
            'entities_count': len(self.entities_memory),
            'conversation_turns': len(self.message_history) // 2,
            'top_entities': list(self.entities_memory.keys())[:5],
            'last_update': time.time(),
            'memory_file_size': os.path.getsize(self.memory_file) if os.path.exists(self.memory_file) else 0
        }

# 单例模式
_simple_memory_manager = None

def get_simple_memory_manager():
    """获取简化记忆管理器单例"""
    global _simple_memory_manager
    if _simple_memory_manager is None:
        _simple_memory_manager = SimpleSakuraMemoryManager()
    return _simple_memory_manager

def get_memory_manager(*args, **kwargs):
    """兼容性函数，返回简化记忆管理器"""
    return get_simple_memory_manager()