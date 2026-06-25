#!/usr/bin/env python3
"""
Bron Assistant – Tkinter interface with tabs, themes, settings, and PDF support.
Matches functionality of the updated PySide6 version.
"""

import sys
import os
import threading
import json
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk, filedialog
from pathlib import Path

# ----------------------------------------------------------------------
# Import agent modules (unchanged from original scripts)
# ----------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))

from config import ORCHESTRATOR_MODEL
from memory import load_memory
from ollama_client import chat  # must support stream=True and num_ctx
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
# Settings persistence (JSON file)
# ----------------------------------------------------------------------
SETTINGS_FILE = Path.home() / ".bron_assistant.json"

DEFAULT_SETTINGS = {
    "theme": "dark",
    "orch_model": ORCHESTRATOR_MODEL,
    "coder_model": CODER_MODEL,
    "verbose": False,
    "pdf_page_limit": 50,
    "geometry": "950x650+100+100"
}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
            return {**DEFAULT_SETTINGS, **data}
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"Could not save settings: {e}")


# ----------------------------------------------------------------------
# Main Application class
# ----------------------------------------------------------------------
class BronGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bron Assistant")

        # Prevent auto‑saves during startup
        self.loading = True

        # Load saved settings
        self.settings = load_settings()
        self.geometry(self.settings["geometry"])
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # State
        self.messages = []          # conversation history
        self.processing = False     # prevent concurrent messages
        self.ollama_connected = False
        self.latest_coder_output = "No coder output yet."
        self.stop_event = threading.Event()
        self.current_theme = self.settings["theme"]

        # Load system memory and build system prompt
        memory_text = load_memory()
        system_prompt = self._build_system_prompt(memory_text)
        self.messages.append({"role": "system", "content": system_prompt})

        # Build UI
        self._build_ui()
        self._apply_theme(self.current_theme)

        # Initial silent Ollama check
        self._update_ollama_status(silent=True)
        if self.ollama_connected:
            self._display_message("System", "Bron is ready. How can I help you?\n")
        else:
            self._on_enable_input(False)
            self._set_status("Disconnected – use Settings to connect")

        self.loading = False  # ready for user interaction

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        # Configure ttk style
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        # Top bar – notebook only
        top_bar = ttk.Frame(self, padding=(8, 5))
        top_bar.pack(fill=tk.X, side=tk.TOP)

        self.notebook = ttk.Notebook(top_bar)
        self.notebook.pack(side=tk.LEFT, fill=tk.Y)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        self.status_bar_label = ttk.Label(
            self, textvariable=self.status_var,
            relief=tk.SUNKEN, anchor=tk.W, padding=5
        )
        self.status_bar_label.pack(side=tk.BOTTOM, fill=tk.X)

        # ---- Tab 0: Chat ----
        chat_frame = ttk.Frame(self.notebook, padding=8)
        self._build_chat_tab(chat_frame)
        self.notebook.add(chat_frame, text="Chat")

        # ---- Tab 1: Coder Output ----
        coder_frame = ttk.Frame(self.notebook, padding=8)
        self._build_coder_tab(coder_frame)
        self.notebook.add(coder_frame, text="Coder Output")

        # ---- Tab 2: Settings ----
        settings_frame = ttk.Frame(self.notebook, padding=8)
        self._build_settings_tab(settings_frame)
        self.notebook.add(settings_frame, text="Settings")

        # ---- Tab 3: Help ----
        help_frame = ttk.Frame(self.notebook, padding=8)
        self._build_help_tab(help_frame)
        self.notebook.add(help_frame, text="?")

    def _build_chat_tab(self, parent):
        paned = tk.PanedWindow(parent, orient=tk.VERTICAL, sashrelief=tk.RAISED, sashwidth=5)
        paned.pack(fill=tk.BOTH, expand=True)

        # Chat display
        self.chat_display = scrolledtext.ScrolledText(
            paned, wrap=tk.WORD, state=tk.DISABLED,
            font=("Consolas", 10)
        )
        paned.add(self.chat_display, minsize=200, stretch="always")

        # Input area
        input_frame = ttk.Frame(paned, padding=(5, 5))
        paned.add(input_frame, minsize=80)

        self.entry = tk.Text(input_frame, wrap=tk.WORD, font=("Segoe UI", 10),
                             height=3, undo=True)
        self.entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        # Buttons sub‑frame (vertical)
        btn_subframe = ttk.Frame(input_frame)
        btn_subframe.pack(side=tk.RIGHT, fill=tk.Y)

        self.btn_upload = ttk.Button(btn_subframe, text="📄 Upload PDF",
                                     command=self.handle_pdf_upload)
        self.btn_upload.pack(pady=(0, 2))

        self.send_btn = ttk.Button(btn_subframe, text="Send", command=self._on_send)
        self.send_btn.pack(pady=2)

        self.stop_btn = ttk.Button(btn_subframe, text="🛑 Stop", command=self._on_stop)
        # Hidden initially, shown when processing
        self.stop_btn.pack(pady=2)
        self.stop_btn.pack_forget()

        # Bind keys
        self.entry.bind("<Control-Return>", lambda e: self._on_send())
        self.entry.bind("<Return>", self._on_enter_key)
        self.entry.bind("<Shift-Return>", lambda e: None)

    def _build_coder_tab(self, parent):
        self.coder_output_display = scrolledtext.ScrolledText(
            parent, wrap=tk.WORD, state=tk.DISABLED,
            font=("Consolas", 10)
        )
        self.coder_output_display.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._update_coder_display(self.latest_coder_output)

    def _build_settings_tab(self, parent):
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # --- Connection group ---
        conn_group = ttk.LabelFrame(scrollable_frame, text="Ollama Connection", padding=10)
        conn_group.pack(fill=tk.X, padx=10, pady=5)

        self.conn_status_label = ttk.Label(conn_group, text="Status: Unknown")
        self.conn_status_label.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_test_conn = ttk.Button(conn_group, text="Test Connection",
                                        command=self._manual_ollama_check)
        self.btn_test_conn.pack(side=tk.LEFT)

        # --- Model selection group ---
        model_group = ttk.LabelFrame(scrollable_frame, text="Model Selection", padding=10)
        model_group.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(model_group, text="Orchestrator Model:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.orch_combo = ttk.Combobox(model_group, state="readonly")
        self.orch_combo.grid(row=0, column=1, sticky=tk.EW, pady=2, padx=5)
        model_group.columnconfigure(1, weight=1)

        ttk.Label(model_group, text="Coder Model:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.coder_combo = ttk.Combobox(model_group, state="readonly")
        self.coder_combo.grid(row=1, column=1, sticky=tk.EW, pady=2, padx=5)

        self.btn_refresh_models = ttk.Button(model_group, text="Refresh Model List",
                                             command=self._populate_models)
        self.btn_refresh_models.grid(row=2, column=0, columnspan=2, pady=10)

        # Bind auto‑save on model change
        self.orch_combo.bind("<<ComboboxSelected>>", lambda e: self._save_settings())
        self.coder_combo.bind("<<ComboboxSelected>>", lambda e: self._save_settings())

        # --- PDF processing group ---
        pdf_group = ttk.LabelFrame(scrollable_frame, text="PDF Processing", padding=10)
        pdf_group.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(pdf_group, text="Page reading limit:").pack(side=tk.LEFT, padx=(0, 5))
        self.spin_pdf_limit = tk.Spinbox(pdf_group, from_=1, to=999, width=5,
                                         command=self._save_settings)
        self.spin_pdf_limit.pack(side=tk.LEFT)
        self.spin_pdf_limit.delete(0, tk.END)
        self.spin_pdf_limit.insert(0, str(self.settings.get("pdf_page_limit", 50)))
        # Bind to save when changed manually
        self.spin_pdf_limit.bind("<KeyRelease>", lambda e: self._save_settings())

        # --- Logging group ---
        log_group = ttk.LabelFrame(scrollable_frame, text="Logging", padding=10)
        log_group.pack(fill=tk.X, padx=10, pady=5)
        self.chk_verbose_var = tk.BooleanVar(value=self.settings.get("verbose", False))
        self.chk_verbose = ttk.Checkbutton(log_group, text="Verbose terminal output",
                                           variable=self.chk_verbose_var,
                                           command=self._save_settings)
        self.chk_verbose.pack(anchor=tk.W)

        # --- Appearance group ---
        theme_group = ttk.LabelFrame(scrollable_frame, text="Appearance", padding=10)
        theme_group.pack(fill=tk.X, padx=10, pady=5)

        self.theme_var = tk.StringVar(value=self.current_theme)
        ttk.Radiobutton(theme_group, text="Dark", variable=self.theme_var,
                        value="dark", command=lambda: self._switch_theme("dark")) \
            .pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(theme_group, text="Light", variable=self.theme_var,
                        value="light", command=lambda: self._switch_theme("light")) \
            .pack(side=tk.LEFT, padx=5)

        # --- Save button ---
        btn_frame = ttk.Frame(scrollable_frame)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        self.btn_save_settings = ttk.Button(btn_frame, text="Save Settings",
                                            command=self._save_settings)
        self.btn_save_settings.pack(side=tk.RIGHT)

        # Load initial model values
        self.orch_combo.set(self.settings["orch_model"])
        self.coder_combo.set(self.settings["coder_model"])
        self._populate_models(from_settings=True)

    def _build_help_tab(self, parent):
        help_text = (
            "How to use Bron\n\n"
            "• Chat: Type your message and press Enter or click Send.\n"
            "• Upload PDF: Click 'Upload PDF' to extract text and summarise.\n"
            "• Coder Output: When a coding task is requested, output appears here.\n"
            "• Settings: Configure Ollama connection, models, PDF limit, theme.\n"
            "• Splitter: Drag the bar between chat and input to resize.\n\n"
            "Keyboard shortcuts:\n"
            "  Enter = Send\n"
            "  Ctrl+Return = Send\n"
            "  Shift+Enter = newline\n"
        )
        help_label = ttk.Label(parent, text=help_text, wraplength=600,
                               justify=tk.LEFT, padding=20)
        help_label.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # Theme management (unchanged from previous version)
    # ------------------------------------------------------------------
    def _apply_theme(self, theme: str):
        self.current_theme = theme
        self.theme_var.set(theme)

        if theme == "dark":
            bg = "#2b2b2b"
            fg = "#cccccc"
            entry_bg = "#3a3a3a"
            entry_fg = "white"
            select_bg = "#1e90ff"
            btn_bg = "#3a3a3a"
            btn_fg = "white"
            btn_active_bg = "#1e90ff"
            tab_bg = "#3a3a3a"
            tab_fg = "#ccc"
            tab_selected_bg = "#2d2d2d"
            tab_selected_fg = "white"
            status_bg = "#1e1e1e"
            status_fg = "#aaa"
        else:
            bg = "#f0f0f0"
            fg = "#333333"
            entry_bg = "white"
            entry_fg = "black"
            select_bg = "#1e90ff"
            btn_bg = "#e0e0e0"
            btn_fg = "black"
            btn_active_bg = "#1e90ff"
            tab_bg = "#e0e0e0"
            tab_fg = "#333"
            tab_selected_bg = "#ffffff"
            tab_selected_fg = "black"
            status_bg = "#dddddd"
            status_fg = "#333"

        # Configure ttk styles
        self.style.configure("TFrame", background=bg)
        self.style.configure("TLabel", background=bg, foreground=fg)
        self.style.configure("TButton", background=btn_bg, foreground=btn_fg,
                             borderwidth=1, focusthickness=3, relief=tk.RAISED)
        self.style.map("TButton",
                       background=[("active", "#4a4a4a" if theme == "dark" else "#d0d0d0"),
                                   ("pressed", btn_active_bg),
                                   ("!disabled", btn_bg)],
                       foreground=[("active", btn_fg)])
        self.style.configure("TCombobox", fieldbackground=entry_bg, foreground=entry_fg,
                             background=entry_bg, selectbackground=select_bg,
                             selectforeground="white" if theme == "dark" else "black")
        self.style.map("TCombobox",
                       fieldbackground=[("readonly", entry_bg)],
                       foreground=[("readonly", entry_fg)])
        self.style.configure("TNotebook", background=bg, borderwidth=0)
        self.style.configure("TNotebook.Tab", background=tab_bg, foreground=tab_fg,
                             padding=[12, 4])
        self.style.map("TNotebook.Tab",
                       background=[("selected", tab_selected_bg)],
                       foreground=[("selected", tab_selected_fg)],
                       expand=[("selected", [1, 1, 1, 0])])
        self.style.configure("TLabelframe", background=bg, foreground=fg)
        self.style.configure("TLabelframe.Label", background=bg, foreground=fg)
        self.style.configure("TCheckbutton", background=bg, foreground=fg)
        self.style.configure("TRadiobutton", background=bg, foreground=fg)
        self.style.configure("TScrollbar", background=btn_bg, troughcolor=bg)
        self.style.configure("Vertical.TScrollbar", background=btn_bg)

        # ScrolledText widgets
        for widget in [self.chat_display, self.coder_output_display]:
            if widget.winfo_exists():
                widget.configure(bg=entry_bg, fg=entry_fg,
                                 insertbackground=entry_fg,
                                 selectbackground=select_bg,
                                 selectforeground="white" if theme == "dark" else "black")

        # Entry widget
        self.entry.configure(bg=entry_bg, fg=entry_fg,
                             insertbackground=entry_fg,
                             selectbackground=select_bg,
                             selectforeground="white" if theme == "dark" else "black")

        # Spinbox
        self.spin_pdf_limit.configure(bg=entry_bg, fg=entry_fg,
                                      insertbackground=entry_fg,
                                      selectbackground=select_bg,
                                      buttonbackground=btn_bg,
                                      readonlybackground=entry_bg)

        # Status bar
        self.status_bar_label.configure(background=status_bg, foreground=status_fg)

    def _switch_theme(self, theme: str):
        self._apply_theme(theme)
        self.settings["theme"] = theme
        self._save_settings()

    # ------------------------------------------------------------------
    # Ollama connection and models
    # ------------------------------------------------------------------
    def _test_ollama(self) -> tuple:
        try:
            import ollama
            ollama.list()
            return True, "Ollama is running"
        except Exception as e:
            return False, str(e)

    def _update_ollama_status(self, silent=False):
        self._print_verbose("Checking Ollama connection...")
        success, msg = self._test_ollama()
        self._print_verbose(f"Ollama connection result: {success}")
        self.ollama_connected = success

        status_text = "✅ Connected" if success else "❌ Disconnected"
        self.conn_status_label.config(text=f"Status: {status_text}",
                                      foreground="green" if success else "red")

        if success:
            self._set_status("Connected to Ollama")
            if not silent:
                messagebox.showinfo("Ollama Connection", f"Connection successful.\n\n{msg}")
        else:
            self._set_status("Disconnected – use Settings to connect")
            if not silent:
                messagebox.showerror("Ollama Connection",
                                     f"Could not connect to Ollama.\n\n{msg}")

    def _manual_ollama_check(self):
        self._update_ollama_status(silent=False)

    def _populate_models(self, from_settings=False):
        self._print_verbose("Refreshing Ollama model list...")
        if self.ollama_connected or not from_settings:
            try:
                import ollama
                response = ollama.list()
                if isinstance(response, dict):
                    models = [m["name"] for m in response.get("models", [])]
                else:
                    models = [m.model for m in response.models]
                self._print_verbose(f"Found {len(models)} models.")
            except Exception as e:
                self._print_verbose(f"Error fetching models: {e}")
                models = []
        else:
            models = []

        current_orch = self.orch_combo.get()
        current_coder = self.coder_combo.get()

        self.orch_combo['values'] = models
        self.coder_combo['values'] = models

        if current_orch in models:
            self.orch_combo.set(current_orch)
        elif models:
            self.orch_combo.set(models[0])
        else:
            self.orch_combo.set(ORCHESTRATOR_MODEL)

        if current_coder in models:
            self.coder_combo.set(current_coder)
        elif models:
            self.coder_combo.set(models[0])
        else:
            self.coder_combo.set(CODER_MODEL)

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------
    def _save_settings(self):
        if self.loading:
            return
        try:
            self.settings["orch_model"] = self.orch_combo.get().strip()
            self.settings["coder_model"] = self.coder_combo.get().strip()
            self.settings["verbose"] = self.chk_verbose_var.get()
            self.settings["pdf_page_limit"] = int(self.spin_pdf_limit.get())
            self.settings["theme"] = self.current_theme
            self.settings["geometry"] = self.geometry()
            save_settings(self.settings)
            self._set_status("Settings saved.")
            self._print_verbose("Settings saved to file.")
        except Exception:
            pass  # ignore save errors during early init

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _print_verbose(self, msg: str):
        if self.chk_verbose_var.get():
            print(f"[BronGUI] {msg}")

    @staticmethod
    def _build_system_prompt(memory: str) -> str:
        return "You are a local teaching assistant agent.\n\n" + memory

    def _display_message(self, sender: str, text: str):
        """Insert a message with bold sender."""
        def _insert():
            self.chat_display.config(state=tk.NORMAL)
            if sender:
                self.chat_display.insert(tk.END, f"{sender}: ", ("bold",))
            self.chat_display.insert(tk.END, text + "\n")
            self.chat_display.see(tk.END)
            self.chat_display.config(state=tk.DISABLED)
        self.after(0, _insert)

    def _display_stream_chunk(self, chunk: str):
        """Append text to the current line (for streaming)."""
        def _insert():
            self.chat_display.config(state=tk.NORMAL)
            self.chat_display.insert(tk.END, chunk)
            self.chat_display.see(tk.END)
            self.chat_display.config(state=tk.DISABLED)
        self.after(0, _insert)

    def _set_status(self, text: str):
        self.after(0, lambda: self.status_var.set(text))

    def _on_enable_input(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.entry.config(state=state)
        self.btn_upload.config(state=state)
        if enabled:
            self.entry.focus_set()
            self.send_btn.pack(pady=2)
            self.stop_btn.pack_forget()
        else:
            self.send_btn.pack_forget()
            self.stop_btn.pack(pady=2)

    def _update_coder_display(self, text: str):
        self.coder_output_display.config(state=tk.NORMAL)
        self.coder_output_display.delete(1.0, tk.END)
        self.coder_output_display.insert(tk.END, text)
        self.coder_output_display.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------
    def _on_enter_key(self, event):
        if not event.state & 0x1:  # Shift not pressed
            self._on_send()
            return "break"
        return None

    def _on_send(self):
        if self.processing or not self.ollama_connected:
            return
        user_text = self.entry.get("1.0", tk.END).strip()
        if not user_text:
            return

        self.entry.delete("1.0", tk.END)
        self._on_enable_input(False)
        self._set_status("Processing...")

        threading.Thread(
            target=self._process_message,
            args=(user_text,),
            daemon=True
        ).start()

    def _on_stop(self):
        if self.processing:
            self._print_verbose("Stop requested by user.")
            self.stop_event.set()
            self._set_status("Stopping...")
            self.stop_btn.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # PDF handling
    # ------------------------------------------------------------------
    def handle_pdf_upload(self):
        file_path = filedialog.askopenfilename(
            title="Select PDF", filetypes=[("PDF Files", "*.pdf")]
        )
        if file_path:
            self._print_verbose(f"Uploading PDF: {file_path}")
            self._set_status("Extracting PDF text...")
            self._on_enable_input(False)
            threading.Thread(target=self.process_pdf_file, args=(file_path,), daemon=True).start()

    def process_pdf_file(self, file_path):
        try:
            import PyPDF2
            text = ""
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                num_pages = len(reader.pages)
                limit = int(self.spin_pdf_limit.get())
                pages_to_read = min(num_pages, limit)

                if num_pages > limit:
                    self._print_verbose(f"PDF has {num_pages} pages, limiting to {limit}.")

                for i in range(pages_to_read):
                    text += reader.pages[i].extract_text() + "\n"

            filename = os.path.basename(file_path)

            # Show upload notice
            self.after(0, lambda: self._display_message("You", f"Uploaded PDF: {filename}"))

            # Add document to system context
            system_msg = f"DOCUMENT PROVIDED: {filename}\nCONTENT:\n{text}"
            self.messages.append({"role": "system", "content": system_msg})

            summary_request = (
                f"Please provide a comprehensive summary of the document '{filename}' "
                "I just uploaded."
            )

            # Trigger message processing with large context window
            self._process_message(summary_request, num_ctx=32768)

        except Exception as e:
            self.after(0, lambda: self._display_message("System", f"Failed to read PDF: {e}"))
            self._finish_processing()

    # ------------------------------------------------------------------
    # Core agent logic (worker thread)
    # ------------------------------------------------------------------
    def _process_message(self, user_text: str, num_ctx=32768):
        try:
            self.processing = True
            self.stop_event.clear()
            self._print_verbose(f"Processing message (context: {num_ctx})...")

            # Update config with chosen models
            import config
            config.ORCHESTRATOR_MODEL = self.orch_combo.get().strip()
            config.CODER_MODEL = self.coder_combo.get().strip()

            # Avoid duplicate user message (e.g., after PDF upload)
            if not any(m["role"] == "user" and m["content"] == user_text
                       for m in self.messages[-2:]):
                self.messages.append({"role": "user", "content": user_text})
                self.after(0, lambda: self._display_message("You", user_text))

            self._set_status("Thinking...")
            self._print_verbose("Calling orchestrator model (streaming)...")

            # Start Bron's message line
            self.after(0, lambda: self._display_message("Bron", ""))

            full_response = ""
            stream = chat(self.messages, stream=True, num_ctx=num_ctx,
                          model=self.orch_combo.get().strip())

            for chunk in stream:
                if self.stop_event.is_set():
                    self._print_verbose("Stream interrupted by stop event.")
                    full_response += " [CANCELLED]"
                    self.after(0, lambda: self._display_stream_chunk(" [CANCELLED]"))
                    break

                token = chunk["message"]["content"]
                full_response += token
                self.after(0, lambda t=token: self._display_stream_chunk(t))

            self._print_verbose("Received full orchestrator response.")
            self.messages.append({"role": "assistant", "content": full_response})

            if not self.stop_event.is_set() and DUMP_SIGNAL in full_response:
                self._handle_coding_task(full_response, num_ctx=8192)

            self._finish_processing()

        except Exception as e:
            if self.stop_event.is_set():
                self._print_verbose("Process interrupted gracefully.")
            else:
                self.after(0, lambda: self._display_message("System", f"Error: {e}"))
            self._finish_processing()

    def _handle_coding_task(self, response: str, num_ctx=8192):
        self._print_verbose("Coding task signal detected. Preparing dump...")
        self._set_status("Preparing coding task...")
        summary_block = extract_summary_block(response)
        dump_ok = write_dump(summary_block, coder_model=self.coder_combo.get().strip())
        if not dump_ok:
            self._print_verbose("Failed to write prompt dump.")
            self.after(0, lambda: self._display_message(
                "System", "Failed to write task dump. Coding skipped."))
            return

        self._print_verbose("Dispatching sub-agent process...")
        self._set_status("Running coder (may take a moment)...")
        coder_ok = run_sub_agent(coder_model=self.coder_combo.get().strip())
        if not coder_ok:
            self._print_verbose("Sub-agent process returned an error.")
            self.after(0, lambda: self._display_message(
                "System", "Coder sub‑agent failed. See console for details."))
            return

        self._print_verbose("Sub-agent completed. Fetching output...")
        self._set_status("Processing coder output...")
        coder_result = read_coder_output()
        if coder_result is None:
            self.after(0, lambda: self._display_message(
                "System", "Coder output not found. Skipping presentation."))
            return

        self.latest_coder_output = coder_result
        self.after(0, lambda: self._update_coder_display(coder_result))

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
        self._set_status("Generating summary...")
        summary_response = chat(self.messages, num_ctx=num_ctx,
                                model=self.orch_combo.get().strip())
        self.messages.append({"role": "assistant", "content": summary_response})
        self.after(0, lambda: self._display_message("Bron", summary_response))

    def _finish_processing(self):
        self.processing = False
        self._on_enable_input(True)
        self._set_status("Ready")
        self.stop_event.clear()

    # ------------------------------------------------------------------
    # Window close
    # ------------------------------------------------------------------
    def on_closing(self):
        self._save_settings()
        self.destroy()


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = BronGUI()
    app.mainloop()