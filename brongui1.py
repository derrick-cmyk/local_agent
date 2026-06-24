#!/usr/bin/env python3
"""
Bron GUI - Tkinter interface for the local teaching assistant agent.
"""

import sys
import os
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox
from datetime import datetime

# Add current directory to path so we can import local modules
sys.path.insert(0, os.path.dirname(__file__))

# ----------------------------------------------------------------------
# Import agent components
# ----------------------------------------------------------------------
from config import (
    ORCHESTRATOR_MODEL
)
from memory import load_memory
from ollama_client import chat
from dump_writer import write_dump
from pipeline import (
    run_sub_agent, DUMP_SIGNAL, extract_summary_block, read_coder_output
)

# ----------------------------------------------------------------------
# GUI Application
# ----------------------------------------------------------------------

class BronGUI(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Bron Assistant")
        self.geometry("800x600")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # State
        self.messages = []          # conversation history (role+content)
        self.processing = False     # flag to prevent concurrent messages
        self.user_input = ""        # current input (for threading)

        # Load memory and build system prompt
        memory_text = load_memory()
        system_prompt = self._build_system_prompt(memory_text)
        self.messages.append({"role": "system", "content": system_prompt})

        # Build UI first, so status bar exists for the check
        self._build_ui()

        # Check if Ollama is accessible
        if self._check_ollama():
            # Show welcome message only if connection is successful
            self._display_message("System", "Bron is ready. How can I help you?\n")
        else:
            self.destroy() # Close the (hidden) window and exit if check fails

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        """Create the widgets."""
        # Main frame
        main_frame = tk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Chat display (scrollable)
        self.chat_display = scrolledtext.ScrolledText(
            main_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Consolas", 10),
            bg="#f5f5f5"
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Input frame
        input_frame = tk.Frame(main_frame)
        input_frame.pack(fill=tk.X, pady=(0, 5))

        self.entry = tk.Entry(input_frame, font=("Segoe UI", 10))
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.entry.bind("<Return>", self._on_enter)

        self.send_btn = tk.Button(
            input_frame,
            text="Send",
            command=self._on_send,
            width=8,
            font=("Segoe UI", 10)
        )
        self.send_btn.pack(side=tk.RIGHT)

        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        status_bar = tk.Label(
            self, textvariable=self.status_var, bd=1, relief=tk.SUNKEN,
            anchor=tk.W, font=("Segoe UI", 9)
        )
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # ------------------------------------------------------------------
    # Ollama Management
    # ------------------------------------------------------------------

    def _check_ollama(self) -> bool:
        """
        Check if the Ollama server is accessible.
        Returns True on success, False on failure.
        """
        self.status_var.set("Checking for Ollama...")
        try:
            import ollama
            # Use list() as it's a standard, lightweight way to check connection
            # without triggering model-not-found errors.
            ollama.list()
            self.status_var.set("Ollama connection successful.")
            return True
        except (ollama.RequestError, Exception) as e:
            # Hide the main window before showing the error dialog
            self.withdraw()
            messagebox.showerror(
                "Ollama Connection Error",
                "Could not connect to the Ollama server.\n\n"
                "Please ensure the Ollama application is running and then restart Bron."
            )
            return False
        except Exception as e:
            self.withdraw()
            messagebox.showerror("Fatal Error", f"An unexpected error occurred: {e}")
            return False

    # ------------------------------------------------------------------
    # Prompt Building
    # ------------------------------------------------------------------

    @staticmethod
    def _build_system_prompt(memory: str) -> str:
        return (
            "You are a local teaching assistant agent.\n\n"
            + memory
        )

    # ------------------------------------------------------------------
    # GUI Helpers (thread‑safe display)
    # ------------------------------------------------------------------

    def _display_message(self, sender: str, text: str):
        """Insert a message into the chat display (from main thread)."""
        self.chat_display.config(state=tk.NORMAL)
        if sender:
            self.chat_display.insert(tk.END, f"{sender}: ", ("bold",))
        self.chat_display.insert(tk.END, text + "\n")
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)

    def _set_status(self, text: str):
        """Update status bar (from main thread)."""
        self.status_var.set(text)

    def _enable_input(self, enabled: bool):
        """Enable/disable input widgets (from main thread)."""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.entry.config(state=state)
        self.send_btn.config(state=state)
        if enabled:
            self.entry.focus()

    # ------------------------------------------------------------------
    # Input Handlers
    # ------------------------------------------------------------------

    def _on_enter(self, event):
        self._on_send()

    def _on_send(self):
        if self.processing:
            return
        user_text = self.entry.get().strip()
        if not user_text:
            return

        # Clear entry and disable while processing
        self.entry.delete(0, tk.END)
        self._enable_input(False)
        self._set_status("Processing...")

        # Start worker thread
        threading.Thread(
            target=self._process_message,
            args=(user_text,),
            daemon=True
        ).start()

    # ------------------------------------------------------------------
    # Core Agent Logic (runs in worker thread)
    # ------------------------------------------------------------------

    def _process_message(self, user_text: str):
        """Handle a user message, call Ollama, and trigger sub‑agent if needed."""
        try:
            # 1. Append and display user message
            self.messages.append({"role": "user", "content": user_text})
            self.after(0, lambda: self._display_message("You", user_text))

            # 2. Get assistant response
            self.after(0, lambda: self._set_status("Thinking..."))
            response = chat(self.messages)
            self.messages.append({"role": "assistant", "content": response})

            # Display assistant response
            self.after(0, lambda: self._display_message("Bron", response))

            # 3. Check for coding task signal
            if DUMP_SIGNAL in response:
                self._handle_coding_task(response)

            # Done
            self.after(0, self._finish_processing)

        except Exception as e:
            error_msg = f"Error: {e}"
            self.after(0, lambda: self._display_message("System", error_msg))
            self.after(0, self._finish_processing)

    def _handle_coding_task(self, response: str):
        """Extract task summary, invoke coder, present result."""
        self.after(0, lambda: self._set_status("Preparing coding task..."))

        # Extract summary
        summary_block = extract_summary_block(response)
        dump_ok = write_dump(summary_block)
        if not dump_ok:
            self.after(0, lambda: self._display_message(
                "System", "Failed to write task dump. Coding skipped."
            ))
            return

        # Run coder sub‑agent
        self.after(0, lambda: self._set_status("Running coder (may take a moment)..."))
        coder_ok = run_sub_agent()  # This blocks

        if not coder_ok:
            self.after(0, lambda: self._display_message(
                "System", "Coder sub‑agent failed. See console for details."
            ))
            return

        # Read coder output and present
        self.after(0, lambda: self._set_status("Processing coder output..."))
        coder_result = read_coder_output()
        if coder_result is None:
            self.after(0, lambda: self._display_message(
                "System", "Coder output not found. Skipping presentation."
            ))
            return

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

        # Ask Bron to present the result
        self.messages.append({"role": "user", "content": presentation_instruction})
        self.after(0, lambda: self._set_status("Generating summary..."))
        summary_response = chat(self.messages)
        self.messages.append({"role": "assistant", "content": summary_response})

        # Display the summary
        self.after(0, lambda: self._display_message("Bron", summary_response))

    def _finish_processing(self):
        """Re‑enable input and reset status."""
        self.processing = False
        self._enable_input(True)
        self._set_status("Ready")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def on_closing(self):
        """Handle window close event."""
        self.destroy()

# ----------------------------------------------------------------------
# Entry Point
# ----------------------------------------------------------------------

if __name__ == "__main__":
    # Create the app but don't run mainloop if it's destroyed during init
    try:
        app = BronGUI()
        if app.winfo_exists():
            app.mainloop()
    except tk.TclError:
        # This can happen if the window is destroyed before mainloop starts
        pass