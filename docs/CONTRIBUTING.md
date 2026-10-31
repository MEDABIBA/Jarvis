## Getting Started

### Prerequisites

- **Python 3.13+** (see `.python-version`)
- **[uv](https://docs.astral.sh/uv/)** package manager
- **PortAudio** headers (required by `sounddevice`):

```bash
# Fedora / RHEL
sudo dnf install portaudio-devel

# Ubuntu / Debian
sudo apt install portaudio19-dev

# macOS
brew install portaudio
```

- **CUDA 12.x** runtime with cuDNN 9 — needed for `faster-whisper` GPU inference. CPU-only setups will still work but STT will be slower.

### Setup

```bash
# Clone and enter the repo
git clone https://github.com/MEDABIBA/Jarvis.git
cd Jarvis

# Install all dependencies (dev + lint + test groups)
uv sync

# Copy the environment template and fill in your API keys
cp .env.example .env
# Edit .env — at minimum set one JARVIS_*_API_KEY
```

### Running locally

```bash
uv run jarvis
```

This starts the voice assistant with microphone input and terminal prompt. Make sure your audio device is accessible.

---

## Development

### Code Quality & Formatting

Linting, formatting, and type checking are managed via [Ruff](https://github.com/astral-sh/ruff) and [ty](https://github.com/astral-sh/ty):

```bash
# Lint with auto-fix
uv run ruff check --fix

# Format
uv run ruff format

# Type check
uv run ty check
```

### Test Suite

```bash
uv run pytest
```

### CI Pipeline

Every push to `main` and every pull request triggers the GitHub Actions workflow (`.github/workflows/linter.yml`) that runs:

1. `ruff check` (no auto-fix)
2. `ruff format --check`
3. `ty check`

Your PR will not be merged with a failing CI.

---

## Branch & Commit Conventions

### Branches

New features are developed on **separate branches**.

### Commit Messages

Write short imperative messages describing **what** the commit does:

```
Add remember and forget tools
Fix system prompt being dropped in openai-compatible branch
Implement Google Calendar integration (list, insert, delete events)
```

For scoped changes you can optionally use the `type(scope):` prefix:

```
feat(tts): implement pronounceable text formatting for urls
```

---

## Pull Requests

- Open a PR against `main`
- Leave a **brief description** of the completed work
- PR is merged after **2 developer reviews** approve it
- Make sure CI is green before requesting review

---

## Proposing Ideas

Open a new issue with the `enhancement` label.

---

## Adding a New Tool

Tools are plain Python functions registered in [`src/jarvis/tools/registry.py`](../src/jarvis/tools/registry.py). To add one:

1. Write your function in the appropriate module under `src/jarvis/tools/` (or create a new module if it's a new domain). The function **must** have a docstring — the LLM sees it as the tool description.

2. Use Python type hints on every parameter — the adapter converts them to JSON Schema via `TYPE_MAP` in `adapters.py` (`str`, `bool`, `int`, `float`).

3. Import and append your function to `AVAILABLE_TOOLS` in `registry.py`:

```python
from jarvis.tools.my_module import my_tool

AVAILABLE_TOOLS: list[Tool] = [
    # ... existing tools ...
    my_tool,
]
```

That's it — the tool is now available to all LLM backends.

### Sandbox constraint

File-system tools must resolve paths through `safe_path()` from `tools/path.py` to stay inside the sandbox. See [SANDBOX_SECURITY.md](./SANDBOX_SECURITY.md) for details.

## Security

- **Never commit `.env` or any file containing API keys.** The `.gitignore` already excludes `.env`.
- All file operations must stay within `JARVIS_SANDBOX`. See [SANDBOX_SECURITY.md](./SANDBOX_SECURITY.md).
- If you discover a security issue, open a private report instead of a public issue.

---

## Further Reading

- [ARCHITECTURE.md](./ARCHITECTURE.md) — system design, concurrency model, data flow
- [COMPONENTS.md](./COMPONENTS.md) — module-level documentation
- [WORKFLOWS.md](./WORKFLOWS.md) — user-facing workflows and interaction patterns
- [SANDBOX_SECURITY.md](./SANDBOX_SECURITY.md) — sandbox enforcement rules
- [ROADMAP.md](./ROADMAP.md) — planned features and priorities
