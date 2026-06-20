# vrclt

언어: [English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [中文](README.zh.md)

`vrclt`는 VRChat과 Discord용 Windows 실시간 번역 도구입니다. Gemini Live API로
내 마이크를 번역하고, 번역 음성을 VB-Audio Virtual Cable을 통해 대상 앱의
마이크 입력으로 보내며, 상대방 음성은 번역 자막으로 표시합니다.

## 주요 기능

- 대시보드, 설정, 로그/정보 탭을 가진 Windows 자체 UI
- 창 열기, 설정 열기, 번역/자막 토글, 종료를 제공하는 트레이 메뉴
- 아웃바운드 번역: 내 마이크 -> Gemini Live -> 번역 음성 -> 대상 앱 마이크
- 인바운드 자막: 대상 앱 오디오 -> Gemini Live -> 번역 자막
- VRChat OSC 챗박스, 아바타 OSC 제어, SteamVR 자막, 손목 메뉴 지원
- 원래 목소리는 그대로 보내고 OSC 챗박스 번역 텍스트만 추가하는 VRChat 텍스트 전용 모드
- Discord 프로세스 오디오 캡처와 VRChat 전용 기능 자동 비활성화
- 단일 exe 빌드: `dist\vrclt.exe`
- 사용자 설정 저장 위치: `%LOCALAPPDATA%\vrclt\config.yaml`

## 요구사항

- Windows 11 권장
- Google Gemini API 키 (아래 발급 방법 참고)
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)
- VR 오버레이와 손목 UI를 사용할 경우 SteamVR
- VRChat 챗박스/아바타 제어를 사용할 경우 VRChat OSC 활성화
- 소스 실행 시 Python 3.12

### Gemini API 키 발급 방법

1. [Google AI Studio](https://aistudio.google.com/)에 접속합니다.
   - Google 계정으로 로그인합니다. 계정이 없으면 새로 만듭니다.
2. 왼쪽 사이드바 하단 또는 상단의 **Get API key** 버튼을 클릭합니다.
   - 또는 직접 [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)로 이동합니다.
3. **Create API key** 버튼을 클릭합니다.
4. API 키를 사용할 Google Cloud 프로젝트를 선택합니다.
   - 기존 프로젝트가 없다면 **Create API key in new project**를 선택하면 자동으로 생성됩니다.
5. 생성된 API 키(`AIza...`로 시작하는 문자열)를 복사합니다.
   - 키는 한 번만 표시되므로 안전한 곳에 보관합니다.
6. 복사한 키를 `vrclt` 설정 탭의 **API 키** 항목에 붙여넣거나,
   `config.yaml`의 `gemini.api_key` 값으로 설정합니다.

> **참고**: Gemini API는 무료 티어(분당 요청 수 제한)가 있어 개인 사용에는 충분합니다.
> API 키는 타인에게 공유하지 않습니다. `config.yaml`에 평문으로 저장되므로 파일을 공개 저장소에 올리지 마세요.

## 빠른 시작

### 릴리스 exe

1. `vrclt-v<version>-windows-x64.exe`를 실행합니다.
2. 설정 탭을 엽니다.
3. Gemini API 키, 앱 모드, 마이크, 번역 음성 출력 장치를 설정합니다.
4. 번역 음성 출력 장치는 `CABLE Input`을 사용합니다.
5. VRChat 또는 Discord의 마이크 입력을 **CABLE Output (VB-Audio Virtual Cable)**으로 설정합니다.
6. 설정을 저장합니다. 런타임은 자동으로 재시작됩니다.

릴리스 exe는 설정을 다음 위치에 저장합니다.

```text
%LOCALAPPDATA%\vrclt\config.yaml
```

API 키는 이 파일에 평문으로 저장됩니다.

### 소스 체크아웃

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m vrclt run --app vrchat
```

소스 체크아웃은 저장소 루트의 `config.yaml`을 읽습니다. 앱을 열기 전에 로컬
기본값을 만들고 싶다면 `config.example.yaml`을 복사합니다.

```powershell
Copy-Item config.example.yaml config.yaml
```

개발/디버그 용도로 `VRCLT_CONFIG` 환경 변수를 사용해 설정 경로를 강제로 지정할 수 있습니다.

## 앱 모드

| 모드 | 대상 | 동작 |
| --- | --- | --- |
| `vrchat` | VRChat | `VRChat.exe` 오디오 캡처, OSC 챗박스, 아바타 OSC 제어, SteamVR 자막, 손목 UI 활성화 |
| `discord` | Discord | `Discord.exe` 오디오 캡처, VRChat OSC/SteamVR 기능 비활성화, 자체 UI 유지 |

설정에서 모드를 고르거나 실행 한 번에만 인자로 지정할 수 있습니다.

```powershell
.\vrclt.exe run --app vrchat
.\vrclt.exe run --app discord
```

VRChat에서 텍스트 전용으로 쓰려면 대시보드 또는 설정의 **텍스트 전용**을
켭니다. 원래 마이크 음성은 VRChat으로 그대로 passthrough되고, Gemini 번역 결과는
번역 음성 없이 OSC 챗박스 텍스트로만 전송됩니다.

Discord Canary 또는 PTB를 사용한다면 설정 또는 `app.profiles.discord.process`에서
프로세스 이름을 바꿉니다.

## 자체 UI

대시보드:

- 런타임 상태와 연결 상태
- VRChat/Discord 모드 토글과 VRChat 텍스트 전용 토글
- 번역 ON/OFF
- 자막 ON/OFF
- 출력 언어와 자막 언어, Gemini Live Translation 70개 이상 지원 언어 검색/추가
- PC 자막 위치 이동/리셋과 글자 크기 조절
- 실시간 자막 미리보기

설정:

- API 키와 모델
- 앱 모드와 대상 프로세스
- 마이크, 번역 음성 출력, 모니터 출력, 인바운드 오디오 장치
- 기본 도착어와 저장된 언어 목록
- 오디오 임계값과 VAD 설정
- OSC, 챗박스, SteamVR 오버레이, 손목 UI 옵션
- UI 언어와 UI 모드

로그/정보:

- 현재 설정 경로
- 현재 로그 파일 경로
- 최근 로그 내용

창을 닫으면 앱은 트레이로 숨겨집니다. 런타임을 멈추고 완전히 종료하려면 트레이의
`Quit` 또는 `종료` 동작을 사용합니다.

## 오디오 라우팅

아웃바운드 번역:

```text
microphone -> Gemini Live -> translated voice -> CABLE Input
                                     target app mic <- CABLE Output
```

인바운드 자막:

```text
target app process audio -> ProcTap -> Gemini Live -> subtitles
```

번역이 OFF이면 마이크는 Gemini를 거치지 않고 `CABLE Input`으로 바로 전달됩니다.
VRChat **텍스트 전용**에서는 원래 목소리가 항상 passthrough되고, 번역 토글은
Gemini 텍스트 번역과 챗박스 출력만 제어합니다.

## VRChat 기능

VRChat 모드에서는 다음 기능을 사용할 수 있습니다.

- 번역 텍스트 OSC 챗박스 출력
- `VRCLT_Enabled`, `VRCLT_Lang` 같은 아바타 OSC 파라미터
- 인바운드 자막용 SteamVR 자막 오버레이
- VR 안에서 제어할 수 있는 SteamVR 손목 메뉴

`ui.mode: auto`에서는 SteamVR이 실행 중일 때 VR 기능이 활성화됩니다. 강제로 VR
오버레이를 켜려면 `ui.mode: vr`, 끄려면 `ui.mode: desktop`을 사용합니다.

## 파일과 경로

| 항목 | 릴리스 exe | 소스 체크아웃 |
| --- | --- | --- |
| 설정 | `%LOCALAPPDATA%\vrclt\config.yaml` | 저장소 루트의 `config.yaml` |
| 설정 경로 강제 지정 | `VRCLT_CONFIG` | `VRCLT_CONFIG` |
| 로그 | `%LOCALAPPDATA%\vrclt\logs\vrclt.log` | `%LOCALAPPDATA%\vrclt\logs\vrclt.log` |
| 빌드 결과 | `dist\vrclt.exe` | `dist\vrclt.exe` |

`config.yaml`, `.venv/`, `build/`, `dist/`, `release/`, 로그 파일은 Git에 올리지 않습니다.

## 설정값 설명

모든 값은 `config.yaml`에 저장됩니다. 릴리스 빌드는 위 AppData 경로를 사용하고,
소스 체크아웃은 `VRCLT_CONFIG`를 지정하지 않는 한 저장소 루트의 `config.yaml`을 사용합니다.

기본값과 앱 프로필:

| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `api_key` | `""` | Gemini API 키. 비어 있으면 `GEMINI_API_KEY` 환경 변수를 사용할 수 있습니다. |
| `model` | `gemini-3.5-live-translate-preview` | Gemini Live 모델 이름. |
| `log_level` | `INFO` | Python 로그 레벨. |
| `app.mode` | `vrchat` | 활성 프로필: `vrchat` 또는 `discord`. |
| `app.profiles.<mode>.process` | `VRChat.exe` / `Discord.exe` | 인바운드 자막용으로 캡처할 프로세스. |
| `app.profiles.<mode>.ui_mode` | `auto` / `desktop` | 프로필이 적용하는 UI 모드. |
| `app.profiles.<mode>.voice_output` | `true` | 번역 음성 출력을 켭니다. |
| `app.profiles.<mode>.passthrough_while_translating` | `false` | 번역 중에도 원본 마이크 음성을 보냅니다. |
| `app.profiles.<mode>.chatbox` | `true` / `false` | VRChat OSC 챗박스 출력을 켭니다. |
| `app.profiles.<mode>.osc_control` | `true` / `false` | 아바타 OSC 제어 리스너를 켭니다. |
| `app.profiles.<mode>.vr_overlay` | `true` / `false` | SteamVR 자막 오버레이를 켭니다. |
| `app.profiles.<mode>.wrist_ui` | `true` / `false` | SteamVR 손목 메뉴를 켭니다. |

대시보드 상태:

| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `dashboard.translation_on` | `true` | 마지막으로 저장된 대시보드 번역 토글 상태. |
| `dashboard.subtitles_on` | `true` | 마지막으로 저장된 대시보드 자막 토글 상태. |

아웃바운드 번역:

| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `outbound.enabled` | `true` | 아웃바운드 파이프라인을 켭니다. |
| `outbound.target_language` | `ja` | 내 말 번역의 기본 BCP-47 언어 코드. UI에서 Gemini Live Translation 70개 이상 지원 언어를 검색해 선택할 수 있습니다. |
| `outbound.echo_target_language` | `false` | 이미 대상 언어인 입력도 따라 말합니다. |
| `outbound.mic_device` | `""` | 마이크 장치 이름 일부. 비어 있으면 기본 입력을 사용합니다. |
| `outbound.tts_device` | `CABLE Input` | 번역 음성과 원음 전달을 내보낼 출력 장치. |
| `outbound.monitor_device` | `""` | 번역 음성을 내가 들을 모니터 출력 장치. |
| `outbound.text_only` | `false` | VRChat 텍스트 전용 모드. 원음 전달과 번역 챗박스 텍스트만 사용합니다. |
| `outbound.voice_output` | `true` | 번역 TTS 음성 출력을 켭니다. |
| `outbound.passthrough_while_translating` | `false` | 번역 활성 상태에서도 원본 마이크 음성을 보냅니다. |
| `outbound.chatbox` | `true` | 번역 텍스트를 VRChat OSC 챗박스로 보냅니다. |

인바운드 자막:

| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `inbound.enabled` | `true` | 자막용 프로세스 오디오 캡처를 켭니다. |
| `inbound.target_language` | `ko` | 기본 자막 BCP-47 언어 코드. UI에서 Gemini Live Translation 70개 이상 지원 언어를 검색해 선택할 수 있습니다. |
| `inbound.languages` | `[ko, en, ja]` | 대시보드와 손목 메뉴에서 사용할 저장된 자막 언어 목록. UI 선택기에서 필요한 언어만 추가합니다. |
| `inbound.process` | `VRChat.exe` | 인바운드 자막용으로 캡처할 프로세스 이름. |
| `inbound.play_audio` | `false` | 인바운드 번역 음성을 내 헤드폰으로 재생합니다. |
| `inbound.audio_device` | `""` | 인바운드 번역 음성 출력 장치. 비어 있으면 기본 출력을 사용합니다. |
| `inbound.vad_enabled` | `true` | 배경음악/잡음을 줄이기 위해 음성 활동 감지를 사용합니다. |
| `inbound.vad_threshold` | `0.5` | `0`부터 `1`까지의 VAD 엄격도. 높을수록 비음성을 더 많이 거릅니다. |
| `inbound.vad_hangover_sec` | `0.6` | 말이 멈춘 뒤 잠깐 더 캡처를 유지하는 시간. |

오버레이와 OSC:

| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `overlay.enabled` | `true` | SteamVR 자막 오버레이를 켭니다. |
| `overlay.width_m` | `0.9` | 자막 오버레이 너비(m). |
| `overlay.distance_m` | `1.2` | HMD 기준 자막 오버레이 거리(m). |
| `overlay.below_m` | `0.35` | HMD 아래쪽 오프셋(m). |
| `overlay.tilt_deg` | `-15.0` | 오버레이 기울기 각도. |
| `overlay.transform` | `null` | VR에서 위치를 다시 잡으면 자동 저장되는 정확한 3x4 자막 위치. |
| `overlay.font` | `bundled:NotoSansCJKkr-Regular.otf` | 자막 오버레이 폰트. |
| `overlay.font_size` | `44` | 자막 글자 크기. |
| `overlay.display_sec` | `7.0` | 확정된 자막 줄이 남아 있는 시간. |
| `overlay.lines` | `3` | 화면에 유지할 최근 확정 자막 줄 수. |
| `overlay.show_source` | `false` | 자막에 원문도 함께 표시합니다. |
| `osc.ip` | `127.0.0.1` | VRChat OSC 대상 IP. |
| `osc.port` | `9000` | VRChat OSC 대상 포트. |
| `osc.throttle_sec` | `1.5` | 챗박스 최소 전송 간격. |
| `osc.notification_sfx` | `false` | VRChat 챗박스 알림음을 요청합니다. |
| `osc.show_source` | `true` | 챗박스에서 번역 위에 원문을 표시합니다. |
| `osc.chunk_display_sec` | `4.0` | 긴 챗박스 메시지를 나눠 보여줄 때 조각별 표시 시간. |

오디오, 제어, UI, 손목 메뉴:

| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `audio.send_interval_ms` | `100` | 마이크 오디오를 Gemini로 보내는 주기. |
| `audio.finalize_silence_sec` | `2.0` | 이만큼 침묵하면 세그먼트를 확정합니다. |
| `audio.mic_idle_disconnect_sec` | `15.0` | 마이크 입력이 없을 때 Gemini 세션을 끊는 시간. |
| `audio.voice_rms_threshold` | `90.0` | 마이크 음성 감지 에너지 임계값. |
| `audio.voice_hangover_sec` | `2.5` | 짧은 멈춤 동안 마이크 턴을 유지하는 시간. |
| `audio.echo_guard_multiplier` | `4.0` | 대상 앱 오디오가 활성일 때 마이크 게이트를 높이는 배수. `1.0`이면 비활성. |
| `control.enabled` | `true` | 아바타 OSC 제어 입력을 켭니다. |
| `control.osc_listen_port` | `9001` | 아바타 제어 파라미터를 받을 로컬 OSC 포트. |
| `control.param_enabled` | `VRCLT_Enabled` | 번역 ON/OFF용 아바타 bool 파라미터. |
| `control.param_lang` | `VRCLT_Lang` | 언어 인덱스용 아바타 int 파라미터. |
| `control.languages` | `[ja, en, ko, zh-Hans, zh-Hant, yue, es, ru, fr, de]` | 대시보드, 아바타, 손목 제어에서 사용할 저장된 출력 언어 목록. UI 선택기에서 필요한 언어만 추가합니다. |
| `control.feedback_chatbox` | `true` | 제어 변경 피드백을 VRChat 챗박스로 보냅니다. |
| `ui.mode` | `auto` | `auto`, `vr`, `desktop` 중 하나. |
| `ui.lang` | `""` | UI 표시 언어. 비어 있으면 자동이며 `en`, `ko`, `ja`, `zh`를 사용할 수 있습니다. |
| `ui.close_action` | `tray` | 창 닫기 버튼 동작: `tray` 또는 `exit`. |
| `wrist_ui.enabled` | `true` | SteamVR 손목 메뉴를 켭니다. |
| `wrist_ui.hand` | `left` | 메뉴를 착용할 손: `left` 또는 `right`. |
| `wrist_ui.width_m` | `0.18` | 손목 메뉴 너비(m). |
| `wrist_ui.offset` | `[-0.0509, -0.065, 0.0891]` | 컨트롤러 좌표계의 x,y,z 오프셋. |
| `wrist_ui.tilt_deg` | `185.636` | 얼굴 쪽으로 향하는 추가 기울기. |
| `wrist_ui.roll_deg` | `-28.633` | 평면 회전. `null`이면 손에 따라 자동 회전합니다. |
| `wrist_ui.transform` | saved 3x4 pose | VR에서 위치를 다시 잡으면 자동 저장되는 정확한 3x4 손목 위치. |
| `wrist_ui.pointer_tilt_deg` | `50.0` | 포인터 레이의 아래쪽 기울기 각도. |
| `wrist_ui.font` | `bundled:NotoSansCJKkr-Bold.otf` | 손목 메뉴 폰트. |

## 빌드

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\pyinstaller.exe vrclt.spec --noconfirm
```

빌드 결과:

```text
dist\vrclt.exe
```

릴리스 산출물 생성:

```powershell
.\scripts\package_release.ps1 -Version 0.1.0
```

릴리스 스크립트 결과:

```text
release\vrclt-v0.1.0-windows-x64.exe
release\vrclt-v0.1.0-windows-x64.exe.sha256
```

## 스모크 테스트

```powershell
.\.venv\Scripts\python.exe -m compileall vrclt
.\.venv\Scripts\python.exe -m vrclt --help
.\.venv\Scripts\pyinstaller.exe vrclt.spec --noconfirm
.\scripts\package_release.ps1 -Version 0.1.0 -SkipBuild
```

실제 런타임 테스트는 exe 실행, 자체 UI에서 설정 저장,
`%LOCALAPPDATA%\vrclt\config.yaml` 생성 확인, 대상 앱이 `CABLE Output`에서
오디오를 받는지 확인하는 순서로 진행합니다.

## 문제 해결

- 대상 앱에 번역 음성이 안 들어감: `outbound.tts_device`가 `CABLE Input`인지, 대상 앱 마이크가 `CABLE Output`인지 확인합니다.
- 인바운드 자막이 안 뜸: 대상 프로세스 이름이 실제 실행 중인 앱과 맞는지 확인합니다. 예: `VRChat.exe`, `Discord.exe`.
- API 키 필요 상태: 설정에 키를 입력하거나 `GEMINI_API_KEY`를 설정합니다.
- VR 오버레이가 안 뜸: SteamVR이 실행 중이고 `overlay.enabled` / `wrist_ui.enabled`가 켜져 있는지 확인합니다.
- 설정을 초기화하고 싶음: 앱을 닫고 `%LOCALAPPDATA%\vrclt\config.yaml`을 다른 이름으로 옮긴 뒤 다시 실행합니다.

## 감사

- [Noto Sans CJK](https://github.com/notofonts/noto-cjk)와 [Pretendard](https://github.com/orioncactus/pretendard): 다국어 UI 폰트 커버리지.
- [PySide6](https://doc.qt.io/qtforpython-6/): Windows 자체 UI.
- [OpenVR](https://github.com/ValveSoftware/openvr), GLFW, PyOpenGL: SteamVR 오버레이 렌더링.
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/): 앱 간 오디오 라우팅.

## 릴리스

릴리스 절차는 [docs/RELEASING.md](docs/RELEASING.md)를 참고합니다.
