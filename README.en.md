# vrclt

Languages: [English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [中文](README.zh.md)

`README.md` is the canonical English README. This file is kept for older links.

See [README.md](README.md).

For Soniox account signup, project API keys, billing balance, app setup,
language selection, and first-run troubleshooting, see
[Soniox API Key](README.md#3c-soniox-api-key). The updated dashboard and
settings navigation are described in [Native UI](README.md#native-ui).

Soniox's `soniox.keep_speaker_context` option is on by default and retains the
session through short pauses, disconnecting after 60 seconds of silence.
Adjust `soniox.speaker_context_idle_sec` in Settings (5–600 seconds). The Soniox
Dashboard shows the synchronized checkbox and effective timeout. Connections
remain billable during silence; speaker diarization stays enabled with either
choice. See the setup section for details.

In v0.19.1, the SteamVR Dashboard groups controls into **Live**, **Audio**, and
**Layout & app** pages; the wrist menu has **Live** and **Settings** pages. The
SteamVR Dashboard includes Qwen spoken-language controls and optional Soniox
recognition hints; the wrist menu selects translation output and subtitle
languages. Both VR panels show Soniox's synchronized speaker-context switch
with the effective silence timeout. See [VRChat Features](README.md#vrchat-features).
