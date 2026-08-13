# Jarvis

Jarvis — a voice-controlled AI assistant with file system access.
Listens for the wake word "jarvis", speaks its answers back
(Piper TTS, EN/RU/PL), and can search, read, create, edit and
delete files within a configured sandbox directory. Runs locally
through Ollama or via API against Claude, Gemini and GPT.

##

### First launch:

- uv sync
- Download ollama `https://ollama.com/download`
- Download the compatible LLM model depending on your system `https://ollama.com/library`
- Download the voices Piper in the Jarvis folder
- Create an .env file and fill it out
- Start the application in the terminal by command `uv run jarvis.py`

##

### Voices

Download the Piper voices before first run:

    python -m piper.download_voices en_GB-alan-medium --download-dir voices/EN
    python -m piper.download_voices ru_RU-denis-medium --download-dir voices/RU
    python -m piper.download_voices pl_PL-bass-high --download-dir voices/PL

##

### Usage

F1 - Switch the model
F2 - Turn on/off the microphone
F3 - Turn on/off the voice
