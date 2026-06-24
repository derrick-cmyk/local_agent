import ollama
import config

def chat(messages):
    response = ollama.chat(
        model=config.ORCHESTRATOR_MODEL,
        messages=messages
    )
    return response["message"]["content"]