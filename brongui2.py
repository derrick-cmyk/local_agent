#!/usr/bin/env python3
"""
Bron Assistant – Polished PySide6 interface with tabs, themes, and settings.
"""

import sys
import os
import threading
import json

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTextEdit, QLineEdit, QPushButton, QStatusBar,
    QTabBar, QStackedWidget, QGroupBox, QFormLayout, QComboBox,
    QLabel, QDialogButtonBox, QMessageBox, QFileDialog, QProgressBar,
    QScrollArea, QFrame, QCheckBox
)
from PySide6.QtCore import Signal, Qt, QSettings, QSize
from PySide6.QtGui import QFont, QColor, QPalette

# ----------------------------------------------------------------------
# Import agent modules (unchanged)
# ----------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))

from config import ORCHESTRATOR_MODEL
from memory import load_memory
from ollama_client import chat
from dump_writer import write_dump
from pipeline import (
    run_sub_agent, DUMP_SIGNAL, extract_summary_block, read_coder_output
)

# Ensure a default coder model exists
try:
    from config import CODER_MODEL
except ImportError:
    CODER_MODEL = "codellama"
    import config
    config.CODER_MODEL = CODER_MODEL


# ----------------------------------------------------------------------
# Custom widgets
# ----------------------------------------------------------------------
class ChatInputEdit(QTextEdit):
    def __init__(self, send_callback, parent=None):
        super().__init__(parent)
        self.send_callback = send_callback

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return and not event.modifiers() & Qt.ShiftModifier:
            self.send_callback()
            event.accept()
        else:
            super().keyPressEvent(event)

# ----------------------------------------------------------------------
# Application class
# ----------------------------------------------------------------------
class BronApp(QMainWindow):
    # Thread‑safe signals
    display_message = Signal(str, str)     # sender, text
    set_status = Signal(str)               # status bar message
    enable_input = Signal(bool)            # enable/disable input
    store_coder_output = Signal(str)       # update coder output tab

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bron Assistant")
        self.resize(950, 650)

        # State
        self.messages = []                  # conversation history
        self.processing = False
        self.ollama_connected = False
        self.latest_coder_output = "No coder output yet."

        # Load system memory
        memory_text = load_memory()
        system_prompt = self._build_system_prompt(memory_text)
        self.messages.append({"role": "system", "content": system_prompt})

        # Theme (default dark)
        self.current_theme = "dark"

        # Build UI
        self._setup_ui()
        self._connect_signals()
        self._load_settings()
        self._apply_theme(self.current_theme)

        # Silent initial Ollama check
        self._update_ollama_status(silent=True)
        if self.ollama_connected:
            self.display_message.emit("System", "Bron is ready. How can I help you?\n")

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Top bar: tab bar + connect button + view coder output button
        top_bar = QHBoxLayout()
        self.tab_bar = QTabBar()
        self.tab_bar.addTab("Chat")
        self.tab_bar.addTab("Coder Output")
        self.tab_bar.addTab("Settings")
        self.tab_bar.addTab("?")
        top_bar.addWidget(self.tab_bar)

        top_bar.addStretch()
        self.btn_connect = QPushButton("🔗 Connect")
        self.btn_connect.clicked.connect(self._manual_ollama_check)
        self.btn_view_coder = QPushButton("📋 View Coder Output")
        self.btn_view_coder.clicked.connect(lambda: self.tab_bar.setCurrentIndex(1))
        top_bar.addWidget(self.btn_connect)
        top_bar.addWidget(self.btn_view_coder)
        main_layout.addLayout(top_bar)

        # Stacked content for tabs
        self.content_stack = QStackedWidget()
        main_layout.addWidget(self.content_stack, 1)

        # ---- Tab 0: Chat ----
        chat_tab = QWidget()
        chat_layout = QVBoxLayout(chat_tab)
        chat_layout.setContentsMargins(0, 0, 0, 0)

        # Splitter between conversation and input
        splitter = QSplitter(Qt.Vertical)

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setFont(QFont("Consolas", 10))
        splitter.addWidget(self.chat_display)

        input_widget = QWidget()
        input_layout = QHBoxLayout(input_widget)
        input_layout.setContentsMargins(0, 0, 0, 0)
        self.entry = ChatInputEdit(self._on_send)
        self.entry.setFont(QFont("Segoe UI", 10))
        self.entry.setMaximumHeight(80)
        input_layout.addWidget(self.entry)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(self.send_btn)
        splitter.addWidget(input_widget)
        splitter.setSizes([400, 150])
        chat_layout.addWidget(splitter)

        self.content_stack.addWidget(chat_tab)

        # ---- Tab 1: Coder Output ----
        coder_tab = QWidget()
        coder_layout = QVBoxLayout(coder_tab)
        coder_layout.setContentsMargins(10, 10, 10, 10)
        self.coder_output_display = QTextEdit()
        self.coder_output_display.setReadOnly(True)
        self.coder_output_display.setFont(QFont("Consolas", 10))
        self.coder_output_display.setPlainText(self.latest_coder_output)
        coder_layout.addWidget(self.coder_output_display)
        self.content_stack.addWidget(coder_tab)

        # ---- Tab 2: Settings ----
        settings_tab = QScrollArea()
        settings_tab.setWidgetResizable(True)
        settings_content = QWidget()
        settings_layout = QVBoxLayout(settings_content)
        settings_layout.setSpacing(15)

        # Ollama connection group
        conn_group = QGroupBox("Ollama Connection")
        conn_layout = QFormLayout(conn_group)
        self.btn_test_conn = QPushButton("Test Connection")
        self.btn_test_conn.clicked.connect(self._manual_ollama_check)
        self.conn_status_label = QLabel("Status: Unknown")
        conn_layout.addRow(self.btn_test_conn, self.conn_status_label)
        settings_layout.addWidget(conn_group)

        # Model selection group
        model_group = QGroupBox("Model Selection")
        model_layout = QFormLayout(model_group)

        self.orch_combo = QComboBox()
        self.orch_combo.setEditable(True)
        model_layout.addRow("Orchestrator Model:", self.orch_combo)

        self.coder_combo = QComboBox()
        self.coder_combo.setEditable(True)
        model_layout.addRow("Coder Model:", self.coder_combo)

        self.btn_refresh_models = QPushButton("Refresh Model List")
        self.btn_refresh_models.clicked.connect(self._populate_models)
        model_layout.addRow(self.btn_refresh_models)
        settings_layout.addWidget(model_group)

        # Logging group
        log_group = QGroupBox("Logging")
        log_layout = QHBoxLayout(log_group)
        self.chk_verbose = QCheckBox("Verbose terminal output")
        log_layout.addWidget(self.chk_verbose)
        log_layout.addStretch()
        settings_layout.addWidget(log_group)

        # Theme toggle
        theme_group = QGroupBox("Appearance")
        theme_layout = QHBoxLayout(theme_group)
        self.btn_dark = QPushButton("Dark")
        self.btn_dark.setCheckable(True)
        self.btn_light = QPushButton("Light")
        self.btn_light.setCheckable(True)
        self.btn_dark.toggled.connect(lambda checked: checked and self._switch_theme("dark"))
        self.btn_light.toggled.connect(lambda checked: checked and self._switch_theme("light"))
        theme_layout.addWidget(self.btn_dark)
        theme_layout.addWidget(self.btn_light)
        theme_layout.addStretch()
        settings_layout.addWidget(theme_group)

        # Save settings button
        btn_layout = QHBoxLayout()
        self.btn_save_settings = QPushButton("Save Settings")
        self.btn_save_settings.clicked.connect(self._save_settings)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save_settings)
        settings_layout.addLayout(btn_layout)

        settings_layout.addStretch()
        settings_tab.setWidget(settings_content)
        self.content_stack.addWidget(settings_tab)

        # ---- Tab 3: Help ----
        help_tab = QScrollArea()
        help_tab.setWidgetResizable(True)
        help_content = QWidget()
        help_layout = QVBoxLayout(help_content)
        help_layout.setContentsMargins(20, 20, 20, 20)
        help_label = QLabel(
            "<h2>How to use Bron</h2>"
            "<ul>"
            "<li><b>Chat</b>: Type your question and press Enter or click Send. The assistant will respond.</li>"
            "<li><b>Coder Output</b>: When a coding task is requested, the sub‑agent output will appear here.</li>"
            "<li><b>Settings</b>: Test the Ollama connection and choose which AI models to use.</li>"
            "<li><b>Connect button</b> (top‑right): Quickly test the Ollama connection.</li>"
            "<li><b>Splitter</b>: Drag to resize the chat/input areas.</li>"
            "</ul>"
            "<p>Keyboard shortcuts: Enter = Send, Ctrl+Return = Send, Ctrl+R = Run (if applicable).</p>"
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("font-size: 14px; line-height: 1.5;")
        help_layout.addWidget(help_label)
        help_layout.addStretch()
        help_tab.setWidget(help_content)
        self.content_stack.addWidget(help_tab)

        # Synchronise tab bar with content stack
        self.tab_bar.currentChanged.connect(self.content_stack.setCurrentIndex)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # Initially disable input until connected
        self._on_enable_input(False)

    def _connect_signals(self):
        self.display_message.connect(self._on_display_message)
        self.set_status.connect(self._on_set_status)
        self.enable_input.connect(self._on_enable_input)
        self.store_coder_output.connect(self._on_store_coder_output)

    # ------------------------------------------------------------------
    # Theme management
    # ------------------------------------------------------------------
    def _apply_theme(self, theme):
        self.current_theme = theme
        self.btn_dark.setChecked(theme == "dark")
        self.btn_light.setChecked(theme == "light")

        dark_stylesheet = """
            QMainWindow, QDialog, QMessageBox { background-color: #2b2b2b; }
            QLabel { color: #cccccc; }
            QPushButton {
                background-color: #3a3a3a; border: none; border-radius: 6px;
                padding: 8px 15px; color: white; font-weight: bold;
            }
            QPushButton:hover { background-color: #4a4a4a; }
            QPushButton:checked { background-color: #1e90ff; color: white; }
            QLineEdit, QTextEdit, QComboBox {
                background-color: #3a3a3a; selection-background-color: #1e90ff;
                border: 1px solid #555; border-radius: 4px; padding: 5px; color: white;
            }
            QComboBox QAbstractItemView { background-color: #3a3a3a; color: white; }
            QGroupBox { color: #aaa; border: 1px solid #555; border-radius: 6px; margin-top: 10px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }
            QTabBar::tab {
                background: #3a3a3a; color: #ccc; padding: 8px 18px; margin-right: 3px;
                border-top-left-radius: 6px; border-top-right-radius: 6px;
            }
            QTabBar::tab:selected { background: #2d2d2d; color: white; border-bottom: 2px solid #1e90ff; }
            QScrollArea, QScrollArea > QWidget { background-color: #2b2b2b; }
            QStatusBar { background-color: #1e1e1e; color: #aaa; }
        """
        light_stylesheet = """
            QMainWindow, QDialog, QMessageBox { background-color: #f0f0f0; }
            QLabel { color: #333333; }
            QPushButton {
                background-color: #e0e0e0; border: none; border-radius: 6px;
                padding: 8px 15px; color: black; font-weight: bold;
            }
            QPushButton:hover { background-color: #d0d0d0; }
            QPushButton:checked { background-color: #1e90ff; color: white; }
            QLineEdit, QTextEdit, QComboBox {
                background-color: white; selection-background-color: #1e90ff;
                border: 1px solid #aaa; border-radius: 4px; padding: 5px; color: black;
            }
            QComboBox QAbstractItemView { background-color: white; color: black; }
            QGroupBox { color: #333; border: 1px solid #aaa; border-radius: 6px; margin-top: 10px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }
            QTabBar::tab {
                background: #e0e0e0; color: #333; padding: 8px 18px; margin-right: 3px;
                border-top-left-radius: 6px; border-top-right-radius: 6px;
            }
            QTabBar::tab:selected { background: #ffffff; color: black; border-bottom: 2px solid #1e90ff; }
            QScrollArea, QScrollArea > QWidget { background-color: #f0f0f0; }
            QStatusBar { background-color: #dddddd; color: #333; }
        """
        self.setStyleSheet(dark_stylesheet if theme == "dark" else light_stylesheet)

    def _switch_theme(self, theme):
        self._apply_theme(theme)
        self._save_settings()

    def _print_verbose(self, msg: str):
        if hasattr(self, 'chk_verbose') and self.chk_verbose.isChecked():
            print(f"[BronGUI] {msg}")

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------
    def _load_settings(self):
        settings = QSettings("BronAssistant", "GUI")
        self.current_theme = settings.value("theme", "dark")
        self._apply_theme(self.current_theme)

        # Restore verbose
        verbose_val = settings.value("verbose", False)
        # Handle string "true"/"false" from ini files
        if isinstance(verbose_val, str):
            verbose_val = verbose_val.lower() == "true"
        self.chk_verbose.setChecked(bool(verbose_val))

        # Restore models
        try:
            self.orch_combo.setCurrentText(settings.value("orch_model", ORCHESTRATOR_MODEL))
        except:
            self.orch_combo.setCurrentText(ORCHESTRATOR_MODEL)
        try:
            self.coder_combo.setCurrentText(settings.value("coder_model", CODER_MODEL))
        except:
            self.coder_combo.setCurrentText(CODER_MODEL)

        # Restore window geometry
        geom = settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)

        # Populate model lists (may be empty if offline; we'll handle later)
        self._populate_models()

    def _save_settings(self):
        settings = QSettings("BronAssistant", "GUI")
        settings.setValue("theme", self.current_theme)
        settings.setValue("orch_model", self.orch_combo.currentText().strip())
        settings.setValue("coder_model", self.coder_combo.currentText().strip())
        settings.setValue("verbose", self.chk_verbose.isChecked())
        settings.setValue("geometry", self.saveGeometry())

    # ------------------------------------------------------------------
    # Ollama connection and model management
    # ------------------------------------------------------------------
    def _test_ollama(self):
        """Return (success, message) without popups."""
        try:
            import ollama
            ollama.list()
            return True, "Ollama is running"
        except Exception as e:
            return False, str(e)

    def _update_ollama_status(self, silent=False):
        """Test connection and update UI state."""
        self._print_verbose("Checking Ollama connection...")
        success, msg = self._test_ollama()
        self._print_verbose(f"Ollama connection result: {success}")
        self.ollama_connected = success
        self.conn_status_label.setText(f"Status: {'✅ Connected' if success else '❌ Disconnected'}")
        self.conn_status_label.setStyleSheet(
            f"color: {'green' if success else 'red'};"
        )
        self.enable_input.emit(success)
        if success:
            self.status_bar.showMessage("Connected to Ollama")
        else:
            self.status_bar.showMessage("Disconnected – use Settings to connect")
            if not silent:
                QMessageBox.warning(self, "Ollama Connection", f"Could not connect.\n\n{msg}")

    def _manual_ollama_check(self):
        """Called from the Connect button or Settings."""
        self._update_ollama_status(silent=False)

    def _populate_models(self):
        """Fetch models from Ollama and fill combos."""
        self._print_verbose("Refreshing Ollama model list...")
        try:
            import ollama
            response = ollama.list()
            # Handle both older dictionaries and modern ListResponse objects
            if isinstance(response, dict):
                models = [m["name"] for m in response.get("models", [])]
            else:
                models = [m.model for m in response.models]
            self._print_verbose(f"Found {len(models)} models.")
        except Exception as e:
            self._print_verbose(f"Error fetching models: {e}")
            models = []

        current_orch = self.orch_combo.currentText()
        current_coder = self.coder_combo.currentText()
        self.orch_combo.clear()
        self.coder_combo.clear()

        if models:
            self.orch_combo.addItems(models)
            self.coder_combo.addItems(models)
        else:
            # Fallback: keep current text editable
            self.orch_combo.setEditText(current_orch)
            self.coder_combo.setEditText(current_coder)

        if current_orch:
            self.orch_combo.setCurrentText(current_orch)
        else:
            self.orch_combo.setCurrentText(ORCHESTRATOR_MODEL)
        if current_coder:
            self.coder_combo.setCurrentText(current_coder)
        else:
            self.coder_combo.setCurrentText(CODER_MODEL)

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------
    @staticmethod
    def _build_system_prompt(memory: str) -> str:
        return "You are a local teaching assistant agent.\n\n" + memory

    # ------------------------------------------------------------------
    # Slots for thread‑safe GUI updates
    # ------------------------------------------------------------------
    def _on_display_message(self, sender: str, text: str):
        self.chat_display.append(f"{sender}: {text}")

    def _on_set_status(self, text: str):
        self.status_bar.showMessage(text)

    def _on_enable_input(self, enabled: bool):
        self.entry.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        if enabled:
            self.entry.setFocus()

    def _on_store_coder_output(self, output: str):
        self.latest_coder_output = output
        self.coder_output_display.setPlainText(output)

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------
    def _on_send(self):
        if self.processing or not self.ollama_connected:
            return
        user_text = self.entry.toPlainText().strip()
        if not user_text:
            return

        self.entry.clear()
        self._on_enable_input(False)
        self.set_status.emit("Processing...")

        threading.Thread(
            target=self._process_message,
            args=(user_text,),
            daemon=True
        ).start()

    # ------------------------------------------------------------------
    # Core agent logic (unchanged from original)
    # ------------------------------------------------------------------
    def _process_message(self, user_text: str):
        try:
            self._print_verbose("Processing user message...")
            # Update model choices before call (in case changed)
            import config
            config.ORCHESTRATOR_MODEL = self.orch_combo.currentText().strip()
            config.CODER_MODEL = self.coder_combo.currentText().strip()
            self._print_verbose(f"Set orchestrator to {config.ORCHESTRATOR_MODEL}, coder to {config.CODER_MODEL}")

            self.messages.append({"role": "user", "content": user_text})
            self.display_message.emit("You", user_text)

            self.set_status.emit("Thinking...")
            self._print_verbose("Calling orchestrator model...")
            response = chat(self.messages)
            self._print_verbose("Received orchestrator response.")
            self.messages.append({"role": "assistant", "content": response})
            self.display_message.emit("Bron", response)

            if DUMP_SIGNAL in response:
                self._handle_coding_task(response)

            self._finish_processing()

        except Exception as e:
            self.display_message.emit("System", f"Error: {e}")
            self._finish_processing()

    def _handle_coding_task(self, response: str):
        self._print_verbose("Coding task signal detected. Preparing dump...")
        self.set_status.emit("Preparing coding task...")
        summary_block = extract_summary_block(response)
        dump_ok = write_dump(summary_block)
        if not dump_ok:
            self._print_verbose("Failed to write prompt dump.")
            self.display_message.emit("System", "Failed to write task dump. Coding skipped.")
            return

        self._print_verbose("Dispatching sub-agent process...")
        self.set_status.emit("Running coder (may take a moment)...")
        coder_ok = run_sub_agent()
        if not coder_ok:
            self._print_verbose("Sub-agent process returned an error.")
            self.display_message.emit("System", "Coder sub‑agent failed. See console for details.")
            return

        self._print_verbose("Sub-agent completed. Fetching output...")
        self.set_status.emit("Processing coder output...")
        coder_result = read_coder_output()
        if coder_result is None:
            self.display_message.emit("System", "Coder output not found. Skipping presentation.")
            return

        # Store and display coder output
        self.store_coder_output.emit(coder_result)

        presentation_instruction = (
            "The coding sub‑agent has finished. Here is its output:\n\n"
            "```\n"
            f"{coder_result}\n"
            "```\n\n"
            "Please do the following:\n"
            "1. Summarise what was produced in 2-3 sentences in plain language.\n"
            "2. Note any obvious issues, limitations, or things the user should be aware of.\n"
            "3. Tell the user the full output is saved to coder_output.txt in the project folder.\n"
            "4. Invite the user to ask follow‑up questions or request revisions."
        )

        self.messages.append({"role": "user", "content": presentation_instruction})
        self.set_status.emit("Generating summary...")
        summary_response = chat(self.messages)
        self.messages.append({"role": "assistant", "content": summary_response})
        self.display_message.emit("Bron", summary_response)

    def _finish_processing(self):
        self.processing = False
        self.enable_input.emit(True)
        self.set_status.emit("Ready")

    # ------------------------------------------------------------------
    # Window close
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        self._save_settings()
        super().closeEvent(event)


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BronApp()
    window.show()
    sys.exit(app.exec())