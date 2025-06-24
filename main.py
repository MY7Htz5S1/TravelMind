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
    """Dify API客户端"""

    def __init__(self, api_key, base_url="https://api.dify.ai/v1"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def chat_completion_stream(self, message, conversation_id=None, user_id="default"):
        """流式对话完成"""
        url = f"{self.base_url}/chat-messages"

        data = {
            "inputs": {},
            "query": message,
            "response_mode": "streaming",
            "user": user_id
        }

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


class AIResponseThread(QThread):
    """使用Dify API的AI响应线程（支持流式输出）"""
    response_chunk = Signal(str)  # 发送每个字符
    response_complete = Signal(str)  # 完成时发送conversation_id
    error_occurred = Signal(str)  # 错误信号

    def __init__(self, message, api_key=None, conversation_id=None, stream=True):
        super().__init__()
        self.message = message
        self.api_key = api_key
        self.conversation_id = conversation_id
        self.stream = stream
        self.is_cancelled = False

        # 如果没有API密钥，使用测试模式
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
        """测试模式响应"""
        time.sleep(0.5)
        response = "这是一个测试回复。请在设置中配置Dify API密钥以获得真正的AI回复。"

        for char in response:
            if self.is_cancelled:
                break
            self.response_chunk.emit(char)
            time.sleep(0.05)

        if not self.is_cancelled:
            self.response_complete.emit("")

    def _handle_streaming_response(self):
        """处理流式响应"""
        try:
            response = self.client.chat_completion_stream(
                self.message,
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
        """处理阻塞式响应（回退方案）"""
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
        if not chat_history:  # Don't save empty chats
            return None

        try:
            # Load existing history
            with open(self.history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except:
            history = []

        # If session_id provided, try to update existing session
        if session_id:
            for i, chat_record in enumerate(history):
                if chat_record.get('id') == session_id:
                    # Update existing session
                    history[i]['messages'] = chat_history.copy()
                    history[i]['last_updated'] = datetime.now().isoformat()

                    # Save back to file
                    with open(self.history_file, 'w', encoding='utf-8') as f:
                        json.dump(history, f, ensure_ascii=False, indent=2)
                    return session_id

        # Create new session
        new_session_id = str(int(time.time() * 1000))
        chat_record = {
            'id': new_session_id,
            'timestamp': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'title': title,
            'messages': chat_history.copy()
        }

        # Add to beginning of history (most recent first)
        history.insert(0, chat_record)

        # Keep only last 50 chats
        history = history[:50]

        # Save back to file
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

        # Remove chat with matching ID
        history = [chat for chat in history if chat.get('id') != chat_id]

        # Save back to file
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    def clear_all_history(self):
        """Clear all chat history"""
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump([], f)


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
        self.current_ai_message = None  # Track current streaming message
        self.cursor_timer = None  # Timer for blinking cursor

        # Session management for auto-save
        self.current_session_id = None  # Track current chat session
        self.auto_save_enabled = True  # Enable auto-save by default

        # History manager
        self.history_manager = ChatHistoryManager()

        # USE CUSTOM TITLE BAR | USE AS "False" FOR MAC OR LINUX
        # ///////////////////////////////////////////////////////////////
        Settings.ENABLE_CUSTOM_TITLE_BAR = True

        # APP NAME
        # ///////////////////////////////////////////////////////////////
        title = "TravelMind"
        description = "TravelMind - AI Travel Assistant"
        # APPLY TEXTS
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

        # LEFT MENUS
        widgets.btn_home.clicked.connect(self.buttonClick)
        widgets.btn_ai_chat.clicked.connect(self.buttonClick)
        widgets.btn_history.clicked.connect(self.buttonClick)
        # widgets.btn_widgets.clicked.connect(self.buttonClick)
        # widgets.btn_new.clicked.connect(self.buttonClick)
        # widgets.btn_save.clicked.connect(self.buttonClick)
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

        # EXTRA LEFT BOX
        # def openCloseLeftBox():
        #     UIFunctions.toggleLeftBox(self, True)

        # widgets.toggleLeftBox.clicked.connect(openCloseLeftBox)
        # widgets.extraCloseColumnBtn.clicked.connect(openCloseLeftBox)

        # EXTRA RIGHT BOX
        # def openCloseRightBox():
        #     UIFunctions.toggleRightBox(self, True)

        # widgets.settingsTopBtn.clicked.connect(openCloseRightBox)

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
            # LOAD AND APPLY STYLE
            UIFunctions.theme(self, themeFile, True)

            # SET HACKS
            AppFunctions.setThemeHack(self)

        # SET HOME PAGE AND SELECT MENU
        # ///////////////////////////////////////////////////////////////
        widgets.stackedWidget.setCurrentWidget(widgets.home)
        widgets.btn_home.setStyleSheet(UIFunctions.selectMenu(widgets.btn_home.styleSheet()))

        widgets.textEdit.setPlainText("")

        def init_dify_integration(self):
            """初始化Dify集成"""
            # Dify相关属性
            self.dify_conversation_id = None

            # 加载API配置
            config = APIConfig.load_config()
            if not config.get("dify_api_key"):
                # 延迟显示设置提示
                QTimer.singleShot(2000, self.showFirstTimeSetup)

    def startChatFromHome(self):
        """从主页跳转到对话页面"""
        # 切换到AI聊天页面
        widgets.stackedWidget.setCurrentWidget(widgets.ai_chat)

        # 重置所有按钮样式并选中AI聊天按钮
        UIFunctions.resetStyle(self, "btn_ai_chat")
        widgets.btn_ai_chat.setStyleSheet(UIFunctions.selectMenu(widgets.btn_ai_chat.styleSheet()))

        # 聚焦到输入框
        widgets.chatInputArea.setFocus()

        print("Started conversation from home page")

    def updateUITexts(self):
        """Update UI texts to English"""
        # Chat title
        widgets.chat_title.setText("🤖 TravelMind AI Assistant")

        # Clear chat button
        widgets.clearChatButton.setText("New Chat")  # 改为更合适的文字

        # Send button
        widgets.sendButton.setText("Send")

        # Input placeholder
        widgets.chatInputArea.setPlaceholderText(
            "Please enter your travel question, e.g.: Recommend a 3-day Shanghai tour...")

        # Welcome message
        widgets.welcome_message.setText(
            "👋 Welcome to TravelMind AI Assistant!\n\n"
            "I can help you plan travel routes, recommend attractions, check weather information, and more.\n"
            "Please enter your question below to start a conversation.")

        # Update suggestion buttons
        suggestions = ["Shanghai 3-day tour", "Xiamen food guide", "Beijing family trip", "Chengdu weekend tour"]
        for i, btn in enumerate(widgets.suggestion_buttons):
            if i < len(suggestions):
                btn.setText(suggestions[i])

    def startNewChat(self):
        """Start a new chat session"""
        # Save current chat if it has content
        if self.chat_history and self.auto_save_enabled:
            self.current_session_id = self.history_manager.save_or_update_chat(
                self.chat_history, self.current_session_id
            )

        # Reset for new chat
        self.chat_history = []
        self.current_session_id = None

        # Clear UI
        self.clearChatUI()

        # Refresh history list
        self.loadHistoryList()

    def autoSaveCurrentChat(self):
        """Automatically save/update current chat session"""
        if self.chat_history and self.auto_save_enabled:
            self.current_session_id = self.history_manager.save_or_update_chat(
                self.chat_history, self.current_session_id
            )

            # Refresh history list in background (don't disturb current conversation)
            QTimer.singleShot(100, self.loadHistoryList)

    def loadHistoryList(self):
        """Load chat history into the list widget"""
        widgets.historyList.clear()
        history = self.history_manager.load_history()

        for chat_data in history:
            item = ChatHistoryItem(chat_data)
            widgets.historyList.addItem(item)

        # Update button states
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

        # Save current chat first if needed
        if self.chat_history and self.auto_save_enabled:
            self.autoSaveCurrentChat()

        # Load chat messages
        chat_data = item.chat_data
        self.chat_history = chat_data['messages'].copy()
        self.current_session_id = chat_data['id']  # Set session ID to existing chat

        # Clear and display messages in chat area
        self.clearChatUI()
        for message in self.chat_history:
            is_user = message['role'] == 'user'
            self.addChatMessage(message['content'], is_user=is_user)

        # Switch to AI chat page
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

        # Confirm deletion
        reply = QMessageBox.question(
            self,
            "Delete Chat",
            "Are you sure you want to delete this chat?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # If deleting current session, reset session ID
            if self.current_session_id == item.chat_data['id']:
                self.current_session_id = None

            # Delete from history file
            self.history_manager.delete_chat(item.chat_data['id'])

            # Reload history list
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
            self.current_session_id = None  # Reset current session
            self.loadHistoryList()

    def eventFilter(self, obj, event):
        """Event filter to handle enter key in input box"""
        if obj == widgets.chatInputArea and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Return and not (event.modifiers() & Qt.ShiftModifier):
                # Enter to send, Shift+Enter for new line
                self.sendMessage()
                return True
            elif event.key() == Qt.Key_Return and (event.modifiers() & Qt.ShiftModifier):
                # Shift+Enter for new line
                return False
        return super().eventFilter(obj, event)

    def addChatMessage(self, message, is_user=True, streaming=False):
        """Add chat message to interface"""
        # Remove welcome message if it exists
        try:
            if hasattr(widgets, 'welcome_message') and widgets.welcome_message:
                widgets.welcome_message.hide()
                self.welcome_shown = True
        except RuntimeError:
            # Widget already deleted, ignore
            pass

        # Create message component
        if streaming:
            # Create empty message for streaming
            chat_message = StreamingChatMessage(is_user=is_user)
        else:
            # Create complete message
            chat_message = StreamingChatMessage(is_user=is_user)
            chat_message.setText(message)

        # Insert into layout (before spacer)
        layout = widgets.chatContentLayout
        layout.insertWidget(layout.count() - 1, chat_message)

        # Scroll to bottom
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
        """发送消息"""
        message = widgets.chatInputArea.toPlainText().strip()
        if not message:
            return

        # 加载API配置
        config = APIConfig.load_config()
        api_key = config.get("dify_api_key", "")

        # 清空输入框
        widgets.chatInputArea.clear()

        # 禁用发送按钮
        widgets.sendButton.setEnabled(False)
        widgets.sendButton.setText("Sending...")

        # 添加用户消息
        self.addChatMessage(message, is_user=True)
        self.chat_history.append({"role": "user", "content": message})

        # 创建AI消息用于流式显示
        self.current_ai_message = self.addChatMessage("", is_user=False, streaming=True)

        # 开始光标闪烁
        self.startCursorBlink()

        # 创建并启动AI响应线程
        self.ai_thread = AIResponseThread(
            message,
            api_key if api_key else None,
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
            # Scroll to bottom with each new character
            self.scrollToBottom()

    def handleDifyResponseComplete(self, conversation_id):
        """处理Dify响应完成"""
        # 停止光标闪烁
        self.stopCursorBlink()

        # 保存conversation_id用于上下文连续对话
        if conversation_id:
            self.dify_conversation_id = conversation_id

        # 添加完整消息到历史
        if self.current_ai_message:
            self.chat_history.append({
                "role": "assistant",
                "content": self.current_ai_message.current_text
            })

        # 自动保存对话
        self.autoSaveCurrentChat()

        # 恢复发送按钮
        widgets.sendButton.setEnabled(True)
        widgets.sendButton.setText("Send")

        # 清理线程
        if self.ai_thread:
            self.ai_thread.quit()
            self.ai_thread.wait()
            self.ai_thread = None

        # 清除当前消息引用
        self.current_ai_message = None

    def handleAPIError(self, error_message):
        """处理API错误"""
        # 停止光标闪烁
        self.stopCursorBlink()

        # 显示错误消息
        if self.current_ai_message:
            self.current_ai_message.setText(f"❌ 错误: {error_message}")

        # 恢复发送按钮
        widgets.sendButton.setEnabled(True)
        widgets.sendButton.setText("Send")

        # 清理线程
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
        self.cursor_timer.start(500)  # Blink every 500ms

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
        # 重置Dify会话ID
        self.dify_conversation_id = None
        # 调用原来的清除方法
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
            # 配置已更新，重置会话
            self.dify_conversation_id = None

    def clearChatUI(self):
        """Clear only the chat UI, not the data"""
        # Stop any ongoing streaming
        if self.ai_thread and self.ai_thread.isRunning():
            self.ai_thread.cancel()
            self.ai_thread.quit()
            self.ai_thread.wait()
            self.ai_thread = None

        # Stop cursor timer
        self.stopCursorBlink()

        # Clear current message reference
        self.current_ai_message = None

        # Clear messages from UI (except welcome message and spacer)
        layout = widgets.chatContentLayout
        # Remove all widgets except the last one (spacer)
        while layout.count() > 1:
            child = layout.takeAt(0)
            if child.widget() and child.widget() != widgets.welcome_message:
                child.widget().deleteLater()

        # Show welcome message if it still exists
        try:
            if hasattr(widgets, 'welcome_message') and widgets.welcome_message:
                widgets.welcome_message.show()
                self.welcome_shown = False
        except RuntimeError:
            # If welcome message was deleted, create a new one
            self.createWelcomeMessage()
            self.welcome_shown = False

        # Clear input box
        widgets.chatInputArea.clear()

        # Enable send button
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

        # Insert at the beginning of the layout
        layout = widgets.chatContentLayout
        layout.insertWidget(0, widgets.welcome_message)

    # BUTTONS CLICK
    # Post here your functions for clicked buttons
    # ///////////////////////////////////////////////////////////////
    def buttonClick(self):
        # GET BUTTON CLICKED
        btn = self.sender()
        btnName = btn.objectName()

        # SHOW HOME PAGE
        if btnName == "btn_home":
            widgets.stackedWidget.setCurrentWidget(widgets.home)
            UIFunctions.resetStyle(self, btnName)
            btn.setStyleSheet(UIFunctions.selectMenu(btn.styleSheet()))

        # SHOW AI CHAT PAGE
        if btnName == "btn_ai_chat":
            widgets.stackedWidget.setCurrentWidget(widgets.ai_chat)
            UIFunctions.resetStyle(self, btnName)
            btn.setStyleSheet(UIFunctions.selectMenu(btn.styleSheet()))

        # SHOW HISTORY PAGE
        if btnName == "btn_history":
            widgets.stackedWidget.setCurrentWidget(widgets.history)
            UIFunctions.resetStyle(self, btnName)
            btn.setStyleSheet(UIFunctions.selectMenu(btn.styleSheet()))
            # Refresh history list when showing the page
            self.loadHistoryList()

        # SHOW WIDGETS PAGE
        # if btnName == "btn_widgets":
        #     widgets.stackedWidget.setCurrentWidget(widgets.widgets)
        #     UIFunctions.resetStyle(self, btnName)
        #     btn.setStyleSheet(UIFunctions.selectMenu(btn.styleSheet()))

        # SHOW NEW PAGE
        # if btnName == "btn_new":
        #     widgets.stackedWidget.setCurrentWidget(widgets.new_page)  # SET PAGE
        #     UIFunctions.resetStyle(self, btnName)  # RESET ANOTHERS BUTTONS SELECTED
        #     btn.setStyleSheet(UIFunctions.selectMenu(btn.styleSheet()))  # SELECT MENU

        # if btnName == "btn_save":
        #     # 手动保存当前对话
        #     if self.chat_history:
        #         self.autoSaveCurrentChat()
        #         QMessageBox.information(self, "保存成功", "当前对话已保存到历史记录")
        #     else:
        #         QMessageBox.information(self, "提示", "当前没有对话内容可以保存")

        if btnName == "btn_theme":
            if self.useCustomTheme:
                themeFile = os.path.abspath(os.path.join(self.absPath, "themes\\py_dracula_light.qss"))
                UIFunctions.theme(self, themeFile, True)
                # SET HACKS
                AppFunctions.setThemeHack(self)
                self.useCustomTheme = False
            else:
                themeFile = os.path.abspath(os.path.join(self.absPath, "themes\\py_dracula_dark.qss"))
                UIFunctions.theme(self, themeFile, True)
                # SET HACKS
                AppFunctions.setThemeHack(self)
                self.useCustomTheme = True

        if btnName == "btn_exit":
            # 退出前保存当前对话
            if self.chat_history and self.auto_save_enabled:
                self.autoSaveCurrentChat()
            print("Exit BTN clicked!")
            QApplication.quit()
            return

        # PRINT BTN NAME
        print(f'Button "{btnName}" pressed!')

    # RESIZE EVENTS
    # ///////////////////////////////////////////////////////////////
    def resizeEvent(self, event):
        # Update Size Grips
        UIFunctions.resize_grips(self)

    # MOUSE CLICK EVENTS
    # ///////////////////////////////////////////////////////////////
    def mousePressEvent(self, event):
        # SET DRAG POS WINDOW
        self.dragPos = event.globalPosition().toPoint()

        # PRINT MOUSE EVENTS
        if event.buttons() == Qt.LeftButton:
            print('Mouse click: LEFT CLICK')
        if event.buttons() == Qt.RightButton:
            print('Mouse click: RIGHT CLICK')

    def closeEvent(self, event):
        """Handle application close event"""
        # Save current chat before closing
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

        # Dify API设置组
        dify_group = QGroupBox("Dify API Configuration")
        dify_layout = QVBoxLayout(dify_group)

        # API密钥
        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel("API Key:"))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("Enter your Dify API key")
        key_layout.addWidget(self.api_key_edit)
        dify_layout.addLayout(key_layout)

        # 显示/隐藏密钥按钮
        show_key_btn = QPushButton("Show/Hide")
        show_key_btn.clicked.connect(self.togglePasswordVisibility)
        key_layout.addWidget(show_key_btn)

        # 基础URL
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("Base URL:"))
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.dify.ai/v1")
        url_layout.addWidget(self.base_url_edit)
        dify_layout.addLayout(url_layout)

        layout.addWidget(dify_group)

        # 响应设置组
        response_group = QGroupBox("Response Settings")
        response_layout = QVBoxLayout(response_group)

        # 流式输出
        self.stream_checkbox = QCheckBox("Enable streaming output (typewriter effect)")
        response_layout.addWidget(self.stream_checkbox)

        # 打字速度
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("Typing speed:"))
        self.speed_spinbox = QSpinBox()
        self.speed_spinbox.setRange(10, 200)
        self.speed_spinbox.setSuffix(" ms/char")
        speed_layout.addWidget(self.speed_spinbox)
        response_layout.addLayout(speed_layout)

        layout.addWidget(response_group)

        # 按钮
        button_layout = QHBoxLayout()
        self.test_button = QPushButton("Test Connection")
        self.save_button = QPushButton("Save")
        self.cancel_button = QPushButton("Cancel")

        button_layout.addWidget(self.test_button)
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        # 连接信号
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
            # 发送测试消息
            response = client.chat_completion_stream("Hello", user_id="test")
            # 如果没有异常，说明连接成功
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
