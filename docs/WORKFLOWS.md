# Operational Workflows

This document outlines key runtime workflows within Jarvis.

---

## 1. Agent Tool Calling Loop

When a user requests a file system action, the engine executes an iterative dialogue loop until the model delivers a final natural language answer.

```mermaid
flowchart TD
START([User Input Received]) --> APPEND_USER[Append User Message to History]
APPEND_USER --> CALL_LLM[Call Active LLM Provider]
CALL_LLM --> HAS_TOOLS{Does message contain Tool Calls?}

    HAS_TOOLS -->|No| RETURN_TEXT[Return Assistant Text Response]
    HAS_TOOLS -->|Yes| ITER_CHECK{Iterations < Max Allowed?}

    ITER_CHECK -->|No| FALLBACK[Append Max Limit Warning & Exit]
    ITER_CHECK -->|Yes| PARSE_CALL[Extract Function Name & Arguments]

    PARSE_CALL --> REGISTRY_CHECK{Function exists in Registry?}
    REGISTRY_CHECK -->|No| TOOL_ERR[Create Tool Error Message]
    REGISTRY_CHECK -->|Yes| EXEC_TOOL[Execute Python Function]

    EXEC_TOOL --> FORMAT_RES[Format Output as Tool Message]
    TOOL_ERR --> FORMAT_RES
    FORMAT_RES --> APPEND_TOOL[Append Tool Message to History]
    APPEND_TOOL --> CALL_LLM

    RETURN_TEXT --> END([Speak / Print Response])
    FALLBACK --> END

```

---

## 2. Dynamic Backend Switching Workflow

The user can cycle active LLM backends at runtime using the `F1` keybinding without restarting the assistant.

```mermaid
sequenceDiagram
autonumber
actor User
participant CLI as PromptSession (UI)
participant KB as Keybinding Handler
participant State as AppState Singleton
participant Conf as AppSettings

    User->>CLI: Presses F1
    CLI->>KB: Trigger _switch_model event
    KB->>State: cycle_model()
    State->>Conf: Read available_models
    Conf-->>State: ['local', 'claude']
    State->>State: Update active_model index (local -> claude)
    State-->>KB: 'claude'
    KB->>CLI: Print confirmation to terminal

```

---

## 3. Multilingual Speech Synthesis Pipeline

Incoming text responses are analyzed for character scripts before selecting the appropriate Piper TTS voice model.

```mermaid
flowchart LR
TEXT[Input Text String] --> REGEX{Language Detection Regex}
REGEX -->|Contains Polish Glyphs| PL[Select Polish Voice: pl_PL-bass-high]
REGEX -->|Contains Cyrillic Glyphs| RU[Select Russian Voice: ru_RU-denis-medium]
REGEX -->|Default / Latin Glyphs| EN[Select English Voice: en_GB-alan-medium]

    PL --> CACHE[Load / Fetch Cached ONNX Model]
    RU --> CACHE
    EN --> CACHE

    CACHE --> SYNTH[PiperVoice.synthesize]
    SYNTH --> RAW_BYTES[Audio Chunks / PCM Bytes]
    RAW_BYTES --> SD[SoundDevice Playback]

```
