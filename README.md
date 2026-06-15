# vrclt — VRChat Live Translator

Gemini Live API(`gemini-3.5-live-translate-preview`) 기반 VRChat 실시간 음성 번역기.
내 말을 번역된 음성(내 목소리 복제)으로 VRChat에 송출하고, 번역 자막을 챗박스로 전송한다.
설계 문서: [PLAN.md](PLAN.md)

> 이 저장소에는 이전에 만든 Whispering Tiger용 플러그인
> ([gemini_live_translate_plugin.py](gemini_live_translate_plugin.py))도 있다. vrclt는 그 대체 독립앱.

## 요구사항

- Windows 11, Python 3.12 (3.10–3.13)
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) 설치
- [Gemini API 키](https://aistudio.google.com/apikey)

## 설치 / 실행

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 로컬 설정 파일 생성 후 api_key 또는 GEMINI_API_KEY, target_language 설정:
Copy-Item config.example.yaml config.yaml
$env:GEMINI_API_KEY = "your-gemini-api-key"
.\.venv\Scripts\python.exe -m vrclt run
```

`config.yaml`은 개인 API 키와 장치 설정이 들어가는 로컬 파일이라 Git에 올리지 않는다.
공유용 기본값은 [config.example.yaml](config.example.yaml)을 수정한다.

### CLI

| 명령 | 설명 |
| --- | --- |
| `python -m vrclt devices` | WASAPI 장치 목록 + VB-Cable 확인 |
| `python -m vrclt sinetest [이름]` | 테스트 톤 재생 (기본: CABLE Input) |
| `python -m vrclt miccheck [이름]` | 마이크 2초 캡처 + 레벨 확인 |
| `python -m vrclt livetest` | Gemini Live 연결 테스트 |
| `python -m vrclt desktoptest` | PC 모드 데스크톱 UI 미리보기 (API 키 불필요) |
| `python -m vrclt run` | 실행 (SteamVR 켜져 있으면 VR, 아니면 PC 모드 자동) |

## VR 모드 / PC 모드

`config.yaml`의 `ui.mode`로 결정 (기본 `auto`):

- **`auto`** — SteamVR 실행 중이면 VR 모드(손목 메뉴 + VR 자막 오버레이), 아니면 PC 모드
- **`vr`** — 항상 VR 모드
- **`desktop`** — 항상 PC 모드

### PC 모드 (VR 없이 데스크톱 VRChat)

SteamVR 없이 실행하면 **항상 위에 뜨는 데스크톱 창** 두 개가 나온다:

- **자막 창** — 반투명, 상대 말 번역 자막. 비어 있으면 자동 숨김. 드래그로 이동
- **컨트롤 바** — 번역 ON/OFF, 출력 언어, 자막 ON/OFF, 자막 언어 드롭다운, 연결 상태 점, ✕(종료). 드래그로 이동

두 창 위치는 자동 저장된다 (`%LOCALAPPDATA%\vrclt\desktop_layout.json`).
핵심 파이프라인(ProcTap으로 VRChat 소리 캡처, VB-Cable로 마이크 송출)은 VR과 동일하게 동작한다.

## VRChat 설정

1. VRChat 마이크 = **CABLE Output (VB-Audio Virtual Cable)**
2. 액션 메뉴 → Options → **OSC 켜기** (챗박스 전송용)
3. `config.yaml`의 `outbound.mic_device`:
   - VR(Virtual Desktop): `""` (기본 입력 = Virtual Desktop Audio)
   - 데스크톱: `Scarlett` 등 실제 마이크 이름 일부

## VR 안에서 조작 (VR 모드)

### 손목 메뉴 (기본, XSOverlay 스타일)

SteamVR 실행 중이면 **왼쪽 손목에 워치형 메뉴**가 자동으로 붙는다.
오른손 컨트롤러 끝을 버튼에 **가까이 대면**(2cm) 클릭 — 햅틱으로 확인된다.

- 큰 버튼: **번역 ON ↔ 원음 송출(패스스루)** 토글
- `◀ ▶`: 출력 언어 전환 (`control.languages` 순환)
- 헤더 점: 세션 연결 상태 (초록 = 번역 중)

위치/방향이 안 맞으면 `config.yaml`의 `wrist_ui.offset`(미터), `tilt_deg`, `roll_deg`를 조정.
손목 메뉴만 따로 띄워 조정하려면: `python -m vrclt wristtest` (API 키 불필요)

### 아바타 파라미터 (보조)

아바타 Expression Parameters + 액션 메뉴(라디얼)로도 조작 가능:

| 파라미터 | 타입 | 동작 |
| --- | --- | --- |
| `VRCLT_Enabled` | bool | ON = 번역 송출 / OFF = 원음 송출(패스스루) |
| `VRCLT_Lang` | int | `control.languages` 리스트 인덱스 (기본: 0=ja, 1=en, 2=ko) |

변경 시 챗박스로 상태가 표시된다 (`control.feedback_chatbox: false`로 끌 수 있음).

## 동작 방식 / 특징

```text
마이크 ──16k──▶ Gemini Live (translationConfig, 목소리 복제)
   │              ├─ 번역 음성 24k ──▶ CABLE Input (= VRChat 마이크)
   │              └─ 번역 자막 ──▶ OSC 챗박스 (1.5s 쓰로틀, 144자)
   └─ (번역 OFF시) 원음 16k ──▶ CABLE Input  [패스스루]
```

- **무음 비용 가드**: 마이크 RMS 에너지 게이트 — 말이 없으면 세션을 닫고 과금 스트리밍을 차단
  (`audio.voice_rms_threshold`, 소음이 세션을 여는 경우 값을 올릴 것)
- 자동 재연결 (연결 ~10분 제한, goAway), 발화 시작 ~1초 프리롤 버퍼링
- 언어 변경은 세션 재시작으로 자동 적용 (~1초)

## 로드맵 (PLAN.md)

- [x] M0 스켈레톤 / M1 아웃바운드 (+ 토글/패스스루/VR 컨트롤)
- [x] 손목 메뉴 (SteamVR 오버레이, 터치 조작)
- [ ] M2 인바운드: ProcTap으로 VRChat 소리만 캡처 → 상대 말 자막
- [ ] M3 SteamVR 오버레이 자막
- [ ] M4 트레이 + 웹 설정 UI / M5 패키징

## 로그

`%LOCALAPPDATA%\vrclt\logs\vrclt.log`

## Git / 배포

- [config.example.yaml](config.example.yaml)은 공유 가능한 기본 설정 예시다.
- `config.yaml`, `.venv/`, `build/`, `dist/`, 로그 파일은 `.gitignore`로 제외한다.
- GitHub Releases 등으로 실행 파일을 배포할 때는 [docs/RELEASING.md](docs/RELEASING.md)의 절차를 따른다.
