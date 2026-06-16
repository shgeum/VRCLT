# vrclt

언어: [English](README.md) | [한국어](README.ko.md)

`vrclt`는 VRChat과 Discord용 Windows 실시간 번역 도구입니다. Gemini Live API로
내 마이크를 번역하고, 번역 음성을 VB-Audio Virtual Cable을 통해 대상 앱의
마이크 입력으로 보내며, 상대방 음성은 번역 자막으로 표시합니다.

현재 앱은 PySide6 기반 자체 UI를 사용합니다. 웹 UI, 로컬 웹 서버, 릴리스 exe 옆
설정 파일은 사용하지 않습니다.

## 주요 기능

- Dashboard, Settings, Logs/About 탭을 가진 Windows 자체 UI
- 창 열기, 설정 열기, 번역/자막 토글, 종료를 제공하는 트레이 메뉴
- 아웃바운드 번역: 내 마이크 -> Gemini Live -> 번역 음성 -> 대상 앱 마이크
- 인바운드 자막: 대상 앱 오디오 -> Gemini Live -> 번역 자막
- VRChat OSC 챗박스, 아바타 OSC 제어, SteamVR 자막, 손목 메뉴 지원
- 원래 목소리는 그대로 보내고 OSC 챗박스 번역 텍스트만 추가하는 VRC Text Only 모드
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
6. 복사한 키를 `vrclt` Settings 탭의 **API Key** 항목에 붙여넣거나,
   `config.yaml`의 `gemini.api_key` 값으로 설정합니다.

> **참고**: Gemini API는 무료 티어(분당 요청 수 제한)가 있어 개인 사용에는 충분합니다.
> API 키는 타인에게 공유하지 않습니다. `config.yaml`에 평문으로 저장되므로 파일을 공개 저장소에 올리지 마세요.

## 빠른 시작

### 릴리스 exe

1. `vrclt-v<version>-windows-x64.exe`를 실행합니다.
2. Settings 탭을 엽니다.
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
| `vrc_text` | VRChat 텍스트 전용 | 원래 목소리는 VRChat으로 passthrough하고, Gemini 번역 결과는 OSC 챗박스 텍스트로만 전송. 번역 음성 출력 없음 |
| `discord` | Discord | `Discord.exe` 오디오 캡처, VRChat OSC/SteamVR 기능 비활성화, 자체 UI 유지 |

Settings에서 모드를 고르거나 실행 한 번에만 인자로 지정할 수 있습니다.

```powershell
.\vrclt.exe run --app vrchat
.\vrclt.exe run --app vrc_text
.\vrclt.exe run --app discord
```

Discord Canary 또는 PTB를 사용한다면 Settings 또는 `app.profiles.discord.process`에서
프로세스 이름을 바꿉니다.

## 자체 UI

Dashboard:

- 런타임 상태와 연결 상태
- 번역 ON/OFF
- 자막 ON/OFF
- 출력 언어와 자막 언어
- 실시간 자막 미리보기

Settings:

- API 키와 모델
- 앱 모드와 대상 프로세스
- 마이크, 번역 음성 출력, 모니터 출력, 인바운드 오디오 장치
- 언어 목록
- 오디오 임계값과 VAD 설정
- OSC, 챗박스, SteamVR 오버레이, 손목 UI 옵션
- UI 언어와 UI 모드

Logs/About:

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
`vrc_text`에서는 원래 목소리가 항상 passthrough되고, 번역 토글은 Gemini 텍스트
번역과 챗박스 출력만 제어합니다.

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
- API key required 상태: Settings에 키를 입력하거나 `GEMINI_API_KEY`를 설정합니다.
- VR 오버레이가 안 뜸: SteamVR이 실행 중이고 `overlay.enabled` / `wrist_ui.enabled`가 켜져 있는지 확인합니다.
- 설정을 초기화하고 싶음: 앱을 닫고 `%LOCALAPPDATA%\vrclt\config.yaml`을 다른 이름으로 옮긴 뒤 다시 실행합니다.

## 릴리스

릴리스 절차는 [docs/RELEASING.md](docs/RELEASING.md)를 참고합니다.
