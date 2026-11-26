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

Each response uses an explicit locale. Public text is displayed immediately and
buffered into sentences for a bounded speech worker. Azure SDK/REST and Piper
share a synthesis contract; playback remains separate.

```mermaid
flowchart TD
    TEXT[Public assistant text deltas] --> FILTER[Filter fenced code and extract sentences]
    FILTER --> QUEUE[Bounded speech queue]
    QUEUE --> NORMALIZE[Normalize using the turn locale]
    NORMALIZE --> PROVIDER[Select configured or fallback provider]
    PROVIDER --> PCM[Raw PCM chunks]
    PCM --> SD[Local player]
    PROVIDER -->|No available voice| SILENT[Continue as text only]
```

Fallback is allowed only before the response's first audio is delivered. A later
failure stops speech rather than replaying earlier text. Muting or F4 cancellation
never selects another provider. See [Speech Output](SPEECH.md) for configuration
and the exact failure/cancellation policy.
