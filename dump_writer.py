import json
import os
import re
from datetime import datetime
from config import PROMPT_DUMP_PATH


def parse_task_summary(text: str) -> dict:
    """
    Parse the orchestrator's plain text task summary into a dictionary.
    Expects the summary block produced by the Phase 3 playbook protocol.
    """
    def extract(label, fallback="none"):
        pattern = rf"{label}\s*:\s*(.+)"
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else fallback

    # Extract constraints — may be a comma-separated list
    raw_constraints = extract("Constraints", "")
    if raw_constraints and raw_constraints.lower() != "none":
        constraints = [c.strip() for c in raw_constraints.split(",") if c.strip()]
    else:
        constraints = []

    return {
        "task_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "language": extract("Language/Ecosystem"),
        "task_type": extract("Task Type"),
        "output_scope": extract("Output Scope"),
        "existing_code": extract("Existing Code"),
        "constraints": constraints,
        "user_request": extract("User Request"),
        "status": "READY_FOR_CODER",
    }


def write_dump(task_summary_text: str, coder_model: str = None) -> bool:
    """
    Parse the task summary and write it to the prompt dump JSON file.
    Returns True on success, False on failure.
    """
    try:
        data = parse_task_summary(task_summary_text)

        if coder_model:
            data['coder_model'] = coder_model

        # Validate required fields are not empty
        required = ["language", "task_type", "output_scope", "user_request"]
        missing = [k for k in required if data[k] == "none" or not data[k]]
        if missing:
            print(f"[DUMP ERROR] Missing required fields: {missing}")
            return False

        with open(PROMPT_DUMP_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"[DUMP WRITTEN] {PROMPT_DUMP_PATH}")
        return True

    except Exception as e:
        print(f"[DUMP ERROR] Failed to write dump: {e}")
        return False


def read_dump() -> dict | None:
    """
    Read and return the current prompt dump as a dictionary.
    Returns None if the file does not exist or is malformed.
    """
    if not os.path.exists(PROMPT_DUMP_PATH):
        return None
    try:
        with open(PROMPT_DUMP_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[DUMP ERROR] Failed to read dump: {e}")
        return None
