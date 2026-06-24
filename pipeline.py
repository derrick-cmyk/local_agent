import os
import sys
import subprocess
import config
from config import SUB_AGENT_SCRIPT, CODER_OUTPUT_PATH
from dump_writer import write_dump

DUMP_SIGNAL = "DUMP_READY"


def extract_summary_block(response: str) -> str:
    """
    Extract the task summary block from the orchestrator response.
    Looks for content between 'CODING TASK DETECTED' and 'DUMP_READY'.
    """
    start = response.find("CODING TASK DETECTED")
    end = response.find(DUMP_SIGNAL)
    if start == -1 or end == -1:
        return response  # fallback: pass full response to parser
    return response[start:end].strip()


def run_sub_agent() -> bool:
    """
    Invoke the coder sub-agent as a blocking subprocess.
    Returns True on success (exit code 0), False otherwise.
    """
    print("\n[PIPELINE] Invoking coder sub-agent...")
    
    env = os.environ.copy()
    if hasattr(config, 'CODER_MODEL'):
        env['CODER_MODEL'] = config.CODER_MODEL
        
    result = subprocess.run(
        [sys.executable, SUB_AGENT_SCRIPT],
        capture_output=False,
        env=env
    )
    if result.returncode == 0:
        print("[PIPELINE] Coder sub-agent finished.")
        return True
    else:
        print(f"[PIPELINE] Coder sub-agent exited with code {result.returncode}.")
        return False


def read_coder_output() -> str | None:
    """
    Reads the content of the coder output file.
    Returns the content as a string, or None if the file doesn't exist or an error occurs.
    """
    if not os.path.exists(CODER_OUTPUT_PATH):
        print("[PIPELINE] No coder output file found.")
        return None

    print("[PIPELINE] Reading coder output...")
    try:
        with open(CODER_OUTPUT_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        print(f"[PIPELINE] Could not read coder output: {e}")
        return None