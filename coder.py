"""
coder.py — Phase 4 Sub-Agent
Reads the prompt dump, builds a coding prompt, calls the coder model,
and writes the result to disk.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import ollama
from config import CODER_MODEL as DEFAULT_CODER_MODEL, CODER_OUTPUT_PATH
from dump_writer import read_dump




# ─────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────

REQUIRED_FIELDS = ["language", "task_type", "output_scope", "user_request"]


def validate_dump(dump: dict) -> bool:
    """Validate status and required fields. Return True if OK."""
    if dump.get("status") != "READY_FOR_CODER":
        print(f"[CODER ERROR] Invalid status: '{dump.get('status')}'. Expected 'READY_FOR_CODER'.")
        return False

    missing = [k for k in REQUIRED_FIELDS if not dump.get(k) or dump[k] == "none"]
    if missing:
        print(f"[CODER ERROR] Missing required fields: {missing}")
        return False

    return True


# ─────────────────────────────────────────────────
# Prompt Builder
# ─────────────────────────────────────────────────

def build_prompt(dump: dict) -> str:
    """Translate the dump fields into a structured coding prompt."""
    language = dump["language"]
    task_type = dump["task_type"]
    output_scope = dump["output_scope"]
    user_request = dump["user_request"]
    existing_code = dump.get("existing_code", "none")
    constraints = dump.get("constraints", [])

    constraint_block = ""
    if constraints:
        constraint_list = "\n".join(f"  - {c}" for c in constraints)
        constraint_block = f"\nConstraints:\n{constraint_list}"

    existing_block = ""
    if existing_code and existing_code.lower() != "none":
        existing_block = f"\nExisting code to integrate with:\n```\n{existing_code}\n```"

    prompt = (
        f"You are an expert {language} developer.\n\n"
        f"Task Type: {task_type}\n"
        f"Output Scope: {output_scope}\n"
        f"Language/Ecosystem: {language}\n"
        f"{constraint_block}"
        f"{existing_block}\n\n"
        f"Request:\n{user_request}\n\n"
        f"Produce only the requested {output_scope}. "
        f"Do not add explanation unless specifically asked. "
        f"Output clean, working {language} code."
    )
    return prompt


# ─────────────────────────────────────────────────
# Coder Entry Point
# ─────────────────────────────────────────────────

def run_coder():
    # Get model from environment variable (passed by pipeline) or use default from config
    coder_model = os.environ.get('CODER_MODEL')
    if not coder_model:
        coder_model = read_dump().get('coder_model', DEFAULT_CODER_MODEL)
    # Step 1: Read dump
    dump = read_dump()
    if dump is None:
        print("[CODER ERROR] No prompt dump found. Run the orchestrator first.")
        sys.exit(1)

    # Step 2: Validate
    if not validate_dump(dump):
        sys.exit(1)

    # Step 3: Build prompt
    prompt = build_prompt(dump)
    print("[CODER] Prompt built. Calling coder model...")
    print(f"[CODER] Model: {coder_model}")
    print(f"[CODER] Task: {dump['task_type']} | Scope: {dump['output_scope']} | Lang: {dump['language']}")

    # Step 4: Call coder model
    try:
        response = ollama.chat(
            model=coder_model,
            messages=[{"role": "user", "content": prompt}]
        )
        result = response["message"]["content"]
    except Exception as e:
        print(f"[CODER ERROR] Model call failed: {e}")
        sys.exit(1)

    # Step 5: Write output
    try:
        with open(CODER_OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write(f"Task ID: {dump['task_id']}\n")
            f.write(f"Language: {dump['language']}\n")
            f.write(f"Task Type: {dump['task_type']}\n")
            f.write(f"Output Scope: {dump['output_scope']}\n")
            f.write("-" * 60 + "\n\n")
            f.write(result)
        print(f"[CODER OUTPUT WRITTEN] {CODER_OUTPUT_PATH}")
    except Exception as e:
        print(f"[CODER ERROR] Failed to write output: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_coder()
