from jarvis_message import message
from tools import available_tools, REGISTRY
from call_llm import call_llm
from ollama import ChatResponse

def handle(user_prompt) -> ChatResponse:
    message.append(user_prompt)

    while True:
        response = call_llm(message, available_tools)
        message.append(response["message"])
        tools = response["message"].get("tool_calls")
        if not tools:
            return response
        for tool in tools:
            name = tool["function"]["name"]
            args = tool["function"]["arguments"]
            print(f"{name} tool called")
            if not name in REGISTRY:
                result = f"Error: cannot find tool with name {name}"
            else:
                try:
                    result = REGISTRY[name](**args)
                except Exception as e:
                    result = f"Exception error {e}"
            message.append({"role": "tool", "content": str(result)})