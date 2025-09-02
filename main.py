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
import subprocess

# Imports for voice and image processing
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

os.environ["QT_FONT_DPI"] = "96"  # Fix problem for High DPI and scale above 100%

# Set as global widgets
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
        font-size: 24px;                                                    /* Font size */
        font-family: "Microsoft YaHei UI", "PingFang SC", system-ui;       /* Font type */
        font-weight: normal;                                                /* Font weight */
        line-height: 1.5;                                                  /* Line height */
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
                    font-size: 24px;
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
                    font-size: 24px;                    /* Font size: 14px -> 16px */
                    font-family: "Microsoft YaHei UI";  /* Font: Microsoft YaHei */
                    font-weight: normal;                /* Font weight */
                    line-height: 1.4;                  /* Line height for better readability */
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
        """Append text to the message (used for streaming display)"""
        self.current_text += text
        self.message_label.setText(self.current_text)
        
    # Ensure the text is fully displayed
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
                font-size: 24px;
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
    """Enhanced Dify API client - with file/image upload support"""

    def __init__(self, api_key, base_url="https://api.dify.ai/v1", user="default_user"):
        self.api_key = api_key
        self.base_url = base_url
        self.user = user  # Add default user identifier
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def upload_file(self, file_path, user=None):
        """Upload a file and return its file ID"""
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
                
                if response.status_code == 201:  # Note: status code 201 for created
                    file_data = response.json()
                    return file_data.get('id')  # Return file ID
                else:
                    error_msg = f"File upload failed ({response.status_code}): {response.text[:100]}"
                    print(error_msg)
                    return None
                
        except Exception as e:
            print(f"File upload error: {e}")
            return None
        

    def get_mime_type(self, filename):
        """Get MIME type based on filename"""
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
    
    # Build file info list
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
        
        # Build request payload
        data = {
            "inputs": {},  # Use format compatible with test.py
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
        
            # Check response status
            if response.status_code not in (200,201):
                error_msg = f"API returned error ({response.status_code}): "
                try:
                    error_data = response.json()
                    error_msg += error_data.get("message", "unknown error")
                    if "detail" in error_data:
                        error_msg += f" - {error_data['detail']}"
                except:
                    error_msg += response.text[:200] + "..."
                raise Exception(error_msg)
            
            return response
        except requests.exceptions.RequestException as e:
            raise Exception(f"API request failed: {str(e)}")
            
    def is_image(self, file_path):
        """More accurate image type check"""
        image_exts = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
        ext = os.path.splitext(file_path)[1].lower()
        return ext in image_exts
    
    
    def extract_image_urls(self,response_text):
        """Extract image URLs (handles HTML tags specially)"""
    # First pattern: match src attributes within tags
        img_pattern = r']*src\s*=\s*[\'"]([^\'"]+)[\'"]'
    
    # Second pattern: match raw URLs (fallback)
        url_pattern = r'(https?://[^\s"\'<]+)'
    
    
        found_urls = []
    
    # First try to extract URLs from tags
        img_matches = re.findall(img_pattern, response_text, re.IGNORECASE)
        for url in img_matches:
            # Clean HTML entities and special characters from URL
            clean_url = url.replace('&amp;', '&').replace('&quot;', '"')
            found_urls.append(clean_url)
    
    # If no tag URLs found, try plain URL matching
        if not found_urls:
            url_matches = re.findall(url_pattern, response_text)
            for url in url_matches:
                # Only keep image URLs
                if any(url.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    found_urls.append(url)
    
        return found_urls

class SimpleVoiceThread(QThread):
    voice_result = Signal(str)
    voice_error = Signal(str)

    def __init__(self):
        super().__init__()
        self.is_recording = False

        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()

        try:
            print("Loading Whisper model...")
            self.whisper_model = whisper.load_model("base")
            print("✅ Whisper model loaded")
        except Exception as e:
            print(f"❌ Whisper Loading failed: {e}")
            self.whisper_model = None

        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
        except Exception as e:
            print(f"Microphone initialiazation warning: {e}")

    def start_recording(self):
        self.is_recording = True
        self.start()

    def stop_recording(self):
        self.is_recording = False

    def run(self):
        try:
            print("🎤 Start recording...")

            with self.microphone as source:
                audio = self.recognizer.listen(source, timeout=10, phrase_time_limit=30)

            if not self.is_recording:
                return

            print("🔄 Working...")
            text = self.recognize_with_whisper(audio)

            if text and text.strip():
                self.voice_result.emit(text.strip())
            else:
                self.voice_error.emit("No valid speech recognized")

        except Exception as e:
            self.voice_error.emit(f"Voice recognition failed: {str(e)}")

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
            print(f"Whisper failed: {e}")
            try:
                return self.recognizer.recognize_google(audio, language="zh-CN")
            except:
                raise Exception("Both Whisper and Google recognition failed")


class APIConfig:
    """Manage API configuration loading and saving"""
    CONFIG_FILE = "api_config.json"

    @staticmethod
    def load_config():
        """Loading configuration"""
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
        with open(APIConfig.CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)


class EnhancedAIResponseThread(QThread):
    response_chunk = Signal(str)
    response_complete = Signal(str, str)
    error_occurred = Signal(str)
    file_received = Signal(dict)  

    def __init__(self, message, api_key=None, file_paths=None, conversation_id=None, stream=True, typing_speed=0.03):
        super().__init__()
        self.message = message
        self.api_key = api_key
        self.file_paths = file_paths or []
        self.conversation_id = conversation_id
        self.stream = stream
        self.typing_speed = typing_speed
        self.is_cancelled = False
        self.full_response = "" 

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
        response = f"This is a test reply. Received message: {self.message}"
        if self.image_path:
            response += "\nI see you uploaded an image, but test mode cannot analyze image content."

        for char in response:
            if self.is_cancelled:
                break
            self.response_chunk.emit(char)
            time.sleep(0.05)

        if not self.is_cancelled:
            self.response_complete.emit("")

    def _handle_streaming_response(self):
        """Handle streaming response - display content block by block"""
        try:
            # Use modified chat_with_files method
            response = self.client.chat_with_files(
                self.message,
                self.file_paths,
                self.conversation_id,
                user_id="travelmind_user"  # Use user identifier from test.py
            )
            
            # Check response status
            if response.status_code != 200:
                error_msg = f"API returned error ({response.status_code}): "
                try:
                    error_data = response.json()
                    error_msg += error_data.get("message", "unknown error")
                    if "detail" in error_data:
                        error_msg += f" - {error_data['detail']}"
                except:
                    error_msg += response.text[:200] + "..."
                raise Exception(error_msg)
            
            # Manually handle SSE stream
            buffer = ""
            new_conversation_id = self.conversation_id
            last_message_id = None
            content_buffer = ""  # Used to accumulate current message content
        
            for line in response.iter_lines():
                if self.is_cancelled:
                    break
                
                if line:
                    # Decode line
                    decoded_line = line.decode('utf-8').strip()

                    # Check event prefix
                    if decoded_line.startswith("data:"):
                        event_data = decoded_line[5:].strip()

                        # Check if it's end marker
                        if event_data == "[DONE]":
                            # Send remaining content in buffer
                            if content_buffer:
                                # Send remaining content character by character
                                for char in content_buffer:
                                    if self.is_cancelled:
                                        break
                                    self.response_chunk.emit(char)
                                    time.sleep(self.typing_speed)  # Add delay for typewriter effect
                            break
                        
                        # Try to parse JSON
                        try:
                            data = json.loads(event_data)
                            event_type = data.get("event")
                        
                            if event_type == "message":
                                # Handle message event
                                if not new_conversation_id and data.get("conversation_id"):
                                    new_conversation_id = data["conversation_id"]
                            
                                # Check if it's a new message
                                message_id = data.get("id")
                                if message_id != last_message_id:
                                    # Send remaining content from previous message
                                    if content_buffer:
                                        # Send remaining content character by character
                                        for char in content_buffer:
                                            if self.is_cancelled:
                                                break
                                            self.response_chunk.emit(char)
                                            time.sleep(self.typing_speed)  # Add delay for typewriter effect
                                    content_buffer = ""
                                    last_message_id = message_id
                            
                                # Get incremental content
                                content = data.get("answer", "")
                                if content:
                                    # Send character by character (simulate typewriter effect)
                                    for char in content:
                                        if self.is_cancelled:
                                            break
                                        self.response_chunk.emit(char)
                                        time.sleep(self.typing_speed)  # Add delay for typewriter effect
                            
                            # Handle files
                            if "files" in data:
                                for file_info in data["files"]:
                                    self.file_received.emit(file_info)
                            
                            elif event_type == "message_end":
                                # Send remaining content and end
                                if content_buffer:
                                    self.response_chunk.emit(content_buffer)
                                break
                                
                            elif event_type == "error":
                                error_msg = data.get("message", "unknown error")
                                self.error_occurred.emit(f"API error: {error_msg}")
                                break
                                
                        except json.JSONDecodeError:
                            print(f"JSON parsing failed: {event_data}")
                            continue
                    
                    # Handle buffering
                    buffer += decoded_line
                    if buffer.startswith("data:") and not buffer.endswith("}"):
                        continue  # Wait for complete data
                    else:
                        buffer = ""  # Reset buffer

            if not self.is_cancelled:
                # Send complete response
                self.response_complete.emit(new_conversation_id or "", self.full_response)

        except Exception as e:
            print(f"Streaming response processing exception: {str(e)}")
            self.error_occurred.emit(f"API call error: {str(e)}")

    def _handle_blocking_response(self):
        try:
            result = self.client.chat_completion(self.message, self.conversation_id)
            content = result.get("answer", "Sorry, I cannot answer your question right now.")
            conversation_id = result.get("conversation_id", "")

            for char in content:
                if self.is_cancelled:
                    break
                self.response_chunk.emit(char)
                time.sleep(0.03)

            if not self.is_cancelled:
                self.response_complete.emit(conversation_id)

        except Exception as e:
            self.error_occurred.emit(f"API call error: {str(e)}")

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
                    # Save file path information
                    updated_messages = []
                    for msg in chat_history:
                        if "file_paths" in msg and msg["file_paths"]:
                            # Only save filenames, not full paths
                            file_names = [os.path.basename(path) for path in msg["file_paths"]]
                            msg["file_info"] = file_names
                            del msg["file_paths"]  # Remove path information
                        updated_messages.append(msg)
                    
                    chat_record['messages'] = updated_messages
                    chat_record['last_updated'] = datetime.now().isoformat()
                    
                    with open(self.history_file, 'w', encoding='utf-8') as f:
                        json.dump(history, f, ensure_ascii=False, indent=2)
                    return session_id

        # Handle new session
        new_session_id = str(int(time.time() * 1000))
        
        # Process file path information
        processed_messages = []
        for msg in chat_history:
            if "file_paths" in msg and msg["file_paths"]:
                # Only save filenames, not full paths
                file_names = [os.path.basename(path) for path in msg["file_paths"]]
                msg["file_info"] = file_names
                del msg["file_paths"]  # Remove path information
            # Handle AI returned files
            if "files" in msg:
                file_info = []
                for file_data in msg["files"]:
                    # Only save necessary file information
                    file_info.append({
                        "name": file_data.get("name", "unknown"),
                        "type": file_data.get("type", "file")
                    })
                msg["files"] = file_info
            processed_messages.append(msg)

        # Process image information
        for msg in processed_messages:
            if msg["role"] == "assistant" and "images" in msg:
                # Only save filenames
                msg["images"] = [os.path.basename(p) for p in msg["images"]]
                                 
        chat_record = {
            'id': new_session_id,
            'timestamp': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'title': title,
            'messages': processed_messages
        }

        history.insert(0, chat_record)
        history = history[:50]  # Only keep the latest 50 records

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
    """Process uploaded image"""
    try:
        with Image.open(image_path) as img:
            print(f"Image info: {img.size}, {img.mode}")

            if img.size[0] > 1024 or img.size[1] > 1024:
                img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                compressed_path = image_path.replace('.', '_compressed.')
                img.save(compressed_path, "JPEG", quality=85)
                return compressed_path

            return image_path

    except Exception as e:
        print(f"Image processing failed: {e}")
        return image_path


class MainWindow(QMainWindow):
    def __init__(self):
        QMainWindow.__init__(self)
        
        # Add client initialization
        config = APIConfig.load_config()
        api_key = config.get("dify_api_key", "")
        self.client = DifyAPIClient(api_key, user="travelmind_user") if api_key else None
        
        # Initialize generated images list
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

        # New: voice and image related variables
        self.voice_thread = None
        self.is_voice_recording = False
        self.current_image_path = None
        self.current_file_paths = []  # Store multiple file paths
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

        # New: setup voice and image functionality
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
        themeFile = "themes/py_dracula_dark.qss"

        # SET THEME AND HACKS
        if useCustomTheme:
            UIFunctions.theme(self, themeFile, True)
            AppFunctions.setThemeHack(self)

        # SET HOME PAGE AND SELECT MENU
        # ///////////////////////////////////////////////////////////////
        widgets.stackedWidget.setCurrentWidget(widgets.home)
        widgets.btn_home.setStyleSheet(UIFunctions.selectMenu(widgets.btn_home.styleSheet()))

        widgets.textEdit.setPlainText("")


        # Modified to store multiple file paths
        # Changed to store multiple file paths
        
        # Add file preview layout
        # Added file preview layout
        self.filePreviewLayout = QHBoxLayout()
        widgets.chat_input_layout.insertLayout(0, self.filePreviewLayout)
        
        # Store images generated during current conversation
        # Store images generated during current conversation
        self.download_dir = os.path.join(os.getcwd(), "downloads")
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)
            
        self.generated_images = []  

        self.setupHistoryListStyle()

    def setupHistoryListStyle(self):
        """Set chat history list style"""
        # Set list overall style
        widgets.historyList.setStyleSheet("""
        QListWidget {
                font-family: "Microsoft YaHei UI";
                font-size: 16px;  /* Overall list font size */
                background-color: rgb(40, 44, 52);
                border: none;
                outline: none;
            }
            QListWidget::item {
                padding: 14px 10px;  /* Increase padding */
                border-bottom: 1px solid rgb(55, 59, 68);
            }
            QListWidget::item:selected {
                background-color: rgb(68, 71, 90);
                color: rgb(221, 221, 221);
            }
            QListWidget::item:hover {
                background-color: rgb(60, 64, 78);
            }
    """)
        
        # Set button style
        buttons = [
            widgets.loadChatButton, 
            widgets.deleteChatButton, 
            widgets.clearHistoryButton
            ]
        
        for btn in buttons:
            btn.setMinimumSize(140, 50)  # Increase button size
            btn.setMaximumSize(180, 60)
            btn.setStyleSheet("""
                QPushButton {
                    font-family: "Microsoft YaHei UI";
                    font-size: 16px;  /* Button text size */
                    font-weight: 500;
                    color: rgb(221, 221, 221);
                    background-color: rgb(68, 71, 90);
                    border-radius: 8px;
                    padding: 12px 20px;
                    min-width: 140px;
                    min-height: 50px;
                }
                QPushButton:hover {
                    background-color: rgb(78, 81, 100);
                }
                QPushButton:pressed {
                    background-color: rgb(58, 61, 80);
                }
                QPushButton:disabled {
                    background-color: rgb(50, 53, 65);
                    color: rgb(150, 150, 150);
                }
            """)

    def init_dify_integration(self):
            """Initialize Dify integration"""
            self.dify_conversation_id = None
            config = APIConfig.load_config()
            if not config.get("dify_api_key"):
                QTimer.singleShot(2000, self.showFirstTimeSetup)

    def setupSimpleVoiceAndImage(self):
        """Set up simple voice and image functionality"""

        # Add voice button
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
        self.voiceButton.setToolTip("Hold to record")

        # Voice button events
        self.voiceButton.pressed.connect(self.startVoiceRecording)
        self.voiceButton.released.connect(self.stopVoiceRecording)

        # Add image button
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
        self.imageButton.setToolTip("Upload image")
        self.imageButton.clicked.connect(self.selectImage)

        # Add button to existing input layout
        widgets.input_horizontal_layout.insertWidget(1, self.voiceButton)
        widgets.input_horizontal_layout.insertWidget(2, self.imageButton)

        # Add image preview label
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
        self.imagePreview.setText("No image")
        self.imagePreview.setAlignment(Qt.AlignCenter)
        self.imagePreview.hide()

        # Add image preview to chat input layout above
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
        self.fileButton.setToolTip("Upload files")
        self.fileButton.clicked.connect(self.selectFiles)
        
        # Add button to input layout
        widgets.input_horizontal_layout.insertWidget(3, self.fileButton)

    def startVoiceRecording(self):
        """Start voice recording"""
        if self.is_voice_recording:
            return

        print("🎤 Start recording...")
        self.is_voice_recording = True

        # Update button style
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

        # Create and start voice thread
        self.voice_thread = SimpleVoiceThread()
        self.voice_thread.voice_result.connect(self.handleVoiceResult)
        self.voice_thread.voice_error.connect(self.handleVoiceError)
        self.voice_thread.start_recording()

    def stopVoiceRecording(self):
        """Stop voice recording"""
        if not self.is_voice_recording:
            return

        print("⏹️ Stop recording...")
        self.is_voice_recording = False

        # Restore button style
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
        """Handle voice recognition result"""
        print(f"✅ Voice recognition successful: {text}")

        # Add recognition result to input box
        current_text = widgets.chatInputArea.toPlainText()
        if current_text.strip():
            widgets.chatInputArea.setPlainText(current_text + " " + text)
        else:
            widgets.chatInputArea.setPlainText(text)

    def handleVoiceError(self, error_msg):
        """Handle voice recognition error"""
        print(f"❌ Voice recognition failed: {error_msg}")

    def selectImage(self):
        """Select multiple image files"""
        file_dialog = QFileDialog()
        file_paths, _ = file_dialog.getOpenFileNames(
            self,
            "Select images",
            "",
            "Image files (*.png *.jpg *.jpeg *.gif *.bmp);;All files (*)"
        )

        if file_paths:
            self.current_file_paths.extend(file_paths)
            self.updateFilePreviews()

    
    def selectFiles(self):
        """Select multiple files (any type)"""
        file_dialog = QFileDialog()
        file_paths, _ = file_dialog.getOpenFileNames(
            self,
            "Select files",
            "",
            "All files (*);;Image files (*.png *.jpg *.jpeg *.gif);;Documents (*.pdf *.doc *.docx *.txt)"
        )
        
        if file_paths:
            self.current_file_paths.extend(file_paths)
            self.updateFilePreviews()

    def updateFilePreviews(self):
        """Update file preview area"""
        # Clear existing previews
        self.clearFilePreviews()
        
        # Add new file previews
        for file_path in self.current_file_paths:
            self.addFilePreview(file_path)

    def clearFilePreviews(self):
        """Clear all file previews"""
        while self.filePreviewLayout.count():
            item = self.filePreviewLayout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def addFilePreview(self, file_path):
        """Add file preview"""
        try:
            filename = os.path.basename(file_path)
            
            # Create preview container
            container = QWidget()
            container.setMaximumSize(100, 100)
            layout = QVBoxLayout(container)
            layout.setContentsMargins(2, 2, 2, 2)
            
            # Display different previews based on file type
            if self.client.is_image(file_path):
                # Image preview
                pixmap = QPixmap(file_path)
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    preview = QLabel()
                    preview.setPixmap(scaled_pixmap)
                    layout.addWidget(preview)
            else:
                # File icon preview
                icon = QLabel("📄📄")
                icon.setAlignment(Qt.AlignCenter)
                icon.setStyleSheet("font-size: 24px;")
                layout.addWidget(icon)
                
            # File name label
            name_label = QLabel(filename)
            name_label.setAlignment(Qt.AlignCenter)
            name_label.setStyleSheet("font-size: 15px;")
            name_label.setWordWrap(True)
            layout.addWidget(name_label)
            
            # Delete button
            delete_btn = QPushButton("×")
            delete_btn.setFixedSize(20, 20)
            delete_btn.setStyleSheet("background-color: red; color: white; border-radius: 10px;")
            delete_btn.clicked.connect(lambda: self.removeFile(file_path))
            
            # Add to preview layout
            self.filePreviewLayout.addWidget(container)
            
        except Exception as e:
            print(f"File preview failed: {e}")

    def removeFile(self, file_path):
        """Remove file"""
        if file_path in self.current_file_paths:
            self.current_file_paths.remove(file_path)
            self.updateFilePreviews()

    def showImagePreview(self, image_path):
        """Show image preview"""
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

                # Double click to clear
                self.imagePreview.mouseDoubleClickEvent = lambda event: self.clearImagePreview()

            else:
                self.imagePreview.setText("Image loading failed")

        except Exception as e:
            print(f"Image preview failed: {e}")
            self.imagePreview.setText("Preview failed")

    def clearImagePreview(self):
        """Clear image preview"""
        self.current_image_path = None
        self.imagePreview.clear()
        self.imagePreview.setText("No image")
        self.imagePreview.hide()
        print("🗑️ Image cleared")

    def addImageToChat(self, image_path):
        """Add image preview to chat area (without showing URL information)"""
        try:
            # Create image container
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
            
            # Load and scale image
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                # Set maximum size
                if pixmap.width() > 600 or pixmap.height() > 400:
                    pixmap = pixmap.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                
                # Create image label
                image_label = QLabel()
                image_label.setPixmap(pixmap)
                image_label.setAlignment(Qt.AlignCenter)
                image_label.setStyleSheet("border: none;")
                layout.addWidget(image_label)
                
                # Image info and control panel
                control_frame = QFrame()
                control_frame.setStyleSheet("background: transparent;")
                control_layout = QHBoxLayout(control_frame)
                
                # Image metadata
                meta_label = QLabel(f"Image {pixmap.width()}×{pixmap.height()}")
                meta_label.setStyleSheet("color: #888; font-size: 12px;")
                control_layout.addWidget(meta_label)
                
                # Action buttons
                action_layout = QHBoxLayout()
                action_layout.setSpacing(8)
                
                # Save button
                save_btn = QPushButton("Save As")
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
                
                # Add to chat area
                widgets.chatContentLayout.insertWidget(
                    widgets.chatContentLayout.count() - 1,
                    container
                )
                
                # Scroll to bottom
                QTimer.singleShot(100, self.scrollToBottom)
            else:
                print(f"Unable to load image: {image_path}")
                
        except Exception as e:
            print(f"Failed to add image to chat: {str(e)}")

    def addFileToChat(self, file_path):
        """Add file preview to chat interface"""
        try:
            filename = os.path.basename(file_path)
            
            # Create file preview widget
            file_widget = QWidget()
            file_layout = QHBoxLayout(file_widget)
            file_layout.setContentsMargins(10, 5, 10, 5)
            
            # File icon
            file_icon = QLabel("📄")
            file_icon.setStyleSheet("font-size: 24px;")
            file_layout.addWidget(file_icon)
            
            # File info
            file_info_widget = QWidget()
            file_info_layout = QVBoxLayout(file_info_widget)
            
            file_name_label = QLabel(filename)
            file_name_label.setStyleSheet("font-weight: bold;")
            file_info_layout.addWidget(file_name_label)
            
            download_btn = QPushButton("Download")
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
            
            # Add to chat area
            layout = widgets.chatContentLayout
            layout.insertWidget(layout.count() - 1, file_widget)
            
            QTimer.singleShot(100, self.scrollToBottom)
            
        except Exception as e:
            print(f"Failed to add file to chat: {e}")

    def openFile(self, file_path):
        """Open downloaded file"""
        try:
            if sys.platform == "win32":
                os.startfile(file_path)
            elif sys.platform == "darwin":  # macOS
                subprocess.call(["open", file_path])
            else:  # Linux
                subprocess.call(["xdg-open", file_path])
        except Exception as e:
            QMessageBox.warning(self, "Open failed", f"Unable to open file: {str(e)}")

    def startChatFromHome(self):
        """Jump from home page to chat page"""
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
        widgets.chatInputArea.setStyleSheet("font-size: 24px;")
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
        """Load selected chat history to AI chat page"""
        selected_items = widgets.historyList.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        if not isinstance(item, ChatHistoryItem):
            return

        # Auto save current chat (if any)
        if self.chat_history and self.auto_save_enabled:
            self.autoSaveCurrentChat()

        # Load selected chat history
        chat_data = item.chat_data
        self.chat_history = chat_data['messages'].copy()
        self.current_session_id = chat_data['id']

        # Clear chat interface
        self.clearChatUI()
        
        # Display historical messages
        for message in self.chat_history:
            is_user = message['role'] == 'user'
            content = message['content']
            
            # Display message content
            self.addChatMessage(content, is_user=is_user)
            # If there's image info, display images
            if not is_user and "images" in message:
                for image_filename in message["images"]:
                    image_path = os.path.join(self.download_dir, image_filename)
                    if os.path.exists(image_path):
                        self.addImageToChat(image_path)
            # If there's file info, display files
            if "file_info" in message:
                files_str = ", ".join(message["file_info"])
                if is_user:
                    file_message = f"📎📎 Uploaded files: {files_str}"
                else:
                    file_message = f"📎📎 Contains files: {files_str}"
                
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
            
            # If there are AI returned files, display files
            if "files" in message:
                for file_info in message["files"]:
                    file_name = file_info.get("name", "unknown")
                    file_type = file_info.get("type", "file")
                    
                    # Create file placeholder
                    file_placeholder = QLabel(f"📄 {file_name} (Downloaded)")
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

        # Switch to chat page
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
        """Send message (supports text, images, and files)"""
        message = widgets.chatInputArea.toPlainText().strip()
    
        # If no message and no files, don't send
        if not message and not self.current_file_paths:
            return
    
        # Get configuration
        config = APIConfig.load_config()
        api_key = config.get("dify_api_key", "")
    
        # Clear input box and file preview
        widgets.chatInputArea.clear()
        file_paths = self.current_file_paths.copy()  # Use copy to avoid modification in subsequent operations
        self.current_file_paths = []
        self.clearFilePreviews()
    
        # Disable send button
        widgets.sendButton.setEnabled(False)
        widgets.sendButton.setText("Sending...")
    
        # Build user message content (including all file info)
        file_messages = []
        combined_message = message
    
        # Process all files (images and non-images)
        for file_path in file_paths:
            # Display files in chat interface
            if self.client.is_image(file_path):
                self.addImageToChat(file_path)
                file_message = f"[Image: {os.path.basename(file_path)}]"
            else:
                self.addFileToChat(file_path) # Add file preview method
                file_message = f"[File: {os.path.basename(file_path)}]"
        
            file_messages.append(file_message)
    
        # If there's file info, add to message
        if file_messages:
            files_str = "\n".join(file_messages)
            if message:
                combined_message = f"{message}\n{files_str}"
            else:
                combined_message = files_str
                message = "Please analyze these files" if len(file_messages) > 1 else "Please analyze this file"
    
        # Add user message to chat history
        self.chat_history.append({
        "role": "user",
        "content": combined_message,
        # Save file path info for loading in history
        "file_paths": file_paths if file_paths else None
        })
    
        # Display user message in chat interface
        self.addChatMessage(combined_message, is_user=True)
    
        # Create AI message for streaming display
        self.current_ai_message = self.addChatMessage("", is_user=False, streaming=True)
        
        # Start cursor blinking
        self.startCursorBlink()
        
        # Create and start AI response thread
        self.ai_thread = EnhancedAIResponseThread(
            message,  # Original text message
            api_key if api_key else None,
            file_paths=file_paths,
            conversation_id=getattr(self, 'dify_conversation_id', None),
            stream=config.get("stream_enabled", True),
            typing_speed=config.get("typing_speed", 0.03)  # Add typing speed configuration
        )
        
        # Connect signals
        self.ai_thread.response_chunk.connect(self.handleStreamingChunk)
        self.ai_thread.response_complete.connect(self.handleDifyResponseComplete)
        self.ai_thread.error_occurred.connect(self.handleAPIError)
        self.ai_thread.file_received.connect(self.handleFileReceived)
        
        self.ai_thread.start()

    def showUploadProgress(self, current, total):
        """Show file upload progress"""
        if total > 0:
            percent = int(current * 100 / total)
            widgets.sendButton.setText(f"Uploading... {percent}%")
    
    def handleFileReceived(self, file_info):
        """Handle received files"""
        try:
            file_name = file_info.get("name", "unknown_file")
            file_url = file_info.get("url", "")
            file_type = file_info.get("type", "file")
            
            if not file_url:
                print("Invalid file URL")
                return
                
            # Create download directory
            download_dir = os.path.join(os.getcwd(), "downloads")
            if not os.path.exists(download_dir):
                os.makedirs(download_dir)
                
            # Download file
            file_path = os.path.join(download_dir, file_name)
            response = requests.get(file_url, stream=True)
            
            if response.status_code == 200:
                with open(file_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                print(f"File download successful: {file_path}")
                
                # Display file in chat interface
                if file_type == "image":
                    self.addImageToChat(file_path)
                else:
                    self.addFileToChat(file_path)
                    
                # Add to chat history
                if self.current_ai_message:
                    self.chat_history[-1]["files"] = self.chat_history[-1].get("files", []) + [file_info]
                    
            else:
                print(f"File download failed: {response.status_code}")
                
        except Exception as e:
            print(f"File processing failed: {e}")

    def handleStreamingChunk(self, char):
        """Handle each character from streaming response"""
        if self.current_ai_message:
            self.current_ai_message.appendText(char)
            self.scrollToBottom()

    def remove_image_urls(self, content, image_urls):
        """Completely remove all image-related HTML tags and URL fragments"""
        if not content:
            return content
        
        clean_content = content
    
        # Step 1: Remove all HTML image tags
        clean_content = re.sub(r'<img[^>]*>', '', clean_content)
    
        # Step 2: Remove all image URLs (including partial and incomplete URLs)
        for url in image_urls:
            # Remove complete URL
            clean_content = clean_content.replace(url, '')
        
            # Remove URL fragments (for error formats in screenshots)
            base_url = url.split("?")[0].split("%")[0]
            if base_url and base_url in clean_content:
                clean_content = clean_content.replace(base_url, '')
    
        # Step 3: Clean special error formats
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
        """Handle Dify response completion"""
        self.stopCursorBlink()
        
        # Update session ID
        self.dify_conversation_id = conversation_id or self.dify_conversation_id
        
        # Save to chat history
        if self.current_ai_message:
            original_content = self.current_ai_message.current_text
            
            try:
                # Extract image URLs
                image_urls = self.client.extract_image_urls(original_content) if self.client else []
                print("Extracted image URLs:")
                for i, url in enumerate(image_urls):
                    print(f"{i+1}. {url}")
                # Download images
                if image_urls:
                    self.download_images(image_urls)
                
                # Create clean text without image URLs
                clean_content = self.remove_image_urls(original_content, image_urls) if original_content else ""
                
                # If content is empty but images were generated, use default text
                if not clean_content.strip() and image_urls:
                    clean_content = "Generated travel images"
                
                # Update message content
                self.current_ai_message.setText(clean_content)
                
                # Save to chat history
                self.chat_history.append({
                    "role": "assistant",
                    "content": clean_content,
                    "images": self.generated_images.copy()
                })
                
            except Exception as e:
                print(f"Error processing AI response: {str(e)}")
                self.current_ai_message.setText("Error processing response, please check API configuration")
                self.chat_history.append({
                    "role": "assistant",
                    "content": "Error processing response, please check API configuration"
                })
                
            finally:
                # Reset image list
                self.generated_images.clear()
        
        # Save session
        if self.dify_conversation_id:
            self.history_manager.save_or_update_chat(
                self.chat_history,
                self.dify_conversation_id
            )
        
        # Restore send button
        widgets.sendButton.setEnabled(True)
        widgets.sendButton.setText("Send")
        self.ai_thread = None
        self.current_ai_message = None

    def process_response_content(self, original_content, image_urls):
        """
        Process response content:
        1. Download and display images
        2. Completely remove image URLs from text
        """
        # Download images
        self.download_images(image_urls)
    
        # Create new cleaned content, only keep non-image parts
        clean_content = original_content
    
        # Remove all image URLs
        for url in image_urls:
            # Remove Markdown format images
            clean_content = re.sub(rf'!$$.*?$$${re.escape(url)}$', '', clean_content)
            # Remove HTML img tags
            clean_content = re.sub(rf'', '', clean_content)
            # Remove bare URLs
            clean_content = clean_content.replace(url, '')
    
        # Remove empty lines and extra spaces
        clean_content = re.sub(r'\n\s*\n', '\n\n', clean_content).strip();
    
        # If content is completely empty, show default message
        if not clean_content:
            clean_content = "Generated related images" if image_urls else "No text content"
    
        return clean_content
    
    def remove_url_placeholders(self, message_text, image_urls):
        """Remove URL placeholder text from message text"""
        # Create URL regex patterns
        url_patterns = [
            r's\s*=\s*[\'\"](https?://[^\s\'\"]+)[\'\"]',      # s="URL" format
            r'image_url\s*:\s*[\'\"](https?://[^\s\'\"]+)[\'\"]',  # image_url:"URL" format
            r'url\s*:\s*(https?://\S+)',                     # url: URL format
            r'a url\s*：\s*(https?://\S+)',                  # a url: format
        ]
        
        clean_text = message_text
        # Remove all URL patterns
        for pattern in url_patterns:
            clean_text = re.sub(pattern, '', clean_text)
        
        # Remove code block comments (code snippets provided in example code)
        code_blocks = re.findall(r'```python[\s\S]+?```', clean_text, re.DOTALL)
        for code_block in code_blocks:
            if "req.get" in code_block or "open(" in code_block:
                clean_text = clean_text.replace(code_block, '')
        
        # If entire message is URL, remove completely
        if clean_text.strip() in image_urls:
            clean_text = "Generated images" if image_urls else ""
        
        # Update message display
        self.current_ai_message.setText(clean_text.strip())
    
    def download_images(self, image_urls):
        """More reliable image download method"""
        if not image_urls:
            return
        
        # Ensure download directory exists
        download_dir = os.path.join("downloads", "images")
        os.makedirs(download_dir, exist_ok=True)
    
        for i, url in enumerate(image_urls):
            try:
                # Clean special formats in URL
                url = url.replace('%!F(MISSING)', '/').replace('%!F', '/')
            
                # Get filename
                filename = os.path.basename(url.split("?")[0])
                if not filename:
                    filename = f"image_{int(time.time())}_{i}.png"
                
                file_path = os.path.join(download_dir, filename)
            
                # Download image
                response = requests.get(url, stream=True, timeout=30)
            
                if response.status_code == 200:
                    with open(file_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)

                    print(f"Image saved to: {file_path}")
                    self.addImageToChat(file_path)
                    self.generated_images.append(file_path)
                else:
                    print(f"Image download failed: {url} - Status code {response.status_code}")
                
            except Exception as e:
                print(f"Image processing error: {str(e)}")

    def handleAPIError(self, error_message):
        """Handle API errors"""
        self.stopCursorBlink()

        # Display detailed error information
        error_dialog = QMessageBox(self)
        error_dialog.setIcon(QMessageBox.Critical)
        error_dialog.setWindowTitle("API Error")
        error_dialog.setText("Error processing API request")
        error_dialog.setInformativeText(error_message)
        error_dialog.setDetailedText("Detailed technical information:\n" + traceback.format_exc())
        error_dialog.exec()
        
        # Restore UI state
        if self.current_ai_message:
            self.current_ai_message.setText(f"❌❌ API Error: {error_message}")

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
        """Clear conversation"""
        self.dify_conversation_id = None
        self.startNewChat()

    def showFirstTimeSetup(self):
        """First-time setup prompt"""
        reply = QMessageBox.question(
            self,
            "Welcome to TravelMind",
            "You haven't configured the Dify API key yet.\n\n"
            "After configuration, you can use AI assistant features, otherwise test mode will be used.\n\n"
            "Configure now?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.showAPISettings()

    def openImage(self, image_path):
        """Open image with system default application"""
        if not os.path.exists(image_path):
            self.showWarning("Image file does not exist", f"Cannot find image file: {image_path}")
            return
            
        try:
            if sys.platform == "win32":
                os.startfile(image_path)
            elif sys.platform == "darwin":  # macOS
                subprocess.call(["open", image_path])
            else:  # Linux
                subprocess.call(["xdg-open", image_path])
        except Exception as e:
            self.showWarning("Open failed", f"Unable to open image: {str(e)}")
    
    def saveImage(self, image_path):
        """Save image to specified location"""
        if not os.path.exists(image_path):
            self.showWarning("File does not exist", "Cannot find image file")
            return
            
        file_filter = "Image files (*.png *.jpg *.jpeg *.gif)"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save image", "", file_filter
        )
        
        if save_path:
            try:
                shutil.copy2(image_path, save_path)
                self.showInfo("Save successful", "Image saved successfully")
            except Exception as e:
                self.showWarning("Save failed", f"Unable to save image: {str(e)}")

    def showAPISettings(self):
        """Show API settings dialog"""
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
    """API settings dialog"""

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
        """Toggle password visibility"""
        if self.api_key_edit.echoMode() == QLineEdit.Password:
            self.api_key_edit.setEchoMode(QLineEdit.Normal)
        else:
            self.api_key_edit.setEchoMode(QLineEdit.Password)

    def loadSettings(self):
        """Load settings"""
        config = APIConfig.load_config()
        self.api_key_edit.setText(config.get("dify_api_key", ""))
        self.base_url_edit.setText(config.get("dify_base_url", "https://api.dify.ai/v1"))
        self.stream_checkbox.setChecked(config.get("stream_enabled", True))
        self.speed_spinbox.setValue(int(config.get("typing_speed", 0.03) * 1000))

    def testConnection(self):
        """Test API connection"""
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip() or "https://api.dify.ai/v1"

        if not api_key:
            QMessageBox.warning(self, "Error", "Please enter API key")
            return

        self.test_button.setEnabled(False)
        self.test_button.setText("Testing...")

        try:
            client = DifyAPIClient(api_key, base_url)
            # Use non-streaming request for testing
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
                error_msg = f"API return error ({response.status_code}): "
                try:
                    error_data = response.json()
                    error_msg += error_data.get("message", "Unknown error")
                    if "detail" in error_data:
                        error_msg += f" - {error_data['detail']}"
                except:
                    error_msg += response.text[:200] + "..."
                QMessageBox.critical(self, "Error", error_msg)
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"API connection test failed:\n{str(e)}")
        finally:
            self.test_button.setEnabled(True)
            self.test_button.setText("Test Connection")

    def saveSettings(self):
        config = {
            "dify_api_key": self.api_key_edit.text().strip(),
            "dify_base_url": self.base_url_edit.text().strip() or "https://api.dify.ai/v1",
            "stream_enabled": self.stream_checkbox.isChecked(),
            "typing_speed": self.speed_spinbox.value() / 1000.0
        }

        APIConfig.save_config(config)
        QMessageBox.information(self, "Success", "Settings saved successfully!")
        self.accept()