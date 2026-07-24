from call_llm import call_llm
from schemas import Message

def handle(user_prompt, message: list[Message]):
    message.append(user_prompt)
    print(message)
    response = call_llm(message)
    return response
