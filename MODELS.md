# Model Swap Guide

All model names are controlled from a single file: `config.py`.
No other file needs to be changed when swapping models.

---

## The Model Slots

| Constant | Role | Current Model |
|---|---|---|
| `ORCHESTRATOR_MODEL` | Bron — conversational, memory-aware orchestrator | `llama3.2:3b` |
| `CODER_MODEL` | Coding sub-agent — generates code from the prompt dump | `qwen2.5-coder:3b` |

Additional specialist models can be added — see [Adding More Models](#adding-more-models) below.

---

## How to Swap a Model

### 1. Pull the new model
```
ollama pull <model-name>
```
Confirm it listed correctly:
```
ollama list
```

### 2. Edit config.py
Open `C:\Users\LAPTOP\local_agent\config.py` and change the relevant constant:
```python
# To swap the orchestrator:
ORCHESTRATOR_MODEL = "llama3.2:3b"   # change this value

# To swap the coder:
CODER_MODEL = "qwen2.5-coder:3b"     # change this value
```

### 3. Restart the agent
```
python main.py
```
No other changes are needed. The new model is picked up immediately on next startup.

---

## Orchestrator Swap — What to Expect

The orchestrator model (Bron) must be able to:
- Follow complex multi-step instructions from a markdown playbook
- Ask clarifying questions one at a time without deviation
- Output a structured summary block in the exact format the playbook specifies
- Output `DUMP_READY` on its own line when instructed

**Good alternatives to `llama3.2:3b`:**

| Model | Notes |
|---|---|
| `llama3.1:8b` | Better instruction-following; needs more VRAM (~5 GB) |
| `mistral:7b` | Strong at structured output; good playbook compliance |
| `qwen2.5:7b` | Excellent instruction-following; multilingual |
| `phi3:mini` | Very small (2.2 GB); lower quality but fast |

> **After swapping the orchestrator:** Run Phase 2 regression tests. Ask for a vague coding task and verify it asks exactly one question at a time and produces the structured summary correctly. If it doesn't, the playbook may need the final reminder line strengthened — see `playbook.md`: `"After producing the task summary, you MUST output the single word DUMP_READY..."`.

---

## Coder Swap — What to Expect

The coder model receives a structured prompt and must return clean code only.
It does not need to follow conversation rules — just generate accurate output.

**Good alternatives to `qwen2.5-coder:3b`:**

| Model | Notes |
|---|---|
| `qwen2.5-coder:7b` | Better quality; needs ~5 GB VRAM |
| `deepseek-coder:6.7b` | Strong at multi-language code generation |
| `codellama:7b` | Meta's coding model; solid for C++ and Python |
| `starcoder2:3b` | Lightweight option similar to current coder |

> **After swapping the coder:** Run Phase 4 T3 — submit a real task through the orchestrator and inspect `coder_output.txt`. Check the output is relevant and respects the constraints from the dump.

---

## Adding More Models

The architecture is designed to expand. Each new specialist model follows the same pattern: a new `config.py` constant, a new script, and a routing rule in the playbook.

### Pattern for a New Specialist

**Step 1 — Add to config.py**
```python
# Example: a summariser model
SUMMARISER_MODEL = "mistral:7b"
SUMMARISER_OUTPUT_PATH = os.path.join(AGENT_DIR, "summariser_output.txt")
SUMMARISER_SCRIPT = os.path.join(AGENT_DIR, "summariser.py")
```

**Step 2 — Create the specialist script** (e.g. `summariser.py`)

Every specialist script follows the same 6-step structure:
```
1. Import config paths and model name
2. Read and validate the prompt dump (read_dump() from dump_writer.py)
3. Build input — translate dump fields into whatever the model needs
4. Act — call ollama.chat() with the specialist model
5. Write output to the specialist's output path
6. Print [SPECIALIST OUTPUT WRITTEN] on success
```

**Step 3 — Add a routing signal to the dump**

The orchestrator needs to know which specialist to call. Add a `specialist` field to the dump format by:
- Adding a question to the Phase 2 checklist in `playbook.md`: *"Which type of task is this? (coding / summarising / ...)"*
- Reading that field in `main.py` after the dump is written to decide which script to invoke

**Step 4 — Add routing logic to main.py**
```python
# After write_dump(summary_block):
dump = read_dump()
specialist = dump.get("specialist", "coder")

if specialist == "coder":
    run_sub_agent()          # calls coder.py
elif specialist == "summariser":
    run_summariser()         # calls summariser.py
```

**Step 5 — Add a presentation rule to playbook.md**

Add a new section (same format as Phase 5 Output Presentation Protocol) that tells Bron how to present the output from the new specialist.

### Example Specialists You Could Add

| Specialist | Model | What it Does |
|---|---|---|
| `summariser.py` | `mistral:7b` | Summarises long documents or session notes |
| `reviewer.py` | `qwen2.5-coder:7b` | Reviews and critiques code from `existing_code` |
| `planner.py` | `llama3.1:8b` | Produces a project plan or task breakdown |
| `explainer.py` | `llama3.2:3b` | Explains code in the dump in plain language |

> **Key principle:** Each specialist is isolated. It reads the dump cold, acts, and writes output. The orchestrator never needs to know how the specialist works — only what it produced.

---

## VRAM Management

The orchestrator and any specialist model are never run simultaneously.
Ollama should release VRAM between runs automatically.

If you see slowdowns (model falling back to CPU), force-release VRAM before running a specialist:
```
curl http://localhost:11434/api/generate -d "{\"model\": \"llama3.2:3b\", \"keep_alive\": 0}"
```
Or set this in your Ollama service environment:
```
OLLAMA_KEEP_ALIVE=0
```
