from loguru import logger

from jarvis.llm.client import call_llm
from jarvis.llm.prompts import SYSTEM_PROMPT
from jarvis.llm.schemas import ChatMessage
from jarvis.tools.registry import AVAILABLE_TOOLS, TOOL_REGISTRY


class AssistantEngine:
    """Maintains dialog context and executes tool calls iteratively."""

    def __init__(self, max_tool_iterations: int = 8) -> None:
        self.history: list[ChatMessage] = [
            ChatMessage(role="system", content=SYSTEM_PROMPT)
        ]
        self.max_tool_iterations = max_tool_iterations

    def handle(self, user_text: str) -> str:
        """Process user input through the LLM and tool execution pipeline."""
        self.history.append(ChatMessage(role="user", content=user_text))

        iterations = 0
        while iterations < self.max_tool_iterations:
            iterations += 1
            response = call_llm(self.history, AVAILABLE_TOOLS)
            msg = response.message
            self.history.append(msg)

            if not msg.tool_calls:
                return msg.content or ""

            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                fn_args = tool_call.function.arguments
                logger.info("Tool invocation requested: {}({})", fn_name, fn_args)

                if fn_name not in TOOL_REGISTRY:
                    result = f"Error: Tool '{fn_name}' does not exist in registry."
                else:
                    try:
                        result = TOOL_REGISTRY[fn_name](**fn_args)
                    except Exception as err:
                        logger.exception("Error executing tool '{}'", fn_name)
                        result = f"Tool execution error: {err}"

                self.history.append(
                    ChatMessage(
                        role="tool",
                        name=fn_name,
                        tool_call_id=tool_call.id,
                        content=str(result),
                    )
                )

        fallback_msg = "I reached the maximum limit of tool actions for this step."
        self.history.append(ChatMessage(role="assistant", content=fallback_msg))
        return fallback_msg
