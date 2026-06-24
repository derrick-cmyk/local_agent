# Local AI Agent — Changelog

> **Note:** This changelog documents every file change across each phase of the build.
> It is intentionally written as a **reusable guide** — if you are setting up a new local agent
> from scratch, follow the phases in order, applying the file changes described here to your
> own project folder. The structure (orchestrator → dump → specialist → presentation) is
> agent-agnostic and can be adapted to any Ollama-based pipeline.

---

## Phase 1 — Orchestrator + Memory

**Files created:**
- `main.py` — main conversation loop; loads memory, builds system prompt, calls Ollama
- `config.py` — central config (model name, memory file paths)
- `memory.py` — `load_memory()` reads `user_profile.md` and `playbook.md` and injects them into the system prompt
- `ollama_client.py` — thin wrapper around `ollama.chat()` using `ORCHESTRATOR_MODEL`
- `agent_memory/user_profile.md` — user identity file read at startup
- `agent_memory/playbook.md` — orchestrator behavioural rules (Phase 1: basic assistant rules)

**What it does:**
The orchestrator (Bron on `llama3.2:3b`) starts up, reads memory from disk, and holds a persistent conversation in the terminal.

---

## Phase 2 — Task Detection and Clarification

**Files modified:**
- `agent_memory/playbook.md` — added Phase 2 coding task detection protocol:
  - Step 0: detect if request is a coding task or not
  - Step 1: gather 5 context items one question at a time (language, task type, scope, existing code, constraints)
  - Step 2: produce structured `CODING TASK DETECTED` summary block with `STATUS: READY_FOR_CODER`
  - Step 3: refuse to write code directly
  - Hallucination prevention rules added

**What it does:**
Bron detects coding requests, asks clarifying questions one at a time, then produces a structured plain-text task summary. No code is generated at this stage.

---

## Phase 3 — Prompt Dump System

**Files created:**
- `dump_writer.py` — three functions:
  - `parse_task_summary(text)` — regex parses the orchestrator's plain-text summary into a dict
  - `write_dump(text)` — validates required fields, writes `prompt_dump.json`
  - `read_dump()` — reads and returns the dump as a dict, or `None` if missing/malformed

**Files modified:**
- `config.py` — rewrote with clean `os.path.join` paths; added `AGENT_DIR`, `PROMPT_DUMP_PATH`, `SESSION_NOTES_PATH`, `PROJECTS_PATH`, `OLLAMA_HOST`
- `main.py` — added `DUMP_SIGNAL = "DUMP_READY"`, `extract_summary_block()`, and DUMP_READY detection in the chat loop; calls `write_dump()` automatically when signal seen
- `agent_memory/playbook.md` — replaced old STATUS line with `STATUS: READY_FOR_CODER`; added mandatory `DUMP_READY` signal instruction after the task summary block

**Runtime artifact created:**
- `prompt_dump.json` — fixed-path JSON file written after every flagged coding task; overwritten each run

**What it does:**
When the orchestrator outputs `DUMP_READY`, `main.py` extracts the summary block and writes it to `prompt_dump.json` with all 8 fields: `task_id`, `language`, `task_type`, `output_scope`, `existing_code`, `constraints`, `user_request`, `status`.

---

## Phase 4 — Coder Sub-Agent

**Files created:**
- `coder.py` — standalone sub-agent script:
  - Reads `prompt_dump.json` via `read_dump()`
  - Validates `status == READY_FOR_CODER` and required fields; exits cleanly on failure
  - Builds a structured coding prompt from dump fields
  - Calls `qwen2.5-coder:3b` via Ollama
  - Writes result to `coder_output.txt` with a task header (task_id, language, type, scope)
- `MODELS.md` — guide for swapping and adding models; see below
- `Changelog.md` — this file

**Files modified:**
- `config.py` — added `CODER_MODEL`, `CODER_OUTPUT_PATH`, `SUB_AGENT_SCRIPT`; added inline model-swap comments

**Runtime artifact created:**
- `coder_output.txt` — fixed-path text file written after each coder run; overwritten each run

**What it does:**
`python coder.py` reads the dump, generates code with the coder model, and saves output to disk. The orchestrator is not involved — models run sequentially to avoid VRAM conflicts.

---

## Phase 5 — Full Pipeline Connected

**Files created:**
- `run_pipeline.bat` — Windows single-command launcher; `cd`s to the project folder and runs `python main.py`

**Files modified:**
- `main.py` — added:
  - `run_sub_agent()` — invokes `coder.py` via `subprocess.run()` (blocking); returns success bool
  - `present_sub_agent_result(messages)` — reads `coder_output.txt`, passes it to the orchestrator with an explicit 4-step presentation instruction, appends both the instruction and response to `messages` so session memory is preserved
  - DUMP_SIGNAL block now chains: `write_dump` → `run_sub_agent` → `present_sub_agent_result`
- `agent_memory/playbook.md` — added Phase 5 Output Presentation Protocol: exact 4-step format Bron must follow when presenting coder results (summary, notes, file location, next steps)

**What it does:**
The full pipeline runs in a single session from one command. User gives a coding task → Bron clarifies → dump written → coder runs automatically → Bron presents the result — all without switching terminals or running scripts manually.

---

## Extending the Agent (Beyond Phase 5)

See `MODELS.md` for:
- How to swap the orchestrator or coder model (one line in `config.py`)
- How to add new specialist models (summariser, reviewer, planner, etc.)
- Routing pattern for directing different task types to different specialists
- VRAM management between sequential model calls
