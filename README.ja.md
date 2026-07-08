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
- 2 つの翻訳エンジン: Google Gemini Live（既定）と、Google を利用できない地域（例: 中国本土）向けの Alibaba Qwen3.5 LiveTranslate
- VRChat OSC チャットボックス、アバター OSC 制御、SteamVR 字幕、手首メニュー対応
- SteamVR ダッシュボード設定パネルと SteamVR 自動起動（スタートアップ/オーバーレイアプリ登録）対応
- 元の声をそのまま通し、OSC チャットボックスに翻訳テキストだけを追加する VRChat テキストのみモード
- Discord プロセス音声キャプチャと、VRChat 専用機能の自動無効化
- 原音送出は 48 kHz の元マイクストリームを直接使い、Gemini 翻訳用ストリームは別にリサンプリング
- GitHub Releases の更新通知と、API キー、保存済み言語リスト、UI 言語、ウィンドウを閉じる動作、選択したオーディオデバイスを保持する安全な設定リセット
- [VRCLT Releases](https://github.com/shgeum/VRCLT/releases) からダウンロードできる Windows exe
- ユーザー設定の保存先: `%LOCALAPPDATA%\vrclt\config.yaml`

## インストール

### 要件

- Windows 11 推奨
- Google Gemini API キー — または Qwen エンジン用の Alibaba Cloud Model Studio (DashScope) API キー (取得方法は下記)
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)
- VR オーバーレイと手首 UI を使う場合は SteamVR
- VRChat チャットボックス/アバター制御を使う場合は VRChat OSC を有効化
- ソースから実行する場合のみ Python 3.12

### 1. vrclt をダウンロード

最新の Windows 実行ファイルは [VRCLT Releases](https://github.com/shgeum/VRCLT/releases) からダウンロードできます。

次のような名前のファイルを使います。

```text
vrclt-v<version>-windows-x64.exe
```

リリース exe は設定を次の場所に保存します。

```text
%LOCALAPPDATA%\vrclt\config.yaml
```

API キーはこのファイルに平文で保存されます。

### 2. VB-Audio Virtual Cable をインストール

VRChat または Discord に翻訳音声をマイクとして受け取らせるには、VB-Audio Virtual Cable が必要です。

1. [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) から **VB-CABLE** をダウンロードします。
2. ダウンロードした ZIP ファイルを展開します。
3. `VBCABLE_Setup_x64.exe` を右クリックし、**管理者として実行**します。
4. **Install Driver** をクリックします。
5. `CABLE Input` / `CABLE Output` が表示されない場合は Windows を再起動します。

インストール後、Windows には次の 2 つの重要なデバイスが追加されます。

| デバイス | 意味 | 選択する場所 |
| --- | --- | --- |
| `CABLE Input` | 仮想ケーブルの再生/出力側 | vrclt の翻訳音声出力デバイス |
| `CABLE Output` | 仮想ケーブルの録音/マイク側 | VRChat または Discord のマイク |

実際のマイクは vrclt 側で選択します。翻訳音声を相手に届けるには、VRChat/Discord のマイクを実マイクではなく `CABLE Output` に設定してください。

### 3. Gemini API キーの取得方法

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

### 3b. 代替: Qwen API キー（Gemini を利用できない地域向け）

お住まいの地域で Google サービスを利用できない場合（例: 中国本土）、vrclt は
Gemini の代わりに **Alibaba Qwen3.5 LiveTranslate** を使えます。

1. Alibaba Cloud アカウントを作成し、**Model Studio** を有効化します。
   - 中国本土: [bailian.console.aliyun.com](https://bailian.console.aliyun.com/)
   - 国際（シンガポール）: [Alibaba Cloud Model Studio](https://www.alibabacloud.com/en/product/modelstudio)
2. API キー（DashScope キー、`sk-...` で始まる）を作成します。
   **キーはリージョンに紐づきます**: 本土（北京）のキーは `beijing`
   エンドポイントでのみ、国際キーは `intl` でのみ動作します。
3. vrclt の設定で **翻訳エンジン** を `qwen` にし、キーを
   **Qwen APIキー (DashScope)** に貼り付け、キーに合った **Qwenサーバー**
   （中国本土は `beijing`、それ以外は `intl`）を選択します。キーは
   `DASHSCOPE_API_KEY` 環境変数でも指定できます。
4. **QwenワークスペースID — `intl` では必須**: 国際（シンガポール）
   エンドポイントはワークスペース専用ドメイン経由でのみ提供されます。
   Model Studio コンソールのホームで左下のアイコンをクリックし、
   **Workspace Details** を開いて ID（`llm-7c72iiw36kd8****` のような形式）を
   コピーし、**QwenワークスペースID** 欄に貼り付けます。`beijing`
   エンドポイントは空のままで構いません（従来の共有 `dashscope` ドメイン）。
   参考: [Obtain the workspace ID](https://www.alibabacloud.com/help/en/model-studio/obtain-api-key-app-id-and-workspace-id)
5. **自分の発話言語** と **相手の発話言語** を設定します — Qwen は発話言語を
   自動検出できません（下の「翻訳エンジン」セクションを参照）。

### 4. 初回起動設定

1. `vrclt-v<version>-windows-x64.exe` を実行します。
2. 設定タブを開きます。
3. Gemini API キーを貼り付けます（または **翻訳エンジン** を `qwen` にして
   DashScope キーを貼り付けます — 手順 3b を参照）。
4. アプリモードを `vrchat` または `discord` にします。
5. **マイク入力**には実際のマイクを選択します。
6. **音声出力**または翻訳音声出力デバイスには `CABLE Input` を選択します。
7. VRChat または Discord のマイク入力を **CABLE Output (VB-Audio Virtual Cable)** に設定します。
8. 設定を保存します。ランタイムは自動で再起動します。

## トラブルシューティング

- 対象アプリに翻訳音声が入らない: `outbound.tts_device` が `CABLE Input` で、対象アプリのマイクが `CABLE Output` になっているか確認します。
- 受信側字幕が出ない: 対象プロセス名が実行中アプリと一致しているか確認します。例: `VRChat.exe`、`Discord.exe`。
- API キーが必要と表示される: 設定にキーを入力するか、`GEMINI_API_KEY` を設定します（Qwen エンジンの場合: `DASHSCOPE_API_KEY`）。
- Qwen キーが拒否される、または接続が即座に失敗する: `qwen.endpoint` がキーのリージョンと一致しているか確認します — `beijing` のキーと `intl` のキーは互換性がありません — さらに `intl` を使う場合はワークスペースID が設定されているか確認します。
- Qwen エラー `Voice '...' is not supported`: リテラルの音声 `default` は音声クローンが有効な間だけ使えます。`qwen.voice_clone` を有効のままにするか、モデル既定の声を使うなら **QwenボイスID** を空にします。
- Qwen が違う言語から翻訳する: **自分の発話言語** / **相手の発話言語** を設定します（設定、ダッシュボード、または SteamVR パネル）。Qwen は自動検出できず、空の場合は英語として扱われます。
- VR オーバーレイが出ない: SteamVR が実行中で、`overlay.enabled` / `wrist_ui.enabled` が有効か確認します。
- passthrough や字幕の遅延が大きい: まずこの README の既定値を使い、接続が安定している場合だけ `audio.turn_end_silence_sec`、`audio.inbound_turn_end_silence_sec`、`audio.subtitle_finalize_silence_sec` を慎重に下げます。
- 設定を初期化したい: 設定タブの **既定値リセット** を使います。API キー、出力言語リスト、字幕言語リスト、UI 言語、ウィンドウを閉じる動作、選択したオーディオデバイスは保持し、それ以外を既定値に戻します。アプリ更新後にも vrclt がこのリセットを 1 回確認します。

## 翻訳エンジン

vrclt は 2 つのリアルタイム翻訳エンジンに対応し、**翻訳エンジン** 設定
（`config.yaml` の `provider`）で選択します。選択したエンジンは、自分の音声と
受信側字幕の両方向に適用されます。

| | Gemini Live（既定） | Qwen3.5 LiveTranslate |
| --- | --- | --- |
| プロバイダー / キー | Google AI Studio (`GEMINI_API_KEY`) | Alibaba Cloud Model Studio / DashScope (`DASHSCOPE_API_KEY`) |
| 中国本土での利用 | 不可 | 可（`beijing` エンドポイント） |
| 発話言語の検出 | 自動検出 | **手動** — 「自分/相手の発話言語」を設定 |
| 対応言語 | `zh-Hans`/`zh-Hant` を含む 70 以上の BCP-47 対象言語 | 音声付き 29 + テキストのみ 31; 中国語は `zh` のみ（簡体字/繁体字の区別なし）; 広東語（`yue`）はテキストのみ |
| 翻訳音声 | 話者の声を再現 | サーバー側の音声クローンで話者の声を再現（`qwen.voice_clone`、既定 `once`）。クローンをオフにすると固定の声 |
| 割り込み（barge-in） | 対応 | 非対応 — 発話が重なると音声がキューに溜まることがあります |

Qwen の注意点:

- **発話言語の設定が必須です。** 設定タブ、ダッシュボードタブ、または SteamVR
  ダッシュボードパネルの最下段で設定します。空の場合は英語として扱われます。
- `zh-Hans`/`zh-Hant` の対象言語は、どちらも `zh` として Qwen に送られます。
- 選んだ対象言語に Qwen の音声対応がない場合、vrclt は自動でセッションを
  テキストのみで実行します（チャットボックス/字幕は動作し続けます）。
- エンドポイント: `intl`（シンガポール）または `beijing`。`intl` は Model Studio
  ワークスペースID が**必須**で、`beijing` はなくても動作します（上の手順 3b を参照）。
- 音声クローン: `qwen.voice_clone: once`（既定）はセッション開始時に話者の声を
  クローンします — 自分のマイクに適しており、音声の遅延も低く抑えられます。
  `always` は応答ごとに再クローンし（複数人が話す音声向けですが、合成の開始が
  目に見えて遅くなります）、`off` はモデル既定の声、または `qwen.voice` に
  設定したクローン済みボイスID（`qwen-translate-vc-...`）を使います。

## アプリモード

| モード | 対象 | 動作 |
| --- | --- | --- |
| `vrchat` | VRChat | `VRChat.exe` の音声をキャプチャし、OSC チャットボックス、アバター OSC 制御、SteamVR 字幕、手首 UI を有効化 |
| `discord` | Discord | ルート `Discord.exe` プロセスツリーの音声をキャプチャし、VRChat OSC/SteamVR 機能を無効化し、PC UI とデスクトップ字幕は維持 |

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
- PC グローバルホットキーで翻訳/字幕を切り替え
- 出力言語と字幕言語、Gemini Live Translation の 70 以上の対応言語を検索して追加
- マイク入力と翻訳音声出力デバイスの選択、出力テストトーンボタン付き。デバイス更新はランタイムを再起動し、後から挿したデバイスも認識します
- 翻訳音声の音量スライダーと、検出しきい値マーカー付きリアルタイムマイクレベルメーター
- Qwen エンジン用の自分/相手の発話言語ピッカー（自動検出する Gemini では無効）
- PC 字幕の位置移動/リセット、ボックスサイズ、文字サイズ
- リアルタイム字幕プレビュー

設定:

- 翻訳エンジン（Gemini / Qwen）、API キー、モデル、Qwen のエンドポイント/ワークスペース
- アプリモードと対象プロセス
- マイク、翻訳音声出力、モニター出力、受信側音声デバイス
- 既定の対象言語と保存済み言語リスト
- PC グローバルホットキー設定
- 音声しきい値と VAD 設定
- API キー、出力言語リスト、字幕言語リスト、UI 言語、ウィンドウを閉じる動作、選択したオーディオデバイスを保持する既定値リセットボタン
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

原音 passthrough は、キャプチャした 48 kHz マイクストリームを直接使います。
Gemini 翻訳用ストリームは別にリサンプリングされるため、passthrough が翻訳
セッションを待たず、不要な音質劣化も抑えられます。

## VRChat 機能

VRChat モードでは次の機能を使えます。

- 翻訳テキストの OSC チャットボックス出力
- `VRCLT_Enabled`、`VRCLT_Lang` などのアバター OSC パラメーター
- 受信側字幕用の SteamVR 字幕オーバーレイ
- VR 内で操作できる SteamVR 手首メニュー — ランタイム再起動、字幕文字サイズ、接続/エラー状態表示付き
- SteamVR ダッシュボード設定パネル（SteamVR メニューを開いて vrclt アイコンを選択）。マイク・音声出力デバイスの選択も可能 — 最後のクリックから少し後にランタイム再起動とともに適用されます — さらに翻訳音声の音量と、エラー状態表示（再接続中、クォータ超過、API キー無効）、Qwen エンジン用の発話言語の行
- SteamVR 自動起動: リリース版 exe は SteamVR 設定 > スタートアップ/オーバーレイアプリに自動登録され、自動起動は SteamVR 設定または vrclt 設定で切り替えます
- 新しいバージョンに更新した後は、新しい exe を一度起動してください。登録自体は維持されますが、自動起動が参照する exe パスは初回起動時に新しいファイルへ更新されます
- VR 字幕編集 laser/cursor 表示と角ハンドルでのサイズ調整

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
| `provider` | `gemini` | 両方向のパイプラインに適用される翻訳エンジン: `gemini` または `qwen`。 |
| `api_key` | `""` | Gemini API キー。空の場合は `GEMINI_API_KEY` 環境変数を使えます。 |
| `model` | `gemini-3.5-live-translate-preview` | Gemini Live モデル名。 |
| `qwen.api_key` | `""` | DashScope API キー。空の場合は `DASHSCOPE_API_KEY` 環境変数を使えます。 |
| `qwen.model` | `qwen3.5-livetranslate-flash-realtime` | Qwen リアルタイム翻訳モデル名。 |
| `qwen.endpoint` | `intl` | `intl`（シンガポール）または `beijing`（中国本土）。キーはリージョンに紐づきます。 |
| `qwen.workspace_id` | `""` | Model Studio ワークスペースID（`maas.aliyuncs.com` ドメイン）。`intl` では必須。`beijing` は空でも構いません。 |
| `qwen.base_url` | `""` | 上級者向け: `wss://` URL 全体の上書き。 |
| `qwen.voice_clone` | `once` | サーバー側の話者音声クローン: `once`（セッション開始時、低遅延）、`always`（応答ごと、遅い）、`off`。 |
| `qwen.voice` | `""` | クローンが `off` のとき: 空ならモデル既定の声、またはクローン済みボイスID（`qwen-translate-vc-...`）。 |
| `log_level` | `INFO` | Python ログレベル。 |
| `meta.last_version` | `""` | 現在の設定で確認済みの最後のアプリバージョン。更新後の 1 回限りのリセット確認に使います。 |
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

PC ホットキー:

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `hotkeys.enabled` | `true` | Windows グローバルホットキーを有効にします。 |
| `hotkeys.translation_toggle` | `Ctrl+Alt+T` | 翻訳 ON/OFF の切り替えホットキー。空にすると無効になります。 |
| `hotkeys.subtitles_toggle` | `Ctrl+Alt+S` | 字幕 ON/OFF の切り替えホットキー。空にすると無効になります。 |
| `hotkeys.enabled_in_vr` | `true` | SteamVR 実行中もグローバルホットキーを有効のままにします。 |
| `hotkeys.translation_hold` | `""` | 押している間だけ翻訳を一時停止（原音送出）するホットキー。空にすると無効になります。 |

送信側翻訳:

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `outbound.enabled` | `true` | 送信側パイプラインを有効にします。 |
| `outbound.target_language` | `ja` | 自分の発話を翻訳する既定の BCP-47 言語コード。UI で Gemini Live Translation の 70 以上の対応言語を検索して選択できます。 |
| `outbound.source_language` | `""` | 自分の発話言語。Qwen では必須（自動検出なし。空なら英語）。Gemini では無視されます。 |
| `outbound.echo_target_language` | `false` | すでに対象言語の入力も復唱します。 |
| `outbound.mic_device` | `""` | マイクデバイス名の一部。空なら既定入力を使います。 |
| `outbound.tts_device` | `CABLE Input` | 翻訳音声と原音送出の出力デバイス。 |
| `outbound.tts_gain` | `1.0` | 翻訳音声の音量 `0.0`–`2.0`（モニター出力にも適用。原音送出はそのまま）。 |
| `outbound.monitor_device` | `""` | 翻訳音声を自分で聞くためのモニター出力。 |
| `outbound.text_only` | `false` | VRChat テキストのみモード。原音送出と翻訳チャットボックステキストだけを使います。 |
| `outbound.voice_output` | `true` | 翻訳 TTS 音声出力を有効にします。 |
| `outbound.passthrough_while_translating` | `false` | 翻訳が有効でも元のマイク音声を送ります。 |
| `outbound.chatbox` | `true` | 翻訳テキストを VRChat OSC チャットボックスへ送ります。 |
| `outbound.glossary` | `""` | 翻訳用語集。1 行に `原文=訳語` の形式で名前や用語の訳を固定します。 |

受信側字幕:

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `inbound.enabled` | `true` | 字幕用のプロセス音声キャプチャを有効にします。 |
| `inbound.target_language` | `ko` | 既定の字幕 BCP-47 言語コード。UI で Gemini Live Translation の 70 以上の対応言語を検索して選択できます。 |
| `inbound.source_language` | `""` | 相手の発話言語（Qwen のみ。`outbound.source_language` と同じルール）。 |
| `inbound.languages` | `[ko, en, ja]` | ダッシュボードと手首メニューで使う保存済み字幕言語リスト。UI の選択リストから必要な言語だけ追加します。 |
| `inbound.process` | `VRChat.exe` | 受信側字幕用にキャプチャするプロセス名。 |
| `inbound.play_audio` | `false` | 受信側の翻訳音声を自分のヘッドホンで再生します。 |
| `inbound.audio_device` | `""` | 受信側翻訳音声の出力デバイス。空なら既定出力を使います。 |
| `inbound.vad_enabled` | `true` | 背景音楽やノイズを減らすため音声活動検出を使います。 |
| `inbound.vad_threshold` | `0.5` | `0` から `1` の VAD 厳格度。高いほど非音声を多く除外します。 |
| `inbound.vad_hangover_sec` | `0.35` | 発話停止後も少しだけキャプチャを維持する時間。低くすると字幕の末尾遅延を減らせます。 |

オーバーレイと OSC:

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `overlay.enabled` | `true` | SteamVR 字幕オーバーレイを有効にします。 |
| `overlay.width_m` | `0.9` | 字幕オーバーレイ幅(m)。 |
| `overlay.height_m` | `0.225` | 字幕オーバーレイ高さ(m)。 |
| `overlay.distance_m` | `1.2` | HMD からの字幕オーバーレイ距離(m)。 |
| `overlay.below_m` | `0.35` | HMD 下方向のオフセット(m)。 |
| `overlay.tilt_deg` | `-15.0` | オーバーレイの傾き角度。 |
| `overlay.transform` | `null` | VR 内で位置を調整した後に自動保存される正確な 3x4 字幕ポーズ。 |
| `overlay.font` | `bundled:NotoSansCJKkr-Regular.otf` | 字幕オーバーレイフォント。 |
| `overlay.font_size` | `27` | 字幕の文字サイズ。 |
| `overlay.display_sec` | `7.0` | 確定字幕行が表示される時間。 |
| `overlay.lines` | `3` | 画面に保持する最近の確定字幕行数。 |
| `overlay.show_source` | `false` | 字幕に原文も表示します。 |
| `osc.ip` | `127.0.0.1` | VRChat OSC 送信先 IP。 |
| `osc.port` | `9000` | VRChat OSC 送信先ポート。 |
| `osc.throttle_sec` | `1.5` | ライブ partial 更新を含むチャットボックスの最小送信間隔。 |
| `osc.notification_sfx` | `false` | VRChat チャットボックス通知音を要求します。 |
| `osc.show_source` | `true` | チャットボックスで翻訳の上に原文を表示します。 |
| `osc.stream_sentences` | `true` | 完成した文をすぐにチャットボックスへ送信し、直近の文を 1 つの吹き出しの中で順次入れ替えます。`false` にすると以前の動作に戻ります（長いセグメントを `chunk_display_sec` 間隔のチャンクで再生）。 |
| `osc.chunk_display_sec` | `4.0` | 長いチャットボックスメッセージを分割表示する時の各チャンク表示時間。 |

オーディオ、制御、UI、手首メニュー:

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `audio.send_interval_ms` | `50` | マイク音声を Gemini へ送る間隔。低くすると翻訳遅延を減らせますが、ネットワーク送信量は少し増えます。 |
| `audio.finalize_silence_sec` | `2.0` | この秒数だけ無音ならセグメントを確定します。 |
| `audio.mic_idle_disconnect_sec` | `15.0` | マイク入力がない Gemini セッションを切断するまでの秒数。 |
| `audio.voice_rms_threshold` | `90.0` | マイク音声検出のエネルギーしきい値。 |
| `audio.voice_hangover_sec` | `2.5` | 短い間の沈黙中もマイクターンを維持する時間。 |
| `audio.turn_end_silence_sec` | `0.55` | 実際のマイク無音がこの秒数続いたら Gemini へターン終了ヒントを送ります。低くすると翻訳音声の遅延を減らせる場合があります。 |
| `audio.inbound_turn_end_silence_sec` | `0.35` | 受信側字幕セッションへより早いターン終了ヒントを送ります。 |
| `audio.subtitle_partial_interval_sec` | `0.15` | 字幕行が確定する前のライブ更新間隔。 |
| `audio.subtitle_finalize_silence_sec` | `0.8` | 受信側字幕行を確定する前に必要な無音時間。 |
| `audio.echo_guard_multiplier` | `4.0` | 対象アプリ音声が有効な時にマイクゲートを上げる倍率。`1.0` で無効。 |
| `audio.echo_guard_hold_sec` | `1.2` | 対象アプリの音声が有効な間、outbound マイク入力をブロックする時間。 |
| `audio.echo_guard_barge_in_multiplier` | `3.0` | エコーガード中でも大きい自分の声を通します。低いほど同時発話が通りやすくなります。 |
| `control.enabled` | `true` | アバター OSC 制御入力を有効にします。 |
| `control.osc_listen_port` | `9001` | アバター制御パラメーターを受けるローカル OSC ポート。 |
| `control.param_enabled` | `VRCLT_Enabled` | 翻訳 ON/OFF 用のアバター bool パラメーター。 |
| `control.param_lang` | `VRCLT_Lang` | 言語インデックス用のアバター int パラメーター。 |
| `control.languages` | `[ja, en, ko, zh-Hans, zh-Hant, yue, es, ru, fr, de]` | ダッシュボード、アバター、手首制御で使う保存済み出力言語リスト。UI の選択リストから必要な言語だけ追加します。 |
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

## ソースから実行

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

## 謝辞

- [Noto Sans CJK](https://github.com/notofonts/noto-cjk) と [Pretendard](https://github.com/orioncactus/pretendard): 多言語 UI フォントカバレッジ。
- [PySide6](https://doc.qt.io/qtforpython-6/): Windows ネイティブ UI。
- [OpenVR](https://github.com/ValveSoftware/openvr)、GLFW、PyOpenGL: SteamVR オーバーレイレンダリング。
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/): アプリ間オーディオルーティング。

## リリース

リリース手順は [docs/RELEASING.md](docs/RELEASING.md) を参照してください。
