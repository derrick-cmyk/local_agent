import ollama
import config

def chat(messages, stream=False, model=None, num_ctx=32768):
    if model is None:
        model = config.ORCHESTRATOR_MODEL

    # The ollama.chat function returns a generator when stream=True
    response_generator = ollama.chat(
        model=model,
        messages=messages,
        stream=stream,
        options={
            "num_ctx": num_ctx
        }
    )

    return response_generator if stream else response_generator["message"]["content"]