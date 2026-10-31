# Jarvis

[![Python Version](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/)
[![Package Manager: uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Code Style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Jarvis – AI-powered personal assistant for everyday tasks with low-latency voice interaction and secure local workspace management.
Jarvis works both locally via [Ollama](https://ollama.com/) and with cloud LLM providers (Anthropic Claude, Google Gemini, OpenAI GPT, Cerebras).

---

## Key Capabilities

- **Always-On Voice Interface:** Wake word detection listening for `"jarvis"`.
- **Offline Multi-Lingual Speech Synthesis:** Fast, local text-to-speech output using Piper TTS with support for English, Polish, and Russian.
- **Google Calendar Integration:** Access your Google Calendar to list, create, and delete events
- **Hybrid LLM Provider Support:** Seamless switching between local inference (Ollama) and cloud providers (Anthropic Claude, OpenAI GPT, Google Gemini, Cerebras) through a unified API abstraction layer.
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

### 2. Local Model Deployment (Ollama)

If utilizing local inference, install and launch the desired model via Ollama:

##### For example, we pull the popular `mistral` model

```bash
ollama pull mistral
```

### 3. Configuration

Copy the environment template and fill in the values you need:

```bash
cp .env.example .env
```

At minimum, set a local model **or** at least one cloud API key + model pair:

```ini
JARVIS_SANDBOX="sandbox/"

# Local inference (requires Ollama running)
JARVIS_LOCAL_MODEL="mistral"

# Cloud providers — fill in the ones you use, leave the rest empty
JARVIS_ANTHROPIC_API_KEY="your-api-key-here"
JARVIS_ANTHROPIC_MODEL="claude-sonnet-4-20250514"

JARVIS_GEMINI_API_KEY="your-api-key-here"
JARVIS_GEMINI_MODEL="gemini-2.5-flash"

JARVIS_GPT_API_KEY="your-api-key-here"
JARVIS_GPT_MODEL="gpt-4o"

JARVIS_CEREBRAS_API_KEY="your-api-key-here"
JARVIS_CEREBRAS_MODEL="llama-4-scout-17b-16e-instruct"
```

---

## Google Workspace Integration

###### Optional — lets Jarvis read and manage your Google Calendar events

1. In the Google Cloud Console, go to **Google Auth platform** > [Branding](https://console.cloud.google.com/auth/branding):

- Under App Information, in App name, enter a name `Jarvis` for the app
- Add your support email where you can be notified about any changes to your project
- Also add your email address to `Developer contact information` to have access to this project
- **Save** the branding

2. Create OAuth credentials for a desktop application:

- In the Google Cloud Console, go to **Google Auth platform** > [Clients](https://console.cloud.google.com/auth/clients)
- Click **Create Client**
- Set **Application type** to **Desktop app** and give it any name
- Click **Create**
- Download the JSON file, rename it to `credentials.json` if needed, and move it to `src/jarvis/tools/google/`

---

## Usage

Start the assistant:

```bash
uv run jarvis
```

---

## Keybindings & Controls

Jarvis registers global keyboard hooks to enable runtime control without interrupting active terminal workflows:

| Key      | Action              | Description                                                                                                      |
| :------- | :------------------ | :--------------------------------------------------------------------------------------------------------------- |
| **`F1`** | Cycle Active Model  | Switches across available backends (`local`, `claude`, `gemini`, `gpt`, `cerebras`) based on active credentials. |
| **`F2`** | Toggle Microphone   | Enables or disables audio input capture and wake word detection.                                                 |
| **`F3`** | Toggle Audio Output | Enables or mutes voice synthesis playback.                                                                       |

---

## Configuration Reference

All settings are resolved through `pydantic-settings` and can be supplied as system environment variables or inside the `.env` file with the `JARVIS_` prefix.

| Parameter                  | Type        | Default     | Description                                             |
| :------------------------- | :---------- | :---------- | :------------------------------------------------------ |
| `JARVIS_DEBUG`             | `bool`      | `true`      | Enables verbose debug logging and stack diagnostics.    |
| `JARVIS_SANDBOX`           | `Path`      | `./sandbox` | Root directory boundary for file system operations.     |
| `JARVIS_LOCAL_MODEL`       | `SecretStr` | `None`      | Model identifier for the local Ollama runtime.          |
| `JARVIS_ANTHROPIC_API_KEY` | `SecretStr` | `None`      | API key for Anthropic Claude.                           |
| `JARVIS_ANTHROPIC_MODEL`   | `SecretStr` | `None`      | Anthropic model name (e.g. `claude-sonnet-4-20250514`). |
| `JARVIS_GEMINI_API_KEY`    | `SecretStr` | `None`      | API key for Google Gemini.                              |
| `JARVIS_GEMINI_MODEL`      | `SecretStr` | `None`      | Gemini model name (e.g. `gemini-2.5-flash`).            |
| `JARVIS_GPT_API_KEY`       | `SecretStr` | `None`      | API key for OpenAI GPT.                                 |
| `JARVIS_GPT_MODEL`         | `SecretStr` | `None`      | GPT model name (e.g. `gpt-4o`).                         |
| `JARVIS_CEREBRAS_API_KEY`  | `SecretStr` | `None`      | API key for Cerebras.                                   |
| `JARVIS_CEREBRAS_MODEL`    | `SecretStr` | `None`      | Cerebras model name.                                    |

---
