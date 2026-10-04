
import math

from loguru import logger

from jarvis.core.state import state
from jarvis.llm.client import call_llm
from jarvis.llm.prompts import (
    MEMORY_DIR,
    MEMORY_FILES,
    SUMMARY_PROMPT,
    generate_dynamic_prompt,
)
from jarvis.llm.schemas import ChatMessage
from jarvis.tools.registry import AVAILABLE_TOOLS, TOOL_REGISTRY


class AssistantEngine:
    """Maintains dialog context and executes tool calls iteratively."""

    def __init__(self, max_tool_iterations: int = 8) -> None:
        self.history: list[ChatMessage] = [
            ChatMessage(role="system", content=generate_dynamic_prompt())
        ]
        self.memory_timestamp = self.read_memory_timestamp()
        self.max_tool_iterations = max_tool_iterations
        self.max_tokens_per_history = 6000
        self.max_tokens_per_history_local_model = 2000

    def read_memory_timestamp(self):
        timestamp: int = 0
        for _, filename in MEMORY_FILES:
            try:
                timestamp += math.floor((MEMORY_DIR / filename).stat().st_mtime)
            except FileNotFoundError:
                logger.debug("Memory file {} not present; skipping", filename)
        return timestamp

    def _memory_changed(self) -> bool:
        current = self.read_memory_timestamp()
        if current == self.memory_timestamp:
            return False
        self.memory_timestamp = current
        return True

    def _estimate_tokens(self):
        chars = sum([len(i.content or "") for i in self.history])
        chars += sum(
            len((str(tc.function.arguments)) + str(len(tc.function.name)))
            for m in self.history
            for tc in m.tool_calls or []
        )
        return chars // 3  # ~3 characters per token;

    def _cut_index(self, keep: int = 3) -> int:
        """Boundary that keeps roughly `keep` last messages without splitting a
        tool call from its results."""
        idx = max(1, len(self.history) - keep)
        while idx > 1 and self.history[idx].role == "tool":
            idx -= 1
        return idx

    def _compact(self) -> None:
        idx = self._cut_index(keep=3)
        head, tail = self.history[1:idx], self.history[idx:]

        transcript = "\n".join(
            f"{m.role}: {m.content}" if m.content else f"{m.role}: [tool_calls]"
            for m in head
        )
        try:
            summary = call_llm(
                [
                    ChatMessage(role="user", content=transcript),
                    ChatMessage(role="user", content=SUMMARY_PROMPT),
                ],
                [],
            ).message.content
        except Exception as err:
            logger.error("Compaction failed, keeping the history as is: {}", err)
            return
        if not summary:
            logger.warning("Compaction returned nothing, keeping the history as is")
            return

        self.history = [
            self.history[0],
            ChatMessage(
                role="user",
                content=f"<conversation_summary>\n{summary}\n</conversation_summary>",
            ),
            *tail,
        ]

    def _reduce_tool_results(self, keep: int = 6, max_len: int = 200):
        """Drop unused tool result, that are no longer recent, to reduce space taken up by the history"""
        for m in self.history[:-keep]:
            if m.role == "tool" and m.content and len(m.content) > max_len:
                m.content = f"{m.content[:max_len]}... [{len(m.content) - max_len} chars dropped from history]"
        return self.history

    def handle(self, user_text: str) -> str:
        """Process user input through the LLM and tool execution pipeline."""

        if self._memory_changed():
            # Memory files changed - rebuild the old system prompt into the new one
            self.history[0] = ChatMessage(
                role="system", content=generate_dynamic_prompt()
            )

        self._reduce_tool_results()

        limit = (
            self.max_tokens_per_history_local_model
            if state.active_model == "local"
            else self.max_tokens_per_history
        )
        if self._estimate_tokens() > limit:
            self._compact()

        self.history.append(ChatMessage(role="user", content=user_text))
        iterations = 0
        while iterations < self.max_tool_iterations:
            iterations += 1
            try:
                msg = call_llm(self.history, AVAILABLE_TOOLS).message
            except Exception as e:
                return f"Backend error: {e}"
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
