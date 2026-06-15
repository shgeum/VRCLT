# VRCLT 릴리스 절차

이 프로젝트는 소스 코드는 Git에 보관하고, 로컬 비밀 설정/가상환경/로그/빌드 산출물은 Git에 올리지 않습니다.
실행 파일은 GitHub Releases 같은 릴리스 첨부 파일로 배포합니다.

## 1. 릴리스 전 확인

먼저 로컬 설정과 빌드 산출물이 커밋 대상에 들어가지 않는지 확인합니다.

```powershell
git status --short --ignored
```

다음 항목은 Git에 들어가면 안 됩니다.

- `config.yaml`
- `.venv/`
- `build/`
- `dist/`
- `release/`
- `build_log.txt`
- 로그 파일

특히 `config.yaml`에는 API 키가 들어갈 수 있으므로 릴리스 zip에 포함하지 않습니다.

## 2. 소스 커밋

릴리스할 소스 상태를 먼저 커밋합니다.

```powershell
git status
git add .
git status
git commit -m "chore: prepare v0.1.0 release"
```

`git add .` 전후로 `config.yaml`, `.venv/`, `build/`, `dist/`, `release/`가 staged 상태에 없는지 확인합니다.

## 3. 빌드와 릴리스 zip 생성

전체 빌드부터 zip 생성까지 한 번에 하려면 다음 명령을 실행합니다.

```powershell
.\scripts\package_release.ps1 -Version 0.1.0
```

이미 `dist/vrclt/`를 빌드해 둔 상태에서 zip만 다시 만들려면 다음 명령을 사용합니다.

```powershell
.\scripts\package_release.ps1 -Version 0.1.0 -SkipBuild
```

스크립트는 다음 파일을 생성합니다.

```text
release/vrclt-v0.1.0-windows-x64.zip
release/vrclt-v0.1.0-windows-x64.zip.sha256
```

zip에는 `dist/vrclt/`의 실행 파일과 런타임 파일, `config.example.yaml`, `README.md`,
`README.en.md`, `docs/RELEASING.md`, `VERSION.txt`가 들어갑니다. 로컬 `config.yaml`은 제외합니다.

## 4. 빌드 산출물 스모크 테스트

zip을 올리기 전에 압축을 풀어서 최소 실행 확인을 합니다.

```powershell
.\dist\vrclt\vrclt.exe --help
.\dist\vrclt\vrclt.exe run --help
.\dist\vrclt\vrclt.exe devices
.\dist\vrclt\vrclt.exe desktoptest
```

가능하면 실제 환경에서 다음도 확인합니다.

- `vrclt.exe run --app vrchat`
- `vrclt.exe run --app discord`
- exe 옆에서 `config.example.yaml`을 `config.yaml`로 복사했을 때 설정을 읽는지
- Discord 모드에서 OSC/VR UI가 꺼지는지
- VRChat 모드에서 OSC 챗박스/VR 자막/손목 UI가 동작하는지

## 5. 태그 생성

소스 커밋이 끝난 뒤 릴리스 태그를 만듭니다.

```powershell
git tag v0.1.0
git push origin main --tags
```

이미 같은 태그가 있으면 새 버전 번호를 사용합니다. 태그는 사용자가 릴리스 zip과 정확히 같은 소스 코드를 찾을 수 있게 해 줍니다.

## 6. GitHub Release 업로드

GitHub 웹 UI를 사용하는 경우 다음 순서로 진행합니다.

1. GitHub 저장소로 이동합니다.
1. Releases -> Draft a new release를 선택합니다.
1. Tag에 `v0.1.0`을 선택합니다.
1. 제목은 `vrclt v0.1.0`처럼 작성합니다.
1. 첨부 파일에 아래 두 파일을 올립니다.

```text
release/vrclt-v0.1.0-windows-x64.zip
release/vrclt-v0.1.0-windows-x64.zip.sha256
```

GitHub CLI를 사용하는 경우 다음 명령으로 업로드할 수 있습니다.

```powershell
gh release create v0.1.0 `
  .\release\vrclt-v0.1.0-windows-x64.zip `
  .\release\vrclt-v0.1.0-windows-x64.zip.sha256 `
  --title "vrclt v0.1.0" `
  --notes "VRChat/Discord live translator release. See README.md for setup instructions."
```

## 7. 사용자 안내

릴리스 본문에는 최소한 다음 내용을 적습니다.

- Windows 전용 빌드입니다.
- VB-Audio Virtual Cable 설치가 필요합니다.
- `config.example.yaml`을 `config.yaml`로 복사한 뒤 API 키와 장치를 설정해야 합니다.
- VRChat은 `vrclt.exe run --app vrchat`을 사용합니다.
- Discord는 `vrclt.exe run --app discord`를 사용합니다.
- 로컬 `config.yaml`은 공유하지 말아야 합니다.
