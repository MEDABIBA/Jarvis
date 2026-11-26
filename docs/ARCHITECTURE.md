# System Architecture

Jarvis is a modular, event-driven, voice-first AI workstation assistant with sandboxed file system capabilities. It operates locally using Ollama and Piper TTS, while supporting dynamic fallback to cloud LLM backends (Anthropic Claude, Google Gemini, OpenAI GPT).

---

## High-Level System Design

The architecture is partitioned into four primary layers:

1. **Input & Capture Layer:** Asynchronous text prompt ingestion (`prompt_toolkit`) and real-time wake-word audio streaming (`RealtimeSTT`).
2. **Orchestration & State Layer:** Core engine managing thread-safe application state, model cycling, and multi-turn message history.
3. **Inference & Execution Layer:** LLM provider abstraction and iterative function execution pipeline.
4. **Speech Output Layer:** Bounded sentence buffering, Azure SDK/REST or local Piper synthesis, and a separate client-side PCM player. See [Speech Output](SPEECH.md) for configuration and fallback policy.

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
        ENG -->|Public text deltas| SENT[Sentence Buffer and Bounded Queue]
        SENT --> TTS[SpeechService]
        TTS --> AZURE[Azure SDK or REST]
        TTS --> PIPER[Local Piper]
        AZURE -->|PCM chunks| SD[Local SoundDevice Player]
        PIPER -->|PCM chunks| SD
        SD -->|Playback State Flag| STT
    end

```

---

## Concurrency & Threading Model

Input and speech use dedicated threads. The main thread consumes engine events and executes synchronous tools. A separate bounded speech queue keeps playback from blocking text generation:

| Thread                   | Role                                                             | Communication Channel              | Blocking Behavior                                           |
| :----------------------- | :--------------------------------------------------------------- | :--------------------------------- | :---------------------------------------------------------- |
| **Main Thread**          | Engine event consumption, tool calling, terminal output          | `task_queue.get()` and LLM streams | Blocking reads; audio runs separately                       |
| **Speech Worker**        | Sentence normalization, synthesis, PCM playback                  | Bounded sentence queue             | Blocking synthesis/playback; cancellable between operations |
| **CLI Input Thread**     | Terminal line editing and global key handling (`prompt_toolkit`) | Writes to `task_queue`             | Blocking on user input                                      |
| **Voice Capture Thread** | Audio recording, VAD, and Whisper STT inference                  | Writes to `task_queue`             | Continuous poll                                             |
| **Playback Sync**        | Prevents microphone feedback loop during speech output           | `threading.Event (is_speaking)`    | Shared flag                                                 |

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
participant S as Speech Worker

    U->>V: Speaks "jarvis, list all python files"
    V->>Q: Enqueue transcribed command
    M->>Q: Pop task event
    M->>E: Process user prompt
    E->>L: Send chat context & tool definitions
    L-->>E: Return ToolCall: find_file("*.py")
    E->>T: Invoke find_file("*.py")
    T-->>E: Return relative file list
    E->>L: Send tool execution result
    loop Public response deltas
        L-->>E: Public text delta
        E-->>M: Turn text event
        M->>S: Queue completed sentences
        S->>U: Stream PCM to local speakers
    end
    E-->>M: Complete event with authoritative final answer

```
