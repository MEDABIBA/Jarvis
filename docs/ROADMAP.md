# ROADMAP:

> **Later sections assume that earlier ones have landed**

## CI/CD

- **Add prettier config**

- **Add types and lint checker on main branch & pull requests**

- **Write the first tests that cover jarvis running**

## Core runtime

- **Behavior in case of failures**

  > Ollama is not running, no network connection, tool threw an exception

- **Handle Gemini and GPT backends**

  > Add Gemini and GPT branches into the `call_llm()` function

- **Ability to _*interrupt*_ Jarvis with your voice while he`s answering**

  > Stop playback and cancel the in-flight turn when the user starts speaking

- **Persist a short chat history across restarts**

  > Compacted history written after each turn (not on exit — crashes skip `finally`),
  > tool results dropped, size bounded by a token budget

- **Voice adjustment directly in bot runtime**

  > Setup the timbre, speech rate asking Jarvis directly

## Optimization

- **Dispatch tool calls asynchronously**

  > Set the tools execution to answer stream to not block the main stream

- **Split tools into groups with lazy load**

  > To make it easier to find model desired tools - **_decrease token usage_** and **_select the accurate tool_**

- **Summary of previous messages**

  > Make a quick summary if history is too long

- **Stream the TTS output by sentences**

  > Stream the TTS output for quickness prompt response

## File system access

- **Improve sandbox, switch to requiring user confirmation for tools to access the file system**

## Tools

- **Fix current time getter tool**

- **Location getter**

  > Resolve approximate location

- **Weather report**

- **Ability to take pictures and screenshots**

- **Make a schedule function that can schedule tasks for user**

  > Function must schedule a note, and return it to user when the time had passed

- **PDF Conversion**

  > Convert DOCX/XLSX/PPTX/HTML/JPG/PNG and other formats to PDF or PDFs to other formats (htmltopdf, pdf to images)

- **Image Processing**

  > Upload, edit, and convert images (imgur, image to pdf, image compressor)

- **File Management**

  > Finish to make File management - a tool that searches files by content (grep)

- **Get computer specifications**

  > battery, dns forward, dns reverse, hostinfo, ip, scan_network, speedtest, os, check ram, system info

- **Fetch information from browser to get a up-to-date info about sports/news/..etc**

## Integrations

- **Connect the assistant to Discord or Telegram**
  > Connect the assistant to API to communicate with Jarvis remotely
