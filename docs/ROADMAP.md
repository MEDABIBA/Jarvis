# Roadmap

> **Later sections assume that earlier ones have landed**

## CI/CD

- [x] **Add types and lint checker on main branch & pull requests**

- **Write the first tests that cover jarvis running**

## Core runtime

- [x] **Behavior in case of failures**

  > Ollama is not running, no network connection, tool threw an exception

- [x] **Replace per-provider branches with an OpenAI-compatible protocol**

  > One branch with a configurable base_url in `call_llm()` instead of a case per provider

- [x] **Create `MEMORY.md` and `USER.md`**

  > Two files holding a brief summary of the chat and of the user

- [x] **Add `remember()` and `forget()` tools**

  > Tools that write and remove notes in `MEMORY.md` and `USER.md`

- **Write compacted history after every _n_ prompts**

- **Store all conversations in a SQLite FTS5 database**

  > Full history on disk, looked up through a `search_history()` tool

- **Stream the model answer and the TTS output by sentences**

  > Start speaking before the full answer is generated, to cut time to first sound

- **Ability to _*interrupt*_ Jarvis with your voice while he's answering**

  > Stop playback and cancel the in-flight turn when the user starts speaking

- **Task Scheduler**

  > Let the model set an alarm or schedule an event
  > Schedule a note and return it to the user when the time has passed

- **Voice adjustment directly in bot runtime**

  > Setup the timbre, speech rate asking Jarvis directly

## Optimization

- **Dispatch tool calls asynchronously**

  > Execute tools without blocking the main answer stream

- **Split tools into groups with lazy load**

  > Make it easier for the model to find the right tool - **_decrease token usage_** and **_select the accurate tool_**

- **Summary of previous messages**

  > Make a quick summary if history is too long

## File system access

- **Improve the sandbox: require user confirmation before tools access the file system**

## Tools

- **Fix current time getter tool**

- **Location getter**

  > Resolve approximate location

- **Weather report**

- **Ability to take pictures and screenshots**

- **PDF Conversion**

  > Convert DOCX/XLSX/PPTX/HTML/JPG/PNG and other formats to PDF or PDFs to other formats (htmltopdf, pdf to images)

- **Image Processing**

  > Upload, edit, and convert images (imgur, image to pdf, image compressor)

- **File Management**

  > Finish file management: a tool that searches files by content (grep)

- **Get computer specifications**

  > battery, dns forward, dns reverse, hostinfo, ip, scan_network, speedtest, os, check ram, system info

- **Fetch information from the browser to get up-to-date info about sports/news/..etc**

## Integrations

- **Connect the assistant to Discord or Telegram**

  > Connect the assistant to an API to communicate with Jarvis remotely
