# vrclt

言語: [English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [中文](README.zh.md)

`vrclt` は VRChat と Discord 向けの Windows リアルタイム翻訳ツールです。
Gemini Live API で自分のマイク音声を翻訳し、翻訳音声を VB-Audio Virtual
Cable 経由で対象アプリのマイク入力へ送り、相手の発話は翻訳字幕として表示します。

## 主な機能

- ダッシュボード、設定、ログ/情報タブを備えた Windows ネイティブ UI
- アプリを開く、設定を開く、翻訳/字幕の切り替え、終了ができるトレイメニュー
- 送信側翻訳: 自分のマイク -> Gemini Live -> 翻訳音声 -> 対象アプリのマイク
- 受信側字幕: 対象アプリの音声 -> Gemini Live -> 翻訳字幕
- VRChat OSC チャットボックス、アバター OSC 制御、SteamVR 字幕、手首メニュー対応
- 元の声をそのまま通し、OSC チャットボックスに翻訳テキストだけを追加する VRChat テキストのみモード
- Discord プロセス音声キャプチャと、VRChat 専用機能の自動無効化
- 単一 exe ビルド: `dist\vrclt.exe`
- ユーザー設定の保存先: `%LOCALAPPDATA%\vrclt\config.yaml`

## 要件

- Windows 11 推奨
- Google Gemini API キー (取得方法は下記)
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)
- VR オーバーレイと手首 UI を使う場合は SteamVR
- VRChat チャットボックス/アバター制御を使う場合は VRChat OSC を有効化
- ソースから実行する場合のみ Python 3.12

### Gemini API キーの取得方法

1. [Google AI Studio](https://aistudio.google.com/) を開き、Google アカウントでログインします。
   - Google アカウントがない場合は先に作成します。
2. 左サイドバー、またはページ上部の **Get API key** ボタンをクリックします。
   - [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey) に直接移動しても構いません。
3. **Create API key** をクリックします。
4. API キーに関連付ける Google Cloud プロジェクトを選択します。
   - 既存プロジェクトがない場合は **Create API key in new project** を選ぶと自動作成されます。
5. 生成されたキー (`AIza...` で始まる文字列) をコピーします。
   - キー全体は一度しか表示されないため、安全な場所に保管してください。
6. コピーしたキーを `vrclt` の設定タブにある **API キー** 欄へ貼り付けるか、
   `config.yaml` の `gemini.api_key` に設定します。

> **注意**: Gemini API には、個人利用には十分な分単位リクエスト制限付き無料枠があります。
> API キーは他人と共有しないでください。`config.yaml` に平文で保存されるため、このファイルを公開リポジトリにコミットしないでください。

## クイックスタート

### リリース exe

1. `vrclt-v<version>-windows-x64.exe` を実行します。
2. 設定タブを開きます。
3. Gemini API キー、アプリモード、マイク、翻訳音声の出力デバイスを設定します。
4. 翻訳音声の出力デバイスには `CABLE Input` を使います。
5. VRChat または Discord 側のマイク入力を **CABLE Output (VB-Audio Virtual Cable)** に設定します。
6. 設定を保存します。ランタイムは自動で再起動します。

リリース exe は設定を次の場所に保存します。

```text
%LOCALAPPDATA%\vrclt\config.yaml
```

API キーはこのファイルに平文で保存されます。

### ソースチェックアウト

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m vrclt run --app vrchat
```

ソースチェックアウトでは、リポジトリルートの `config.yaml` を読み込みます。
アプリを開く前にローカルの既定値を作りたい場合は、`config.example.yaml` をコピーします。

```powershell
Copy-Item config.example.yaml config.yaml
```

開発/デバッグ用途では、`VRCLT_CONFIG` 環境変数で設定ファイルのパスを上書きできます。

## アプリモード

| モード | 対象 | 動作 |
| --- | --- | --- |
| `vrchat` | VRChat | `VRChat.exe` の音声をキャプチャし、OSC チャットボックス、アバター OSC 制御、SteamVR 字幕、手首 UI を有効化 |
| `discord` | Discord | `Discord.exe` の音声をキャプチャし、VRChat OSC/SteamVR 機能を無効化し、ネイティブ UI は維持 |

設定でモードを選ぶか、1 回の起動だけ引数で指定できます。

```powershell
.\vrclt.exe run --app vrchat
.\vrclt.exe run --app discord
```

VRChat でテキストのみの挙動にするには、ダッシュボードまたは設定の
**テキストのみ**を有効にします。元のマイク音声は VRChat へそのまま通り、
Gemini の翻訳結果は翻訳音声なしで OSC チャットボックスのテキストとして送信されます。

Discord Canary または PTB を使う場合は、設定または `app.profiles.discord.process`
で Discord のプロセス名を変更します。

## ネイティブ UI

ダッシュボード:

- ランタイム状態と接続状態
- VRChat/Discord モード切り替えと VRChat テキストのみ切り替え
- 翻訳 ON/OFF
- 字幕 ON/OFF
- 出力言語と字幕言語
- PC 字幕の位置移動/リセットと文字サイズ
- リアルタイム字幕プレビュー

設定:

- API キーとモデル
- アプリモードと対象プロセス
- マイク、翻訳音声出力、モニター出力、受信側音声デバイス
- 言語リスト
- 音声しきい値と VAD 設定
- OSC、チャットボックス、SteamVR オーバーレイ、手首 UI オプション
- UI 言語と UI モード

ログ/情報:

- 現在の設定パス
- 現在のログファイルパス
- 直近のログ内容

ウィンドウを閉じると、アプリはトレイに隠れます。ランタイムを停止して完全に終了するには、
トレイの `Quit` または `終了` 操作を使います。

## オーディオルーティング

送信側翻訳:

```text
microphone -> Gemini Live -> translated voice -> CABLE Input
                                     target app mic <- CABLE Output
```

受信側字幕:

```text
target app process audio -> ProcTap -> Gemini Live -> subtitles
```

翻訳が OFF の場合、マイクは Gemini を通らず `CABLE Input` へ直接送られます。
VRChat **テキストのみ**では元の声が常に passthrough され、翻訳トグルは
Gemini のテキスト翻訳とチャットボックス出力だけを制御します。

## VRChat 機能

VRChat モードでは次の機能を使えます。

- 翻訳テキストの OSC チャットボックス出力
- `VRCLT_Enabled`、`VRCLT_Lang` などのアバター OSC パラメーター
- 受信側字幕用の SteamVR 字幕オーバーレイ
- VR 内で操作できる SteamVR 手首メニュー

`ui.mode: auto` では、SteamVR 実行中に VR 機能が有効になります。
VR オーバーレイを強制的に有効にするには `ui.mode: vr`、無効に保つには
`ui.mode: desktop` を使います。

## ファイルとパス

| 項目 | リリース exe | ソースチェックアウト |
| --- | --- | --- |
| 設定 | `%LOCALAPPDATA%\vrclt\config.yaml` | リポジトリルートの `config.yaml` |
| 設定パス上書き | `VRCLT_CONFIG` | `VRCLT_CONFIG` |
| ログ | `%LOCALAPPDATA%\vrclt\logs\vrclt.log` | `%LOCALAPPDATA%\vrclt\logs\vrclt.log` |
| ビルド出力 | `dist\vrclt.exe` | `dist\vrclt.exe` |

`config.yaml`、`.venv/`、`build/`、`dist/`、`release/`、ログファイルは Git にコミットしないでください。

## 設定値リファレンス

すべての値は `config.yaml` に保存されます。リリースビルドは上記の AppData
パスを使い、ソースチェックアウトは `VRCLT_CONFIG` がない限りリポジトリルートの
`config.yaml` を使います。

基本値とアプリプロファイル:

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `api_key` | `""` | Gemini API キー。空の場合は `GEMINI_API_KEY` 環境変数を使えます。 |
| `model` | `gemini-3.5-live-translate-preview` | Gemini Live モデル名。 |
| `log_level` | `INFO` | Python ログレベル。 |
| `app.mode` | `vrchat` | 有効なプロファイル: `vrchat` または `discord`。 |
| `app.profiles.<mode>.process` | `VRChat.exe` / `Discord.exe` | 受信側字幕用にキャプチャするプロセス。 |
| `app.profiles.<mode>.ui_mode` | `auto` / `desktop` | プロファイルが適用する UI モード。 |
| `app.profiles.<mode>.voice_output` | `true` | 翻訳音声出力を有効にします。 |
| `app.profiles.<mode>.passthrough_while_translating` | `false` | 翻訳中も元のマイク音声を送ります。 |
| `app.profiles.<mode>.chatbox` | `true` / `false` | VRChat OSC チャットボックス出力を有効にします。 |
| `app.profiles.<mode>.osc_control` | `true` / `false` | アバター OSC 制御リスナーを有効にします。 |
| `app.profiles.<mode>.vr_overlay` | `true` / `false` | SteamVR 字幕オーバーレイを有効にします。 |
| `app.profiles.<mode>.wrist_ui` | `true` / `false` | SteamVR 手首メニューを有効にします。 |

ダッシュボード状態:

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `dashboard.translation_on` | `true` | 最後に保存されたダッシュボード翻訳トグル状態。 |
| `dashboard.subtitles_on` | `true` | 最後に保存されたダッシュボード字幕トグル状態。 |

送信側翻訳:

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `outbound.enabled` | `true` | 送信側パイプラインを有効にします。 |
| `outbound.target_language` | `ja` | 自分の発話を翻訳する既定の対象言語。 |
| `outbound.echo_target_language` | `false` | すでに対象言語の入力も復唱します。 |
| `outbound.mic_device` | `""` | マイクデバイス名の一部。空なら既定入力を使います。 |
| `outbound.tts_device` | `CABLE Input` | 翻訳音声と原音送出の出力デバイス。 |
| `outbound.monitor_device` | `""` | 翻訳音声を自分で聞くためのモニター出力。 |
| `outbound.text_only` | `false` | VRChat テキストのみモード。原音送出と翻訳チャットボックステキストだけを使います。 |
| `outbound.voice_output` | `true` | 翻訳 TTS 音声出力を有効にします。 |
| `outbound.passthrough_while_translating` | `false` | 翻訳が有効でも元のマイク音声を送ります。 |
| `outbound.chatbox` | `true` | 翻訳テキストを VRChat OSC チャットボックスへ送ります。 |

受信側字幕:

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `inbound.enabled` | `true` | 字幕用のプロセス音声キャプチャを有効にします。 |
| `inbound.target_language` | `ko` | 既定の字幕対象言語。 |
| `inbound.languages` | `[ko, en, ja]` | 手首メニューで切り替える字幕言語リスト。 |
| `inbound.process` | `VRChat.exe` | 受信側字幕用にキャプチャするプロセス名。 |
| `inbound.play_audio` | `false` | 受信側の翻訳音声を自分のヘッドホンで再生します。 |
| `inbound.audio_device` | `""` | 受信側翻訳音声の出力デバイス。空なら既定出力を使います。 |
| `inbound.vad_enabled` | `true` | 背景音楽やノイズを減らすため音声活動検出を使います。 |
| `inbound.vad_threshold` | `0.5` | `0` から `1` の VAD 厳格度。高いほど非音声を多く除外します。 |
| `inbound.vad_hangover_sec` | `0.6` | 発話停止後も少しだけキャプチャを維持する時間。 |

オーバーレイと OSC:

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `overlay.enabled` | `true` | SteamVR 字幕オーバーレイを有効にします。 |
| `overlay.width_m` | `0.9` | 字幕オーバーレイ幅(m)。 |
| `overlay.distance_m` | `1.2` | HMD からの字幕オーバーレイ距離(m)。 |
| `overlay.below_m` | `0.35` | HMD 下方向のオフセット(m)。 |
| `overlay.tilt_deg` | `-15.0` | オーバーレイの傾き角度。 |
| `overlay.transform` | `null` | VR 内で位置を調整した後に自動保存される正確な 3x4 字幕ポーズ。 |
| `overlay.font` | `bundled:NotoSansCJKkr-Regular.otf` | 字幕オーバーレイフォント。 |
| `overlay.font_size` | `44` | 字幕の文字サイズ。 |
| `overlay.display_sec` | `7.0` | 確定字幕行が表示される時間。 |
| `overlay.lines` | `3` | 画面に保持する最近の確定字幕行数。 |
| `overlay.show_source` | `false` | 字幕に原文も表示します。 |
| `osc.ip` | `127.0.0.1` | VRChat OSC 送信先 IP。 |
| `osc.port` | `9000` | VRChat OSC 送信先ポート。 |
| `osc.throttle_sec` | `1.5` | チャットボックスの最小送信間隔。 |
| `osc.notification_sfx` | `false` | VRChat チャットボックス通知音を要求します。 |
| `osc.show_source` | `true` | チャットボックスで翻訳の上に原文を表示します。 |
| `osc.chunk_display_sec` | `4.0` | 長いチャットボックスメッセージを分割表示する時の各チャンク表示時間。 |

オーディオ、制御、UI、手首メニュー:

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `audio.send_interval_ms` | `100` | マイク音声を Gemini へ送る間隔。 |
| `audio.finalize_silence_sec` | `2.0` | この秒数だけ無音ならセグメントを確定します。 |
| `audio.mic_idle_disconnect_sec` | `15.0` | マイク入力がない Gemini セッションを切断するまでの秒数。 |
| `audio.voice_rms_threshold` | `90.0` | マイク音声検出のエネルギーしきい値。 |
| `audio.voice_hangover_sec` | `2.5` | 短い間の沈黙中もマイクターンを維持する時間。 |
| `audio.echo_guard_multiplier` | `4.0` | 対象アプリ音声が有効な時にマイクゲートを上げる倍率。`1.0` で無効。 |
| `control.enabled` | `true` | アバター OSC 制御入力を有効にします。 |
| `control.osc_listen_port` | `9001` | アバター制御パラメーターを受けるローカル OSC ポート。 |
| `control.param_enabled` | `VRCLT_Enabled` | 翻訳 ON/OFF 用のアバター bool パラメーター。 |
| `control.param_lang` | `VRCLT_Lang` | 言語インデックス用のアバター int パラメーター。 |
| `control.languages` | `[ja, en, ko, zh-Hans, zh-Hant, yue, es, ru, fr, de]` | アバターと手首制御で使う出力言語リスト。 |
| `control.feedback_chatbox` | `true` | 制御変更フィードバックを VRChat チャットボックスへ送ります。 |
| `ui.mode` | `auto` | `auto`、`vr`、`desktop` のいずれか。 |
| `ui.lang` | `""` | UI 表示言語。空なら自動。`en`、`ko`、`ja`、`zh` を使えます。 |
| `ui.close_action` | `tray` | ウィンドウを閉じるボタンの動作: `tray` または `exit`。 |
| `wrist_ui.enabled` | `true` | SteamVR 手首メニューを有効にします。 |
| `wrist_ui.hand` | `left` | メニューを装着する手: `left` または `right`。 |
| `wrist_ui.width_m` | `0.16` | 手首メニュー幅(m)。 |
| `wrist_ui.offset` | `[-0.0509, -0.065, 0.0891]` | コントローラー座標での x,y,z オフセット。 |
| `wrist_ui.tilt_deg` | `185.636` | 顔の方へ向ける追加の傾き。 |
| `wrist_ui.roll_deg` | `-28.633` | 平面内回転。`null` なら手に応じて自動回転。 |
| `wrist_ui.transform` | saved 3x4 pose | VR 内で位置を調整した後に自動保存される正確な 3x4 手首ポーズ。 |
| `wrist_ui.pointer_tilt_deg` | `50.0` | ポインターレイの下向き傾き角度。 |
| `wrist_ui.font` | `bundled:NotoSansCJKkr-Bold.otf` | 手首メニューフォント。 |

## ビルド

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\pyinstaller.exe vrclt.spec --noconfirm
```

ビルド結果:

```text
dist\vrclt.exe
```

リリース成果物を作成:

```powershell
.\scripts\package_release.ps1 -Version 0.1.0
```

リリーススクリプトの結果:

```text
release\vrclt-v0.1.0-windows-x64.exe
release\vrclt-v0.1.0-windows-x64.exe.sha256
```

## スモークテスト

```powershell
.\.venv\Scripts\python.exe -m compileall vrclt
.\.venv\Scripts\python.exe -m vrclt --help
.\.venv\Scripts\pyinstaller.exe vrclt.spec --noconfirm
.\scripts\package_release.ps1 -Version 0.1.0 -SkipBuild
```

実際のランタイムテストは、exe を起動し、ネイティブ UI で設定を保存し、
`%LOCALAPPDATA%\vrclt\config.yaml` が作成されることを確認し、対象アプリが
`CABLE Output` から音声を受け取ることを確認します。

## トラブルシューティング

- 対象アプリに翻訳音声が入らない: `outbound.tts_device` が `CABLE Input` で、対象アプリのマイクが `CABLE Output` になっているか確認します。
- 受信側字幕が出ない: 対象プロセス名が実行中アプリと一致しているか確認します。例: `VRChat.exe`、`Discord.exe`。
- API キーが必要と表示される: 設定にキーを入力するか、`GEMINI_API_KEY` を設定します。
- VR オーバーレイが出ない: SteamVR が実行中で、`overlay.enabled` / `wrist_ui.enabled` が有効か確認します。
- 設定を初期化したい: アプリを閉じ、`%LOCALAPPDATA%\vrclt\config.yaml` を別名に移動してから再起動します。

## 謝辞

- [Noto Sans CJK](https://github.com/notofonts/noto-cjk) と [Pretendard](https://github.com/orioncactus/pretendard): 多言語 UI フォントカバレッジ。
- [PySide6](https://doc.qt.io/qtforpython-6/): Windows ネイティブ UI。
- [OpenVR](https://github.com/ValveSoftware/openvr)、GLFW、PyOpenGL: SteamVR オーバーレイレンダリング。
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/): アプリ間オーディオルーティング。

## リリース

リリース手順は [docs/RELEASING.md](docs/RELEASING.md) を参照してください。
