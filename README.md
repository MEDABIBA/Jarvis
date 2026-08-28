# Jarvis

[![Python Version](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/)
[![Package Manager: uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Code Style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A voice-controlled, sandboxed AI workstation assistant designed for low-latency voice interaction and secure local workspace management. Jarvis supports multi-lingual speech synthesis via Piper TTS, local inference through Ollama, and optional cloud LLM backends (Anthropic, Google AI, OpenAI).

---

## Key Capabilities

- **Always-On Voice Interface:** Continuous acoustic wake word detection listening for `"jarvis"`.
- **Offline Multi-Lingual Speech Synthesis:** Fast, local text-to-speech output using Piper TTS with support for English, Polish, and Russian.
- **Secure File System Sandbox:** Autonomous search, file inspection, modification, and creation restricted strictly to the `./sandbox` directory.
- **Hybrid LLM Provider Support:** Dynamic model routing between offline Ollama instances and external cloud APIs (Claude, Gemini, GPT).
- **Runtime Hotkeys:** Dedicated keyboard shortcuts for toggling audio capture, speech synthesis, and switching active model backends on the fly.

---

## System Requirements

- **Python:** 3.13 or later
- **Package & Project Manager:** [uv](https://docs.astral.sh/uv/)
- **Local LLM Engine (Optional):** [Ollama](https://ollama.com/) (required only for offline inference)

---

## Installation & Setup

### 1. Repository Setup

Clone the repository and synchronize the environment dependencies using `uv`:

```bash
git clone https://github.com/MEDABIBA/jarvis.git
cd jarvis
uv sync
```

### 2. Voice Model Assets

Download the required Piper TTS voice models into the local storage structure:

```bash
# English (Alan - Medium)
python -m piper.download_voices en_GB-alan-medium --download-dir voices/EN

# Polish (Bass - High)
python -m piper.download_voices pl_PL-bass-high --download-dir voices/PL

# Russian (Denis - Medium)
python -m piper.download_voices ru_RU-denis-medium --download-dir voices/RU
```

### 3. Local Model Deployment (Ollama)

If utilizing local inference, install and launch the desired model via Ollama:

```bash
ollama pull mistral
```

### 4. Configuration

Create a `.env` configuration file in the project root:

```ini
# Core Runtime Configuration

JARVIS_DEBUG=false
JARVIS_LOCAL_MODEL="mistral"
JARVIS_SANDBOX="./sandbox"

# Cloud Model API Keys (Optional - leave empty for offline-only mode)

JARVIS_ANTHROPIC_API_KEY=""
JARVIS_GEMINI_API_KEY=""
JARVIS_GPT_API_KEY=""
```

---

## Execution

Start the assistant runtime:

```bash
uv run jarvis
```

---

## Keybindings & Controls

Jarvis registers global keyboard hooks to enable runtime control without interrupting active terminal workflows:

| Key      | Action              | Description                                                                                          |
| :------- | :------------------ | :--------------------------------------------------------------------------------------------------- |
| **`F1`** | Cycle Active Model  | Switches across available backends (`local`, `claude`, `gemini`, `gpt`) based on active credentials. |
| **`F2`** | Toggle Microphone   | Enables or disables audio input capture and wake word detection.                                     |
| **`F3`** | Toggle Audio Output | Enables or mutes voice synthesis playback.                                                           |

---

## Configuration Reference

All settings are resolved through `pydantic-settings` and can be supplied as system environment variables or inside the `.env` file with the `JARVIS_` prefix.

| Parameter                  | Type        | Default     | Description                                                   |
| :------------------------- | :---------- | :---------- | :------------------------------------------------------------ |
| `JARVIS_DEBUG`             | `bool`      | `true`      | Enables verbose debug logging and detailed stack diagnostics. |
| `JARVIS_LOCAL_MODEL`       | `str`       | _Required_  | Local model identifier target for Ollama runtime.             |
| `JARVIS_SANDBOX`           | `Path`      | `./sandbox` | Root directory boundary for agent file system operations.     |
| `JARVIS_ANTHROPIC_API_KEY` | `SecretStr` | `None`      | API credential for Anthropic Claude integration.              |
| `JARVIS_GEMINI_API_KEY`    | `SecretStr` | `None`      | API credential for Google Gemini integration.                 |
| `JARVIS_GPT_API_KEY`       | `SecretStr` | `None`      | API credential for OpenAI GPT integration.                    |

---

## Development

### Code Quality & Formatting

Linting and code formatting are managed via [Ruff](https://github.com/astral-sh/ruff):

```bash
# Run linting checks and apply safe fixes
uv run ruff check --fix

# Format source code
uv run ruff format
```

### Test Suite

Execute automated unit and integration tests:

```bash
uv run pytest
```
