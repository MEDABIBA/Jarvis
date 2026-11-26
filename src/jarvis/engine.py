import math
from collections.abc import Generator
from contextlib import closing
from uuid import uuid4

from loguru import logger

from jarvis.core.state import state
from jarvis.llm.client import call_llm, stream_llm
from jarvis.llm.prompts import (
    MEMORY_DIR,
    MEMORY_FILES,
    SUMMARY_PROMPT,
    generate_dynamic_prompt,
)
from jarvis.llm.schemas import ChatMessage, ToolCall, TurnEvent
from jarvis.tools.registry import AVAILABLE_TOOLS, TOOL_REGISTRY


class AssistantEngine:
    """Maintains dialog context and executes tool calls iteratively."""

    def __init__(self, max_tool_iterations: int = 8) -> None:
        self.history: list[ChatMessage] = [
            ChatMessage(
                turn_id=str(uuid4()), role="system", content=generate_dynamic_prompt()
            )
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

    def _compact(self, *, backend: str | None = None) -> None:
        """Replace the older part of the history with a summary of it.

        Called when the number of tokens exceeds the set limit (max_tokens_per_history_local_model or max_tokens_per_history).
        Asks the model to compact the chat history into one <conversation_summary> message with the user role. The recent tail stays verbatim"""
        self._reduce_tool_results()
        idx = self._cut_index(keep=3)
        head, tail = self.history[1:idx], self.history[idx:]

        transcript = "\n".join(
            f"{m.role}: {m.content}" if m.content else f"{m.role}: [tool_calls]"
            for m in head
        )
        try:
            summary = call_llm(
                [
                    ChatMessage(turn_id=str(uuid4()), role="user", content=transcript),
                    ChatMessage(
                        turn_id=str(uuid4()), role="user", content=SUMMARY_PROMPT
                    ),
                ],
                [],
                backend=backend,
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
                turn_id=str(uuid4()),
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

    def handle_stream(self, user_text: str) -> Generator[TurnEvent]:
        """Yield public progress and one terminal complete/error event.

        The backend is fixed when iteration starts, including compaction and tool
        follow-ups. Close the iterator to cancel; no new tool starts after close.
        """
        turn_id = str(uuid4())
        backend = state.active_model
        partial_text: list[str] = []
        pending_tools: list[ToolCall] = []

        def preserve_interrupted_history() -> None:
            if partial_text:
                self.history.append(
                    ChatMessage(
                        turn_id=turn_id, role="assistant", content="".join(partial_text)
                    )
                )
                partial_text.clear()
            # A completed assistant tool message must always have matching results,
            # even if the consumer cancels at tool_start or between two calls.
            for call in pending_tools:
                self.history.append(
                    ChatMessage(
                        turn_id=turn_id,
                        role="tool",
                        name=call.function.name,
                        tool_call_id=call.id,
                        content="Tool execution cancelled before a result was available.",
                    )
                )
            pending_tools.clear()

        try:
            if self._memory_changed():
                self.history[0] = ChatMessage(
                    turn_id=turn_id, role="system", content=generate_dynamic_prompt()
                )

            limit = (
                self.max_tokens_per_history_local_model
                if backend == "local"
                else self.max_tokens_per_history
            )
            if self._estimate_tokens() > limit:
                self._compact(backend=backend)

            self.history.append(
                ChatMessage(turn_id=turn_id, role="user", content=user_text)
            )
            for _ in range(self.max_tool_iterations):
                msg: ChatMessage | None = None
                with closing(
                    stream_llm(self.history, AVAILABLE_TOOLS, backend=backend)
                ) as events:
                    for event in events:
                        if event.kind == "text_delta":
                            partial_text.append(event.text)
                            yield TurnEvent(
                                turn_id=turn_id, kind="text_delta", text=event.text
                            )
                        elif event.kind == "message_complete":
                            msg = event.message
                if msg is None:
                    raise RuntimeError("LLM stream did not produce a complete message")
                msg = msg.model_copy(update={"turn_id": turn_id})
                self.history.append(msg)
                partial_text.clear()

                if not msg.tool_calls:
                    yield TurnEvent(
                        turn_id=turn_id, kind="complete", answer=msg.content or ""
                    )
                    return

                pending_tools.extend(msg.tool_calls)
                for tool_call in msg.tool_calls:
                    fn_name = tool_call.function.name
                    yield TurnEvent(
                        turn_id=turn_id,
                        kind="tool_start",
                        tool_name=fn_name,
                        tool_call_id=tool_call.id,
                    )
                    logger.info("Tool invocation requested: {}", fn_name)
                    if fn_name not in TOOL_REGISTRY:
                        result = f"Error: Tool '{fn_name}' does not exist in registry."
                    else:
                        try:
                            result = TOOL_REGISTRY[fn_name](
                                **tool_call.function.arguments
                            )
                        except Exception as err:
                            logger.exception("Error executing tool '{}'", fn_name)
                            result = f"Tool execution error: {err}"

                    self.history.append(
                        ChatMessage(
                            turn_id=turn_id,
                            role="tool",
                            name=fn_name,
                            tool_call_id=tool_call.id,
                            content=str(result),
                        )
                    )
                    pending_tools.pop(0)
                    yield TurnEvent(
                        turn_id=turn_id,
                        kind="tool_end",
                        tool_name=fn_name,
                        tool_call_id=tool_call.id,
                    )

            fallback = "I reached the maximum limit of tool actions for this step."
            self.history.append(
                ChatMessage(turn_id=turn_id, role="assistant", content=fallback)
            )
            yield TurnEvent(turn_id=turn_id, kind="text_delta", text=fallback)
            yield TurnEvent(turn_id=turn_id, kind="complete", answer=fallback)
        except Exception as err:
            preserve_interrupted_history()
            answer = f"Backend error: {err}"
            yield TurnEvent(
                turn_id=turn_id,
                kind="error",
                text=answer,
                answer=answer,
                error=str(err),
            )
        finally:
            preserve_interrupted_history()

    def handle(self, user_text: str) -> tuple[str, str]:
        """Compatibility consumer returning only the final answer and turn ID."""
        with closing(self.handle_stream(user_text)) as events:
            for event in events:
                if event.kind in ("complete", "error"):
                    return event.answer, event.turn_id
        raise RuntimeError("Turn stream did not produce a terminal event")
