# Speech output

Jarvis streams public assistant text to the terminal and queues sentences for speech.
The LLM does not wait for playback. Tool arguments, tool results, and reasoning
fields are not sent directly to TTS. Public assistant text before a tool call is
spoken as progress; only the final answer is stored as the turn's answer.

## Configuration

Speech is muted at startup. Press **F3** to enable it for the next reply. Muting
stops the current speech session; enabling it again takes effect on the next turn.

The default provider is local Piper. Cloud synthesis is opt-in:

```ini
JARVIS_SPEECH__PROVIDER=azure_sdk
JARVIS_SPEECH__LOCALE=pl-PL
JARVIS_SPEECH__AZURE_KEY=your-speech-resource-key
JARVIS_SPEECH__AZURE_REGION=westeurope
```

Use the key and matching region of an Azure Speech resource. Keep the key in
`.env` or the backend's secret store, never in client code or source control.
Azure receives the text being synthesized and charges according to your resource's
pricing and quota. Selecting `piper` or `text` never falls back to cloud services.

Install and run the optional SDK with:

```sh
uv sync --extra azure
uv run --extra azure jarvis
```

The SDK is imported lazily. If its package or native dependencies are unavailable,
Jarvis can use Azure REST without that extra:

```ini
JARVIS_SPEECH__PROVIDER=azure_rest
```

```sh
uv run jarvis
```

Other provider values are `piper` and `text`. Text mode does not load a voice or
open an output device. The Azure SDK import has been checked on Linux/Python 3.13;
cloud synthesis and device playback still need a test in the deployment environment.

### Local voices and additional languages

Set `JARVIS_VOICES_DIR` to the directory containing Piper models and their matching
configuration files. Default mappings preserve the existing layout:

| Locale | Piper model | Azure voice |
| --- | --- | --- |
| `en-GB` | `EN/en_GB-northern_english_male-medium.onnx` | `en-GB-RyanNeural` |
| `pl-PL` | `PL/pl_PL-mc_speech-medium.onnx` | `pl-PL-MarekNeural` |
| `ru-RU` | `RU/ru_RU-ruslan-medium.onnx` | `ru-RU-DmitryNeural` |

Voice availability depends on the Azure region. Check the resource's voices list
before choosing a voice. To add a language, set its locale and provide the relevant
maps as JSON. Each supplied map **replaces** its default map:

```ini
JARVIS_SPEECH__LOCALE=de-DE
JARVIS_SPEECH__AZURE_VOICES='{"de-DE":"de-DE-ConradNeural"}'
JARVIS_SPEECH__PIPER_VOICES='{"de-DE":"DE/de_DE-thorsten-medium.onnx"}'
```

Piper paths must stay inside the voices directory. Voices are loaded lazily and
cached per locale. A missing local voice leaves text available; Jarvis does not
read an unsupported language with an unrelated voice.

Locale is explicit and fixed for a turn. The old character-based language guessing
has been removed: Polish without diacritics no longer silently selects English.
Set `JARVIS_SPEECH__LOCALE=pl-PL` if Polish is your usual language. URL/email
normalization currently has English, Polish, and Russian vocabularies; other
locales use English normalization until a vocabulary is added in `speech/text.py`.

### Limits

| Setting | Default | Purpose |
| --- | --- | --- |
| `JARVIS_SPEECH__FIRST_AUDIO_TIMEOUT` | `5` | Shared cloud first-audio budget in seconds, per sentence |
| `JARVIS_SPEECH__COOLDOWN` | `30` | Seconds before retrying a failed provider on a later turn |
| `JARVIS_SPEECH__QUEUE_SIZE` | `8` | Maximum pending sentences |
| `JARVIS_SPEECH__MAX_SEGMENT_LENGTH` | `300` | Maximum buffered text segment length |

If speech falls behind and its queue fills, speech is cancelled for that turn;
the text stream continues. This bounds buffering without blocking LLM generation.
Increasing the queue permits longer speech lag. There is no automatic second
LLM request to shorten or rewrite the answer.

## Fallback policy

With `azure_sdk` selected, the candidate order is:

```text
Azure SDK -> Azure REST -> Piper -> text only
```

- SDK/package failures may use REST. Authentication, quota, network, and shared
  Azure service failures skip the remaining Azure adapter.
- Each adapter is tried at most once per sentence. There is no sleep/retry loop.
- Failed providers enter a cooldown. Azure-wide failures affect both Azure adapters;
  provider/voice failures are scoped to the provider and locale. A numeric
  `Retry-After` can extend the cooldown; HTTP-date values are not parsed.
- Cloud attempts share the first-audio deadline. Local synthesis gets a fresh
  first-audio budget so cloud exhaustion does not prevent offline fallback.
  Local model loading/inference is cooperatively checked, not forcibly timed out.
- Once any PCM has been delivered for a response, its provider is pinned. A later
  failure stops speech for the rest of that response, even across sentences.
  Jarvis never restarts already spoken text at another provider.
- The start boundary is the first yielded audio, not a speaker acknowledgement.
  This is intentionally conservative until a remote client can acknowledge playback.
- Device errors and user cancellation never trigger another provider.

## Cancellation

**F4** requests cancellation of the reply and stops further speech. **F3** only
mutes speech; text generation and tool handling continue.

Playback checks cancellation between small PCM writes. Native audio operations
are closed by their owning worker, not concurrently from the keyboard thread.
A stuck native call cannot be killed safely. While an old speech worker is still
stopping, new speech sessions stay disabled rather than accumulating workers.

LLM cancellation is cooperative: the consumer closes the network iterator when
control returns from the current read. Already-running synchronous tools cannot
be interrupted or rolled back. Cancelled partial replies are retained in engine
context but are not inserted as completed answers into the history database.

Voice interruption is not implemented. The existing `is_speaking` gate drops STT
transcriptions during playback; echo cancellation and barge-in need separate work.

## Module boundaries

- `llm/client.py`: provider-specific streams, public text deltas, assembled tool calls.
- `engine.py`: turn events, history, and tool execution. No speaker dependency.
- `runtime.py`: routes public text to a consumer and optional speech output.
- `speech/text.py`: bounded sentence extraction and locale-driven normalization.
- `speech/types.py`: raw signed little-endian int16 PCM and provider contracts.
- `speech/service.py`: fallback, deadlines, provider cooldowns, and per-turn state.
- `speech/azure.py`: SDK/REST synthesis; no output device.
- `speech/piper.py`: lazy local synthesis; no output device.
- `speech/output.py`: bounded local speech worker and lazy `sounddevice` player.
- `speech/tts.py`: local convenience entry point and playback event.

The current Azure adapters accept complete sentences and stream audio. SDK
synthesis uses SSML and a push output stream; it does **not** yet use native
incremental input (`TextStream`). SDK connections are per sentence; REST reuses
its HTTP client. Further latency improvements should measure connection setup,
time to first LLM token, first audio, and first playback separately.

There is no client/backend transport yet. A remote implementation can consume
engine events and `SpeechService` PCM without importing the local player. It
still needs authenticated transport, turn IDs/audio sequence numbers, format
negotiation, playback acknowledgements, and session-scoped model configuration.
The CLI currently uses the existing single-session application state.

## Validation

```sh
uv sync --group test --group lint
uv run --group test pytest
uv run --group lint ruff check --no-fix
uv run --group lint ruff format --check
uv run --group lint ty check
```

Tests use mocked Azure services, local models, and devices. They cover streamed
text/tool assembly, fallback before audio, no replay after audio, fragmented code
fences, locale configuration, queue limits, cancellation, and native resource
ownership. Real voice quality, network latency, regional voice availability, and
physical device behavior require an integration test with an Azure resource and
a speaker.

## References

- [Azure REST text to speech](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech)
- [Speech SDK streaming and latency](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-lower-speech-synthesis-latency)
