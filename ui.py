import math
import os, re, threading
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, Signal, QObject
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QTextEdit, QVBoxLayout,
    QHBoxLayout, QFrame, QProgressBar, QLineEdit, QMessageBox
)
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtCore import QUrl

from config import (
    APP_NAME, APP_VERSION, WINDOW_WIDTH, WINDOW_HEIGHT, SAFE_MODE, SOUNDS_DIR,
    ALWAYS_LISTEN, AUTO_SPEAK, CONFIRM_REQUIRED_TOOLS,
)
import database
from database import MemoryDB
from ollama_client import OllamaClient
from system_monitor import get_stats
from tools import execute_tool, log_blocked_tool
from voice import VoiceEngine
from sounds import make_sound_pack

STYLE = '''
QMainWindow, QWidget {
    background: #05080d;
    color: #d9f7ff;
    font-family: "Segoe UI";
}
QFrame#panel {
    background: #08111a;
    border: 1px solid #12384b;
    border-radius: 12px;
}
QLabel#title {
    color: #6de7ff;
    font-size: 26px;
    font-weight: 700;
    letter-spacing: 4px;
}
QLabel#status {
    color: #45f0c2;
    font-size: 12px;
    font-weight: 700;
}
QLabel#section {
    color: #55c9ea;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
}
QTextEdit, QLineEdit {
    background: #03070b;
    border: 1px solid #16485e;
    border-radius: 8px;
    color: #dffaff;
    padding: 10px;
    selection-background-color: #07506b;
}
QPushButton {
    background: #071824;
    border: 1px solid #17617d;
    border-radius: 8px;
    color: #8deaff;
    padding: 9px 13px;
    font-weight: 600;
}
QPushButton:hover {
    background: #0b2a3a;
    border: 1px solid #43d9ff;
}
QProgressBar {
    background: #020508;
    border: 1px solid #12384b;
    border-radius: 4px;
    text-align: right;
    color: #b8f4ff;
}
QProgressBar::chunk {
    background: #0787b2;
    border-radius: 4px;
}
'''

class Worker(QObject):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, client, messages):
        super().__init__()
        self.client = client
        self.messages = messages

    def run(self):
        try:
            self.finished.emit(self.client.chat(self.messages))
        except Exception as e:
            self.error.emit(str(e))

class VoiceBridge(QObject):
    """Marshals background-thread mic callbacks safely onto the Qt UI thread."""
    heard = Signal(str)
    mic_error = Signal(str)


class AICore(QWidget):
    def __init__(self):
        super().__init__()
        self.angle = 0
        self.pulse = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(30)
        self.setMinimumSize(300, 300)

    def animate(self):
        self.angle = (self.angle + 2) % 360
        self.pulse = (self.pulse + 1) % 100
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.rect().center()
        radius = min(self.width(), self.height()) // 4
        p.setPen(QPen(QColor("#0d5770"), 1))
        for r in [radius+35, radius+55, radius+75]:
            p.drawEllipse(c, r, r)

        p.save()
        p.translate(c)
        p.rotate(self.angle)
        p.setPen(QPen(QColor("#33d9ff"), 2))
        for r in [radius+35, radius+55]:
            p.drawArc(-r, -r, 2*r, 2*r, 0, 70*16)
        p.restore()

        glow = 25 + int(8 * abs(math.sin(self.pulse/10)))
        p.setBrush(QBrush(QColor(0, 145, 190, 45)))
        p.setPen(QPen(QColor("#61e8ff"), 2))
        p.drawEllipse(c, radius+glow, radius+glow)
        p.setBrush(QBrush(QColor("#062431")))
        p.drawEllipse(c, radius, radius)

        p.setPen(QPen(QColor("#8ff3ff")))
        font = QFont("Segoe UI", 18, QFont.Bold)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, "NOVA")

        p.setPen(QPen(QColor("#4cdfff")))
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        p.drawText(self.rect().adjusted(0, 52, 0, 0), Qt.AlignCenter, "NEURAL CORE")


class NovaWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        make_sound_pack(SOUNDS_DIR)
        started = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.db = MemoryDB(conversation_title=f"NOVA session {started}")
        self.conversation_named = False
        self.client = OllamaClient()
        self.voice = VoiceEngine()
        self.messages = []
        self.mic_muted = False
        self.voice_bridge = VoiceBridge()
        self.voice_bridge.heard.connect(self.on_voice_heard)
        self.voice_bridge.mic_error.connect(self.on_voice_error)
        self.setWindowTitle(f"{APP_NAME} AI Assistant v{APP_VERSION}")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setStyleSheet(STYLE)
        self.build_ui()
        self.update_stats()
        self.update_clock()
        if ALWAYS_LISTEN:
            self.start_continuous_voice()

    def panel(self):
        f = QFrame()
        f.setObjectName("panel")
        return f

    def label(self, text, object_name=None):
        l = QLabel(text)
        if object_name:
            l.setObjectName(object_name)
        return l

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(self.label("N O V A", "title"))
        header.addStretch()
        self.status = self.label("● SYSTEM INITIALIZING", "status")
        header.addWidget(self.status)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(12)

        # Left system panel
        left = self.panel()
        lv = QVBoxLayout(left)
        lv.addWidget(self.label("SYSTEM TELEMETRY", "section"))
        self.cpu = self.add_meter(lv, "CPU")
        self.ram = self.add_meter(lv, "RAM")
        self.gpu = self.add_meter(lv, "GPU")
        self.disk = self.add_meter(lv, "DISK")
        lv.addSpacing(10)
        self.gpu_info = self.label("GPU TEMP  -- °C")
        lv.addWidget(self.gpu_info)
        self.clock = self.label("--")
        lv.addWidget(self.clock)
        lv.addStretch()

        # Center
        center = self.panel()
        cv = QVBoxLayout(center)
        self.core = AICore()
        cv.addWidget(self.core, 1)
        self.state = self.label("● STANDBY", "status")
        self.state.setAlignment(Qt.AlignCenter)
        cv.addWidget(self.state)
        self.wave = self.label("▁▂▃▄▅▄▃▂▁")
        self.wave.setAlignment(Qt.AlignCenter)
        cv.addWidget(self.wave)

        # Right
        right = self.panel()
        rv = QVBoxLayout(right)
        rv.addWidget(self.label("NEURAL CONSOLE", "section"))
        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setPlaceholderText("NOVA communication stream...")
        rv.addWidget(self.chat, 1)

        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Command NOVA...")
        self.input.returnPressed.connect(self.send_message)
        input_row.addWidget(self.input, 1)
        self.send_btn = QPushButton("SEND")
        self.send_btn.clicked.connect(self.send_message)
        input_row.addWidget(self.send_btn)
        rv.addLayout(input_row)

        btns = QHBoxLayout()
        self.listen_btn = QPushButton("🎙 LISTEN")
        self.listen_btn.setToolTip(
            "NOVA is always listening automatically. Click to mute/unmute the mic."
        )
        self.listen_btn.clicked.connect(self.toggle_mic)
        btns.addWidget(self.listen_btn)

        self.speak_btn = QPushButton("🔊 SPEAK")
        self.speak_btn.setToolTip(
            "Replies are spoken automatically. Click to replay the last answer."
        )
        self.speak_btn.clicked.connect(self.speak_last)
        btns.addWidget(self.speak_btn)

        for text, fn in [
            ("SYSTEM", self.show_system),
            ("MEMORY", self.show_memory),
            ("DATABASE", self.show_database),
        ]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        rv.addLayout(btns)

        body.addWidget(left, 1)
        body.addWidget(center, 2)
        body.addWidget(right, 3)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.addWidget(self.label(
            f"NOVA CORE // {self.client.model} // DB: {database.ACTIVE_BACKEND.upper()}"))
        footer.addStretch()
        footer.addWidget(self.label("CTRL+SHIFT+SPACE  VOICE"))
        root.addLayout(footer)

        self.hotkey_timer = QTimer(self)
        self.hotkey_timer.timeout.connect(self.check_hotkey)
        self.hotkey_timer.start(200)

    def add_meter(self, layout, name):
        layout.addWidget(self.label(name, "section"))
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setFormat("%p%")
        layout.addWidget(bar)
        return bar

    def update_clock(self):
        self.clock.setText(datetime.now().strftime("%A  %d %B %Y\n%H:%M:%S"))
        QTimer.singleShot(1000, self.update_clock)

    def update_stats(self):
        s = get_stats()
        self.cpu.setValue(int(s["cpu"]))
        self.ram.setValue(int(s["ram"]))
        self.gpu.setValue(int(s["gpu_data"]["gpu"]))
        self.disk.setValue(int(s["disk"]))
        self.gpu_info.setText(
            f"GPU {s['gpu_data']['gpu']:.0f}%  |  "
            f"VRAM {s['gpu_data']['vram_used']:.0f}/{s['gpu_data']['vram_total']:.0f} MB  |  "
            f"{s['gpu_data']['temperature']:.0f}°C"
        )
        self.status.setText("● LM STUDIO ONLINE" if self.client.is_online() else "● LM STUDIO OFFLINE")
        QTimer.singleShot(1500, self.update_stats)

    def set_state(self, text):
        self.state.setText(text)

    def append_chat(self, who, text):
        self.chat.append(f"<b style='color:#54ddff'>{who}</b><br>{text}<br>")

    def send_message(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.append_chat("USER", text)
        self.db.add_message("user", text)
        if not self.conversation_named:
            self.db.rename_conversation(text[:60])
            self.conversation_named = True
        self.messages.append({"role": "user", "content": text})

        self.set_state("◉ THINKING")
        self.send_btn.setEnabled(False)

        recent_memory = self.db.recent_memories()
        if recent_memory:
            context = "\nRelevant memory:\n" + "\n".join("- " + x for x in recent_memory)
            request_messages = self.messages[-10:] + [{"role": "system", "content": context}]
        else:
            request_messages = self.messages[-10:]

        worker = Worker(self.client, request_messages)
        thread = threading.Thread(target=worker.run, daemon=True)
        worker.finished.connect(self.on_ai_response)
        worker.error.connect(self.on_ai_error)
        thread.start()

    def on_ai_response(self, text, speak=True, tool_depth=0):
        # Don't read the internal TOOL: line aloud / show it raw if the model
        # is about to trigger a tool call - the spoken part comes after the
        # tool result loop below.
        display_text = text
        self.append_chat("NOVA", display_text)
        self.db.add_message("assistant", text)
        self.messages.append({"role": "assistant", "content": text})
        self.set_state("● READY")
        self.send_btn.setEnabled(True)
        triggered_tool = self.handle_tool(text, tool_depth=tool_depth)
        if speak and AUTO_SPEAK and not triggered_tool:
            self.voice.speak(self._clean_for_speech(text))

    def on_ai_error(self, error):
        self.append_chat("NOVA ERROR", error)
        self.set_state("⚠ CONNECTION ERROR")
        self.send_btn.setEnabled(True)

    def _clean_for_speech(self, text):
        """Strip TOOL: control lines and basic markdown so TTS doesn't read
        out raw syntax."""
        cleaned = re.sub(r"^TOOL:.*$", "", text, flags=re.MULTILINE)
        cleaned = re.sub(r"[*_`#]+", "", cleaned)
        return cleaned.strip()

    # Comparisons may legitimately need several searches in a row (one per
    # item being compared) - this caps the chain so a confused model can't
    # loop forever calling tools on its own without ever answering.
    MAX_TOOL_CHAIN_DEPTH = 6

    # If a weaker/local model doesn't follow the exact "TOOL: name | arg"
    # format, it often still produces something close - e.g. no "TOOL:"
    # prefix, or an invented name like OPEN_BROWSER instead of the real
    # open_application. This maps those near-misses back to a real tool
    # instead of silently doing nothing.
    TOOL_ALIASES = {
        "open_browser": "open_application",
        "openbrowser": "open_application",
        "launch_application": "open_application",
        "launch_app": "open_application",
        "launchapp": "open_application",
        "open_app": "open_application",
        "openapp": "open_application",
        "start_application": "open_application",
        "browse": "open_url",
        "go_to": "open_url",
        "navigate": "open_url",
        "navigate_to": "open_url",
        "search": "web_search",
        "search_web": "web_search",
        "google": "web_search",
        "new_doc": "new_document",
        "new_presentation": "new_document",
        "create_document": "new_document",
    }
    KNOWN_TOOLS = {
        "system_info", "list_directory", "open_application", "open_url",
        "screenshot", "remember", "recall", "db_stats", "web_search",
        "new_document",
    }

    def _extract_tool_call(self, text):
        """Returns (tool_name, argument) or (None, None). Tries the exact
        required format first, then falls back to catching near-miss
        formats a weaker model might produce instead."""
        match = re.search(r"TOOL:\s*([a-zA-Z_]+)\s*(?:\|\s*(.*?))?\s*$", text, re.MULTILINE)
        if match:
            name = match.group(1).lower()
            arg = (match.group(2) or "").strip()
            return self.TOOL_ALIASES.get(name, name), arg

        # Fallback: a line that looks like "SOME_NAME | argument" or
        # "SOME_NAME: argument" without the required "TOOL:" prefix. Only
        # matches if the left side is letters/underscores only (to avoid
        # false-triggering on ordinary sentences that happen to contain a
        # "|" or ":") and resolves to a tool we actually recognise.
        for fallback_match in re.finditer(
            r"^([A-Za-z][A-Za-z_]{2,30})\s*[|:]\s*(.+)$", text, re.MULTILINE
        ):
            raw_name = fallback_match.group(1).lower()
            canonical = self.TOOL_ALIASES.get(raw_name, raw_name)
            if canonical in self.KNOWN_TOOLS:
                return canonical, fallback_match.group(2).strip()

        return None, None

    def handle_tool(self, text, tool_depth=0):
        """Runs a TOOL: line if the model emitted one (or something close
        enough to one - see _extract_tool_call). Returns True if a tool was
        triggered (so the caller doesn't also speak the raw line as if it
        were the final answer)."""
        name, arg = self._extract_tool_call(text)
        if not name:
            return False

        if tool_depth >= self.MAX_TOOL_CHAIN_DEPTH:
            msg = (
                "That's taking more tool calls than I'll chain in one go - "
                "here's what I've found so far, ask me to keep digging if "
                "you want more."
            )
            self.append_chat("NOVA", msg)
            if AUTO_SPEAK:
                self.voice.speak(msg)
            return True

        if SAFE_MODE and name in CONFIRM_REQUIRED_TOOLS:
            reason = f"Tool request detected: {name}. SAFE MODE requires manual approval."
            log_blocked_tool(name, arg, self.db, reason)
            self.append_chat("NOVA", reason)
            if AUTO_SPEAK:
                self.voice.speak(reason)
            return True

        self.set_state("◉ SEARCHING" if name == "web_search" else "◉ WORKING")
        result = execute_tool(name, arg, self.db)
        self.db.add_message("tool", f"{name}({arg}) -> {result}")
        self.append_chat("TOOL", result)

        # Feed the tool result back to the model so NOVA gives a real,
        # spoken answer instead of just dumping raw tool output.
        followup = {
            "role": "system",
            "content": (
                f"Tool '{name}' returned:\n{result}\n\n"
                "If you were comparing multiple items and still need to "
                "search for another one, you may output one more TOOL line "
                "now. Otherwise, using everything gathered so far, give the "
                "user a short natural spoken answer (and a clear "
                "recommendation if they asked you to decide)."
            ),
        }
        request_messages = self.messages[-10:] + [followup]
        worker = Worker(self.client, request_messages)
        thread = threading.Thread(target=worker.run, daemon=True)
        worker.finished.connect(lambda t: self.on_ai_response(t, speak=True, tool_depth=tool_depth + 1))
        worker.error.connect(self.on_ai_error)
        thread.start()
        return True

    # ------------------------------------------------------------------
    # Voice: always-on listening + manual overrides
    # ------------------------------------------------------------------
    def start_continuous_voice(self):
        """Opens the mic once, for the whole session. No LISTEN click needed
        - just talk, and NOVA answers back automatically."""
        def on_heard(text):
            self.voice_bridge.heard.emit(text)

        def on_error(err):
            self.voice_bridge.mic_error.emit(err)

        try:
            self.voice.start_background_listening(on_heard, on_error)
            self.set_state("● LISTENING (VOICE ON)")
            self.append_chat(
                "NOVA",
                "Voice channel is open — just start talking, no button needed. "
                "Click LISTEN any time to mute the mic.",
            )
        except Exception as e:
            self.append_chat(
                "NOVA",
                f"Continuous voice unavailable ({e}). You can still type, "
                "or click LISTEN for a one-off voice command.",
            )

    def on_voice_heard(self, text):
        """Runs on the UI thread whenever the always-on mic finishes a phrase."""
        if self.mic_muted:
            return
        self.input.setText(text)
        self.send_message()

    def on_voice_error(self, err):
        self.append_chat("NOVA", f"[mic error: {err}]")

    def toggle_mic(self):
        """LISTEN button: manual mute/unmute override for the always-on mic."""
        self.mic_muted = not self.mic_muted
        if self.mic_muted:
            self.voice.mute()
            self.listen_btn.setText("🔇 MUTED")
            self.set_state("○ MIC MUTED")
            self.append_chat("NOVA", "Microphone muted.")
        else:
            self.voice.unmute()
            self.listen_btn.setText("🎙 LISTEN")
            self.set_state("● LISTENING (VOICE ON)")
            self.append_chat("NOVA", "Microphone resumed - I'm listening again.")

    def speak_last(self):
        """SPEAK button: manually replay NOVA's last answer (replies are
        already spoken automatically as they arrive)."""
        if self.messages and self.messages[-1]["role"] == "assistant":
            self.voice.speak(self._clean_for_speech(self.messages[-1]["content"]))

    def show_system(self):
        from tools import system_info
        self.append_chat("SYSTEM", str(system_info()))

    def show_memory(self):
        mem = self.db.memories_detailed(20)
        if not mem:
            self.append_chat("MEMORY", "No saved memories.")
            return
        lines = [
            f"#{m['id']:<4} [{m['memory_type']:<10}] imp {m['importance']:>2}  {m['content']}"
            for m in mem
        ]
        self.append_chat("MEMORY", "<pre>" + "\n".join(lines) + "</pre>")

    def show_database(self):
        s = self.db.stats()
        lines = [
            f"Backend       : {database.ACTIVE_BACKEND}",
            f"{database.BACKEND_MESSAGE}",
            "",
            f"conversations : {s['conversations']}",
            f"messages      : {s['messages']}",
            f"memories      : {s['memories']}",
            f"tasks         : {s['tasks']}",
            f"tool_logs     : {s['tool_logs']}",
            "",
            "Recent tools:",
        ]
        for t in self.db.recent_tool_logs(8):
            lines.append(f"  {t['created_at']}  {t['tool_name']:<18} {t['status']}")
        self.append_chat("DATABASE", "<pre>" + "\n".join(lines) + "</pre>")

    def check_hotkey(self):
        # Reserved for a future global-hotkey backend.
        pass

    def closeEvent(self, event):
        try:
            self.voice.stop_background_listening()
        except Exception:
            pass
        self.db.close()
        event.accept()