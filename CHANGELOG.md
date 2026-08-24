# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Release artifacts are attached to [GitHub Releases](https://github.com/shgeum/VRCLT/releases)
as `vrclt-v<version>-windows-x64.exe` plus a `.sha256` checksum.

## [0.18.1] - 2026-08-24

### Fixed

- **Raw microphone passthrough could sound robotic or repeatedly cut out.**
  The Pico input and VB-Cable output are independently clocked devices, but
  passthrough previously ran with no jitter cushion and ignored PortAudio's
  output-underflow signal.  Passthrough now starts with a 40 ms cushion,
  rebuilds that cushion after starvation/underflow, and opens the output at
  its endpoint-default rate with an in-process resampler when needed.  TTS and
  inbound playback retain their existing buffering behavior.
- Microphone callback status/gaps and passthrough queue/underflow/write timing
  are summarized in the normal INFO log so another device-specific failure is
  distinguishable from a network or VRChat problem.

## [0.18.0] - 2026-08-24

### Fixed

- **The microphone was always opened at 48 kHz**, whatever rate the device
  actually runs at, which pushed a sample-rate conversion into the driver. On
  hardware with an unusual rate — a 30 kHz headset-link mic, for instance — that
  conversion against a fixed 10 ms block produced audible chopping. The stream
  is now opened at the device's own rate and resampled here instead; the
  passthrough still leaves at 48 kHz, so nothing downstream changes. Devices
  already running at 48 kHz behave exactly as before.

## [0.17.0] - 2026-08-11

### Added

- **OpenAI realtime translation engine.** `provider: openai` runs both pipelines
  on OpenAI's dedicated `/v1/realtime/translations` endpoint with
  `gpt-realtime-translate` — speech-to-speech, returning translated audio and
  transcript deltas while the source audio is still arriving.
  - The ASR that produces the original-language line inside the same session
    is chosen per pipeline, since the two sides display it differently:
    `openai.transcribe_model` (default `gpt-realtime-whisper`) feeds the
    outbound chatbox, which prints the source above the translation, while
    `openai.inbound_transcribe_model` (default empty) leaves subtitles
    translation-only. Each is billed per minute on top of the translation.
  - `openai.noise_reduction` picks server-side input noise reduction:
    `near_field` (headset), `far_field` (room mic), or empty to disable.
  - The API key comes from Settings or the `OPENAI_API_KEY` environment
    variable, and the first-run setup banner links to the OpenAI key page.
  - Known limits of this model: **13 output languages**
    (`en es pt fr ja ru zh de ko hi id vi it`), one target language per session
    (changing it reconnects), plain `zh` only, no glossary or voice selection
    (the voice adapts to the speaker), and no barge-in.
  - The spoken-language settings are ignored — this model always auto-detects
    across its 70+ input languages, like Gemini and unlike Qwen.
- **Cross-platform groundwork.** Every OS difference now lives in
  `vrclt/platform_support.py`, so the rest of the app is platform-free. Windows
  behavior is unchanged; macOS and Linux get their own audio host API, user-data
  location, and process naming, and Win32-only extras report themselves
  unavailable instead of raising.
  - Audio devices resolve through a per-platform host API order (WASAPI →
    DirectSound → MME on Windows, Core Audio on macOS, PulseAudio → ALSA → JACK
    on Linux) instead of being pinned to WASAPI.
  - Config, logs, and the downloaded Silero VAD model move to the platform's
    per-user data directory (`%LOCALAPPDATA%\vrclt` on Windows, unchanged).
  - The default loopback device hint follows the platform: VB-Cable
    (`CABLE Input`) on Windows, BlackHole on macOS.
  - Global hotkeys, the audio-session process picker, and SteamVR registration
    are gated behind capability checks rather than `os.name` tests.
- **Capture diagnostics.** The inbound capture used to log two lines in its
  whole lifetime, so a capture that broke after starting left no trace at all.
  It now reports the scope and format it actually got on start
  (`process-scoped`/`SYSTEM-WIDE`, `format=48000Hz/2ch/32bit`), a summary every
  15 seconds (`calls`, seconds of audio, VAD pass rate, queue depth, dropped
  chunks, errors), and a one-time warning when audio stops arriving for a
  minute. Conversion failures log the first few in full and are counted after
  that instead of flooding the log.
- The periodic memory diagnostics line now carries the change since the last
  tick, the OS handle count, and whether the VR renderer is running — enough to
  tell a native heap leak from a handle leak without another build.
- Smoke tests for the platform layer and for the OpenAI session, the latter
  driving a mock realtime endpoint that asserts the auth header, session
  configuration, 24 kHz audio, transcript deltas, and the close handshake.

### Fixed

- **Inbound capture could silently record the whole desktop.** The ProcTap
  library answers a failed per-process activation by opening a system-wide
  loopback on the default output device — every application, plus vrclt's own
  translated voice — and reports success either way. Nothing surfaced it, so
  affected users saw all system audio subtitled in every app mode.
  - vrclt now verifies that the capture it got is genuinely process-scoped and
    refuses the fallback by default, logging `process-scoped` or `SYSTEM-WIDE`
    on every tap start.
  - Set `inbound.allow_system_audio: true` to accept whole-desktop capture
    where per-process capture is unavailable. Note that this also breaks the
    echo-proofing, since the translated voice is re-captured.
  - The reproducible trigger is ProcTap's Windows build gate, which no Windows
    10 build can pass (WASAPI process loopback requires build 20348+), but six
    other failure paths can trigger the same fallback on Windows 11.

- **The chatbox reset itself during long conversations.** Rolling-bubble
  sentences expired on absolute age, so a sentence 15 seconds old vanished
  mid-conversation and the bubble appeared to restart. Entries now expire on a
  gap in the conversation: while talking continues the bubble only rolls by
  length, and a real pause still clears it.

### Changed

- The engine comparison table and configuration reference in all four READMEs
  now cover three engines.

## [0.16.0]

### Added

- Custom app mode: capture any application, chosen from the processes that
  currently hold a Windows audio session, with the ones playing sound listed
  first. The capture-process picker was reworked around the same list.

### Fixed

- Memory-leak paths on runtime stop and restart, with a periodic diagnostics
  line (RSS, VMS, threads, GC objects, listener counts) written to the log for
  leak hunting.

## [0.15.0]

### Added

- Log tab: follow-tail, level filter, search, and an open-folder button.
- Settings tab: schema-driven field specs, numeric widgets with validation and
  defaults, plus a search filter that preserves scroll and focus position.
- VR panels: a language grid picker on both the wrist and dashboard panels,
  hover and pressed button states, restart progress feedback, a subtitle armed
  indicator, and two-corner overlay resizing with hover.
- Application icon and a version-stamped window title.
- Offscreen smoke suite covering the Qt UI, settings form, log panel, and VR
  renders.

### Changed

- Qt UI internals: registry-based retranslation, state-driven QSS instead of
  per-refresh inline stylesheets, a split dashboard builder, shared color
  tokens in `ui/theme.py`, and a declarative VR button table.

## [0.14.0]

### Added

- **Qwen3.5 LiveTranslate engine** (Alibaba Cloud Model Studio / DashScope) as
  an alternative to Gemini for regions without Google access, including
  workspace-scoped endpoints (`qwen.workspace_id` / `qwen.base_url`),
  server-side voice cloning, provider and source-language pickers in Settings,
  the dashboard, and the SteamVR panel.
- Sentence-streaming chatbox output (`osc.stream_sentences`, on by default).

### Fixed

- Qwen turn boundaries: client-side gates strip the silence the server's VAD
  needs, so pauses are reconstructed in real time instead of committing turns
  manually.

### Changed

- Provider-neutral `session_base` extracted so neither engine imports the other.

## [0.13.0]

### Changed

- Subtitle overlay and wrist UI reworked for pointer handling and settings
  management.

## [0.12.0]

### Changed

- Audio device management improvements and README updates.

## [0.11.0]

### Added

- SteamVR dashboard settings panel.
- Registration as a SteamVR startup app, with an auto-launch toggle.

### Fixed

- VR overlays stay alive across runtime restarts (no more wrist-menu blink).

---

Entries for 0.16.0 and earlier were reconstructed from commit history after the
fact and are less granular than 0.17.0. Versions before 0.11.0 are not covered
here; see the commit log and the GitHub Releases page.
