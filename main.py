import sys
import os
import platform
import time
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

    def appendText(self, char):
        """Append a character to the message (for streaming)"""
        self.current_text += char
        self.message_label.setText(self.current_text)

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

    def __init__(self, api_key, base_url="https://api.dify.ai/v1"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def upload_file(self, file_path):
        """上传文件到Dify"""
        try:
            with open(file_path, 'rb') as f:
                files = {
                    'file': (os.path.basename(file_path), f, 'image/jpeg')
                }
                headers = {
                    "Authorization": f"Bearer {self.api_key}"
                }

                response = requests.post(
                    f"{self.base_url}/files/upload",
                    headers=headers,
                    files=files
                )

                if response.status_code == 200:
                    file_data = response.json()
                    return file_data.get('id')
                else:
                    print(f"文件上传失败: {response.text}")
                    return None

        except Exception as e:
            print(f"文件上传错误: {e}")
            return None

    def chat_with_image(self, message, image_path=None, conversation_id=None, user_id="default"):
        """发送带图片的消息给Dify"""
        url = f"{self.base_url}/chat-messages"

        data = {
            "inputs": {},
            "query": message,
            "response_mode": "streaming",
            "user": user_id
        }

        if image_path and os.path.exists(image_path):
            file_id = self.upload_file(image_path)
            if file_id:
                data["files"] = [{"type": "image", "transfer_method": "remote_url", "url": file_id}]
            else:
                print("图片上传失败，仅发送文字消息")

        if conversation_id:
            data["conversation_id"] = conversation_id

        try:
            response = requests.post(
                url,
                headers=self.headers,
                json=data,
                stream=True,
                timeout=30
            )
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            raise Exception(f"API请求失败: {str(e)}")

    def chat_completion_stream(self, message, conversation_id=None, user_id="default"):
        """流式对话完成（保持向后兼容）"""
        return self.chat_with_image(message, None, conversation_id, user_id)


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
                "typing_speed": 0.03
            }

    @staticmethod
    def save_config(config):
        """保存配置"""
        with open(APIConfig.CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)


class EnhancedAIResponseThread(QThread):
    """支持图片的AI响应线程"""
    response_chunk = Signal(str)
    response_complete = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, message, api_key=None, image_path=None, conversation_id=None, stream=True):
        super().__init__()
        self.message = message
        self.api_key = api_key
        self.image_path = image_path
        self.conversation_id = conversation_id
        self.stream = stream
        self.is_cancelled = False

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
        try:
            response = self.client.chat_with_image(
                self.message,
                self.image_path,
                self.conversation_id
            )

            client = SSEClient(response)
            complete_response = ""
            new_conversation_id = self.conversation_id

            for event in client.events():
                if self.is_cancelled:
                    break

                if event.data and event.data != '[DONE]':
                    try:
                        data = json.loads(event.data)

                        if data.get("event") == "message":
                            if not new_conversation_id and data.get("conversation_id"):
                                new_conversation_id = data["conversation_id"]

                            content = data.get("answer", "")
                            if content:
                                complete_response = content
                                for char in content:
                                    if self.is_cancelled:
                                        break
                                    self.response_chunk.emit(char)
                                    time.sleep(0.03)

                        elif data.get("event") == "message_end":
                            break

                    except json.JSONDecodeError:
                        continue

            if not self.is_cancelled:
                self.response_complete.emit(new_conversation_id or "")

        except Exception as e:
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
        """Save new chat or update existing chat session"""
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
                    history[i]['messages'] = chat_history.copy()
                    history[i]['last_updated'] = datetime.now().isoformat()

                    with open(self.history_file, 'w', encoding='utf-8') as f:
                        json.dump(history, f, ensure_ascii=False, indent=2)
                    return session_id

        new_session_id = str(int(time.time() * 1000))
        chat_record = {
            'id': new_session_id,
            'timestamp': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'title': title,
            'messages': chat_history.copy()
        }

        history.insert(0, chat_record)
        history = history[:50]

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

        # USE CUSTOM TITLE BAR | USE AS "False" FOR MAC OR LINUX
        # ///////////////////////////////////////////////////////////////
        Settings.ENABLE_CUSTOM_TITLE_BAR = True

        # APP NAME
        # ///////////////////////////////////////////////////////////////
        title = "TravelMind"
        description = "TravelMind - AI Travel Assistant"
        self.setWindowTitle(title)
        widgets.titleRightInfo.setText(description)

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
        """选择图片"""
        file_dialog = QFileDialog()
        image_path, _ = file_dialog.getOpenFileName(
            self,
            "选择图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp);;所有文件 (*)"
        )

        if image_path:
            try:
                processed_path = process_uploaded_image(image_path)
                self.current_image_path = processed_path
                self.showImagePreview(processed_path)
                print(f"✅ 图片已选择: {os.path.basename(processed_path)}")

            except Exception as e:
                print(f"❌ 图片处理失败: {e}")
                self.current_image_path = None

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
        """添加图片到聊天界面"""
        try:
            image_widget = QLabel()
            image_widget.setMaximumSize(QSize(300, 200))
            image_widget.setStyleSheet("""
                QLabel {
                    border: 1px solid rgb(89, 92, 111);
                    border-radius: 8px;
                    padding: 5px;
                    background-color: rgb(44, 49, 58);
                }
            """)

            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    280, 180,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                image_widget.setPixmap(scaled_pixmap)
            else:
                image_widget.setText("🖼️ 图片显示失败")

            layout = widgets.chatContentLayout
            layout.insertWidget(layout.count() - 1, image_widget)

            QTimer.singleShot(100, self.scrollToBottom)

        except Exception as e:
            print(f"添加图片到聊天失败: {e}")

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
        """Load the selected chat into the AI chat page"""
        selected_items = widgets.historyList.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        if not isinstance(item, ChatHistoryItem):
            return

        if self.chat_history and self.auto_save_enabled:
            self.autoSaveCurrentChat()

        chat_data = item.chat_data
        self.chat_history = chat_data['messages'].copy()
        self.current_session_id = chat_data['id']

        self.clearChatUI()
        for message in self.chat_history:
            is_user = message['role'] == 'user'
            self.addChatMessage(message['content'], is_user=is_user)

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
        """发送消息（支持语音识别的文字和图片）"""
        message = widgets.chatInputArea.toPlainText().strip()

        if not message and not self.current_image_path:
            return

        config = APIConfig.load_config()
        api_key = config.get("dify_api_key", "")

        # 清空输入框和图片预览
        widgets.chatInputArea.clear()
        image_path = self.current_image_path
        self.clearImagePreview()

        # 禁用发送按钮
        widgets.sendButton.setEnabled(False)
        widgets.sendButton.setText("Sending...")

        # 添加用户消息
        if message:
            self.addChatMessage(message, is_user=True)
            self.chat_history.append({"role": "user", "content": message})

        # 如果有图片，也显示在聊天中
        if image_path:
            self.addImageToChat(image_path)
            img_message = f"[图片: {os.path.basename(image_path)}]"
            if message:
                combined_message = f"{message}\n{img_message}"
            else:
                combined_message = img_message
                message = "请分析这张图片"

            self.chat_history.append({"role": "user", "content": combined_message})

        # 创建AI消息用于流式显示
        self.current_ai_message = self.addChatMessage("", is_user=False, streaming=True)

        # 开始光标闪烁
        self.startCursorBlink()

        # 创建并启动AI响应线程
        self.ai_thread = EnhancedAIResponseThread(
            message,
            api_key if api_key else None,
            image_path,
            getattr(self, 'dify_conversation_id', None),
            stream=config.get("stream_enabled", True)
        )

        # 连接信号
        self.ai_thread.response_chunk.connect(self.handleStreamingChunk)
        self.ai_thread.response_complete.connect(self.handleDifyResponseComplete)
        self.ai_thread.error_occurred.connect(self.handleAPIError)

        self.ai_thread.start()

    def handleStreamingChunk(self, char):
        """Handle each character from streaming response"""
        if self.current_ai_message:
            self.current_ai_message.appendText(char)
            self.scrollToBottom()

    def handleDifyResponseComplete(self, conversation_id):
        """处理Dify响应完成"""
        self.stopCursorBlink()

        if conversation_id:
            self.dify_conversation_id = conversation_id

        if self.current_ai_message:
            self.chat_history.append({
                "role": "assistant",
                "content": self.current_ai_message.current_text
            })

        self.autoSaveCurrentChat()

        widgets.sendButton.setEnabled(True)
        widgets.sendButton.setText("Send")

        if self.ai_thread:
            self.ai_thread.quit()
            self.ai_thread.wait()
            self.ai_thread = None

        self.current_ai_message = None

    def handleAPIError(self, error_message):
        """处理API错误"""
        self.stopCursorBlink()

        if self.current_ai_message:
            self.current_ai_message.setText(f"❌ 错误: {error_message}")

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
            response = client.chat_completion_stream("Hello", user_id="test")
            QMessageBox.information(self, "Success", "API connection test successful!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"API connection test failed:\n{str(e)}")
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
