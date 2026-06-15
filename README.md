# vrclt — VRChat / Discord Live Translator

언어: [한국어](README.md) | [English](README.en.md)

`vrclt`는 Gemini Live API(`gemini-3.5-live-translate-preview`)를 사용해 내 목소리를
실시간 번역 음성으로 내보내고, 상대방의 말을 자막으로 보여주는 Windows용 번역 도구입니다.
VRChat과 Discord를 모두 지원하며, VB-Audio Virtual Cable을 통해 번역 음성을 대상 앱의 마이크 입력으로 보냅니다.

## 주요 기능

- 내 마이크 입력을 Gemini Live로 번역하고 번역 음성을 `CABLE Input`으로 출력합니다.
- 번역 OFF 시 원래 마이크 소리를 그대로 보내는 패스스루 모드를 제공합니다.
- VRChat 모드에서는 OSC 챗박스 전송, SteamVR 자막 오버레이, 손목 메뉴, 아바타 OSC 파라미터 제어를 사용합니다.
- Discord 모드에서는 Discord 프로세스 오디오 캡처, PC 자막 창, VRChat 전용 기능 자동 비활성화를 사용합니다.
- 상대방 음성은 ProcTap 프로세스 루프백으로 앱별 캡처합니다.
- 웹 설정/제어 UI는 `http://127.0.0.1:8765`에서 사용할 수 있습니다.
- 로컬 설정과 API 키는 Git에 올라가지 않도록 분리합니다.

## 요구사항

- Windows 11을 권장합니다.
- Python 3.12를 권장하며, 3.10-3.13 범위를 지원합니다.
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)이 필요합니다.
- [Gemini API 키](https://aistudio.google.com/apikey)가 필요합니다.
- VR 모드를 사용하려면 SteamVR이 필요합니다.
- VRChat 자막/챗박스 기능을 사용하려면 VRChat OSC를 활성화해야 합니다.

## 설치

1. 저장소를 준비합니다.

```powershell
git clone <repository-url>
Set-Location VRCLT
```

이미 소스 폴더를 받은 상태라면 해당 폴더에서 다음 단계부터 진행합니다.

1. Python 가상환경을 만들고 의존성을 설치합니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

1. 로컬 설정 파일을 만듭니다.

```powershell
Copy-Item config.example.yaml config.yaml
```

`config.yaml`에는 개인 API 키, 장치명, 언어 설정이 들어갑니다. 이 파일은 Git에 커밋하지 않습니다.
공유 가능한 기본값은 [config.example.yaml](config.example.yaml)을 수정합니다.

1. Gemini API 키를 설정합니다.

```powershell
$env:GEMINI_API_KEY = "your-gemini-api-key"
```

이 방식은 현재 PowerShell 세션에만 적용됩니다. 계속 유지하려면 Windows 환경 변수로
`GEMINI_API_KEY`를 등록하거나, 로컬 전용 [config.yaml](config.yaml)의 `api_key`에 넣을 수 있습니다.

1. 장치와 Gemini 연결을 확인합니다.

```powershell
.\.venv\Scripts\python.exe -m vrclt devices
.\.venv\Scripts\python.exe -m vrclt sinetest "CABLE Input"
.\.venv\Scripts\python.exe -m vrclt miccheck
.\.venv\Scripts\python.exe -m vrclt livetest
```

`devices`에서 `VB-Cable: FOUND`가 보여야 합니다. `sinetest`는 대상 앱의 마이크 테스트에서
소리가 들어오는지 확인할 때 사용합니다.

## 빠른 시작

### VRChat

1. VRChat의 마이크 입력 장치를 **CABLE Output (VB-Audio Virtual Cable)**으로 설정합니다.
2. VRChat 액션 메뉴에서 Options -> OSC를 켭니다.
3. [config.yaml](config.yaml)의 `outbound.mic_device`를 실제 마이크에 맞춥니다.
   비워 두면 Windows 기본 입력 장치를 사용합니다.
4. 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m vrclt run --app vrchat
```

`--app vrchat`은 생략할 수 있습니다. 기본값은 [config.yaml](config.yaml)의 `app.mode`이며,
초기 예시는 `vrchat`입니다.

### Discord

1. Discord의 입력 장치를 **CABLE Output (VB-Audio Virtual Cable)**으로 설정합니다.
2. [config.yaml](config.yaml)의 `outbound.tts_device`가 `CABLE Input`인지 확인합니다.
3. `outbound.mic_device`를 실제 마이크 이름 일부로 설정하거나 비워 둡니다.
4. 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m vrclt run --app discord
```

Discord 모드는 데스크톱 자막/컨트롤 창을 사용하며, VRChat OSC 챗박스/아바타 제어/SteamVR UI를 자동으로 끕니다.
Discord Canary 또는 PTB를 사용하는 경우 [config.yaml](config.yaml)의
`app.profiles.discord.process`를 `DiscordCanary.exe` 또는 `DiscordPTB.exe`로 바꿉니다.

## 사용 방법

### 실행 중 제어

- **번역 ON/OFF**: 번역 ON이면 Gemini 번역 음성이 대상 앱으로 나가며, OFF면 원래 마이크가 패스스루로 나갑니다.
- **출력 언어**: 내 말이 번역될 언어입니다. `control.languages` 목록에서 선택합니다.
- **자막 ON/OFF**: 상대방 말 자막 파이프라인을 켜거나 끕니다.
- **자막 언어**: 상대방 말을 어떤 언어로 볼지 정합니다. `inbound.languages` 목록에서 선택합니다.
- **웹 UI**: 실행 중 `http://127.0.0.1:8765`에서 설정 저장, 언어 변경, 실시간 자막 확인을 할 수 있습니다.
- **트레이 아이콘**: `web.tray: true`일 때 빠른 제어와 종료 메뉴를 제공합니다.

### PC / Desktop 모드

SteamVR 없이 실행하거나 `ui.mode: desktop`일 때 항상 위에 뜨는 데스크톱 창 두 개가 표시됩니다.

- 자막 창: 상대방 말 번역 자막을 표시합니다. 비어 있으면 자동으로 숨습니다.
- 컨트롤 바: 번역 토글, 출력 언어, 자막 토글, 자막 언어, 연결 상태, 종료 버튼을 제공합니다.
- 창 위치는 `%LOCALAPPDATA%\vrclt\desktop_layout.json`에 저장됩니다.

데스크톱 UI만 미리 보려면 다음 명령을 사용합니다. API 키는 필요하지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m vrclt desktoptest
```

### VR 모드

`ui.mode: auto`에서 SteamVR이 실행 중이면 VR 모드로 들어갑니다. 강제로 VR 모드를 사용하려면
[config.yaml](config.yaml)의 `ui.mode`를 `vr`로 설정합니다.

VR 모드에서 사용할 수 있는 UI는 다음과 같습니다.

- SteamVR 자막 오버레이: 상대방 말 번역 자막을 HMD 앞쪽에 표시합니다.
- 손목 메뉴: 기본적으로 왼쪽 손목에 붙습니다. 반대쪽 컨트롤러로 가리켜 클릭합니다.
- 아바타 OSC 파라미터: `VRCLT_Enabled`, `VRCLT_Lang`으로 번역 토글과 언어 전환을 할 수 있습니다.

손목 메뉴만 테스트하려면 다음 명령을 사용합니다.

```powershell
.\.venv\Scripts\python.exe -m vrclt wristtest
```

오버레이 위치를 초기화하려면 다음 명령을 사용합니다.

```powershell
.\.venv\Scripts\python.exe -m vrclt resetpos
```

## 앱 모드

앱 모드는 [config.yaml](config.yaml)의 `app.mode` 또는 실행 인자 `--app`으로 선택합니다.
실행 인자가 있으면 실행 중에는 그 값이 우선합니다.

| 모드 | 실행 명령 | 주요 동작 |
| --- | --- | --- |
| `vrchat` | `python -m vrclt run --app vrchat` | VRChat 프로세스 오디오 캡처, OSC 챗박스, VR UI 사용 |
| `discord` | `python -m vrclt run --app discord` | Discord 프로세스 오디오 캡처, 데스크톱 UI 사용, VRChat 전용 기능 비활성화 |

모드별 기본값은 `app.profiles`에서 조정할 수 있습니다.

| 설정 | 설명 |
| --- | --- |
| `process` | 상대방 음성을 캡처할 대상 프로세스 이름 |
| `ui_mode` | `auto`, `vr`, `desktop` 중 실행 UI 모드 |
| `chatbox` | VRChat OSC 챗박스 전송 여부 |
| `osc_control` | VRChat 아바타 OSC 제어 수신 여부 |
| `vr_overlay` | SteamVR 자막 오버레이 사용 여부 |
| `wrist_ui` | SteamVR 손목 메뉴 사용 여부 |

## 설정

주요 설정은 [config.yaml](config.yaml)에 있습니다. 로컬 환경마다 장치명이 다르기 때문에
먼저 `python -m vrclt devices`로 입력/출력 장치 이름을 확인하는 것이 좋습니다.

| 설정 | 설명 |
| --- | --- |
| `api_key` | 비워 두면 `GEMINI_API_KEY` 환경 변수를 사용합니다. |
| `model` | Gemini Live 모델 이름 |
| `app.mode` | 기본 실행 대상: `vrchat` 또는 `discord` |
| `outbound.target_language` | 내 말 번역 출력 언어 |
| `outbound.mic_device` | 실제 마이크 입력 장치 이름 일부. `""`이면 기본 입력 |
| `outbound.tts_device` | 번역 음성을 보낼 출력 장치. 보통 `CABLE Input` |
| `outbound.monitor_device` | 번역 음성을 내가 들을 별도 출력 장치. `""`이면 꺼짐 |
| `outbound.chatbox` | VRChat OSC 챗박스 전송 여부 |
| `inbound.enabled` | 상대방 말 자막 파이프라인 사용 여부 |
| `inbound.process` | 캡처 대상 프로세스. 앱 프로필 적용 후 자동 설정됩니다. |
| `inbound.target_language` | 상대방 말 자막 기본 언어 |
| `inbound.play_audio` | 상대방 말 번역 음성을 내 출력 장치로 재생할지 여부 |
| `audio.voice_rms_threshold` | 마이크 음성 감지 임계값. 소음이 세션을 열면 올리고, 말이 잘리면 낮춥니다. |
| `audio.echo_guard_multiplier` | 상대방 소리가 마이크로 새어 들어올 때 마이크 게이트를 강화하는 배수 |
| `web.port` | 웹 UI 포트. 기본 `8765` |
| `ui.mode` | `auto`, `vr`, `desktop` |

언어 코드는 BCP-47 형식을 사용합니다. 예: `ja`, `en`, `ko`, `zh-Hans`, `zh-Hant`, `es`, `fr`, `de`.

## CLI 명령

| 명령 | 설명 |
| --- | --- |
| `python -m vrclt devices` | WASAPI 장치 목록과 VB-Cable 감지 결과 출력 |
| `python -m vrclt sinetest [이름]` | 지정한 출력 장치에 테스트 톤 재생. 기본 `CABLE Input` |
| `python -m vrclt miccheck [이름]` | 마이크를 약 4초 캡처하고 RMS 레벨과 추천 임계값 출력 |
| `python -m vrclt livetest [--app vrchat\|discord]` | Gemini Live 연결과 모델 접근 권한 테스트 |
| `python -m vrclt desktoptest [--app vrchat\|discord]` | PC 자막/컨트롤 UI 미리보기. API 키 불필요 |
| `python -m vrclt wristtest [--app vrchat\|discord]` | SteamVR 손목 메뉴 테스트. API 키 불필요 |
| `python -m vrclt overlaytest [--app vrchat\|discord]` | SteamVR 자막 오버레이 테스트 |
| `python -m vrclt resetpos` | 저장된 VR 오버레이/손목 메뉴 위치 초기화 |
| `python -m vrclt run [--app vrchat\|discord]` | 실제 번역 실행 |

## 오디오 라우팅

기본 흐름은 다음과 같습니다.

```text
내 마이크 -> Gemini Live -> 번역 음성 -> CABLE Input -> 대상 앱의 CABLE Output 마이크 입력
          -> 번역 텍스트 -> VRChat 챗박스 또는 자막/웹 UI

대상 앱 프로세스 오디오 -> ProcTap -> Gemini Live -> 내 언어 자막 -> PC/VR/웹 UI
```

번역을 끄면 내 마이크는 Gemini를 거치지 않고 `CABLE Input`으로 바로 패스스루됩니다.
Discord 모드에서도 오디오 라우팅은 동일하지만, OSC 챗박스 전송은 사용하지 않습니다.

## 문제 해결

### `VB-Cable: NOT INSTALLED`가 보입니다

VB-Audio Virtual Cable을 설치한 뒤 Windows를 재시작하거나 오디오 장치 목록을 새로고침합니다.
그 다음 `python -m vrclt devices`를 다시 실행합니다.

### 대상 앱에서 마이크 소리가 들어가지 않습니다

대상 앱의 입력 장치가 **CABLE Output**인지 확인합니다. `sinetest "CABLE Input"`을 실행했을 때
대상 앱의 마이크 테스트가 반응해야 합니다.

### 내 말이 번역되지 않거나 자주 끊깁니다

`python -m vrclt miccheck`로 추천 RMS 값을 확인한 뒤 `audio.voice_rms_threshold`를 낮춥니다.
반대로 주변 소음 때문에 세션이 계속 열리면 값을 올립니다.

### 상대방 자막이 표시되지 않습니다

캡처 대상 앱이 실행 중인지 확인합니다. VRChat은 `VRChat.exe`, Discord는 `Discord.exe`가 기본값입니다.
Canary/PTB 등 다른 실행 파일을 사용하면 `app.profiles.discord.process`를 실제 프로세스 이름으로 바꿉니다.

### 웹 UI가 열리지 않습니다

기본 주소는 `http://127.0.0.1:8765`입니다. 포트가 충돌하면 [config.yaml](config.yaml)의
`web.port`를 다른 값으로 바꾼 뒤 앱을 재시작합니다.

### Gemini 연결 테스트가 실패합니다

`GEMINI_API_KEY` 환경 변수 또는 [config.yaml](config.yaml)의 `api_key`를 확인합니다.
모델 접근 권한이 있는지도 [Google AI Studio](https://aistudio.google.com/apikey)에서 확인합니다.

## 로그

로그 파일은 다음 위치에 저장됩니다.

```text
%LOCALAPPDATA%\vrclt\logs\vrclt.log
```

문제가 생겼을 때는 이 파일에서 장치 선택, 프로세스 캡처, Gemini 연결 로그를 먼저 확인합니다.

## 개발

개발 중에는 가상환경을 활성화한 뒤 CLI를 실행하면 됩니다.

```powershell
.\.venv\Scripts\Activate.ps1
python -m vrclt devices
python -m vrclt run --app vrchat
```

패키징은 PyInstaller spec을 사용합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\pyinstaller.exe vrclt.spec --noconfirm
```

결과물은 `dist/vrclt/`에 생성됩니다.

## Git / 배포

- [config.example.yaml](config.example.yaml)은 공유 가능한 설정 예시입니다.
- `config.yaml`, `.venv/`, `build/`, `dist/`, 로그 파일은 Git에 올리지 않습니다.
- 릴리스 zip은 `scripts/package_release.ps1`로 생성합니다.
- 실행 파일이나 압축본은 Git 커밋이 아니라 GitHub Releases 같은 릴리스 첨부 파일로 배포합니다.
- 자세한 릴리스 절차는 [docs/RELEASING.md](docs/RELEASING.md)를 참고합니다.
