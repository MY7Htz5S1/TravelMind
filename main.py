import sys
import os
import re
from urllib.parse import urlparse
import shutil
import platform
import time
import traceback
import json
from datetime import datetime
from os.path import abspath
import requests
import json
from sseclient import SSEClient

# 新增：语音和图片处理相关导入
import base64
import tempfile
import speech_recognition as sr
import whisper
from PIL import Image

# IMPORT / GUI AND MODULES AND WIDGETS
# ///////////////////////////////////////////////////////////////
from modules import *
from widgets import *
from PySide6.QtCore import QThread, Signal

os.environ["QT_FONT_DPI"] = "96"  # FIX Problem for High DPI and Scale above 100%

# SET AS GLOBAL WIDGETS
# ///////////////////////////////////////////////////////////////
widgets = None


class ChatHistoryItem(QListWidgetItem):
    """Custom history item with chat data"""

    def __init__(self, chat_data, parent=None):
        super().__init__(parent)
        self.chat_data = chat_data

        # Create display text
        timestamp = datetime.fromisoformat(chat_data['timestamp']).strftime("%Y-%m-%d %H:%M")

        # Use custom title if available, otherwise use first message
        if chat_data.get('title'):
            display_title = chat_data['title']
        else:
            first_message = chat_data['messages'][0]['content'] if chat_data['messages'] else "Empty chat"
            # Truncate long messages
            if len(first_message) > 50:
                first_message = first_message[:50] + "..."
            display_title = first_message

        display_text = f"[{timestamp}] {display_title}"
        self.setText(display_text)

        # Set tooltip with more details
        message_count = len([msg for msg in chat_data['messages'] if msg['role'] == 'user'])
        tooltip = f"Time: {timestamp}\nMessages: {message_count}\nFirst message: {chat_data['messages'][0]['content'] if chat_data['messages'] else 'None'}"
        self.setToolTip(tooltip)


class StreamingChatMessage(QFrame):
    """Custom chat message component with streaming support"""

    def __init__(self, is_user=True, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        self.message_label = None
        self.current_text = ""
        self.setupUI()

    def setupUI(self):
        self.setObjectName("chatMessage")
        self.setFrameShape(QFrame.NoFrame)
        self.setFrameShadow(QFrame.Raised)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        if self.is_user:
            # User message: right-aligned
            spacer = QSpacerItem(200, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)  # Reduced from 40
            layout.addItem(spacer)

            self.message_label = QLabel()
            self.message_label.setWordWrap(True)
            self.message_label.setMaximumWidth(800)  # Increased from 500
            self.message_label.setStyleSheet("""
                QLabel {
        background-color: rgb(44, 49, 58);
        color: rgb(221, 221, 221);
        border-radius: 12px;
        padding: 12px 16px;
        font-size: 16px;                                                    /* 字体大小 */
        font-family: "Microsoft YaHei UI", "PingFang SC", system-ui;       /* 字体类型 */
        font-weight: normal;                                                /* 字体粗细 */
        line-height: 1.5;                                                  /* 行高 */
        margin-left: 10px;
    }
            """)
            layout.addWidget(self.message_label)
        else:
            # AI message: left-aligned
            # AI avatar
            avatar = QLabel("🤖")
            avatar.setFixedSize(30, 30)
            avatar.setAlignment(Qt.AlignCenter)
            avatar.setStyleSheet("""
                QLabel {
                    background-color: rgb(68, 71, 90);
                    border-radius: 15px;
                    font-size: 16px;
                }
            """)
            layout.addWidget(avatar)

            self.message_label = QLabel()
            self.message_label.setWordWrap(True)
            self.message_label.setMaximumWidth(800)  # Increased from 500
            self.message_label.setStyleSheet("""
                QLabel {
                    background-color: rgb(44, 49, 58);
                    color: rgb(221, 221, 221);
                    border-radius: 12px;
                    padding: 10px 15px;
                    font-size: 16px;                    /* 字体大小：14px -> 16px */
                    font-family: "Microsoft YaHei UI";  /* 字体：微软雅黑 */
                    font-weight: normal;                /* 字体粗细 */
                    line-height: 1.4;                  /* 行高：让文字更易读 */
                    margin-left: 10px;
                }
            """)
            layout.addWidget(self.message_label)

            spacer = QSpacerItem(100, 20, QSizePolicy.Minimum, QSizePolicy.Minimum)  # Reduced space on right
            layout.addItem(spacer)

    def setText(self, text):
        """Set the complete text"""
        self.current_text = text
        self.message_label.setText(text)

    def appendText(self, text):
        """追加文本到消息（用于流式显示）"""
        self.current_text += text
        self.message_label.setText(self.current_text)
        
        # 确保文本显示完整
        self.message_label.adjustSize()
        self.adjustSize()
        

    def addCursor(self):
        """Add a blinking cursor effect"""
        self.message_label.setText(self.current_text + "▌")

    def removeCursor(self):
        """Remove the cursor"""
        self.message_label.setText(self.current_text)


class TypingIndicator(QFrame):
    """Typing indicator"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()
        self.timer = QTimer()
        self.timer.timeout.connect(self.updateDots)
        self.dots = 0

    def setupUI(self):
        self.setObjectName("typingIndicator")
        self.setFrameShape(QFrame.NoFrame)
        self.setFrameShadow(QFrame.Raised)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        # AI avatar
        avatar = QLabel("🤖")
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet("""
            QLabel {
                background-color: rgb(68, 71, 90);
                border-radius: 15px;
                font-size: 16px;
            }
        """)
        layout.addWidget(avatar)

        self.typing_label = QLabel("Typing...")
        self.typing_label.setStyleSheet("""
            QLabel {
                background-color: rgb(44, 49, 58);
                color: rgb(113, 126, 149);
                border-radius: 12px;
                padding: 10px 15px;
                font-size: 14px;
                font-style: italic;
                margin-left: 10px;
            }
        """)
        layout.addWidget(self.typing_label)

        spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout.addItem(spacer)

    def start(self):
        self.timer.start(500)

    def stop(self):
        self.timer.stop()

    def updateDots(self):
        self.dots = (self.dots + 1) % 4
        text = "Typing" + "." * self.dots
        self.typing_label.setText(text)


class DifyAPIClient:
    """增强版 Dify API客户端 - 支持图片上传"""

    def __init__(self, api_key, base_url="https://api.dify.ai/v1", user="default_user"):
        self.api_key = api_key
        self.base_url = base_url
        self.user = user  # 添加默认用户标识
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def upload_file(self, file_path, user=None):
        """上传文件并返回文件ID"""
        if user is None:
            user = self.user
            
        try:
            with open(file_path, 'rb') as f:
                filename = os.path.basename(file_path)
                mime_type = self.get_mime_type(filename)
                
                files = {'file': (filename, f, mime_type)}
                headers = {"Authorization": f"Bearer {self.api_key}"}
                data = {'user': user}
                
                response = requests.post(
                    f"{self.base_url}/files/upload",
                    headers=headers,
                    files=files,
                    data=data
                )
                
                if response.status_code == 201:  # 注意状态码改为201
                    file_data = response.json()
                    return file_data.get('id')  # 返回文件ID
                else:
                    error_msg = f"文件上传失败 ({response.status_code}): {response.text[:100]}"
                    print(error_msg)
                    return None
                
        except Exception as e:
            print(f"文件上传错误: {e}")
            return None
        

    def get_mime_type(self, filename):
        """根据文件名获取MIME类型"""
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.txt': 'text/plain',
        }
        ext = os.path.splitext(filename)[1].lower()
        return mime_types.get(ext, 'application/octet-stream')
    
    def chat_with_files(self, message, file_paths=None, conversation_id=None, user_id="travelmind_user"):
        url = f"{self.base_url}/chat-messages"
    
        # 构建文件信息列表
        piclist = []
        if file_paths:
            for file_path in file_paths:
                if os.path.exists(file_path):
                    file_id = self.upload_file(file_path, user=user_id)
                    if file_id:
                        piclist.append({
                            "type": "image" if self.is_image(file_path) else "file",
                            "transfer_method": "local_file",
                            "upload_file_id": file_id
                        })
        
        # 构建请求数据
        data = {
            "inputs": {},  # 使用test.py的格式
            "user": user_id,
            "query": message,
            "response_mode": "streaming",
            "files":piclist,
            "conversation_id": conversation_id or ""
        }
        
        try:
            response = requests.post(
                url,
                headers=self.headers,
                json=data,
                stream=True,
                timeout=30
            )
        
            # 检查响应状态
            if response.status_code not in (200,201):
                error_msg = f"API返回错误 ({response.status_code}): "
                try:
                    error_data = response.json()
                    error_msg += error_data.get("message", "未知错误")
                    if "detail" in error_data:
                        error_msg += f" - {error_data['detail']}"
                except:
                    error_msg += response.text[:200] + "..."
                raise Exception(error_msg)
            
            return response
        except requests.exceptions.RequestException as e:
            raise Exception(f"API请求失败: {str(e)}")
            
    def is_image(self, file_path):
        """更精确的图片类型检查"""
        image_exts = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
        ext = os.path.splitext(file_path)[1].lower()
        return ext in image_exts
    
    
    def extract_image_urls(self, response_text):
        """提取不带签名的图片URL"""
        # 查找所有可能的URL片段
        pattern = r'(https?://[^\s"\'<]+)'
        raw_urls = re.findall(pattern, response_text)
    
        clean_urls = []
        for url in raw_urls:
            # 修复特殊格式问题
            url = url.replace('%!F(MISSING)', '/').replace('%!F', '/')
        
            # 移除URL末尾的无效字符
            url = re.sub(r'[?&]+$', '', url)
        
            # 仅保留有效的图片URL
            if any(url.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif']):
                clean_urls.append(url)
    
        return clean_urls

    def clean_url(self, url):
        """清理并修正URL"""
        # 去除末尾的标点符号和空格
        clean_url = re.sub(r'[.,;)\s]+$', '', url.strip())
    
        # 处理不完整URL
        clean_url = re.sub(r'\\.$', '', clean_url)
    
        # 移除常见多余字符
        for char in ['"', "'", '`', '>', '<', '}']:
            clean_url = clean_url.replace(char, '')
        
        return clean_url
    

class SimpleVoiceThread(QThread):
    """简单的语音识别线程"""
    voice_result = Signal(str)
    voice_error = Signal(str)

    def __init__(self):
        super().__init__()
        self.is_recording = False

        # 初始化语音识别
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()

        # 初始化Whisper
        try:
            print("正在加载Whisper模型...")
            self.whisper_model = whisper.load_model("base")
            print("✅ Whisper模型加载完成")
        except Exception as e:
            print(f"❌ Whisper加载失败: {e}")
            self.whisper_model = None

        # 调整环境噪音
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
        except Exception as e:
            print(f"麦克风初始化警告: {e}")

    def start_recording(self):
        self.is_recording = True
        self.start()

    def stop_recording(self):
        self.is_recording = False

    def run(self):
        try:
            print("🎤 开始录音...")

            with self.microphone as source:
                audio = self.recognizer.listen(source, timeout=10, phrase_time_limit=30)

            if not self.is_recording:
                return

            print("🔄 正在识别语音...")
            text = self.recognize_with_whisper(audio)

            if text and text.strip():
                self.voice_result.emit(text.strip())
            else:
                self.voice_error.emit("未识别到有效语音")

        except Exception as e:
            self.voice_error.emit(f"语音识别失败: {str(e)}")

    def recognize_with_whisper(self, audio):
        try:
            if self.whisper_model:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
                    tmp_filename = tmp_file.name
                    with open(tmp_filename, "wb") as f:
                        f.write(audio.get_wav_data())

                result = self.whisper_model.transcribe(tmp_filename, language="zh")
                os.unlink(tmp_filename)
                return result["text"]
            else:
                return self.recognizer.recognize_google(audio, language="zh-CN")

        except Exception as e:
            print(f"Whisper识别错误: {e}")
            try:
                return self.recognizer.recognize_google(audio, language="zh-CN")
            except:
                raise Exception("所有识别方法都失败了")


class APIConfig:
    """API配置管理"""
    CONFIG_FILE = "api_config.json"

    @staticmethod
    def load_config():
        """加载配置"""
        try:
            with open(APIConfig.CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {
                "dify_api_key": "",
                "dify_base_url": "https://api.dify.ai/v1",
                "stream_enabled": True,
                "typing_speed": 0.03  # 默认打字速度
            }

    @staticmethod
    def save_config(config):
        """保存配置"""
        with open(APIConfig.CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)


class EnhancedAIResponseThread(QThread):
    """支持图片的AI响应线程"""
    response_chunk = Signal(str)
    response_complete = Signal(str, str)
    error_occurred = Signal(str)
    file_received = Signal(dict)  # 文件接收信号

    def __init__(self, message, api_key=None, file_paths=None, conversation_id=None, stream=True, typing_speed=0.03):
        super().__init__()
        self.message = message
        self.api_key = api_key
        self.file_paths = file_paths or []
        self.conversation_id = conversation_id
        self.stream = stream
        self.typing_speed = typing_speed  # 添加打字速度属性
        self.is_cancelled = False
        self.full_response = ""  # 存储完整的响应文本

        if not api_key:
            self.test_mode = True
        else:
            self.test_mode = False
            self.client = DifyAPIClient(api_key)

    def run(self):
        try:
            if self.test_mode:
                self._handle_test_response()
            elif self.stream:
                self._handle_streaming_response()
            else:
                self._handle_blocking_response()
        except Exception as e:
            self.error_occurred.emit(str(e))

    def _handle_test_response(self):
        time.sleep(0.5)
        response = f"这是测试回复。收到消息: {self.message}"
        if self.image_path:
            response += "\n我看到您上传了一张图片，但测试模式无法分析图片内容。"

        for char in response:
            if self.is_cancelled:
                break
            self.response_chunk.emit(char)
            time.sleep(0.05)

        if not self.is_cancelled:
            self.response_complete.emit("")

    def _handle_streaming_response(self):
        """处理流式响应 - 逐块显示内容"""
        try:
            # 使用修改后的chat_with_files方法
            response = self.client.chat_with_files(
                self.message,
                self.file_paths,
                self.conversation_id,
                user_id="travelmind_user"  # 使用test.py中的用户标识
            )
            
            # 检查响应状态
            if response.status_code != 200:
                error_msg = f"API返回错误 ({response.status_code}): "
                try:
                    error_data = response.json()
                    error_msg += error_data.get("message", "未知错误")
                    if "detail" in error_data:
                        error_msg += f" - {error_data['detail']}"
                except:
                    error_msg += response.text[:200] + "..."
                raise Exception(error_msg)
            
            # 手动处理SSE流
            buffer = ""
            new_conversation_id = self.conversation_id
            last_message_id = None
            content_buffer = ""  # 用于累积当前消息的内容
        
            for line in response.iter_lines():
                if self.is_cancelled:
                    break
                
                if line:
                    # 解码行
                    decoded_line = line.decode('utf-8').strip()

                    # 检查事件前缀
                    if decoded_line.startswith("data:"):
                        event_data = decoded_line[5:].strip()

                        # 检查是否是结束标记
                        if event_data == "[DONE]":
                            # 发送缓冲区中剩余的内容
                            if content_buffer:
                                # 逐字符发送剩余内容
                                for char in content_buffer:
                                    if self.is_cancelled:
                                        break
                                    self.response_chunk.emit(char)
                                    time.sleep(self.typing_speed)  # 添加延迟以实现打字机效果
                            break
                        
                        # 尝试解析JSON
                        try:
                            data = json.loads(event_data)
                            event_type = data.get("event")
                        
                            if event_type == "message":
                                # 处理消息事件
                                if not new_conversation_id and data.get("conversation_id"):
                                    new_conversation_id = data["conversation_id"]
                            
                                # 检查是否是新的消息
                                message_id = data.get("id")
                                if message_id != last_message_id:
                                    # 发送上一条消息的剩余内容
                                    if content_buffer:
                                        # 逐字符发送剩余内容
                                        for char in content_buffer:
                                            if self.is_cancelled:
                                                break
                                            self.response_chunk.emit(char)
                                            time.sleep(self.typing_speed)  # 添加延迟以实现打字机效果
                                    content_buffer = ""
                                    last_message_id = message_id
                            
                                # 获取增量内容
                                content = data.get("answer", "")
                                if content:
                                    # 逐字符发送（模拟打字机效果）
                                    for char in content:
                                        if self.is_cancelled:
                                            break
                                        self.response_chunk.emit(char)
                                        time.sleep(self.typing_speed)  # 添加延迟以实现打字机效果
                            
                            # 处理文件
                            if "files" in data:
                                for file_info in data["files"]:
                                    self.file_received.emit(file_info)
                            
                            elif event_type == "message_end":
                                # 发送剩余内容并结束
                                if content_buffer:
                                    self.response_chunk.emit(content_buffer)
                                break
                                
                            elif event_type == "error":
                                error_msg = data.get("message", "未知错误")
                                self.error_occurred.emit(f"API错误: {error_msg}")
                                break
                                
                        except json.JSONDecodeError:
                            print(f"JSON解析失败: {event_data}")
                            continue
                    
                    # 处理缓冲
                    buffer += decoded_line
                    if buffer.startswith("data:") and not buffer.endswith("}"):
                        continue  # 等待完整数据
                    else:
                        buffer = ""  # 重置缓冲区

            if not self.is_cancelled:
                # 发送完整响应
                self.response_complete.emit(new_conversation_id or "", self.full_response)

        except Exception as e:
            print(f"流式响应处理异常: {str(e)}")
            self.error_occurred.emit(f"API调用错误: {str(e)}")

    def _handle_blocking_response(self):
        try:
            result = self.client.chat_completion(self.message, self.conversation_id)
            content = result.get("answer", "抱歉，我现在无法回答您的问题。")
            conversation_id = result.get("conversation_id", "")

            for char in content:
                if self.is_cancelled:
                    break
                self.response_chunk.emit(char)
                time.sleep(0.03)

            if not self.is_cancelled:
                self.response_complete.emit(conversation_id)

        except Exception as e:
            self.error_occurred.emit(f"API调用错误: {str(e)}")

    def cancel(self):
        self.is_cancelled = True


class ChatHistoryManager:
    """Manage chat history storage and retrieval with auto-save support"""

    def __init__(self):
        self.history_file = "chat_history.json"
        self.ensure_history_file()

    def ensure_history_file(self):
        """Ensure history file exists"""
        if not os.path.exists(self.history_file):
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def save_or_update_chat(self, chat_history, session_id=None, title=None):
        """保存新聊天或更新现有聊天会话"""
        if not chat_history:
            return None

        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except:
            history = []

        if session_id:
            for i, chat_record in enumerate(history):
                if chat_record.get('id') == session_id:
                    # 保存文件路径信息
                    updated_messages = []
                    for msg in chat_history:
                        if "file_paths" in msg and msg["file_paths"]:
                            # 只保存文件名，不保存完整路径
                            file_names = [os.path.basename(path) for path in msg["file_paths"]]
                            msg["file_info"] = file_names
                            del msg["file_paths"]  # 删除路径信息
                        updated_messages.append(msg)
                    
                    chat_record['messages'] = updated_messages
                    chat_record['last_updated'] = datetime.now().isoformat()
                    
                    with open(self.history_file, 'w', encoding='utf-8') as f:
                        json.dump(history, f, ensure_ascii=False, indent=2)
                    return session_id

        # 处理新会话
        new_session_id = str(int(time.time() * 1000))
        
        # 处理文件路径信息
        processed_messages = []
        for msg in chat_history:
            if "file_paths" in msg and msg["file_paths"]:
                # 只保存文件名，不保存完整路径
                file_names = [os.path.basename(path) for path in msg["file_paths"]]
                msg["file_info"] = file_names
                del msg["file_paths"]  # 删除路径信息
            # 处理AI返回的文件
            if "files" in msg:
                file_info = []
                for file_data in msg["files"]:
                    # 只保存必要的文件信息
                    file_info.append({
                        "name": file_data.get("name", "unknown"),
                        "type": file_data.get("type", "file")
                    })
                msg["files"] = file_info
            processed_messages.append(msg)

        # 处理图片信息
        for msg in processed_messages:
            if msg["role"] == "assistant" and "images" in msg:
                # 只保存文件名
                msg["images"] = [os.path.basename(p) for p in msg["images"]]
                                 
        chat_record = {
            'id': new_session_id,
            'timestamp': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'title': title,
            'messages': processed_messages
        }

        history.insert(0, chat_record)
        history = history[:50]  # 只保留最近的50条记录

        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        return new_session_id

    def load_history(self):
        """Load all chat history"""
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []

    def delete_chat(self, chat_id):
        """Delete a specific chat from history"""
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except:
            return

        history = [chat for chat in history if chat.get('id') != chat_id]

        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    def clear_all_history(self):
        """Clear all chat history"""
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump([], f)


def process_uploaded_image(image_path):
    """处理上传的图片"""
    try:
        with Image.open(image_path) as img:
            print(f"图片信息: {img.size}, {img.mode}")

            if img.size[0] > 1024 or img.size[1] > 1024:
                img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                compressed_path = image_path.replace('.', '_compressed.')
                img.save(compressed_path, "JPEG", quality=85)
                return compressed_path

            return image_path

    except Exception as e:
        print(f"图片处理失败: {e}")
        return image_path


class MainWindow(QMainWindow):
    def __init__(self):
        QMainWindow.__init__(self)
        
        # 添加客户端初始化
        config = APIConfig.load_config()
        api_key = config.get("dify_api_key", "")
        self.client = DifyAPIClient(api_key, user="travelmind_user") if api_key else None
        
        # 初始化生成的图片列表
        self.generated_images = []

        # SET AS GLOBAL WIDGETS
        # ///////////////////////////////////////////////////////////////
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        global widgets
        widgets = self.ui

        # AI chat related variables
        self.chat_history = []
        self.typing_indicator = None
        self.ai_thread = None
        self.current_ai_message = None
        self.cursor_timer = None

        # Session management for auto-save
        self.current_session_id = None
        self.auto_save_enabled = True

        # History manager
        self.history_manager = ChatHistoryManager()

        # 新增：语音和图片相关变量
        self.voice_thread = None
        self.is_voice_recording = False
        self.current_image_path = None
        self.current_file_paths = []  # 存储多个文件路径
        # USE CUSTOM TITLE BAR | USE AS "False" FOR MAC OR LINUX
        # ///////////////////////////////////////////////////////////////
        Settings.ENABLE_CUSTOM_TITLE_BAR = True

        # APP NAME
        # ///////////////////////////////////////////////////////////////
        title = "TravelMind"
        description = "TravelMind - AI Travel Assistant"
        self.setWindowTitle(title)
        widgets.titleRightInfo.setText(description)
        self.filePreviewLayout = QHBoxLayout()
        widgets.chat_input_layout.insertLayout(0, self.filePreviewLayout)
        # Update UI texts to English
        self.updateUITexts()

        # TOGGLE MENU
        # ///////////////////////////////////////////////////////////////
        widgets.toggleButton.clicked.connect(lambda: UIFunctions.toggleMenu(self, True))

        # SET UI DEFINITIONS
        # ///////////////////////////////////////////////////////////////
        UIFunctions.uiDefinitions(self)

        # QTableWidget PARAMETERS
        # ///////////////////////////////////////////////////////////////
        widgets.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # BUTTONS CLICK
        # ///////////////////////////////////////////////////////////////
        widgets.btn_home.clicked.connect(self.buttonClick)
        widgets.btn_ai_chat.clicked.connect(self.buttonClick)
        widgets.btn_history.clicked.connect(self.buttonClick)
        widgets.btn_theme.clicked.connect(self.buttonClick)
        widgets.btn_exit.clicked.connect(self.buttonClick)

        # Home page buttons
        widgets.start_chat_button.clicked.connect(self.startChatFromHome)

        # AI chat function buttons
        widgets.sendButton.clicked.connect(self.sendMessage)
        widgets.clearChatButton.clicked.connect(self.clearChat)

        # History page buttons
        widgets.loadChatButton.clicked.connect(self.loadSelectedChat)
        widgets.deleteChatButton.clicked.connect(self.deleteSelectedChat)
        widgets.clearHistoryButton.clicked.connect(self.clearAllHistory)

        # Input box enter to send
        widgets.chatInputArea.installEventFilter(self)

        # Quick suggestion buttons
        for btn in widgets.suggestion_buttons:
            btn.clicked.connect(lambda checked, button=btn: self.sendSuggestion(button.text()))

        # History list selection change
        widgets.historyList.itemSelectionChanged.connect(self.onHistorySelectionChanged)

        # 新增：设置语音和图片功能
        self.setupSimpleVoiceAndImage()

        # Load history on startup
        self.loadHistoryList()

        # SHOW APP
        # ///////////////////////////////////////////////////////////////
        self.show()

        # SET CUSTOM THEME
        # ///////////////////////////////////////////////////////////////
        if getattr(sys, "frozen", False):
            absPath = os.path.dirname(os.path.abspath(sys.executable))
        elif __file__:
            absPath = os.path.dirname(os.path.abspath(__file__))
        useCustomTheme = True
        self.useCustomTheme = useCustomTheme
        self.absPath = absPath
        themeFile = "themes\\py_dracula_dark.qss"

        # SET THEME AND HACKS
        if useCustomTheme:
            UIFunctions.theme(self, themeFile, True)
            AppFunctions.setThemeHack(self)

        # SET HOME PAGE AND SELECT MENU
        # ///////////////////////////////////////////////////////////////
        widgets.stackedWidget.setCurrentWidget(widgets.home)
        widgets.btn_home.setStyleSheet(UIFunctions.selectMenu(widgets.btn_home.styleSheet()))

        widgets.textEdit.setPlainText("")


        # 修改为存储多个文件路径
        self.current_file_paths = []  # 存储多个文件路径
        
        # 添加文件预览布局
        self.filePreviewLayout = QHBoxLayout()
        widgets.chat_input_layout.insertLayout(0, self.filePreviewLayout)
        
        # 存储当前对话生成的图片
        self.download_dir = os.path.join(os.getcwd(), "downloads")
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)
            
        self.generated_images = []  

    def init_dify_integration(self):
            """初始化Dify集成"""
            self.dify_conversation_id = None
            config = APIConfig.load_config()
            if not config.get("dify_api_key"):
                QTimer.singleShot(2000, self.showFirstTimeSetup)

    def setupSimpleVoiceAndImage(self):
        """设置简单的语音和图片功能"""

        # 添加语音按钮
        self.voiceButton = QPushButton()
        self.voiceButton.setObjectName("voiceButton")
        self.voiceButton.setMinimumSize(QSize(50, 80))
        self.voiceButton.setMaximumSize(QSize(50, 80))
        self.voiceButton.setCursor(QCursor(Qt.PointingHandCursor))
        self.voiceButton.setStyleSheet("""
            QPushButton {
                background-color: rgb(34, 139, 34);
                border: none;
                border-radius: 8px;
                padding: 8px;
                font-size: 20px;
            }
            QPushButton:hover {
                background-color: rgb(50, 155, 50);
            }
            QPushButton:pressed {
                background-color: rgb(220, 53, 69);
            }
        """)
        self.voiceButton.setText("🎤")
        self.voiceButton.setToolTip("按住录音")

        # 语音按钮事件
        self.voiceButton.pressed.connect(self.startVoiceRecording)
        self.voiceButton.released.connect(self.stopVoiceRecording)

        # 添加图片按钮
        self.imageButton = QPushButton()
        self.imageButton.setObjectName("imageButton")
        self.imageButton.setMinimumSize(QSize(50, 80))
        self.imageButton.setMaximumSize(QSize(50, 80))
        self.imageButton.setCursor(QCursor(Qt.PointingHandCursor))
        self.imageButton.setStyleSheet("""
            QPushButton {
                background-color: rgb(102, 51, 153);
                border: none;
                border-radius: 8px;
                padding: 8px;
                font-size: 20px;
            }
            QPushButton:hover {
                background-color: rgb(122, 71, 173);
            }
            QPushButton:pressed {
                background-color: rgb(82, 31, 133);
            }
        """)
        self.imageButton.setText("📷")
        self.imageButton.setToolTip("上传图片")
        self.imageButton.clicked.connect(self.selectImage)

        # 将按钮添加到现有的输入布局中
        widgets.input_horizontal_layout.insertWidget(1, self.voiceButton)
        widgets.input_horizontal_layout.insertWidget(2, self.imageButton)

        # 添加图片预览标签
        self.imagePreview = QLabel()
        self.imagePreview.setObjectName("imagePreview")
        self.imagePreview.setMaximumSize(QSize(100, 80))
        self.imagePreview.setStyleSheet("""
            QLabel {
                border: 2px dashed rgb(89, 92, 111);
                border-radius: 8px;
                background-color: rgba(44, 49, 58, 0.5);
                color: rgb(113, 126, 149);
                text-align: center;
            }
        """)
        self.imagePreview.setText("暂无图片")
        self.imagePreview.setAlignment(Qt.AlignCenter)
        self.imagePreview.hide()

        # 将图片预览添加到聊天输入布局上方
        widgets.chat_input_layout.insertWidget(0, self.imagePreview)


        self.fileButton = QPushButton()
        self.fileButton.setObjectName("fileButton")
        self.fileButton.setMinimumSize(QSize(50, 80))
        self.fileButton.setMaximumSize(QSize(50, 80))
        self.fileButton.setCursor(QCursor(Qt.PointingHandCursor))
        self.fileButton.setStyleSheet("""
            QPushButton {
                background-color: rgb(153, 102, 51);
                border: none;
                border-radius: 8px;
                padding: 8px;
                font-size: 20px;
            }
            QPushButton:hover {
                background-color: rgb(173, 122, 71);
            }
            QPushButton:pressed {
                background-color: rgb(133, 82, 31);
            }
        """)
        self.fileButton.setText("📄📄📄📄")
        self.fileButton.setToolTip("上传文件")
        self.fileButton.clicked.connect(self.selectFiles)
        
        # 将按钮添加到输入布局
        widgets.input_horizontal_layout.insertWidget(3, self.fileButton)

    def startVoiceRecording(self):
        """开始语音录制"""
        if self.is_voice_recording:
            return

        print("🎤 开始录音...")
        self.is_voice_recording = True

        # 更新按钮样式
        self.voiceButton.setText("⏹️")
        self.voiceButton.setStyleSheet("""
            QPushButton {
                background-color: rgb(220, 53, 69);
                border: none;
                border-radius: 8px;
                padding: 8px;
                font-size: 20px;
            }
        """)

        # 创建并启动语音线程
        self.voice_thread = SimpleVoiceThread()
        self.voice_thread.voice_result.connect(self.handleVoiceResult)
        self.voice_thread.voice_error.connect(self.handleVoiceError)
        self.voice_thread.start_recording()

    def stopVoiceRecording(self):
        """停止语音录制"""
        if not self.is_voice_recording:
            return

        print("⏹️ 停止录音...")
        self.is_voice_recording = False

        # 恢复按钮样式
        self.voiceButton.setText("🎤")
        self.voiceButton.setStyleSheet("""
            QPushButton {
                background-color: rgb(34, 139, 34);
                border: none;
                border-radius: 8px;
                padding: 8px;
                font-size: 20px;
            }
            QPushButton:hover {
                background-color: rgb(50, 155, 50);
            }
        """)

        if self.voice_thread:
            self.voice_thread.stop_recording()

    def handleVoiceResult(self, text):
        """处理语音识别结果"""
        print(f"✅ 语音识别成功: {text}")

        # 将识别结果添加到输入框
        current_text = widgets.chatInputArea.toPlainText()
        if current_text.strip():
            widgets.chatInputArea.setPlainText(current_text + " " + text)
        else:
            widgets.chatInputArea.setPlainText(text)

    def handleVoiceError(self, error_msg):
        """处理语音识别错误"""
        print(f"❌ 语音识别失败: {error_msg}")

    def selectImage(self):
        """选择多个图片文件"""
        file_dialog = QFileDialog()
        file_paths, _ = file_dialog.getOpenFileNames(
            self,
            "选择图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp);;所有文件 (*)"
        )

        if file_paths:
            self.current_file_paths.extend(file_paths)
            self.updateFilePreviews()

    
    def selectFiles(self):
        """选择多个文件（任意类型）"""
        file_dialog = QFileDialog()
        file_paths, _ = file_dialog.getOpenFileNames(
            self,
            "选择文件",
            "",
            "所有文件 (*);;图片文件 (*.png *.jpg *.jpeg *.gif);;文档 (*.pdf *.doc *.docx *.txt)"
        )
        
        if file_paths:
            self.current_file_paths.extend(file_paths)
            self.updateFilePreviews()

    def updateFilePreviews(self):
        """更新文件预览区域"""
        # 清除现有预览
        self.clearFilePreviews()
        
        # 添加新文件预览
        for file_path in self.current_file_paths:
            self.addFilePreview(file_path)

    def clearFilePreviews(self):
        """清除所有文件预览"""
        while self.filePreviewLayout.count():
            item = self.filePreviewLayout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def addFilePreview(self, file_path):
        """添加文件预览"""
        try:
            filename = os.path.basename(file_path)
            
            # 创建预览容器
            container = QWidget()
            container.setMaximumSize(100, 100)
            layout = QVBoxLayout(container)
            layout.setContentsMargins(2, 2, 2, 2)
            
            # 根据文件类型显示不同预览
            if self.client.is_image(file_path):
                # 图片预览
                pixmap = QPixmap(file_path)
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    preview = QLabel()
                    preview.setPixmap(scaled_pixmap)
                    layout.addWidget(preview)
            else:
                # 文件图标预览
                icon = QLabel("📄📄")
                icon.setAlignment(Qt.AlignCenter)
                icon.setStyleSheet("font-size: 24px;")
                layout.addWidget(icon)
                
            # 文件名标签
            name_label = QLabel(filename)
            name_label.setAlignment(Qt.AlignCenter)
            name_label.setStyleSheet("font-size: 10px;")
            name_label.setWordWrap(True)
            layout.addWidget(name_label)
            
            # 删除按钮
            delete_btn = QPushButton("×")
            delete_btn.setFixedSize(20, 20)
            delete_btn.setStyleSheet("background-color: red; color: white; border-radius: 10px;")
            delete_btn.clicked.connect(lambda: self.removeFile(file_path))
            
            # 添加到预览布局
            self.filePreviewLayout.addWidget(container)
            
        except Exception as e:
            print(f"文件预览失败: {e}")

    def removeFile(self, file_path):
        """移除文件"""
        if file_path in self.current_file_paths:
            self.current_file_paths.remove(file_path)
            self.updateFilePreviews()



    def showImagePreview(self, image_path):
        """显示图片预览"""
        try:
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    80, 60,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.imagePreview.setPixmap(scaled_pixmap)
                self.imagePreview.setText("")
                self.imagePreview.show()

                # 双击清除
                self.imagePreview.mouseDoubleClickEvent = lambda event: self.clearImagePreview()

            else:
                self.imagePreview.setText("图片加载失败")

        except Exception as e:
            print(f"图片预览失败: {e}")
            self.imagePreview.setText("预览失败")

    def clearImagePreview(self):
        """清除图片预览"""
        self.current_image_path = None
        self.imagePreview.clear()
        self.imagePreview.setText("暂无图片")
        self.imagePreview.hide()
        print("🗑️ 图片已清除")

    def addImageToChat(self, image_path):
        """添加图片预览到聊天区域（不显示URL信息）"""
        try:
            # 创建图片容器
            container = QWidget()
            container.setObjectName("imageContainer")
            container.setStyleSheet("""
                QWidget#imageContainer {
                    background-color: #2A2D37;
                    border-radius: 8px;
                    padding: 8px;
                    margin-bottom: 12px;
                }
            """)
            layout = QVBoxLayout(container)
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(8)
            
            # 加载并缩放图片
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                # 设置最大尺寸
                if pixmap.width() > 600 or pixmap.height() > 400:
                    pixmap = pixmap.scaled(600, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                
                # 创建图片标签
                image_label = QLabel()
                image_label.setPixmap(pixmap)
                image_label.setAlignment(Qt.AlignCenter)
                image_label.setStyleSheet("border: none;")
                layout.addWidget(image_label)
                
                # 图片信息和控制面板
                control_frame = QFrame()
                control_frame.setStyleSheet("background: transparent;")
                control_layout = QHBoxLayout(control_frame)
                
                # 图片元数据
                meta_label = QLabel(f"图片 {pixmap.width()}×{pixmap.height()}")
                meta_label.setStyleSheet("color: #888; font-size: 12px;")
                control_layout.addWidget(meta_label)
                
                # 操作按钮
                action_layout = QHBoxLayout()
                action_layout.setSpacing(8)
                
                # 查看按钮
                view_btn = QPushButton("查看图片")
                view_btn.setFixedSize(90, 30)
                view_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #4CAF50;
                        color: white;
                        border-radius: 4px;
                        font-size: 12px;
                    }
                    QPushButton:hover { background-color: #45a049; }
                """)
                view_btn.clicked.connect(lambda _, p=image_path: self.openImage(p))
                action_layout.addWidget(view_btn)
                
                # 保存按钮
                save_btn = QPushButton("另存为")
                save_btn.setFixedSize(90, 30)
                save_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #2196F3;
                        color: white;
                        border-radius: 4px;
                        font-size: 12px;
                    }
                    QPushButton:hover { background-color: #0b7dda; }
                """)
                save_btn.clicked.connect(lambda _, p=image_path: self.saveImage(p))
                action_layout.addWidget(save_btn)
                
                control_layout.addLayout(action_layout)
                layout.addWidget(control_frame)
                
                # 添加到聊天区域
                widgets.chatContentLayout.insertWidget(
                    widgets.chatContentLayout.count() - 1,
                    container
                )
                
                # 滚动到底部
                QTimer.singleShot(100, self.scrollToBottom)
            else:
                print(f"无法加载图片: {image_path}")
                
        except Exception as e:
            print(f"添加图片到聊天失败: {str(e)}")

    def addFileToChat(self, file_path):
        """添加文件预览到聊天界面"""
        try:
            filename = os.path.basename(file_path)
            
            # 创建文件预览控件
            file_widget = QWidget()
            file_layout = QHBoxLayout(file_widget)
            file_layout.setContentsMargins(10, 5, 10, 5)
            
            # 文件图标
            file_icon = QLabel("📄")
            file_icon.setStyleSheet("font-size: 24px;")
            file_layout.addWidget(file_icon)
            
            # 文件信息
            file_info_widget = QWidget()
            file_info_layout = QVBoxLayout(file_info_widget)
            
            file_name_label = QLabel(filename)
            file_name_label.setStyleSheet("font-weight: bold;")
            file_info_layout.addWidget(file_name_label)
            
            download_btn = QPushButton("下载")
            download_btn.setFixedSize(60, 25)
            download_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3498db;
                    color: white;
                    border-radius: 4px;
                    padding: 2px 5px;
                }
                QPushButton:hover {
                    background-color: #2980b9;
                }
            """)
            download_btn.clicked.connect(lambda: self.openFile(file_path))
            file_info_layout.addWidget(download_btn)
            
            file_layout.addWidget(file_info_widget)
            
            # 添加到聊天区域
            layout = widgets.chatContentLayout
            layout.insertWidget(layout.count() - 1, file_widget)
            
            QTimer.singleShot(100, self.scrollToBottom)
            
        except Exception as e:
            print(f"添加文件到聊天失败: {e}")

    def openFile(self, file_path):
        """打开下载的文件"""
        try:
            if sys.platform == "win32":
                os.startfile(file_path)
            elif sys.platform == "darwin":  # macOS
                subprocess.call(["open", file_path])
            else:  # Linux
                subprocess.call(["xdg-open", file_path])
        except Exception as e:
            QMessageBox.warning(self, "打开失败", f"无法打开文件: {str(e)}")

    def startChatFromHome(self):
        """从主页跳转到对话页面"""
        widgets.stackedWidget.setCurrentWidget(widgets.ai_chat)
        UIFunctions.resetStyle(self, "btn_ai_chat")
        widgets.btn_ai_chat.setStyleSheet(UIFunctions.selectMenu(widgets.btn_ai_chat.styleSheet()))
        widgets.chatInputArea.setFocus()
        print("Started conversation from home page")

    def updateUITexts(self):
        """Update UI texts to English"""
        widgets.chat_title.setText("🤖 TravelMind AI Assistant")
        widgets.clearChatButton.setText("New Chat")
        widgets.sendButton.setText("Send")
        widgets.chatInputArea.setPlaceholderText(
            "Please enter your travel question, e.g.: Recommend a 3-day Shanghai tour...")
        widgets.welcome_message.setText(
            "👋 Welcome to TravelMind AI Assistant!\n\n"
            "I can help you plan travel routes, recommend attractions, check weather information, and more.\n"
            "Please enter your question below to start a conversation.")

        suggestions = ["Shanghai 3-day tour", "Xiamen food guide", "Beijing family trip", "Chengdu weekend tour"]
        for i, btn in enumerate(widgets.suggestion_buttons):
            if i < len(suggestions):
                btn.setText(suggestions[i])

    def startNewChat(self):
        """Start a new chat session"""
        if self.chat_history and self.auto_save_enabled:
            self.current_session_id = self.history_manager.save_or_update_chat(
                self.chat_history, self.current_session_id
            )

        self.chat_history = []
        self.current_session_id = None
        self.clearChatUI()
        self.loadHistoryList()

    def autoSaveCurrentChat(self):
        """Automatically save/update current chat session"""
        if self.chat_history and self.auto_save_enabled:
            self.current_session_id = self.history_manager.save_or_update_chat(
                self.chat_history, self.current_session_id
            )
            QTimer.singleShot(100, self.loadHistoryList)

    def loadHistoryList(self):
        """Load chat history into the list widget"""
        widgets.historyList.clear()
        history = self.history_manager.load_history()

        for chat_data in history:
            item = ChatHistoryItem(chat_data)
            widgets.historyList.addItem(item)

        self.onHistorySelectionChanged()

    def onHistorySelectionChanged(self):
        """Handle history list selection change"""
        selected_items = widgets.historyList.selectedItems()
        has_selection = len(selected_items) > 0

        widgets.loadChatButton.setEnabled(has_selection)
        widgets.deleteChatButton.setEnabled(has_selection)

    def loadSelectedChat(self):
        """加载选中的聊天记录到AI聊天页面"""
        selected_items = widgets.historyList.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        if not isinstance(item, ChatHistoryItem):
            return

        # 自动保存当前聊天（如果有）
        if self.chat_history and self.auto_save_enabled:
            self.autoSaveCurrentChat()

        # 加载选中的聊天记录
        chat_data = item.chat_data
        self.chat_history = chat_data['messages'].copy()
        self.current_session_id = chat_data['id']

        # 清空聊天界面
        self.clearChatUI()
        
        # 显示历史消息
        for message in self.chat_history:
            is_user = message['role'] == 'user'
            content = message['content']
            
            # 显示消息内容
            self.addChatMessage(content, is_user=is_user)
            # 如果有图片信息，显示图片
            if not is_user and "images" in message:
                for image_filename in message["images"]:
                    image_path = os.path.join(self.download_dir, image_filename)
                    if os.path.exists(image_path):
                        self.addImageToChat(image_path)
            # 如果有文件信息，显示文件
            if "file_info" in message:
                files_str = ", ".join(message["file_info"])
                if is_user:
                    file_message = f"📎📎 已上传文件: {files_str}"
                else:
                    file_message = f"📎📎 包含文件: {files_str}"
                
                file_widget = QLabel(file_message)
                file_widget.setStyleSheet("""
                    QLabel {
                        color: #888888;
                        font-style: italic;
                        padding: 5px;
                        background-color: rgba(44, 49, 58, 0.3);
                        border-radius: 5px;
                        margin: 5px 0;
                    }
                """)
                
                layout = widgets.chatContentLayout
                layout.insertWidget(layout.count() - 1, file_widget)
            
            # 如果有AI返回的文件，显示文件
            if "files" in message:
                for file_info in message["files"]:
                    file_name = file_info.get("name", "unknown")
                    file_type = file_info.get("type", "file")
                    
                    # 创建文件占位符
                    file_placeholder = QLabel(f"📄 {file_name} (已下载)")
                    file_placeholder.setStyleSheet("""
                        QLabel {
                            color: #3498db;
                            font-style: italic;
                            padding: 5px;
                            background-color: rgba(44, 49, 58, 0.3);
                            border-radius: 5px;
                            margin: 5px 0;
                        }
                    """)
                    
                    layout = widgets.chatContentLayout
                    layout.insertWidget(layout.count() - 1, file_placeholder)

        # 切换到聊天页面
        widgets.stackedWidget.setCurrentWidget(widgets.ai_chat)
        UIFunctions.resetStyle(self, "btn_ai_chat")
        widgets.btn_ai_chat.setStyleSheet(UIFunctions.selectMenu(widgets.btn_ai_chat.styleSheet()))

    def deleteSelectedChat(self):
        """Delete the selected chat from history"""
        selected_items = widgets.historyList.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        if not isinstance(item, ChatHistoryItem):
            return

        reply = QMessageBox.question(
            self,
            "Delete Chat",
            "Are you sure you want to delete this chat?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            if self.current_session_id == item.chat_data['id']:
                self.current_session_id = None

            self.history_manager.delete_chat(item.chat_data['id'])
            self.loadHistoryList()

    def clearAllHistory(self):
        """Clear all chat history"""
        reply = QMessageBox.question(
            self,
            "Clear All History",
            "Are you sure you want to delete all chat history? This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.history_manager.clear_all_history()
            self.current_session_id = None
            self.loadHistoryList()

    def eventFilter(self, obj, event):
        """Event filter to handle enter key in input box"""
        if obj == widgets.chatInputArea and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Return and not (event.modifiers() & Qt.ShiftModifier):
                self.sendMessage()
                return True
            elif event.key() == Qt.Key_Return and (event.modifiers() & Qt.ShiftModifier):
                return False
        return super().eventFilter(obj, event)

    def addChatMessage(self, message, is_user=True, streaming=False):
        """Add chat message to interface"""
        try:
            if hasattr(widgets, 'welcome_message') and widgets.welcome_message:
                widgets.welcome_message.hide()
                self.welcome_shown = True
        except RuntimeError:
            pass

        if streaming:
            chat_message = StreamingChatMessage(is_user=is_user)
        else:
            chat_message = StreamingChatMessage(is_user=is_user)
            chat_message.setText(message)

        layout = widgets.chatContentLayout
        layout.insertWidget(layout.count() - 1, chat_message)

        QTimer.singleShot(100, self.scrollToBottom)

        return chat_message

    def scrollToBottom(self):
        """Scroll chat area to bottom"""
        scrollbar = widgets.chatDisplayArea.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def showTypingIndicator(self):
        """Show typing indicator"""
        if self.typing_indicator is None:
            self.typing_indicator = TypingIndicator()
            layout = widgets.chatContentLayout
            layout.insertWidget(layout.count() - 1, self.typing_indicator)

        self.typing_indicator.start()
        self.scrollToBottom()

    def hideTypingIndicator(self):
        """Hide typing indicator"""
        if self.typing_indicator:
            self.typing_indicator.stop()
            self.typing_indicator.setParent(None)
            self.typing_indicator = None

    def sendMessage(self):
        """发送消息（支持文本、图片和文件）"""
        message = widgets.chatInputArea.toPlainText().strip()
    
        # 如果没有消息也没有文件，则不发送
        if not message and not self.current_file_paths:
            return
    
        # 获取配置
        config = APIConfig.load_config()
        api_key = config.get("dify_api_key", "")
    
        # 清空输入框和文件预览
        widgets.chatInputArea.clear()
        file_paths = self.current_file_paths.copy()  # 使用副本，避免在后续操作中被修改
        self.current_file_paths = []
        self.clearFilePreviews()
    
        # 禁用发送按钮
        widgets.sendButton.setEnabled(False)
        widgets.sendButton.setText("Sending...")
    
        # 构建用户消息内容（包含所有文件信息）
        file_messages = []
        combined_message = message
    
        # 处理所有文件（图片和非图片）
        for file_path in file_paths:
            # 在聊天界面显示文件
            if self.client.is_image(file_path):
                self.addImageToChat(file_path)
                file_message = f"[图片: {os.path.basename(file_path)}]"
            else:
                self.addFileToChat(file_path)  # 添加文件预览方法
                file_message = f"[文件: {os.path.basename(file_path)}]"
        
            file_messages.append(file_message)
    
        # 如果有文件信息，添加到消息中
        if file_messages:
            files_str = "\n".join(file_messages)
            if message:
                combined_message = f"{message}\n{files_str}"
            else:
                combined_message = files_str
                message = "请分析这些文件" if len(file_messages) > 1 else "请分析这个文件"
    
        # 添加用户消息到聊天历史
        self.chat_history.append({
        "role": "user",
        "content": combined_message,
        # 保存文件路径信息，以便在历史记录中加载
        "file_paths": file_paths if file_paths else None
        })
    
        # 在聊天界面显示用户消息
        self.addChatMessage(combined_message, is_user=True)
    
        # 创建AI消息用于流式显示
        self.current_ai_message = self.addChatMessage("", is_user=False, streaming=True)
        
        # 开始光标闪烁
        self.startCursorBlink()
        
        # 创建并启动AI响应线程
        self.ai_thread = EnhancedAIResponseThread(
            message,  # 原始文本消息
            api_key if api_key else None,
            file_paths=file_paths,
            conversation_id=getattr(self, 'dify_conversation_id', None),
            stream=config.get("stream_enabled", True),
            typing_speed=config.get("typing_speed", 0.03)  # 添加打字速度配置
        )
        
        # 连接信号
        self.ai_thread.response_chunk.connect(self.handleStreamingChunk)
        self.ai_thread.response_complete.connect(self.handleDifyResponseComplete)
        self.ai_thread.error_occurred.connect(self.handleAPIError)
        self.ai_thread.file_received.connect(self.handleFileReceived)
        
        self.ai_thread.start()
    
#    def handleStreamingChunk(self, chunk):
#        """处理流式响应的每个数据块"""
#        if self.current_ai_message:
#            self.current_ai_message.appendText(chunk)
#            self.scrollToBottom()

    def showUploadProgress(self, current, total):
        """显示文件上传进度"""
        if total > 0:
            percent = int(current * 100 / total)
            widgets.sendButton.setText(f"上传中... {percent}%")
    
    def handleFileReceived(self, file_info):
        """处理接收到的文件"""
        try:
            file_name = file_info.get("name", "unknown_file")
            file_url = file_info.get("url", "")
            file_type = file_info.get("type", "file")
            
            if not file_url:
                print("文件URL无效")
                return
                
            # 创建下载目录
            download_dir = os.path.join(os.getcwd(), "downloads")
            if not os.path.exists(download_dir):
                os.makedirs(download_dir)
                
            # 下载文件
            file_path = os.path.join(download_dir, file_name)
            response = requests.get(file_url, stream=True)
            
            if response.status_code == 200:
                with open(file_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                print(f"文件下载成功: {file_path}")
                
                # 在聊天界面显示文件
                if file_type == "image":
                    self.addImageToChat(file_path)
                else:
                    self.addFileToChat(file_path)
                    
                # 添加到聊天历史
                if self.current_ai_message:
                    self.chat_history[-1]["files"] = self.chat_history[-1].get("files", []) + [file_info]
                    
            else:
                print(f"文件下载失败: {response.status_code}")
                
        except Exception as e:
            print(f"处理文件失败: {e}")

    def handleStreamingChunk(self, char):
        """Handle each character from streaming response"""
        if self.current_ai_message:
            self.current_ai_message.appendText(char)
            self.scrollToBottom()

    def remove_image_urls(self, content, image_urls):
        """彻底清除所有图片相关的HTML标签和URL片段"""
        if not content:
            return content
        
        clean_content = content
    
        # 第一步：移除所有HTML图片标签
        clean_content = re.sub(r'<img[^>]*>', '', clean_content)
    
        # 第二步：移除所有图片URL（包括部分和不完整URL）
        for url in image_urls:
            # 移除完整URL
            clean_content = clean_content.replace(url, '')
        
            # 移除URL的部分片段（针对截图中的错误格式）
            base_url = url.split("?")[0].split("%")[0]
            if base_url and base_url in clean_content:
                clean_content = clean_content.replace(base_url, '')
    
        # 第三步：清理特殊错误格式
        patterns_to_remove = [
        r'%!F$MISSING$', 
        r'%!s$MISSING$', 
        r'string=',
        r'&&', 
        r'\?\s*$',
        r'<img[^>]*'
        ]
    
        for pattern in patterns_to_remove:
            clean_content = re.sub(pattern, '', clean_content)
    
        
    
        return clean_content.strip()

    def handleDifyResponseComplete(self, conversation_id, full_text=None):
        """处理Dify响应完成"""
        self.stopCursorBlink()
        
        # 更新会话ID
        self.dify_conversation_id = conversation_id or self.dify_conversation_id
        
        # 保存到聊天历史
        if self.current_ai_message:
            original_content = self.current_ai_message.current_text
            
            try:
                # 提取图片URL
                image_urls = self.client.extract_image_urls(original_content) if self.client else []
                
                # 下载图片
                if image_urls:
                    self.download_images(image_urls)
                
                # 创建不含图片URL的纯净文本
                clean_content = self.remove_image_urls(original_content, image_urls) if original_content else ""
                
                # 如果内容为空但生成了图片，使用默认文本
                if not clean_content.strip() and image_urls:
                    clean_content = "已生成行程图片"
                
                # 更新消息内容
                self.current_ai_message.setText(clean_content)
                
                # 保存到聊天历史
                self.chat_history.append({
                    "role": "assistant",
                    "content": clean_content,
                    "images": self.generated_images.copy()
                })
                
            except Exception as e:
                print(f"处理AI响应时出错: {str(e)}")
                self.current_ai_message.setText("处理响应时出错，请检查API配置")
                self.chat_history.append({
                    "role": "assistant",
                    "content": "处理响应时出错，请检查API配置"
                })
                
            finally:
                # 重置图片列表
                self.generated_images.clear()
        
        # 保存会话
        if self.dify_conversation_id:
            self.history_manager.save_or_update_chat(
                self.chat_history,
                self.dify_conversation_id
            )
        
        # 恢复发送按钮
        widgets.sendButton.setEnabled(True)
        widgets.sendButton.setText("Send")
        self.ai_thread = None
        self.current_ai_message = None

    def process_response_content(self, original_content, image_urls):
        """
        处理响应内容：
        1. 下载图片并显示
        2. 从文本中完全移除图片URL
        """
        # 下载图片
        self.download_images(image_urls)
    
        # 创建一个新的清理后的内容，只保留非图片部分
        clean_content = original_content
    
        # 移除所有图片URL
        for url in image_urls:
            # 移除Markdown格式的图片
            clean_content = re.sub(rf'!$$.*?$$${re.escape(url)}$', '', clean_content)
            # 移除HTML img标签
            clean_content = re.sub(rf'', '', clean_content)
            # 移除裸URL
            clean_content = clean_content.replace(url, '')
    
        # 移除空行和多余空格
        clean_content = re.sub(r'\n\s*\n', '\n\n', clean_content).strip()
    
        # 如果内容完全为空，显示默认消息
        if not clean_content:
            clean_content = "已生成相关图片" if image_urls else "无文本内容"
    
        return clean_content
    
    def remove_url_placeholders(self, message_text, image_urls):
        """从消息文本中移除URL占位文本"""
        # 创建URL正则模式
        url_patterns = [
            r's\s*=\s*[\'\"](https?://[^\s\'\"]+)[\'\"]',      # s="URL" 格式
            r'image_url\s*:\s*[\'\"](https?://[^\s\'\"]+)[\'\"]',  # image_url:"URL" 格式
            r'url\s*:\s*(https?://\S+)',                     # url: URL 格式
            r'一个url\s*：\s*(https?://\S+)',                  # 一个url：中文格式
        ]
        
        clean_text = message_text
        # 移除所有URL模式
        for pattern in url_patterns:
            clean_text = re.sub(pattern, '', clean_text)
        
        # 移除代码段注释（示例代码中提供的代码片段）
        code_blocks = re.findall(r'```python[\s\S]+?```', clean_text, re.DOTALL)
        for code_block in code_blocks:
            if "req.get" in code_block or "open(" in code_block:
                clean_text = clean_text.replace(code_block, '')
        
        # 如果整条消息都是URL，则完全移除
        if clean_text.strip() in image_urls:
            clean_text = "已生成图片" if image_urls else ""
        
        # 更新消息显示
        self.current_ai_message.setText(clean_text.strip())
    
    def download_images(self, image_urls):
        """更可靠的图片下载方法"""
        if not image_urls:
            return
        
        # 确保下载目录存在
        download_dir = os.path.join("downloads", "images")
        os.makedirs(download_dir, exist_ok=True)
    
        for i, url in enumerate(image_urls):
            try:
                # 清理URL中的特殊格式
                url = url.replace('%!F(MISSING)', '/').replace('%!F', '/')
            
                # 获取文件名
                filename = os.path.basename(url.split("?")[0])
                if not filename:
                    filename = f"image_{int(time.time())}_{i}.png"
                
                file_path = os.path.join(download_dir, filename)
            
                # 添加阿里云OSS域名（如果缺少）
                if "oss-cn-shanghai.aliyuncs.com" not in url:
                    path = urlparse(url).path
                    oss_url = f"https://sc-maas.oss-cn-shanghai.aliyuncs.com{path}"
                else:
                    oss_url = url
                
                # 下载图片
                response = requests.get(oss_url, stream=True, timeout=30)
            
                if response.status_code == 200:
                    with open(file_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)

                    print(f"图片保存到: {file_path}")
                    self.addImageToChat(file_path)
                    self.generated_images.append(file_path)
                else:
                    print(f"图片下载失败: {oss_url} - 状态码 {response.status_code}")
                
            except Exception as e:
                print(f"图片处理错误: {str(e)}")


    def handleAPIError(self, error_message):
        """处理API错误"""
        self.stopCursorBlink()

        # 显示详细的错误信息
        error_dialog = QMessageBox(self)
        error_dialog.setIcon(QMessageBox.Critical)
        error_dialog.setWindowTitle("API错误")
        error_dialog.setText("处理API请求时出错")
        error_dialog.setInformativeText(error_message)
        error_dialog.setDetailedText("详细技术信息:\n" + traceback.format_exc())
        error_dialog.exec()
        
        # 恢复UI状态
        if self.current_ai_message:
            self.current_ai_message.setText(f"❌❌ API错误: {error_message}")

        widgets.sendButton.setEnabled(True)
        widgets.sendButton.setText("Send")

        if self.ai_thread:
            self.ai_thread.quit()
            self.ai_thread.wait()
            self.ai_thread = None

        self.current_ai_message = None

    def startCursorBlink(self):
        """Start blinking cursor effect"""
        self.cursor_visible = True
        self.cursor_timer = QTimer()
        self.cursor_timer.timeout.connect(self.toggleCursor)
        self.cursor_timer.start(500)

    def stopCursorBlink(self):
        """Stop blinking cursor effect"""
        if self.cursor_timer:
            self.cursor_timer.stop()
            self.cursor_timer = None
        if self.current_ai_message:
            self.current_ai_message.removeCursor()

    def toggleCursor(self):
        """Toggle cursor visibility"""
        if self.current_ai_message:
            if self.cursor_visible:
                self.current_ai_message.removeCursor()
            else:
                self.current_ai_message.addCursor()
            self.cursor_visible = not self.cursor_visible

    def sendSuggestion(self, suggestion):
        """Send quick suggestion"""
        widgets.chatInputArea.setPlainText(suggestion)
        self.sendMessage()

    def clearChat(self):
        """清除对话"""
        self.dify_conversation_id = None
        self.startNewChat()

    def showFirstTimeSetup(self):
        """首次使用设置提示"""
        reply = QMessageBox.question(
            self,
            "Welcome to TravelMind",
            "您还未配置Dify API密钥。\n\n"
            "配置后即可使用AI助手功能，否则将使用测试模式。\n\n"
            "是否现在配置？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.showAPISettings()

    def openImage(self, image_path):
        """使用系统默认应用打开图片"""
        if not os.path.exists(image_path):
            self.showWarning("图片文件不存在", f"找不到图片文件: {image_path}")
            return
            
        try:
            if sys.platform == "win32":
                os.startfile(image_path)
            elif sys.platform == "darwin":  # macOS
                subprocess.call(["open", image_path])
            else:  # Linux
                subprocess.call(["xdg-open", image_path])
        except Exception as e:
            self.showWarning("打开失败", f"无法打开图片: {str(e)}")
    
    def saveImage(self, image_path):
        """保存图片到指定位置"""
        if not os.path.exists(image_path):
            self.showWarning("文件不存在", "无法找到图片文件")
            return
            
        file_filter = "图片文件 (*.png *.jpg *.jpeg *.gif)"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存图片", "", file_filter
        )
        
        if save_path:
            try:
                shutil.copy2(image_path, save_path)
                self.showInfo("保存成功", "图片已成功保存")
            except Exception as e:
                self.showWarning("保存失败", f"无法保存图片: {str(e)}")

    def showAPISettings(self):
        """显示API设置对话框"""
        dialog = APISettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.dify_conversation_id = None

    def clearChatUI(self):
        """Clear only the chat UI, not the data"""
        if self.ai_thread and self.ai_thread.isRunning():
            self.ai_thread.cancel()
            self.ai_thread.quit()
            self.ai_thread.wait()
            self.ai_thread = None

        self.stopCursorBlink()
        self.current_ai_message = None

        layout = widgets.chatContentLayout
        while layout.count() > 1:
            child = layout.takeAt(0)
            if child.widget() and child.widget() != widgets.welcome_message:
                child.widget().deleteLater()

        try:
            if hasattr(widgets, 'welcome_message') and widgets.welcome_message:
                widgets.welcome_message.show()
                self.welcome_shown = False
        except RuntimeError:
            self.createWelcomeMessage()
            self.welcome_shown = False

        widgets.chatInputArea.clear()
        widgets.sendButton.setEnabled(True)
        widgets.sendButton.setText("Send")

    def createWelcomeMessage(self):
        """Create or recreate welcome message"""
        widgets.welcome_message = QLabel(widgets.chatContentWidget)
        widgets.welcome_message.setObjectName(u"welcome_message")
        widgets.welcome_message.setAlignment(Qt.AlignCenter)
        widgets.welcome_message.setWordWrap(True)
        widgets.welcome_message.setStyleSheet(u"""
            QLabel {
                color: rgb(113, 126, 149);
                font-size: 14px;
                padding: 20px;
                background-color: rgba(44, 49, 58, 0.3);
                border-radius: 10px;
                border: 1px dashed rgb(89, 92, 111);
            }
        """)
        widgets.welcome_message.setText(
            "👋 Welcome to TravelMind AI Assistant!\n\n"
            "I can help you plan travel routes, recommend attractions, check weather information, and more.\n"
            "Please enter your question below to start a conversation.")

        layout = widgets.chatContentLayout
        layout.insertWidget(0, widgets.welcome_message)

    def buttonClick(self):
        """Handle button clicks"""
        btn = self.sender()
        btnName = btn.objectName()

        if btnName == "btn_home":
            widgets.stackedWidget.setCurrentWidget(widgets.home)
            UIFunctions.resetStyle(self, btnName)
            btn.setStyleSheet(UIFunctions.selectMenu(btn.styleSheet()))

        if btnName == "btn_ai_chat":
            widgets.stackedWidget.setCurrentWidget(widgets.ai_chat)
            UIFunctions.resetStyle(self, btnName)
            btn.setStyleSheet(UIFunctions.selectMenu(btn.styleSheet()))

        if btnName == "btn_history":
            widgets.stackedWidget.setCurrentWidget(widgets.history)
            UIFunctions.resetStyle(self, btnName)
            btn.setStyleSheet(UIFunctions.selectMenu(btn.styleSheet()))
            self.loadHistoryList()

        if btnName == "btn_theme":
            if self.useCustomTheme:
                themeFile = os.path.abspath(os.path.join(self.absPath, "themes\\py_dracula_light.qss"))
                UIFunctions.theme(self, themeFile, True)
                AppFunctions.setThemeHack(self)
                self.useCustomTheme = False
            else:
                themeFile = os.path.abspath(os.path.join(self.absPath, "themes\\py_dracula_dark.qss"))
                UIFunctions.theme(self, themeFile, True)
                AppFunctions.setThemeHack(self)
                self.useCustomTheme = True

        if btnName == "btn_exit":
            if self.chat_history and self.auto_save_enabled:
                self.autoSaveCurrentChat()
            print("Exit BTN clicked!")
            QApplication.quit()
            return

        print(f'Button "{btnName}" pressed!')

    def resizeEvent(self, event):
        """Handle resize events"""
        UIFunctions.resize_grips(self)

    def mousePressEvent(self, event):
        """Handle mouse press events"""
        self.dragPos = event.globalPosition().toPoint()

        if event.buttons() == Qt.LeftButton:
            print('Mouse click: LEFT CLICK')
        if event.buttons() == Qt.RightButton:
            print('Mouse click: RIGHT CLICK')

    def closeEvent(self, event):
        """Handle application close event"""
        if self.chat_history and self.auto_save_enabled:
            self.autoSaveCurrentChat()
        event.accept()


class APISettingsDialog(QDialog):
    """API设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API Settings")
        self.setFixedSize(450, 350)
        self.setupUI()
        self.loadSettings()

    def setupUI(self):
        layout = QVBoxLayout(self)

        dify_group = QGroupBox("Dify API Configuration")
        dify_layout = QVBoxLayout(dify_group)

        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel("API Key:"))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("Enter your Dify API key")
        key_layout.addWidget(self.api_key_edit)
        dify_layout.addLayout(key_layout)

        show_key_btn = QPushButton("Show/Hide")
        show_key_btn.clicked.connect(self.togglePasswordVisibility)
        key_layout.addWidget(show_key_btn)

        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("Base URL:"))
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.dify.ai/v1")
        url_layout.addWidget(self.base_url_edit)
        dify_layout.addLayout(url_layout)

        layout.addWidget(dify_group)

        response_group = QGroupBox("Response Settings")
        response_layout = QVBoxLayout(response_group)

        self.stream_checkbox = QCheckBox("Enable streaming output (typewriter effect)")
        response_layout.addWidget(self.stream_checkbox)

        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("Typing speed:"))
        self.speed_spinbox = QSpinBox()
        self.speed_spinbox.setRange(10, 200)
        self.speed_spinbox.setSuffix(" ms/char")
        speed_layout.addWidget(self.speed_spinbox)
        response_layout.addLayout(speed_layout)

        layout.addWidget(response_group)

        button_layout = QHBoxLayout()
        self.test_button = QPushButton("Test Connection")
        self.save_button = QPushButton("Save")
        self.cancel_button = QPushButton("Cancel")

        button_layout.addWidget(self.test_button)
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        self.test_button.clicked.connect(self.testConnection)
        self.save_button.clicked.connect(self.saveSettings)
        self.cancel_button.clicked.connect(self.reject)

    def togglePasswordVisibility(self):
        """切换密码可见性"""
        if self.api_key_edit.echoMode() == QLineEdit.Password:
            self.api_key_edit.setEchoMode(QLineEdit.Normal)
        else:
            self.api_key_edit.setEchoMode(QLineEdit.Password)

    def loadSettings(self):
        """加载设置"""
        config = APIConfig.load_config()
        self.api_key_edit.setText(config.get("dify_api_key", ""))
        self.base_url_edit.setText(config.get("dify_base_url", "https://api.dify.ai/v1"))
        self.stream_checkbox.setChecked(config.get("stream_enabled", True))
        self.speed_spinbox.setValue(int(config.get("typing_speed", 0.03) * 1000))

    def testConnection(self):
        """测试API连接"""
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip() or "https://api.dify.ai/v1"

        if not api_key:
            QMessageBox.warning(self, "Error", "Please enter API key")
            return

        self.test_button.setEnabled(False)
        self.test_button.setText("Testing...")

        try:
            client = DifyAPIClient(api_key, base_url)
            # 使用非流式请求进行测试
            test_data = {
                "inputs": {},
                "query": "Hello",
                "response_mode": "blocking",
                "user": "test_user"
            }
            
            response = requests.post(
                f"{base_url}/chat-messages",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=test_data
            )
            
            if response.status_code == 200:
                QMessageBox.information(self, "Success", "API connection test successful!")
            else:
                error_msg = f"API返回错误 ({response.status_code}): "
                try:
                    error_data = response.json()
                    error_msg += error_data.get("message", "未知错误")
                    if "detail" in error_data:
                        error_msg += f" - {error_data['detail']}"
                except:
                    error_msg += response.text[:200] + "..."
                QMessageBox.critical(self, "Error", error_msg)
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"API连接测试失败:\n{str(e)}")
        finally:
            self.test_button.setEnabled(True)
            self.test_button.setText("Test Connection")

    def saveSettings(self):
        """保存设置"""
        config = {
            "dify_api_key": self.api_key_edit.text().strip(),
            "dify_base_url": self.base_url_edit.text().strip() or "https://api.dify.ai/v1",
            "stream_enabled": self.stream_checkbox.isChecked(),
            "typing_speed": self.speed_spinbox.value() / 1000.0
        }

        APIConfig.save_config(config)
        QMessageBox.information(self, "Success", "Settings saved successfully!")
        self.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("icon.ico"))
    window = MainWindow()
    sys.exit(app.exec())
