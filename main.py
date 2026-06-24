import sys
import os
import subprocess

sys.path.insert(0, os.path.dirname(__file__))

from memory import load_memory
from ollama_client import chat
from pipeline import (
    DUMP_SIGNAL,
    extract_summary_block,
    run_sub_agent,
    read_coder_output
)

def build_system_prompt(memory: str) -> str:
    return (
        "You are a local teaching assistant agent.\n\n"
        + memory
    )


def present_sub_agent_result(messages: list) -> None:
    """
    Read the coder output file and pass it to the orchestrator
    with a presentation instruction. Appends the result to the
    live conversation so session memory is preserved.
    """
    coder_result = read_coder_output()
    if coder_result is None:
        print("[PIPELINE] Skipping result presentation.")
        return

    presentation_instruction = (
        "The coding sub-agent has finished. Here is its output:\n\n"
        "```\n"
        f"{coder_result}\n"
        "```\n\n"
        "Please do the following:\n"
        "1. Summarise what was produced in 2-3 sentences in plain language.\n"
        "2. Note any obvious issues, limitations, or things the user should be aware of.\n"
        "3. Tell the user the full output is saved to coder_output.txt in the project folder.\n"
        "4. Invite the user to ask follow-up questions or request revisions."
    )

    messages.append({"role": "user", "content": presentation_instruction})

    print("\n[PIPELINE] Asking orchestrator to present result...\nAgent: ", end="", flush=True)
    response = chat(messages)
    print(response)
    print()

    messages.append({"role": "assistant", "content": response})


def main():
    print("[SYSTEM] Loading memory...")
    memory = load_memory()
    system_prompt = build_system_prompt(memory)

    messages = [{"role": "system", "content": system_prompt}]

    print("Agent ready. Type your message. Press Ctrl+C to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSession ended.")
            break

        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        print("\n[ORCHESTRATOR] Thinking...\nAgent: ", end="", flush=True)
        response = chat(messages)
        print(response)
        print()

        messages.append({"role": "assistant", "content": response})

        # Check for dump signal — trigger sub-agent pipeline
        if DUMP_SIGNAL in response:
            print("\n[PIPELINE] DUMP_SIGNAL detected. Starting sub-agent pipeline...")
            summary_block = extract_summary_block(response)
            from dump_writer import write_dump
            dump_ok = write_dump(summary_block)
            if dump_ok:
                coder_ok = run_sub_agent()
                if coder_ok:
                    present_sub_agent_result(messages)
                else:
                    print("[PIPELINE] Coder failed — skipping result presentation.")


if __name__ == "__main__":
    main()