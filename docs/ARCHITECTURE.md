# System Architecture

Jarvis is a modular, event-driven, voice-first AI workstation assistant with sandboxed file system capabilities. It operates locally using Ollama and Piper TTS, while supporting dynamic fallback to cloud LLM backends (Anthropic Claude, Google Gemini, OpenAI GPT).

---

## High-Level System Design

The architecture is partitioned into four primary layers:

1. **Input & Capture Layer:** Asynchronous text prompt ingestion (`prompt_toolkit`) and real-time wake-word audio streaming (`RealtimeSTT`).
2. **Orchestration & State Layer:** Core engine managing thread-safe application state, model cycling, and multi-turn message history.
3. **Inference & Execution Layer:** LLM provider abstraction and iterative function execution pipeline.
4. **Speech Output Layer:** Local low-latency multilingual speech synthesis via Piper TTS and PortAudio.

```mermaid
graph TD
subgraph Input_Layer [Input Layer]
MIC[Microphone Stream] -->|Audio Frames| STT[RealtimeSTT Engine]
CLI[Terminal Prompt] -->|Key / Text Events| PT[PromptSession UI]
STT -->|Transcribed Text| Q[Task Queue]
PT -->|Submitted Command| Q
end

    subgraph Core_Runtime [Core Orchestration Engine]
        Q -->|Get Event| ENG[AssistantEngine]
        STATE[AppState Singleton] <-->|Read / Mutate| ENG
        HOTKEYS[Keybinding Handlers F1-F3] -->|Toggle / Cycle| STATE
    end

    subgraph LLM_Layer [Inference & Tool Pipeline]
        ENG -->|Messages + Tools| ROUTER[LLM Router / Client]
        ROUTER -->|Local RPC| OLLAMA[Ollama Runtime]
        ROUTER -->|HTTPS REST| CLAUDE[Anthropic Claude API]
        ROUTER -->|HTTPS REST| GEMINI[Google Gemini API]
        ROUTER -->|HTTPS REST| GPT[OpenAI GPT API]
        ROUTER -->|Tool Calls| DISPATCH[Tool Dispatcher]
        DISPATCH -->|Execute within Sandbox| FS[Sandboxed File System]
        FS -->|Tool Result| ENG
    end

    subgraph Audio_Output [Speech Synthesis Layer]
        ENG -->|Text Stream| TTS[Piper TTS Engine]
        TTS -->|PCM Audio Buffer| SD[SoundDevice Output]
        SD -->|Playback State Flag| STT
    end

```

---

## Concurrency & Threading Model

Jarvis enforces non-blocking concurrent execution using dedicated threads communicating through thread-safe queues and atomic synchronization primitives:

| Thread                   | Role                                                             | Communication Channel           | Blocking Behavior      |
| :----------------------- | :--------------------------------------------------------------- | :------------------------------ | :--------------------- |
| **Main Thread**          | Event loop, Engine execution, Tool calling, Audio playback       | `task_queue.get(timeout=0.2)`   | Non-blocking poll      |
| **CLI Input Thread**     | Terminal line editing and global key handling (`prompt_toolkit`) | Writes to `task_queue`          | Blocking on user input |
| **Voice Capture Thread** | Audio recording, VAD, and Whisper STT inference                  | Writes to `task_queue`          | Continuous poll        |
| **Playback Sync**        | Prevents microphone feedback loop during speech output           | `threading.Event (is_speaking)` | Shared flag            |

```mermaid
sequenceDiagram
autonumber
participant U as User
participant V as Voice Loop (RealtimeSTT)
participant Q as Task Queue
participant M as Main Loop
participant E as Assistant Engine
participant L as LLM Backend
participant T as Tool Registry
participant S as Piper TTS

    U->>V: Speaks "jarvis, list all python files"
    V->>Q: Enqueue transcribed command
    M->>Q: Pop task event
    M->>E: Process user prompt
    E->>L: Send chat context & tool definitions
    L-->>E: Return ToolCall: find_file("*.py")
    E->>T: Invoke find_file("*.py")
    T-->>E: Return relative file list
    E->>L: Send tool execution result
    L-->>E: Return final natural language response
    E-->>M: Return response string
    M->>S: Synthesize and stream audio
    S->>U: Audio output via speakers

```
