import os

# ─────────────────────────────────────────────────
# MODEL CONFIGURATION
# ─────────────────────────────────────────────────
# To swap models, change only the values below.
# No other file needs to be touched.
#
# ORCHESTRATOR_MODEL — conversational model (Bron)
#   Confirmed working: llama3.2:3b
#   Alternatives: any chat-capable model in `ollama list`
#
# CODER_MODEL — specialist coding model
#   Confirmed working: qwen2.5-coder:3b
#   Alternatives: qwen2.5-coder:7b (better quality, more VRAM)
#
# Note: both models are called sequentially, never simultaneously.
# The orchestrator releases VRAM before the coder runs.
# See MODELS.md for full swap instructions.
# ───────────────────────────────────────────────── "llama3.2:3b"
ORCHESTRATOR_MODEL = "coney_/deepseek-r1_claude-sonnet4.6:latest"
CODER_MODEL = "qwen2.5-coder:3b"

# ─────────────────────────────────────────────────
# DIRECTORY REFERENCES
# ─────────────────────────────────────────────────
AGENT_DIR = os.path.join(os.path.expanduser("~"), "local_agent")
MEMORY_DIR = os.path.join(AGENT_DIR, "agent_memory")

# ─────────────────────────────────────────────────
# MEMORY FILE PATHS
# ─────────────────────────────────────────────────
USER_PROFILE_PATH = os.path.join(MEMORY_DIR, "user_profile.md")
PLAYBOOK_PATH = os.path.join(MEMORY_DIR, "playbook.md")
SESSION_NOTES_PATH = os.path.join(MEMORY_DIR, "session_notes.md")
PROJECTS_PATH = os.path.join(MEMORY_DIR, "projects.md")

# ─────────────────────────────────────────────────
# PIPELINE FILE PATHS
# ─────────────────────────────────────────────────
# Prompt dump: orchestrator writes → coder reads
PROMPT_DUMP_PATH = os.path.join(AGENT_DIR, "prompt_dump.json")

# Coder output: coder writes → orchestrator reads
CODER_OUTPUT_PATH = os.path.join(AGENT_DIR, "coder_output.txt")

# Sub-agent script path (used by Phase 5 to auto-invoke coder)
SUB_AGENT_SCRIPT = os.path.join(AGENT_DIR, "coder.py")

# ─────────────────────────────────────────────────
# OLLAMA API
# ─────────────────────────────────────────────────
OLLAMA_HOST = "http://localhost:11434"
