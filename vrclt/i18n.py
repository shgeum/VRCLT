"""Shared UI-language strings for the Qt app and VR wrist menu.

Display language is held in AppState.ui_lang so a change in any UI propagates
live to the others.

This is the *display* language (chrome), separate from the translation target
languages (those use the shared language catalog in UI controls).
"""
import logging

log = logging.getLogger(__name__)

# supported UI display languages
LANGS = ["en", "ko", "ja", "zh"]
UI_LANG_LABELS = {"en": "English", "ko": "한국어", "ja": "日本語", "zh": "中文"}

# key -> {lang: text}.  "f.*" keys are settings-field labels.
STRINGS = {
    # ---- header / connection ----
    "conn_on": {"ko": "연결됨", "en": "Connected", "ja": "接続済み", "zh": "已连接"},
    "conn_off": {"ko": "대기", "en": "Idle", "ja": "待機", "zh": "待机"},
    "status_stopped": {"ko": "중지됨", "en": "Stopped", "ja": "停止中", "zh": "已停止"},
    "status_starting": {"ko": "시작 중", "en": "Starting", "ja": "起動中", "zh": "启动中"},
    "status_running": {"ko": "실행 중", "en": "Running", "ja": "実行中", "zh": "运行中"},
    "status_api_key_required": {"ko": "API 키 필요", "en": "API key required",
                                "ja": "APIキーが必要", "zh": "需要 API 密钥"},
    "status_api_key_invalid": {"ko": "API 키 오류", "en": "API key invalid",
                               "ja": "APIキーが無効", "zh": "API 密钥无效"},
    "status_failed": {"ko": "실패", "en": "Failed", "ja": "失敗", "zh": "失败"},
    "status_degraded": {"ko": "일부 오류", "en": "Degraded", "ja": "一部エラー", "zh": "部分异常"},
    "status_reconnecting": {"ko": "재연결 중…", "en": "Reconnecting…",
                            "ja": "再接続中…", "zh": "正在重连…"},
    "status_quota_exceeded": {"ko": "API 사용량 초과", "en": "Quota exceeded",
                              "ja": "クォータ超過", "zh": "配额已用尽"},
    # ---- control ----
    "tab_dashboard": {"ko": "대시보드", "en": "Dashboard", "ja": "ダッシュボード", "zh": "仪表板"},
    "tab_settings": {"ko": "설정", "en": "Settings", "ja": "設定", "zh": "设置"},
    "tab_logs": {"ko": "로그/정보", "en": "Logs/About", "ja": "ログ/情報", "zh": "日志/关于"},
    "label_app_mode": {"ko": "앱 모드", "en": "App mode", "ja": "アプリモード", "zh": "应用模式"},
    "label_out_lang": {"ko": "출력 언어", "en": "Output language", "ja": "出力言語", "zh": "输出语言"},
    "label_sub_lang": {"ko": "자막 언어", "en": "Subtitle language", "ja": "字幕言語", "zh": "字幕语言"},
    "label_pc_sub_size": {"ko": "PC 자막 크기", "en": "PC subtitle size",
                          "ja": "PC字幕サイズ", "zh": "PC 字幕大小"},
    "label_close_action": {"ko": "창 닫기 동작", "en": "Window close action",
                           "ja": "ウィンドウを閉じる動作", "zh": "关闭窗口动作"},
    "label_mic_device": {"ko": "마이크 입력", "en": "Mic input",
                         "ja": "マイク入力", "zh": "麦克风输入"},
    "label_voice_out_device": {"ko": "음성 출력", "en": "Voice output",
                               "ja": "音声出力", "zh": "语音输出"},
    "label_tts_gain": {"ko": "번역 음성 볼륨", "en": "Translated voice volume",
                       "ja": "翻訳音声の音量", "zh": "翻译语音音量"},
    "label_mic_level": {"ko": "마이크 레벨", "en": "Mic level",
                        "ja": "マイクレベル", "zh": "麦克风电平"},
    "tip_mic_level": {
        "ko": "초록색 = 음성 감지 임계값 초과. 표시선은 현재 임계값입니다 (게임 소리 재생 중에는 상승).",
        "en": "Green = above the voice gate. The marker is the current detection "
              "threshold (raised while game audio plays).",
        "ja": "緑 = 音声ゲート超過。マーカーは現在の検出しきい値です (ゲーム音声の再生中は上昇)。",
        "zh": "绿色 = 超过语音门限。标记线为当前检测阈值（游戏声音播放时会提高）。"},
    "dash_voice_volume": {"ko": "음성 볼륨", "en": "Voice volume",
                          "ja": "音声音量", "zh": "语音音量"},
    "label_src_lang": {"ko": "내 언어 (Qwen)", "en": "My language (Qwen)",
                       "ja": "自分の言語 (Qwen)", "zh": "我的语言 (Qwen)"},
    "label_in_src_lang": {"ko": "상대 언어 (Qwen)", "en": "Their language (Qwen)",
                          "ja": "相手の言語 (Qwen)", "zh": "对方语言 (Qwen)"},
    "tip_src_lang": {
        "ko": "발화 언어 지정 (Qwen 전용 — 자동 감지가 없습니다. 비우면 영어로 간주). "
              "Gemini 사용 시에는 자동 감지되므로 무시됩니다.",
        "en": "Spoken language for Qwen - it cannot auto-detect (empty = assumes "
              "English). Ignored while using Gemini (auto-detected).",
        "ja": "発話言語の指定 (Qwen専用 — 自動検出なし。空欄は英語扱い)。"
              "Gemini使用時は自動検出のため無視されます。",
        "zh": "指定语音语言（仅 Qwen — 无法自动检测，留空则视为英语）。"
              "使用 Gemini 时自动检测，此设置被忽略。"},
    "ph_src_auto": {"ko": "언어 검색 (비우면 자동/영어)", "en": "Search language (empty = auto/en)",
                    "ja": "言語を検索 (空欄 = 自動/英語)", "zh": "搜索语言（留空 = 自动/英语）"},
    "dash_src_out": {"ko": "내 발화 언어", "en": "My spoken language",
                     "ja": "自分の発話言語", "zh": "我的语音语言"},
    "dash_src_in": {"ko": "상대 발화 언어", "en": "Their spoken language",
                    "ja": "相手の発話言語", "zh": "对方语音语言"},
    "dash_src_auto": {"ko": "발화 언어 자동 감지 (Gemini)",
                      "en": "Spoken language auto-detected (Gemini)",
                      "ja": "発話言語を自動検出 (Gemini)",
                      "zh": "语音语言自动检测 (Gemini)"},
    "close_action_tray": {"ko": "트레이로 숨김", "en": "Hide to tray",
                          "ja": "トレイに隠す", "zh": "隐藏到托盘"},
    "close_action_exit": {"ko": "즉시 종료", "en": "Exit immediately",
                          "ja": "すぐ終了", "zh": "立即退出"},
    "btn_restart_runtime": {"ko": "런타임 재시작", "en": "Restart runtime",
                            "ja": "ランタイム再起動", "zh": "重启运行时"},
    "btn_overlay_move": {"ko": "자막 위치 이동", "en": "Move subtitles",
                         "ja": "字幕位置を移動", "zh": "移动字幕位置"},
    "btn_overlay_done": {"ko": "자막 이동 완료", "en": "Done moving",
                         "ja": "移動完了", "zh": "移动完成"},
    "btn_overlay_reset": {"ko": "자막 위치 리셋", "en": "Reset subtitle pos",
                          "ja": "字幕位置リセット", "zh": "重置字幕位置"},
    "subtitle_live_placeholder": {"ko": "실시간 자막이 여기에 표시됩니다.",
                                  "en": "Live subtitles appear here.",
                                  "ja": "リアルタイム字幕がここに表示されます。",
                                  "zh": "实时字幕会显示在这里。"},
    "desktop_subtitle_title": {"ko": "vrclt 자막", "en": "vrclt subtitles",
                               "ja": "vrclt 字幕", "zh": "vrclt 字幕"},
    "ctl_my_translate": {"ko": "내 말 번역", "en": "Translate my speech",
                         "ja": "自分の発話を翻訳", "zh": "翻译我的发言"},
    "ctl_their_sub": {"ko": "상대 말 자막", "en": "Subtitles for others",
                      "ja": "相手の字幕", "zh": "对方字幕"},
    "btn_trans_on": {"ko": "번역 ON", "en": "Translate ON", "ja": "翻訳 ON", "zh": "翻译 开"},
    "btn_trans_off": {"ko": "원음 송출", "en": "Passthrough", "ja": "原音送出", "zh": "原声直传"},
    "btn_sub_on": {"ko": "자막 ON", "en": "Subtitles ON", "ja": "字幕 ON", "zh": "字幕 开"},
    "btn_sub_off": {"ko": "자막 OFF", "en": "Subtitles OFF", "ja": "字幕 OFF", "zh": "字幕 关"},
    "btn_text_only_on": {"ko": "텍스트 전용", "en": "Text only", "ja": "テキストのみ", "zh": "仅文本"},
    "btn_text_only_off": {"ko": "음성 번역", "en": "Voice mode", "ja": "音声翻訳", "zh": "语音模式"},
    # dashboard panel device pickers (captions reuse label_mic_device /
    # label_voice_out_device; the default entry reuses default_device)
    "dash_applying": {"ko": "적용 중…", "en": "Applying…", "ja": "適用中…", "zh": "应用中…"},
    "dash_apply_failed": {"ko": "적용 실패", "en": "Apply failed",
                          "ja": "適用失敗", "zh": "应用失败"},
    # ---- wrist menu captions / buttons ----
    "out_lang": {"ko": "출력", "en": "Output", "ja": "出力", "zh": "输出"},
    "sub_lang": {"ko": "자막", "en": "Subs", "ja": "字幕", "zh": "字幕"},
    "my_to_other": {"ko": "내말→상대", "en": "Me→others", "ja": "自分→相手", "zh": "我→对方"},
    "other_to_sub": {"ko": "상대→자막", "en": "Others→subs",
                     "ja": "相手→字幕", "zh": "对方→字幕"},
    "wrist_move": {"ko": "손목", "en": "Wrist", "ja": "手首", "zh": "手腕"},
    "pos_reset": {"ko": "리셋", "en": "Reset", "ja": "リセット", "zh": "重置"},
    # wrist reset button: dual-purpose, labeled by what it will reset
    "reset_watch_pos": {"ko": "시계 리셋", "en": "Reset watch",
                        "ja": "時計リセット", "zh": "重置手表"},
    "reset_sub_pos": {"ko": "자막 리셋", "en": "Reset subs",
                      "ja": "字幕リセット", "zh": "重置字幕"},
    "btn_restarting": {"ko": "재시작 중...", "en": "Restarting...",
                       "ja": "再起動中...", "zh": "正在重启..."},
    "sub_move": {"ko": "자막", "en": "Subs", "ja": "字幕", "zh": "字幕"},
    "ui_lang": {"ko": "UI 언어", "en": "UI lang", "ja": "UI言語", "zh": "界面语言"},
    "sub_placeholder": {"ko": "⠿ 자막 위치 (드래그)", "en": "⠿ subtitle area (drag)",
                        "ja": "⠿ 字幕の位置 (ドラッグ)", "zh": "⠿ 字幕位置 (拖动)"},
    # ---- settings ----
    "ph_out_add": {"ko": "추가할 출력 언어 검색", "en": "Search output language to add",
                   "ja": "追加する出力言語を検索", "zh": "搜索要添加的输出语言"},
    "ph_sub_add": {"ko": "추가할 자막 언어 검색", "en": "Search subtitle language to add",
                   "ja": "追加する字幕言語を検索", "zh": "搜索要添加的字幕语言"},
    "label_add_out_lang": {"ko": "출력 언어 추가", "en": "Add output language",
                           "ja": "出力言語を追加", "zh": "添加输出语言"},
    "label_add_sub_lang": {"ko": "자막 언어 추가", "en": "Add subtitle language",
                           "ja": "字幕言語を追加", "zh": "添加字幕语言"},
    "btn_add": {"ko": "추가", "en": "Add", "ja": "追加", "zh": "添加"},
    "grp_api": {"ko": "기본 / API", "en": "General / API", "ja": "基本 / API", "zh": "基本 / API"},
    "grp_lang": {"ko": "언어", "en": "Languages", "ja": "言語", "zh": "语言"},
    "grp_ui": {"ko": "UI", "en": "UI", "ja": "UI", "zh": "UI"},
    "grp_hotkeys": {"ko": "PC 핫키", "en": "PC hotkeys", "ja": "PCホットキー", "zh": "PC 热键"},
    "grp_dev": {"ko": "장치", "en": "Devices", "ja": "デバイス", "zh": "设备"},
    "grp_audio": {"ko": "오디오 / 게이팅", "en": "Audio / gating",
                  "ja": "オーディオ / ゲーティング", "zh": "音频 / 门控"},
    "grp_osc_vr": {"ko": "OSC / VR", "en": "OSC / VR", "ja": "OSC / VR", "zh": "OSC / VR"},
    "grp_overlay_wrist": {"ko": "VR 오버레이 / 손목 UI", "en": "VR overlay / wrist UI",
                          "ja": "VR オーバーレイ / 手首UI", "zh": "VR 叠加层 / 手腕 UI"},
    "grp_steamvr": {"ko": "SteamVR 연동", "en": "SteamVR integration",
                    "ja": "SteamVR連携", "zh": "SteamVR 集成"},
    "btn_save_restart": {"ko": "설정 저장 및 재시작", "en": "Save settings and restart",
                         "ja": "設定を保存して再起動", "zh": "保存设置并重启"},
    "btn_refresh_devices": {"ko": "장치 목록 새로고침", "en": "Refresh devices",
                            "ja": "デバイス一覧を更新", "zh": "刷新设备列表"},
    "btn_test_output": {"ko": "테스트", "en": "Test", "ja": "テスト", "zh": "测试"},
    "msg_test_playing": {"ko": "테스트 소리 재생 중...", "en": "Playing test tone...",
                         "ja": "テスト音を再生中...", "zh": "正在播放测试音..."},
    "msg_test_failed": {"ko": "소리 테스트 실패", "en": "Sound test failed",
                        "ja": "テスト再生に失敗", "zh": "测试播放失败"},
    "msg_devices_refreshing": {"ko": "장치 새로고침 중 (런타임 재시작)...",
                               "en": "Refreshing devices (restarts the runtime)...",
                               "ja": "デバイスを更新中 (ランタイム再起動)...",
                               "zh": "正在刷新设备（将重启运行时）..."},
    "btn_reset_config": {"ko": "기본값 리셋", "en": "Reset defaults",
                         "ja": "既定値にリセット", "zh": "重置为默认值"},
    "btn_refresh_log": {"ko": "로그 새로고침", "en": "Refresh log",
                        "ja": "ログを更新", "zh": "刷新日志"},
    "btn_update_open": {"ko": "릴리즈 열기", "en": "Open release",
                        "ja": "リリースを開く", "zh": "打开发布页"},
    "label_log_file": {"ko": "로그 파일", "en": "Log file", "ja": "ログファイル", "zh": "日志文件"},
    "btn_open_log_folder": {"ko": "폴더 열기", "en": "Open folder",
                            "ja": "フォルダーを開く", "zh": "打开文件夹"},
    "logs_follow": {"ko": "실시간 따라가기", "en": "Follow",
                    "ja": "自動追従", "zh": "实时跟随"},
    "logs_level_all": {"ko": "전체 레벨", "en": "All levels",
                       "ja": "全レベル", "zh": "全部级别"},
    "logs_search_ph": {"ko": "로그 검색...", "en": "Search log...",
                       "ja": "ログを検索...", "zh": "搜索日志..."},
    "about_paths": {"ko": "설정: {config}\n릴리스 exe는 설정을 AppData에 저장합니다.",
                    "en": "Config: {config}\nStandalone mode stores settings in AppData when running as an exe.",
                    "ja": "設定: {config}\nリリースexeは設定をAppDataに保存します。",
                    "zh": "配置: {config}\n发行版 exe 会把设置保存到 AppData。"},
    "tray_show": {"ko": "창 열기", "en": "Open window", "ja": "ウィンドウを開く", "zh": "打开窗口"},
    "tray_settings": {"ko": "설정 열기", "en": "Open settings", "ja": "設定を開く", "zh": "打开设置"},
    "tray_update": {"ko": "업데이트 열기", "en": "Open update",
                    "ja": "アップデートを開く", "zh": "打开更新"},
    "tray_trans": {"ko": "번역 ON/OFF", "en": "Translation ON/OFF",
                   "ja": "翻訳 ON/OFF", "zh": "翻译 开/关"},
    "tray_subs": {"ko": "자막 ON/OFF", "en": "Subtitles ON/OFF",
                  "ja": "字幕 ON/OFF", "zh": "字幕 开/关"},
    "tray_quit": {"ko": "종료", "en": "Quit", "ja": "終了", "zh": "退出"},
    "tray_still_running": {"ko": "트레이에서 계속 실행 중입니다.",
                           "en": "Still running in the tray.",
                           "ja": "トレイで実行中です。",
                           "zh": "仍在托盘中运行。"},
    "update_title": {"ko": "vrclt 업데이트 가능", "en": "vrclt update available",
                     "ja": "vrclt アップデートがあります", "zh": "vrclt 有可用更新"},
    "update_body": {"ko": "새 버전 {latest}이 있습니다. 현재 버전은 {current}입니다.",
                    "en": "Version {latest} is available. Current version: {current}.",
                    "ja": "新しいバージョン {latest} があります。現在: {current}。",
                    "zh": "新版本 {latest} 可用。当前版本：{current}。"},
    "version_unknown": {"ko": "알 수 없음", "en": "unknown", "ja": "不明", "zh": "未知"},
    "reset_config_title": {"ko": "설정 기본값 리셋", "en": "Reset settings to defaults",
                           "ja": "設定を既定値にリセット", "zh": "将设置重置为默认值"},
    "reset_config_body": {
        "ko": "설정을 기본값으로 되돌리고 런타임을 재시작할까요?\n\n보존: API 키, 출력 언어 목록, 자막 언어 목록, UI 언어, 창 닫기 동작, 선택한 오디오 장치\n초기화: 오디오 튜닝, OSC, VR 위치, 핫키 등",
        "en": "Reset settings to defaults and restart the runtime?\n\nKept: API key, output language list, subtitle language list, UI language, window close action, selected audio devices\nReset: audio tuning, OSC, VR positions, hotkeys, and other settings",
        "ja": "設定を既定値に戻してランタイムを再起動しますか?\n\n保持: APIキー、出力言語リスト、字幕言語リスト、UI言語、ウィンドウを閉じる動作、選択したオーディオデバイス\nリセット: オーディオ調整、OSC、VR位置、ホットキーなど",
        "zh": "将设置重置为默认值并重启运行时吗？\n\n保留：API 密钥、输出语言列表、字幕语言列表、UI 语言、窗口关闭行为、已选择的音频设备\n重置：音频调校、OSC、VR 位置、热键等",
    },
    "reset_config_update_body": {
        "ko": "앱 버전이 {previous}에서 {current}(으)로 바뀌었습니다.\n새 기본값을 적용하도록 설정을 리셋할까요?\n\n보존: API 키, 출력 언어 목록, 자막 언어 목록, UI 언어, 창 닫기 동작, 선택한 오디오 장치\n초기화: 오디오 튜닝, OSC, VR 위치, 핫키 등\n\n아니요를 선택하면 이번 버전에서는 다시 묻지 않습니다.",
        "en": "App version changed from {previous} to {current}.\nReset settings to apply the new defaults?\n\nKept: API key, output language list, subtitle language list, UI language, window close action, selected audio devices\nReset: audio tuning, OSC, VR positions, hotkeys, and other settings\n\nChoosing No will not ask again for this version.",
        "ja": "アプリのバージョンが {previous} から {current} に変わりました。\n新しい既定値を適用するために設定をリセットしますか?\n\n保持: APIキー、出力言語リスト、字幕言語リスト、UI言語、ウィンドウを閉じる動作、選択したオーディオデバイス\nリセット: オーディオ調整、OSC、VR位置、ホットキーなど\n\nいいえを選ぶと、このバージョンでは再表示しません。",
        "zh": "应用版本已从 {previous} 变为 {current}。\n要重置设置以应用新的默认值吗？\n\n保留：API 密钥、输出语言列表、字幕语言列表、UI 语言、窗口关闭行为、已选择的音频设备\n重置：音频调校、OSC、VR 位置、热键等\n\n选择“否”后，此版本不会再次询问。",
    },
    "msg_save_failed": {"ko": "저장 실패", "en": "Save failed", "ja": "保存失敗", "zh": "保存失败"},
    "msg_save_restarting": {"ko": "저장됨. 런타임 재시작 중...",
                            "en": "Saved. Restarting runtime...",
                            "ja": "保存しました。ランタイムを再起動中...",
                            "zh": "已保存。正在重启运行时..."},
    "msg_applied": {"ko": "적용됨", "en": "Applied", "ja": "適用しました", "zh": "已应用"},
    "msg_saved_start_failed": {"ko": "저장됨. 런타임 시작 실패",
                               "en": "Saved. Runtime start failed",
                               "ja": "保存しました。ランタイム起動失敗",
                               "zh": "已保存。运行时启动失败"},
    "msg_runtime_restarting": {"ko": "런타임 재시작 중...",
                               "en": "Restarting runtime...",
                               "ja": "ランタイムを再起動中...",
                               "zh": "正在重启运行时..."},
    "msg_reset_restarting": {"ko": "설정 리셋 중...",
                             "en": "Resetting settings...",
                             "ja": "設定をリセット中...",
                             "zh": "正在重置设置..."},
    "msg_reset_done": {"ko": "설정을 기본값으로 리셋했습니다.",
                       "en": "Settings were reset to defaults.",
                       "ja": "設定を既定値にリセットしました。",
                       "zh": "设置已重置为默认值。"},
    "msg_reset_failed": {"ko": "설정 리셋 실패", "en": "Settings reset failed",
                         "ja": "設定リセット失敗", "zh": "设置重置失败"},
    "msg_devices_refreshed": {"ko": "장치 목록을 새로고침했습니다.",
                              "en": "Device list refreshed.",
                              "ja": "デバイス一覧を更新しました。",
                              "zh": "设备列表已刷新。"},
    "msg_device_applying": {"ko": "오디오 장치 적용 중...",
                            "en": "Applying audio device...",
                            "ja": "オーディオデバイスを適用中...",
                            "zh": "正在应用音频设备..."},
    "msg_device_failed": {"ko": "오디오 장치 적용 실패", "en": "Audio device apply failed",
                          "ja": "オーディオデバイス適用失敗", "zh": "音频设备应用失败"},
    "msg_mode_failed": {"ko": "모드 적용 실패", "en": "Mode apply failed",
                        "ja": "モード適用失敗", "zh": "模式应用失败"},
    "msg_mode_applying": {"ko": "앱 모드 적용 중...", "en": "Applying app mode...",
                          "ja": "アプリモードを適用中...", "zh": "正在应用模式..."},
    "msg_mode_applied": {"ko": "앱 모드 적용됨", "en": "App mode applied",
                         "ja": "アプリモードを適用しました", "zh": "应用模式已生效"},
    "msg_text_only_failed": {"ko": "텍스트 전용 적용 실패", "en": "Text-only apply failed",
                             "ja": "テキストのみ適用失敗", "zh": "仅文本模式应用失败"},
    "msg_text_only_applying": {"ko": "텍스트 전용 적용 중...", "en": "Applying text-only mode...",
                               "ja": "テキストのみを適用中...", "zh": "正在应用仅文本模式..."},
    "osc_feedback_translation_on": {"ko": "번역 ON", "en": "Translation ON",
                                    "ja": "翻訳 ON", "zh": "翻译 开"},
    "osc_feedback_translation_off_voice": {"ko": "번역 OFF (원음 송출)",
                                           "en": "Translation OFF (voice passthrough)",
                                           "ja": "翻訳 OFF (原音送出)",
                                           "zh": "翻译 关（原声直传）"},
    "osc_feedback_translation_off_text": {"ko": "번역 OFF (텍스트 전송 중지)",
                                          "en": "Translation OFF (text output stopped)",
                                          "ja": "翻訳 OFF (テキスト送信停止)",
                                          "zh": "翻译 关（文本发送停止）"},
    "osc_feedback_language": {"ko": "번역 언어: {language}",
                              "en": "Translation language: {language}",
                              "ja": "翻訳言語: {language}",
                              "zh": "翻译语言: {language}"},
    "msg_log_missing": {"ko": "아직 로그 파일이 생성되지 않았습니다.",
                        "en": "Log file has not been created yet.",
                        "ja": "ログファイルはまだ作成されていません。",
                        "zh": "日志文件尚未创建。"},
    "msg_log_failed": {"ko": "로그 읽기 실패", "en": "Failed to read log",
                       "ja": "ログ読み込み失敗", "zh": "读取日志失败"},
    "err_api_key_url": {"ko": "API 키에는 URL이 아니라 Gemini API 키를 입력해야 합니다.",
                        "en": "Enter a Gemini API key, not a URL.",
                        "ja": "URLではなくGemini APIキーを入力してください。",
                        "zh": "请输入 Gemini API 密钥，而不是 URL。"},
    "err_api_key_empty": {"ko": "API 키가 비어 있습니다.",
                          "en": "API key is empty.",
                          "ja": "APIキーが空です。",
                          "zh": "API 密钥为空。"},
    "err_qwen_api_key_url": {"ko": "API 키에는 URL이 아니라 DashScope API 키를 입력해야 합니다.",
                             "en": "Enter a DashScope API key, not a URL.",
                             "ja": "URLではなくDashScope APIキーを入力してください。",
                             "zh": "请输入 DashScope API 密钥，而不是 URL。"},
    "err_qwen_api_key_empty": {"ko": "Qwen(DashScope) API 키가 비어 있습니다.",
                               "en": "Qwen (DashScope) API key is empty.",
                               "ja": "Qwen (DashScope) APIキーが空です。",
                               "zh": "Qwen (DashScope) API 密钥为空。"},
    "err_qwen_workspace_required": {
        "ko": "Qwen intl 서버는 Model Studio 워크스페이스 ID가 필요합니다.",
        "en": "Qwen intl endpoint requires a Model Studio workspace ID.",
        "ja": "Qwen intlサーバーにはModel StudioワークスペースIDが必要です。",
        "zh": "Qwen intl 服务器需要 Model Studio 工作空间 ID。"},
    "default_device": {"ko": "(기본)", "en": "(default)", "ja": "(既定)", "zh": "(默认)"},
    # ---- settings field labels ----
    "f.provider": {"ko": "번역 엔진 (gemini | qwen)", "en": "Translation engine (gemini | qwen)",
                   "ja": "翻訳エンジン (gemini | qwen)", "zh": "翻译引擎 (gemini | qwen)"},
    "f.api_key": {"ko": "Gemini API 키", "en": "Gemini API key",
                  "ja": "Gemini APIキー", "zh": "Gemini API 密钥"},
    "f.model": {"ko": "Gemini 모델", "en": "Gemini model",
                "ja": "Geminiモデル", "zh": "Gemini 模型"},
    "f.qwen.api_key": {"ko": "Qwen API 키 (DashScope)", "en": "Qwen API key (DashScope)",
                       "ja": "Qwen APIキー (DashScope)", "zh": "Qwen API 密钥 (DashScope)"},
    "f.qwen.model": {"ko": "Qwen 모델", "en": "Qwen model",
                     "ja": "Qwenモデル", "zh": "Qwen 模型"},
    "f.qwen.endpoint": {"ko": "Qwen 서버 (intl=국제 | beijing=중국)",
                        "en": "Qwen endpoint (intl | beijing)",
                        "ja": "Qwenサーバー (intl=国際 | beijing=中国)",
                        "zh": "Qwen 服务器 (intl=国际 | beijing=中国大陆)"},
    "f.qwen.workspace_id": {"ko": "Qwen 워크스페이스 ID (intl 필수)",
                            "en": "Qwen workspace ID (required for intl)",
                            "ja": "QwenワークスペースID (intlでは必須)",
                            "zh": "Qwen 工作空间 ID（intl 必填）"},
    "f.qwen.voice_clone": {
        "ko": "Qwen 음성 복제 (once=시작 시 | always=응답마다·느림 | off)",
        "en": "Qwen voice cloning (once | always=slower | off)",
        "ja": "Qwen音声クローン (once=開始時 | always=毎回·遅い | off)",
        "zh": "Qwen 声音复刻（once=开始时 | always=每次·较慢 | off）"},
    "f.qwen.voice": {"ko": "Qwen 음성 ID (복제 off일 때, 비우면 기본)",
                     "en": "Qwen voice ID (when cloning off; empty = default)",
                     "ja": "QwenボイスID (クローンoff時, 空欄 = 既定)",
                     "zh": "Qwen 语音 ID（复刻 off 时，留空 = 默认）"},
    "f.app.mode": {"ko": "기본 실행 대상", "en": "Default app target",
                   "ja": "既定の実行対象", "zh": "默认应用目标"},
    "f.app.profiles.discord.process": {"ko": "Discord 캡처 프로세스", "en": "Discord capture process",
                                        "ja": "Discordキャプチャプロセス", "zh": "Discord 捕获进程"},
    "f.outbound.target_language": {"ko": "기본 출력 언어", "en": "Default output language",
                                   "ja": "既定の出力言語", "zh": "默认输出语言"},
    "f.outbound.source_language": {"ko": "내 발화 언어 (Qwen 필수)",
                                   "en": "My spoken language (Qwen: required)",
                                   "ja": "自分の発話言語 (Qwen: 必須)",
                                   "zh": "我的语音语言（Qwen 必填）"},
    "f.inbound.source_language": {"ko": "상대 발화 언어 (Qwen 필수)",
                                  "en": "Others' spoken language (Qwen: required)",
                                  "ja": "相手の発話言語 (Qwen: 必須)",
                                  "zh": "对方语音语言（Qwen 必填）"},
    "f.control.languages": {"ko": "출력 언어 목록", "en": "Output language list",
                            "ja": "出力言語リスト", "zh": "输出语言列表"},
    "f.inbound.target_language": {"ko": "기본 자막 언어", "en": "Default subtitle language",
                                  "ja": "既定の字幕言語", "zh": "默认字幕语言"},
    "f.inbound.languages": {"ko": "자막 언어 목록", "en": "Subtitle language list",
                            "ja": "字幕言語リスト", "zh": "字幕语言列表"},
    "f.ui.mode": {"ko": "UI 모드", "en": "UI mode", "ja": "UIモード", "zh": "UI 模式"},
    "f.ui.lang": {"ko": "UI 언어(auto/en/ko/ja/zh)", "en": "UI language (auto/en/ko/ja/zh)",
                  "ja": "UI言語 (auto/en/ko/ja/zh)", "zh": "UI 语言 (auto/en/ko/ja/zh)"},
    "f.hotkeys.enabled": {"ko": "PC 핫키 사용", "en": "Enable PC hotkeys",
                          "ja": "PCホットキーを有効化", "zh": "启用 PC 热键"},
    "f.hotkeys.translation_toggle": {"ko": "번역 토글 핫키", "en": "Translation toggle hotkey",
                                     "ja": "翻訳切替ホットキー", "zh": "翻译开关热键"},
    "f.hotkeys.subtitles_toggle": {"ko": "자막 토글 핫키", "en": "Subtitles toggle hotkey",
                                   "ja": "字幕切替ホットキー", "zh": "字幕开关热键"},
    "f.hotkeys.translation_hold": {"ko": "번역 일시중지 핫키 (누르는 동안)",
                                   "en": "Hold-to-pause translation hotkey",
                                   "ja": "翻訳一時停止ホットキー（押下中）",
                                   "zh": "按住暂停翻译热键"},
    "f.hotkeys.enabled_in_vr": {"ko": "VR 실행 중에도 핫키 사용",
                                "en": "Hotkeys active while in VR",
                                "ja": "VR中もホットキーを有効化",
                                "zh": "VR 运行时也启用热键"},
    "f.outbound.mic_device": {"ko": "마이크 (입력)", "en": "Microphone (input)",
                              "ja": "マイク (入力)", "zh": "麦克风 (输入)"},
    "f.outbound.text_only": {"ko": "텍스트 전용(원음 전달 + 챗박스)",
                             "en": "Text only (mic passthrough + chatbox)",
                             "ja": "テキストのみ (原音送出 + チャット)",
                             "zh": "仅文本（原声直传 + 聊天框）"},
    "f.outbound.tts_device": {"ko": "번역음성 출력 (케이블)", "en": "Translated voice out (cable)",
                              "ja": "翻訳音声出力 (ケーブル)", "zh": "翻译语音输出 (虚拟线)"},
    "f.outbound.monitor_device": {"ko": "번역음성 모니터 (내 헤드폰)", "en": "Voice monitor (my headphones)",
                                  "ja": "音声モニター (自分のヘッドホン)", "zh": "语音监听 (我的耳机)"},
    "f.inbound.audio_device": {"ko": "인바운드 음성 출력", "en": "Inbound voice output",
                               "ja": "受信音声の出力", "zh": "接收语音输出"},
    "f.inbound.process": {"ko": "캡처 프로세스", "en": "Capture process",
                          "ja": "キャプチャプロセス", "zh": "捕获进程"},
    "f.outbound.tts_gain": {"ko": "번역 음성 볼륨 (0–2)", "en": "Translated voice volume (0–2)",
                            "ja": "翻訳音声の音量 (0–2)", "zh": "翻译语音音量 (0–2)"},
    "f.outbound.glossary": {"ko": "번역 용어집 (한 줄에 원문=번역)",
                            "en": "Translation glossary (source=target per line)",
                            "ja": "翻訳用語集（1行に 原文=訳語）",
                            "zh": "翻译词汇表（每行 原文=译文）"},
    "f.audio.voice_rms_threshold": {"ko": "음성 감지 임계값", "en": "Voice detection threshold",
                                    "ja": "音声検出しきい値", "zh": "语音检测阈值"},
    "f.audio.voice_hangover_sec": {"ko": "발화 유지(초)", "en": "Speech hold (s)",
                                   "ja": "発話保持 (秒)", "zh": "语音保持 (秒)"},
    "f.audio.turn_end_silence_sec": {"ko": "번역 턴 종료 침묵(초)",
                                     "en": "Translation turn-end silence (s)",
                                     "ja": "翻訳ターン終了の無音 (秒)",
                                     "zh": "翻译轮次结束静音 (秒)"},
    "f.audio.inbound_turn_end_silence_sec": {"ko": "자막 턴 종료 침묵(초)",
                                             "en": "Subtitle turn-end silence (s)",
                                             "ja": "字幕ターン終了の無音 (秒)",
                                             "zh": "字幕轮次结束静音 (秒)"},
    "f.audio.subtitle_partial_interval_sec": {"ko": "자막 실시간 갱신 간격(초)",
                                              "en": "Live subtitle refresh interval (s)",
                                              "ja": "ライブ字幕更新間隔 (秒)",
                                              "zh": "实时字幕刷新间隔 (秒)"},
    "f.audio.subtitle_finalize_silence_sec": {"ko": "자막 확정 침묵(초)",
                                              "en": "Subtitle finalize silence (s)",
                                              "ja": "字幕確定の無音 (秒)",
                                              "zh": "字幕定稿静音 (秒)"},
    "f.audio.echo_guard_multiplier": {"ko": "에코 가드 배수", "en": "Echo guard multiplier",
                                      "ja": "エコーガード倍率", "zh": "回声防护倍数"},
    "f.audio.echo_guard_hold_sec": {"ko": "상대 음성 차단 유지(초)",
                                    "en": "Other voice block hold (s)",
                                    "ja": "相手音声ブロック保持 (秒)",
                                    "zh": "对方语音阻断保持 (秒)"},
    "f.audio.echo_guard_barge_in_multiplier": {"ko": "동시 발화 통과 배수",
                                               "en": "Barge-in threshold multiplier",
                                               "ja": "同時発話通過倍率",
                                               "zh": "同时说话通过倍数"},
    "f.audio.send_interval_ms": {"ko": "전송 주기(ms)", "en": "Send interval (ms)",
                                 "ja": "送信間隔 (ms)", "zh": "发送间隔 (ms)"},
    "f.audio.finalize_silence_sec": {"ko": "문장 확정 침묵(초)", "en": "Finalize silence (s)",
                                     "ja": "文確定の無音 (秒)", "zh": "断句静音 (秒)"},
    "f.audio.mic_idle_disconnect_sec": {"ko": "마이크 유휴 연결 해제(초)",
                                        "en": "Mic idle disconnect (s)",
                                        "ja": "マイク無音切断 (秒)",
                                        "zh": "麦克风空闲断开 (秒)"},
    "f.outbound.echo_target_language": {"ko": "대상언어 입력도 따라말함", "en": "Echo target language too",
                                        "ja": "対象言語も復唱", "zh": "同时复述目标语言"},
    "f.inbound.vad_enabled": {"ko": "배경음악 게이팅(VAD)", "en": "Music gating (VAD)",
                              "ja": "音楽ゲーティング (VAD)", "zh": "背景音乐门控 (VAD)"},
    "f.inbound.vad_threshold": {"ko": "VAD 임계값(0-1)", "en": "VAD threshold (0-1)",
                                "ja": "VADしきい値 (0-1)", "zh": "VAD 阈值 (0-1)"},
    "f.inbound.vad_hangover_sec": {"ko": "VAD 유지(초)", "en": "VAD hold (s)",
                                   "ja": "VAD保持 (秒)", "zh": "VAD 保持 (秒)"},
    "f.inbound.play_audio": {"ko": "인바운드 음성 재생", "en": "Play inbound voice",
                             "ja": "受信音声を再生", "zh": "播放接收语音"},
    "f.outbound.chatbox": {"ko": "VRChat 챗박스 전송", "en": "Send to VRChat chatbox",
                           "ja": "VRChatチャットボックス送信", "zh": "发送到 VRChat 聊天框"},
    "f.osc.ip": {"ko": "OSC IP", "en": "OSC IP", "ja": "OSC IP", "zh": "OSC IP"},
    "f.osc.port": {"ko": "OSC 포트", "en": "OSC port", "ja": "OSCポート", "zh": "OSC 端口"},
    "f.osc.throttle_sec": {"ko": "OSC 전송 간격(초)", "en": "OSC send interval (s)",
                           "ja": "OSC送信間隔 (秒)", "zh": "OSC 发送间隔（秒）"},
    "f.osc.notification_sfx": {"ko": "챗박스 알림음", "en": "Chatbox notification sound",
                               "ja": "チャット通知音", "zh": "聊天框提示音"},
    "f.osc.show_source": {"ko": "챗박스에 원문 표시", "en": "Show source in chatbox",
                          "ja": "チャットボックスに原文表示", "zh": "聊天框显示原文"},
    "f.osc.stream_sentences": {"ko": "챗박스 문장 단위 즉시 전송",
                               "en": "Chatbox: stream sentence by sentence",
                               "ja": "チャットボックス: 文単位で即時送信",
                               "zh": "聊天框：按句即时发送"},
    "f.osc.chunk_display_sec": {"ko": "긴 메시지 조각 표시(초)",
                                "en": "Long message chunk display (s)",
                                "ja": "長文分割表示 (秒)", "zh": "长消息分段显示（秒）"},
    "f.control.enabled": {"ko": "아바타 OSC 제어", "en": "Avatar OSC control",
                          "ja": "アバターOSC制御", "zh": "角色 OSC 控制"},
    "f.control.osc_listen_port": {"ko": "OSC 수신 포트", "en": "OSC listen port",
                                  "ja": "OSC受信ポート", "zh": "OSC 监听端口"},
    "f.control.feedback_chatbox": {"ko": "제어 변경 챗박스 피드백",
                                   "en": "Chatbox feedback for control changes",
                                   "ja": "制御変更のチャット通知",
                                   "zh": "控制变更聊天框反馈"},
    "f.overlay.enabled": {"ko": "SteamVR 자막 오버레이", "en": "SteamVR subtitle overlay",
                          "ja": "SteamVR字幕オーバーレイ", "zh": "SteamVR 字幕叠加层"},
    "f.overlay.width_m": {"ko": "자막 너비(m)", "en": "Subtitle width (m)",
                          "ja": "字幕幅 (m)", "zh": "字幕宽度 (m)"},
    "f.overlay.height_m": {"ko": "자막 높이(m)", "en": "Subtitle height (m)",
                           "ja": "字幕高さ (m)", "zh": "字幕高度 (m)"},
    "f.overlay.font_size": {"ko": "자막 글자크기", "en": "Subtitle font size",
                            "ja": "字幕の文字サイズ", "zh": "字幕字号"},
    "f.overlay.distance_m": {"ko": "거리(m)", "en": "Distance (m)", "ja": "距離 (m)", "zh": "距离 (m)"},
    "f.overlay.below_m": {"ko": "아래 오프셋(m)", "en": "Below offset (m)",
                          "ja": "下オフセット (m)", "zh": "向下偏移 (m)"},
    "f.overlay.tilt_deg": {"ko": "기울기(°)", "en": "Tilt (°)", "ja": "傾き (°)", "zh": "倾斜 (°)"},
    "f.overlay.lines": {"ko": "표시 줄수", "en": "Lines shown", "ja": "表示行数", "zh": "显示行数"},
    "f.overlay.display_sec": {"ko": "표시 시간(초)", "en": "Display time (s)",
                              "ja": "表示時間 (秒)", "zh": "显示时间（秒）"},
    "f.overlay.show_source": {"ko": "자막에 원문 표시", "en": "Show source in subtitles",
                              "ja": "字幕に原文表示", "zh": "字幕显示原文"},
    "f.wrist_ui.enabled": {"ko": "손목 UI", "en": "Wrist UI", "ja": "手首UI", "zh": "手腕 UI"},
    "f.wrist_ui.hand": {"ko": "착용 손(left/right)", "en": "Wrist hand (left/right)",
                        "ja": "装着する手 (left/right)", "zh": "佩戴手 (left/right)"},
    "f.wrist_ui.width_m": {"ko": "손목 UI 너비(m)", "en": "Wrist UI width (m)",
                           "ja": "手首UI幅 (m)", "zh": "手腕 UI 宽度 (m)"},
    "f.wrist_ui.offset": {"ko": "손목 UI 오프셋 x,y,z", "en": "Wrist UI offset x,y,z",
                          "ja": "手首UIオフセット x,y,z", "zh": "手腕 UI 偏移 x,y,z"},
    "f.wrist_ui.tilt_deg": {"ko": "손목 UI 기울기", "en": "Wrist UI tilt",
                            "ja": "手首UI傾き", "zh": "手腕 UI 倾斜"},
    "f.wrist_ui.roll_deg": {"ko": "손목 UI 롤(blank=auto)", "en": "Wrist UI roll (blank=auto)",
                            "ja": "手首UIロール (空欄=auto)", "zh": "手腕 UI 滚转 (空=auto)"},
    "f.wrist_ui.pointer_tilt_deg": {"ko": "포인터 기울기", "en": "Pointer tilt",
                                    "ja": "ポインター傾き", "zh": "指针倾斜"},
    "f.steamvr.register": {"ko": "SteamVR 시작 앱 목록에 등록", "en": "List in SteamVR startup apps",
                           "ja": "SteamVRスタートアップに登録", "zh": "注册到 SteamVR 启动应用"},
    "f.steamvr.dashboard_panel": {"ko": "SteamVR 대시보드 패널", "en": "SteamVR dashboard panel",
                                  "ja": "SteamVRダッシュボードパネル", "zh": "SteamVR 仪表板面板"},
    "f.steamvr.auto_launch": {"ko": "SteamVR와 함께 자동 시작", "en": "Auto-start with SteamVR",
                              "ja": "SteamVRと同時に自動起動", "zh": "随 SteamVR 自动启动"},
    "tip_steamvr_unavailable": {"ko": "SteamVR 실행 중(릴리스 빌드)에서만 사용 가능",
                                "en": "Available only while SteamVR is running (release build)",
                                "ja": "SteamVR実行中（リリースビルド）のみ利用可能",
                                "zh": "仅在 SteamVR 运行时可用（发布版本）"},
    "btn_autostart_on": {"ko": "자동 시작 ON", "en": "Auto-start ON",
                         "ja": "自動起動 ON", "zh": "自动启动 开"},
    "btn_autostart_off": {"ko": "자동 시작 OFF", "en": "Auto-start OFF",
                          "ja": "自動起動 OFF", "zh": "自动启动 关"},
    "dash_font_size": {"ko": "자막 크기", "en": "Subtitle size",
                       "ja": "字幕サイズ", "zh": "字幕大小"},
    # ---- update check (Logs/About tab) ----
    "btn_check_update": {"ko": "업데이트 확인", "en": "Check for updates",
                         "ja": "アップデートを確認", "zh": "检查更新"},
    "update_checking": {"ko": "업데이트 확인 중…", "en": "Checking for updates…",
                        "ja": "アップデートを確認中…", "zh": "正在检查更新…"},
    "update_status_idle": {"ko": "현재 버전: v{current}", "en": "Current version: v{current}",
                           "ja": "現在のバージョン: v{current}", "zh": "当前版本：v{current}"},
    "update_up_to_date": {"ko": "v{current} — 최신 버전입니다", "en": "v{current} — up to date",
                          "ja": "v{current} — 最新です", "zh": "v{current} — 已是最新"},
    "update_available_short": {"ko": "업데이트 가능: {latest} (현재 v{current})",
                               "en": "Update available: {latest} (current v{current})",
                               "ja": "アップデートあり: {latest} (現在 v{current})",
                               "zh": "有可用更新：{latest}（当前 v{current}）"},
    "update_check_failed": {"ko": "업데이트 확인 실패: {reason}",
                            "en": "Update check failed: {reason}",
                            "ja": "アップデート確認失敗: {reason}",
                            "zh": "检查更新失败：{reason}"},
    "update_err_rate_limited": {"ko": "GitHub 요청 한도 초과 — 잠시 후 다시 시도하세요",
                                "en": "GitHub rate limit reached — try again later",
                                "ja": "GitHubのリクエスト上限に達しました — 後でもう一度お試しください",
                                "zh": "已达 GitHub 请求上限——请稍后再试"},
    "update_err_no_release": {"ko": "릴리스를 찾을 수 없음", "en": "No release found",
                              "ja": "リリースが見つかりません", "zh": "未找到发布版本"},
    "update_err_ssl": {"ko": "보안 연결(TLS) 실패", "en": "Secure connection (TLS) failed",
                       "ja": "セキュア接続 (TLS) に失敗", "zh": "安全连接 (TLS) 失败"},
    "update_err_timeout": {"ko": "연결 시간 초과", "en": "Connection timed out",
                           "ja": "接続がタイムアウトしました", "zh": "连接超时"},
    "update_err_network": {"ko": "네트워크 오류", "en": "Network error",
                           "ja": "ネットワークエラー", "zh": "网络错误"},
    "update_err_http": {"ko": "GitHub API 오류", "en": "GitHub API error",
                        "ja": "GitHub APIエラー", "zh": "GitHub API 错误"},
    "update_err_parse": {"ko": "GitHub 응답이 올바르지 않음",
                         "en": "Unexpected response from GitHub",
                         "ja": "GitHubからの応答が不正です", "zh": "GitHub 响应异常"},
    # ---- background-error toasts ----
    "err_config_save_failed": {"ko": "설정 저장 실패", "en": "Failed to save settings",
                               "ja": "設定の保存に失敗", "zh": "保存设置失败"},
    "err_audio_reinit_failed": {"ko": "오디오 장치 새로고침 실패",
                                "en": "Audio device refresh failed",
                                "ja": "オーディオデバイスの更新に失敗",
                                "zh": "音频设备刷新失败"},
    # ---- dashboard group titles ----
    "dash_grp_mode": {"ko": "모드", "en": "Mode", "ja": "モード", "zh": "模式"},
    "dash_grp_out": {"ko": "내 말 → 상대", "en": "My speech → others",
                     "ja": "自分の発話 → 相手", "zh": "我的发言 → 对方"},
    "dash_grp_in": {"ko": "상대 말 → 나 (자막)", "en": "Others → me (subtitles)",
                    "ja": "相手の発話 → 自分 (字幕)", "zh": "对方发言 → 我（字幕）"},
    "dash_grp_audio": {"ko": "오디오 장치", "en": "Audio devices",
                       "ja": "オーディオデバイス", "zh": "音频设备"},
    "dash_grp_display": {"ko": "자막 표시", "en": "Subtitle display",
                         "ja": "字幕表示", "zh": "字幕显示"},
    "dash_grp_app": {"ko": "앱", "en": "Application", "ja": "アプリ", "zh": "应用"},
    # ---- first-run setup banner ----
    "setup_title": {"ko": "처음 설정", "en": "First-time setup",
                    "ja": "初回セットアップ", "zh": "首次设置"},
    "setup_intro": {"ko": "번역 엔진을 고르고 API 키를 입력한 뒤 오디오 장치를 확인하세요.",
                    "en": "Pick an engine, add its API key, then check your audio devices.",
                    "ja": "翻訳エンジンを選び、APIキーを入力して、オーディオデバイスを確認してください。",
                    "zh": "选择翻译引擎，填写 API 密钥，然后检查音频设备。"},
    "setup_step_engine": {"ko": "① 번역 엔진: {provider} — 바꾸려면 설정에서 변경",
                          "en": "① Engine: {provider} — change it in Settings if needed",
                          "ja": "① 翻訳エンジン: {provider} — 変更は設定から",
                          "zh": "① 翻译引擎：{provider}——如需更换请在设置中修改"},
    "setup_step_key": {"ko": "② API 키 입력 — [API 키 받기]에서 발급 후 설정에 붙여넣기",
                       "en": "② Add the API key — get one with [Get API key], then paste it in Settings",
                       "ja": "② APIキー入力 — [APIキーを取得]で発行し、設定に貼り付け",
                       "zh": "② 填写 API 密钥——点击[获取 API 密钥]申请后粘贴到设置中"},
    "setup_step_devices": {
        "ko": "③ 오디오 장치 확인 — 말할 때 아래 '마이크 레벨'이 움직이는지, '음성 출력'이 VB-Cable/헤드셋인지 확인",
        "en": "③ Check audio devices — the mic level below should move when you speak; "
              "voice output should be your VB-Cable / headset",
        "ja": "③ オーディオデバイス確認 — 話すと下の「マイクレベル」が動くか、"
              "「音声出力」がVB-Cable/ヘッドセットかを確認",
        "zh": "③ 检查音频设备——说话时下方“麦克风电平”应有反应；“语音输出”应为 VB-Cable/耳机"},
    "setup_btn_get_key": {"ko": "API 키 받기", "en": "Get API key",
                          "ja": "APIキーを取得", "zh": "获取 API 密钥"},
    "setup_btn_open_settings": {"ko": "설정 열기", "en": "Open Settings",
                                "ja": "設定を開く", "zh": "打开设置"},
    # ---- dashboard control tooltips ----
    "tip_app_mode": {
        "ko": "번역할 대상 앱 프로필 — VRChat(마이크→게임, OSC 챗박스) 또는 Discord(캡처 프로세스 변경).",
        "en": "Which app profile to translate for — VRChat (mic→game, OSC chatbox) or "
              "Discord (different capture process).",
        "ja": "翻訳対象のアプリプロファイル — VRChat (マイク→ゲーム、OSCチャット) または "
              "Discord (キャプチャ対象が変わります)。",
        "zh": "要翻译的应用配置——VRChat（麦克风→游戏、OSC 聊天框）或 Discord（更改捕获进程）。"},
    "tip_text_only": {
        "ko": "켜면 번역 음성 대신 원음을 내보내고 번역문은 텍스트(챗박스/자막)로만 전송합니다.",
        "en": "When on, your real voice passes through and translations are sent as "
              "text only (chatbox/subtitles).",
        "ja": "オンにすると原音をそのまま送出し、翻訳はテキスト（チャット/字幕）のみで送信します。",
        "zh": "开启后直接传出原声，翻译仅以文本（聊天框/字幕）发送。"},
    "tip_translate_toggle": {
        "ko": "내 말 번역 ON/OFF. OFF(원음 송출)면 마이크 원음이 그대로 전달됩니다.",
        "en": "Toggle translating your speech. In Passthrough, your raw mic audio is "
              "forwarded unchanged.",
        "ja": "自分の発話翻訳のON/OFF。原音送出ではマイク音声がそのまま送られます。",
        "zh": "开关翻译我的发言。原声直传时麦克风原声将原样传出。"},
    "tip_subtitles_toggle": {
        "ko": "상대 말을 인식해 자막으로 표시할지 전환합니다.",
        "en": "Toggle transcribing/translating what others say into subtitles.",
        "ja": "相手の発話を字幕として表示するかを切り替えます。",
        "zh": "开关将对方发言识别并显示为字幕。"},
    "tip_out_lang": {
        "ko": "내 말이 번역되어 나가는 언어입니다.",
        "en": "The language your speech is translated into.",
        "ja": "自分の発話の翻訳先言語です。",
        "zh": "我的发言被翻译成的语言。"},
    "tip_sub_lang": {
        "ko": "상대 말 자막이 표시될 언어입니다.",
        "en": "The language subtitles for others are shown in.",
        "ja": "相手の字幕を表示する言語です。",
        "zh": "对方字幕显示的语言。"},
    "tip_add_out_lang": {
        "ko": "출력 언어 드롭다운에 언어를 추가합니다 (손목 UI/핫키 순환 목록에도 반영).",
        "en": "Add a language to the output dropdown (also used by the wrist UI / "
              "hotkey cycle).",
        "ja": "出力言語ドロップダウンに言語を追加します（手首UI/ホットキーの切替リストにも反映）。",
        "zh": "向输出语言下拉框添加语言（也用于手腕 UI/热键循环）。"},
    "tip_add_sub_lang": {
        "ko": "자막 언어 드롭다운에 언어를 추가합니다.",
        "en": "Add a language to the subtitle dropdown.",
        "ja": "字幕言語ドロップダウンに言語を追加します。",
        "zh": "向字幕语言下拉框添加语言。"},
    "tip_tts_gain": {
        "ko": "번역 음성의 출력 볼륨 (100% = 원본 크기).",
        "en": "Output volume of the translated voice (100% = original level).",
        "ja": "翻訳音声の出力音量 (100% = 元の音量)。",
        "zh": "翻译语音的输出音量（100% = 原始音量）。"},
    "tip_mic_device": {
        "ko": "내 목소리를 받는 실제 마이크를 선택하세요.",
        "en": "Select the physical microphone that captures your voice.",
        "ja": "自分の声を拾う実際のマイクを選択します。",
        "zh": "选择拾取你声音的实体麦克风。"},
    "tip_voice_out_device": {
        "ko": "번역 음성이 나갈 장치. VRChat/Discord에 들리게 하려면 VB-Cable 같은 가상 케이블의 "
              "Input을 선택하고, 게임의 마이크를 그 케이블로 설정하세요.",
        "en": "Where the translated voice is played. To be heard in VRChat/Discord, pick "
              "a virtual cable input (e.g. VB-Cable) and set the game's mic to that cable.",
        "ja": "翻訳音声の出力先。VRChat/Discordに聞かせるにはVB-Cableなどの仮想ケーブルの"
              "Inputを選び、ゲームのマイクをそのケーブルに設定してください。",
        "zh": "翻译语音的输出设备。要让 VRChat/Discord 听到，请选择虚拟声卡（如 VB-Cable）的 "
              "Input，并把游戏的麦克风设为该虚拟声卡。"},
    "tip_test_output": {
        "ko": "선택한 출력 장치로 테스트 소리를 재생합니다.",
        "en": "Play a test tone on the selected output device.",
        "ja": "選択した出力デバイスでテスト音を再生します。",
        "zh": "在所选输出设备上播放测试音。"},
    "tip_pc_sub_size": {
        "ko": "PC 데스크톱 자막 오버레이의 글자 크기입니다.",
        "en": "Font size of the desktop subtitle overlay.",
        "ja": "PCデスクトップ字幕オーバーレイの文字サイズです。",
        "zh": "桌面字幕叠加层的字号。"},
    "tip_overlay_move": {
        "ko": "데스크톱 자막 오버레이를 드래그로 이동할 수 있게 전환합니다.",
        "en": "Toggle drag-to-move for the desktop subtitle overlay.",
        "ja": "デスクトップ字幕オーバーレイをドラッグ移動できるようにします。",
        "zh": "开关桌面字幕叠加层的拖动移动。"},
    "tip_close_action": {
        "ko": "창을 닫을 때 트레이로 숨길지 완전히 종료할지 선택합니다.",
        "en": "Choose whether closing the window hides to tray or exits.",
        "ja": "ウィンドウを閉じたときにトレイへ隠すか終了するかを選びます。",
        "zh": "选择关闭窗口时是隐藏到托盘还是退出。"},
    # ---- settings field tooltips (f.<path>.tip; optional — shown when present) ----
    "f.provider.tip": {
        "ko": "gemini: 발화 언어 자동 감지, Google AI Studio 키 사용. "
              "qwen: 음성 복제 지원, 발화 언어 지정 필수, DashScope 키 사용.",
        "en": "gemini: auto-detects spoken language, uses a Google AI Studio key. "
              "qwen: supports voice cloning, requires fixed spoken languages, uses a "
              "DashScope key.",
        "ja": "gemini: 発話言語を自動検出、Google AI Studioのキーを使用。"
              "qwen: 音声クローン対応、発話言語の指定が必須、DashScopeのキーを使用。",
        "zh": "gemini：自动检测语音语言，使用 Google AI Studio 密钥。"
              "qwen：支持声音复刻，需指定语音语言，使用 DashScope 密钥。"},
    "f.api_key.tip": {
        "ko": "Google AI Studio(aistudio.google.com/apikey)에서 발급. "
              "비워두면 GEMINI_API_KEY 환경변수를 사용합니다.",
        "en": "Create one at Google AI Studio (aistudio.google.com/apikey). "
              "If empty, the GEMINI_API_KEY environment variable is used.",
        "ja": "Google AI Studio (aistudio.google.com/apikey) で発行。"
              "空欄の場合はGEMINI_API_KEY環境変数を使用します。",
        "zh": "在 Google AI Studio（aistudio.google.com/apikey）创建。"
              "留空时使用 GEMINI_API_KEY 环境变量。"},
    "f.qwen.api_key.tip": {
        "ko": "DashScope의 sk-… 키. 서버(intl/beijing)에 따라 발급처가 다르며 서로 호환되지 "
              "않습니다. 비우면 DASHSCOPE_API_KEY 환경변수 사용.",
        "en": "DashScope sk-... key. Keys are region-bound (intl vs beijing) and not "
              "interchangeable. If empty, the DASHSCOPE_API_KEY environment variable is used.",
        "ja": "DashScopeのsk-…キー。サーバー (intl/beijing) ごとに発行が異なり互換性は"
              "ありません。空欄の場合はDASHSCOPE_API_KEY環境変数を使用。",
        "zh": "DashScope 的 sk-… 密钥。密钥按区域（intl/beijing）发放且不通用。"
              "留空时使用 DASHSCOPE_API_KEY 环境变量。"},
    "f.qwen.endpoint.tip": {
        "ko": "intl = 국제(싱가포르, Model Studio), beijing = 중국 본토(Bailian). "
              "API 키는 각 서버 전용입니다.",
        "en": "intl = international (Singapore, Model Studio); beijing = mainland China "
              "(Bailian). API keys are specific to each endpoint.",
        "ja": "intl = 国際 (シンガポール、Model Studio)、beijing = 中国本土 (Bailian)。"
              "APIキーはサーバーごとに専用です。",
        "zh": "intl = 国际（新加坡，Model Studio）；beijing = 中国大陆（百炼）。"
              "API 密钥仅限对应服务器使用。"},
    "f.qwen.workspace_id.tip": {
        "ko": "intl 서버 필수. Model Studio 콘솔의 워크스페이스 메뉴에서 llm-… ID를 복사하세요.",
        "en": "Required on the intl endpoint. Copy the llm-... ID from the workspace "
              "menu in the Model Studio console.",
        "ja": "intlサーバーでは必須。Model Studioコンソールのワークスペースメニューから"
              "llm-… IDをコピーしてください。",
        "zh": "intl 服务器必填。在 Model Studio 控制台的工作空间菜单中复制 llm-… ID。"},
    "f.qwen.voice_clone.tip": {
        "ko": "once: 응답 시작 시 1회 복제(권장). always: 응답마다 복제해 내 목소리와 더 "
              "비슷하지만 느림. off: 아래 음성 ID 사용.",
        "en": "once: clone your voice once at session start (recommended). always: clone "
              "per response — closer to your voice but slower. off: use the voice ID below.",
        "ja": "once: セッション開始時に1回クローン (推奨)。always: 応答ごとにクローンし"
              "声に近いが遅い。off: 下のボイスIDを使用。",
        "zh": "once：会话开始时复刻一次（推荐）。always：每次响应都复刻，更像你的声音但更慢。"
              "off：使用下方语音 ID。"},
    "f.qwen.voice.tip": {
        "ko": "복제 off일 때 사용할 Qwen 내장 음성 ID (예: Cherry). 비우면 기본 음성.",
        "en": "Built-in Qwen voice ID used when cloning is off (e.g. Cherry). "
              "Empty = default voice.",
        "ja": "クローンoff時に使うQwen内蔵ボイスID (例: Cherry)。空欄 = 既定の声。",
        "zh": "复刻关闭时使用的 Qwen 内置语音 ID（如 Cherry）。留空 = 默认语音。"},
    "f.app.mode.tip": {
        "ko": "시작 시 적용할 앱 프로필. 캡처 프로세스·챗박스·오버레이 동작이 프로필에 따라 바뀝니다.",
        "en": "App profile applied at startup. Switches the capture process, chatbox, "
              "and overlay behavior.",
        "ja": "起動時に適用するアプリプロファイル。キャプチャ対象・チャットボックス・"
              "オーバーレイの動作が切り替わります。",
        "zh": "启动时应用的应用配置。会切换捕获进程、聊天框和叠加层行为。"},
    "f.app.profiles.discord.process.tip": {
        "ko": "Discord 모드에서 상대 음성을 캡처할 프로세스 이름 (예: Discord.exe).",
        "en": "Process name whose audio is captured in Discord mode (e.g. Discord.exe).",
        "ja": "Discordモードで相手音声をキャプチャするプロセス名 (例: Discord.exe)。",
        "zh": "Discord 模式下捕获对方语音的进程名（如 Discord.exe）。"},
    "f.outbound.source_language.tip": {
        "ko": "Qwen 전용 — 자동 감지가 없어 내가 말하는 언어를 지정해야 합니다. "
              "비우면 영어로 간주, Gemini는 무시.",
        "en": "Qwen only — it cannot auto-detect, so set the language you speak. "
              "Empty = assumes English; ignored by Gemini.",
        "ja": "Qwen専用 — 自動検出がないため自分が話す言語を指定します。"
              "空欄は英語扱い、Geminiでは無視。",
        "zh": "仅 Qwen——无法自动检测，需指定你说的语言。留空视为英语；Gemini 忽略此项。"},
    "f.inbound.source_language.tip": {
        "ko": "Qwen 전용 — 상대가 말하는 언어를 지정합니다. 비우면 영어로 간주, Gemini는 무시.",
        "en": "Qwen only — the language others speak. Empty = assumes English; "
              "ignored by Gemini.",
        "ja": "Qwen専用 — 相手が話す言語を指定します。空欄は英語扱い、Geminiでは無視。",
        "zh": "仅 Qwen——对方说的语言。留空视为英语；Gemini 忽略此项。"},
    "f.control.languages.tip": {
        "ko": "출력 언어 드롭다운/손목 UI/OSC 순환에 표시될 언어 목록 "
              "(쉼표로 구분한 언어 코드, 예: en, ja, zh-Hans).",
        "en": "Languages offered in the output dropdown / wrist UI / OSC cycle "
              "(comma-separated codes, e.g. en, ja, zh-Hans).",
        "ja": "出力言語ドロップダウン/手首UI/OSC切替に表示する言語リスト "
              "(カンマ区切りコード、例: en, ja, zh-Hans)。",
        "zh": "输出语言下拉框/手腕 UI/OSC 循环中提供的语言列表"
              "（逗号分隔代码，如 en, ja, zh-Hans）。"},
    "f.inbound.languages.tip": {
        "ko": "자막 언어 드롭다운에 표시될 언어 목록 (쉼표로 구분한 언어 코드).",
        "en": "Languages offered in the subtitle dropdown (comma-separated codes).",
        "ja": "字幕言語ドロップダウンに表示する言語リスト (カンマ区切りコード)。",
        "zh": "字幕语言下拉框中提供的语言列表（逗号分隔代码）。"},
    "f.outbound.glossary.tip": {
        "ko": "고정 번역어 지정. 한 줄에 하나씩 원문=번역 형식 (예: 아방=avatar).",
        "en": "Force specific translations. One source=target pair per line "
              "(e.g. 아방=avatar).",
        "ja": "訳語を固定します。1行に1つ 原文=訳語 形式 (例: 아방=avatar)。",
        "zh": "强制特定译法。每行一条 原文=译文（如 아방=avatar）。"},
    "f.outbound.mic_device.tip": {
        "ko": "장치 이름 일부만 적어도 됩니다(부분 일치). 비우면 시스템 기본 입력 장치.",
        "en": "Substring match on the device name. Empty = system default input device.",
        "ja": "デバイス名の一部でも一致します。空欄 = システム既定の入力デバイス。",
        "zh": "设备名支持部分匹配。留空 = 系统默认输入设备。"},
    "f.outbound.tts_device.tip": {
        "ko": "번역 음성이 재생될 장치. VRChat/Discord에 들리게 하려면 VB-Cable 같은 가상 "
              "케이블의 Input을 선택하고, 게임의 마이크를 그 케이블(CABLE Output)로 설정하세요.",
        "en": "Device the translated voice plays into. To be heard in-game, pick a "
              "virtual cable input (e.g. VB-Cable 'CABLE Input') and set the game's "
              "microphone to that cable's output.",
        "ja": "翻訳音声の再生先。ゲームに聞かせるにはVB-Cableなどの仮想ケーブルのInputを選び、"
              "ゲームのマイクをそのケーブル (CABLE Output) に設定してください。",
        "zh": "翻译语音播放到的设备。要让游戏听到，请选择虚拟声卡（如 VB-Cable 的 CABLE "
              "Input），并把游戏的麦克风设为该虚拟声卡的输出。"},
    "f.outbound.monitor_device.tip": {
        "ko": "번역 음성을 내 귀로도 듣고 싶을 때 헤드폰 장치를 지정합니다. 비우면 끔.",
        "en": "Also hear the translated voice yourself — set your headphones here. "
              "Empty = off.",
        "ja": "翻訳音声を自分でも聞きたい場合にヘッドホンを指定します。空欄 = オフ。",
        "zh": "想自己也听到翻译语音时，在此指定耳机。留空 = 关闭。"},
    "f.inbound.process.tip": {
        "ko": "상대 음성을 캡처할 앱의 프로세스 이름 (VRChat 모드: VRChat.exe). "
              "이 앱의 소리가 자막으로 변환됩니다.",
        "en": "Process whose audio is captured for subtitles (VRChat mode: VRChat.exe).",
        "ja": "字幕用に音声をキャプチャするアプリのプロセス名 (VRChatモード: VRChat.exe)。",
        "zh": "为字幕捕获音频的应用进程名（VRChat 模式：VRChat.exe）。"},
    "f.audio.voice_rms_threshold.tip": {
        "ko": "마이크 음성 감지 문턱값. 소음이 오인식되면 올리고, 말이 잘리면 낮추세요. "
              "대시보드의 마이크 레벨 미터로 확인할 수 있습니다.",
        "en": "Mic voice gate. Raise it if noise triggers translation; lower it if your "
              "speech is missed. Watch the dashboard mic level meter.",
        "ja": "マイク音声ゲート。ノイズで誤検出するなら上げ、発話を取り逃すなら下げてください。"
              "ダッシュボードのマイクレベルで確認できます。",
        "zh": "麦克风语音门限。噪音误触发就调高，漏识别就调低。可通过仪表板的麦克风电平确认。"},
    "f.audio.voice_hangover_sec.tip": {
        "ko": "짧은 숨 고르기에도 발화가 끊기지 않게 유지하는 시간(초).",
        "en": "How long (s) the turn stays open through short pauses in speech.",
        "ja": "短い間でも発話が途切れないよう保持する時間 (秒)。",
        "zh": "说话短暂停顿时保持语音段不中断的时长（秒）。"},
    "f.audio.turn_end_silence_sec.tip": {
        "ko": "이만큼 침묵하면 발화가 끝난 것으로 보고 번역을 시작합니다. "
              "짧으면 빠르지만 문장이 잘릴 수 있습니다.",
        "en": "Silence (s) that ends your turn and triggers translation. "
              "Shorter = faster but may chop sentences.",
        "ja": "この無音時間で発話終了とみなし翻訳を開始します。"
              "短いと速い反面、文が途切れることがあります。",
        "zh": "静音达到此时长即视为说完并开始翻译。越短越快，但可能截断句子。"},
    "f.audio.echo_guard_multiplier.tip": {
        "ko": "게임 소리 재생 중 마이크 문턱값을 높여 스피커 소리 재입력(에코)을 막습니다. 1.0 = 끔.",
        "en": "Raises the mic gate while game audio plays to keep speaker echo out. "
              "1.0 = off.",
        "ja": "ゲーム音声の再生中にマイクゲートを引き上げ、スピーカー音の回り込みを防ぎます。"
              "1.0 = オフ。",
        "zh": "游戏声音播放时提高麦克风门限，防止扬声器回声混入。1.0 = 关闭。"},
    "f.inbound.vad_threshold.tip": {
        "ko": "0–1. 높일수록 음악/효과음을 더 엄격하게 걸러 자막 오인식이 줄어듭니다.",
        "en": "0–1. Higher rejects music/SFX more strictly, reducing false subtitles.",
        "ja": "0–1。高いほど音楽/効果音を厳しく除外し、誤字幕が減ります。",
        "zh": "0–1。越高对音乐/音效过滤越严格，减少误出字幕。"},
    "f.ui.mode.tip": {
        "ko": "auto: SteamVR 실행 중에만 VR 오버레이 표시. desktop: VR 기능 끔.",
        "en": "auto: VR overlays only while SteamVR is running. desktop: VR features off.",
        "ja": "auto: SteamVR実行中のみVRオーバーレイを表示。desktop: VR機能オフ。",
        "zh": "auto：仅在 SteamVR 运行时显示 VR 叠加层。desktop：关闭 VR 功能。"},
    # ---- settings form chrome ----
    "val_auto": {"ko": "자동", "en": "auto", "ja": "自動", "zh": "自动"},
    "default_prefix": {"ko": "기본값: {value}", "en": "Default: {value}",
                       "ja": "既定値: {value}", "zh": "默认值: {value}"},
    "reset_field": {"ko": "기본값으로 재설정", "en": "Reset to default",
                    "ja": "既定値に戻す", "zh": "重置为默认值"},
    "msg_invalid_field": {
        "ko": "잘못된 값이 있습니다: {fields}",
        "en": "Invalid value in: {fields}",
        "ja": "不正な値があります: {fields}",
        "zh": "存在无效值：{fields}"},
    "settings_search_ph": {
        "ko": "설정 검색...", "en": "Search settings...",
        "ja": "設定を検索...", "zh": "搜索设置..."},
    # ---- additional field tooltips ----
    "f.outbound.tts_gain.tip": {
        "ko": "번역 음성 볼륨 (0.0–2.0). 대시보드 슬라이더와 같은 값입니다.",
        "en": "Translated-voice volume (0.0–2.0). Same value as the dashboard slider.",
        "ja": "翻訳音声の音量 (0.0–2.0)。ダッシュボードのスライダーと同じ値です。",
        "zh": "翻译语音音量（0.0–2.0）。与仪表板滑块相同。"},
    "f.outbound.text_only.tip": {
        "ko": "켜면 원본 마이크를 그대로 내보내고 번역은 챗박스 텍스트로만 표시합니다.",
        "en": "Pass the raw mic through and show translations as chatbox text only.",
        "ja": "元のマイク音声をそのまま送り、翻訳はチャットボックスのテキストのみで表示。",
        "zh": "直通原始麦克风，翻译仅以聊天框文字显示。"},
    "f.outbound.echo_target_language.tip": {
        "ko": "출력 언어로 말했을 때도 번역 결과를 그대로 되풀이합니다.",
        "en": "Repeat the translation even when you already spoke the target language.",
        "ja": "出力言語で話した場合でも翻訳結果をそのまま出力します。",
        "zh": "即使你已用目标语言说话，也会照样输出翻译。"},
    "f.audio.send_interval_ms.tip": {
        "ko": "마이크 오디오를 API로 보내는 주기(ms). 낮을수록 빠르지만 트래픽이 늘어납니다.",
        "en": "How often (ms) mic audio is flushed to the API. Lower = faster, more traffic.",
        "ja": "マイク音声をAPIへ送る間隔 (ms)。短いほど速いが通信量が増えます。",
        "zh": "麦克风音频发送到 API 的间隔（毫秒）。越低越快，但流量更多。"},
    "f.audio.finalize_silence_sec.tip": {
        "ko": "전사(음성 인식)가 이만큼 조용하면 세그먼트를 마무리합니다.",
        "en": "Finalize a segment after this much transcription silence (s).",
        "ja": "文字起こしがこの時間無音なら区切りを確定します (秒)。",
        "zh": "转写静音达到该时长后结束当前语段（秒）。"},
    "f.audio.mic_idle_disconnect_sec.tip": {
        "ko": "이만큼 무음이면 API 세션을 닫아 비용을 아낍니다. 0 = 항상 유지.",
        "en": "Close the API session after this much mic silence to save cost. 0 = keep open.",
        "ja": "この時間無音ならAPIセッションを閉じて課金を抑えます。0 = 維持。",
        "zh": "麦克风静音达到该时长后关闭 API 会话以省费用。0 = 一直保持。"},
    "f.audio.inbound_turn_end_silence_sec.tip": {
        "ko": "자막(수신) 세션의 발화 종료 무음 시간. 짧을수록 자막이 빨리 확정됩니다.",
        "en": "Turn-end silence for inbound subtitle sessions. Shorter finalizes subtitles sooner.",
        "ja": "字幕（受信）セッションの発話終了無音時間。短いほど字幕が早く確定します。",
        "zh": "字幕（接收）会话的话轮结束静音时长。越短字幕定稿越快。"},
    "f.audio.subtitle_partial_interval_sec.tip": {
        "ko": "라이브 자막(회색 진행 줄)의 갱신 주기(초).",
        "en": "Refresh cadence (s) of the live partial subtitle line.",
        "ja": "ライブ字幕（進行中の行）の更新間隔 (秒)。",
        "zh": "实时字幕（进行中行）的刷新间隔（秒）。"},
    "f.audio.subtitle_finalize_silence_sec.tip": {
        "ko": "이만큼 조용하면 자막 줄을 확정해 흰색으로 고정합니다.",
        "en": "Silence (s) after which a subtitle line is finalized.",
        "ja": "この無音時間で字幕行を確定します (秒)。",
        "zh": "静音达到该时长后将字幕行定稿（秒）。"},
    "f.audio.echo_guard_hold_sec.tip": {
        "ko": "게임에서 말소리가 들리는 동안 + 이 시간만큼 내 마이크 게이트를 높게 유지합니다.",
        "en": "Keep the raised mic gate this long after inbound game speech stops.",
        "ja": "ゲーム内の発話が止まった後もこの時間マイクゲートを高く維持します。",
        "zh": "游戏语音停止后，仍将麦克风门限保持提高该时长。"},
    "f.audio.echo_guard_barge_in_multiplier.tip": {
        "ko": "에코 가드 중에도 이 배수보다 큰 내 목소리는 통과시킵니다.",
        "en": "During echo guard, your own louder speech above this multiplier still passes.",
        "ja": "エコーガード中でも、この倍率を超える自分の声は通します。",
        "zh": "回声防护期间，超过此倍数的你的语音仍可通过。"},
    "f.inbound.vad_enabled.tip": {
        "ko": "Silero VAD로 말소리만 API에 보냅니다(음악/효과음 차단). 끄면 모든 소리를 보냅니다.",
        "en": "Send only detected speech to the API (filters music/SFX). Off = send everything.",
        "ja": "Silero VADで音声のみAPIへ送信（音楽/効果音を遮断）。オフで全音声を送信。",
        "zh": "仅将检测到的语音发送到 API（过滤音乐/音效）。关闭则发送全部声音。"},
    "f.inbound.vad_hangover_sec.tip": {
        "ko": "말이 멈춘 뒤에도 이만큼 더 캡처해 문장 끝이 잘리지 않게 합니다.",
        "en": "Keep capturing this long after speech stops so sentence ends aren't cut.",
        "ja": "発話停止後もこの時間キャプチャを続け、文末の欠落を防ぎます。",
        "zh": "语音停止后继续捕获该时长，避免句尾被截断。"},
    "f.inbound.play_audio.tip": {
        "ko": "상대 음성의 번역을 내 헤드폰으로도 재생합니다(자막과 별개).",
        "en": "Also play translated inbound speech to your headphones (besides subtitles).",
        "ja": "相手の音声の翻訳をヘッドホンでも再生します（字幕とは別）。",
        "zh": "将对方语音的翻译也播放到你的耳机（独立于字幕）。"},
    "f.inbound.audio_device.tip": {
        "ko": "번역 음성 재생 장치. 비우면 기본 출력 장치를 사용합니다.",
        "en": "Playback device for translated inbound speech. Empty = default output.",
        "ja": "翻訳音声の再生デバイス。空欄なら既定の出力デバイス。",
        "zh": "翻译语音的播放设备。留空使用默认输出。"},
    "f.osc.throttle_sec.tip": {
        "ko": "VRChat 챗박스 전송 최소 간격(초). VRChat의 스팸 제한을 피합니다.",
        "en": "Minimum interval (s) between chatbox sends, avoiding VRChat's spam limit.",
        "ja": "チャットボックス送信の最小間隔 (秒)。VRChatのスパム制限を回避します。",
        "zh": "聊天框发送的最小间隔（秒），避免 VRChat 的刷屏限制。"},
    "f.osc.chunk_display_sec.tip": {
        "ko": "긴 문장을 나눠 보낼 때 각 조각의 표시 시간(초).",
        "en": "Display time (s) of each part when a long message is split.",
        "ja": "長文を分割送信するときの各パートの表示時間 (秒)。",
        "zh": "长消息拆分发送时每段的显示时长（秒）。"},
    "f.osc.stream_sentences.tip": {
        "ko": "문장이 끝날 때마다 즉시 챗박스에 표시합니다(굴러가는 말풍선). "
              "끄면 세그먼트 완료 후 나눠서 재생합니다.",
        "en": "Flush each finished sentence to the chatbox immediately (rolling bubble). "
              "Off = replay long segments in delayed parts.",
        "ja": "文が完成するたびに即チャットボックスへ表示（ローリング表示）。"
              "オフでは完了後に分割表示します。",
        "zh": "每完成一句立即显示到聊天框（滚动气泡）。关闭则在语段完成后分段显示。"},
    "f.osc.show_source.tip": {
        "ko": "챗박스에 원문을 위, 번역을 아래로 함께 표시합니다.",
        "en": "Chatbox shows the source text on top with the translation below.",
        "ja": "チャットボックスに原文を上、翻訳を下に表示します。",
        "zh": "聊天框上方显示原文，下方显示译文。"},
    "f.overlay.distance_m.tip": {
        "ko": "VR 자막 패널까지의 거리(미터). VR에서 편집 모드로 잡아 옮길 수도 있습니다.",
        "en": "Distance (m) to the VR subtitle panel. You can also grab-move it in VR edit mode.",
        "ja": "VR字幕パネルまでの距離 (m)。VR内の編集モードで掴んで移動もできます。",
        "zh": "到 VR 字幕面板的距离（米）。也可在 VR 编辑模式中抓取移动。"},
    "f.overlay.below_m.tip": {
        "ko": "시선 기준 아래쪽 오프셋(미터). 클수록 자막이 낮게 보입니다.",
        "en": "Downward offset (m) from your gaze. Larger = subtitles sit lower.",
        "ja": "視線からの下方向オフセット (m)。大きいほど字幕が下に表示されます。",
        "zh": "相对视线的向下偏移（米）。越大字幕越低。"},
    "f.overlay.display_sec.tip": {
        "ko": "확정된 자막 줄이 화면에 남는 시간(초).",
        "en": "How long (s) a finalized subtitle line stays visible.",
        "ja": "確定した字幕行が表示され続ける時間 (秒)。",
        "zh": "定稿字幕行的停留时长（秒）。"},
    "f.overlay.lines.tip": {
        "ko": "동시에 표시할 최근 자막 줄 수.",
        "en": "Number of recent finalized lines kept on screen.",
        "ja": "同時に表示する直近の字幕行数。",
        "zh": "同时保留在屏幕上的最近字幕行数。"},
    "f.overlay.show_source.tip": {
        "ko": "자막 아래에 원문도 작게 표시합니다.",
        "en": "Also show the original text (smaller) under the subtitles.",
        "ja": "字幕の下に原文も小さく表示します。",
        "zh": "在字幕下方以小字显示原文。"},
    "f.wrist_ui.offset.tip": {
        "ko": "컨트롤러 기준 손목 시계 위치(미터). VR에서 '시계 이동' 모드로 잡아 "
              "옮기면 자동 저장되므로 직접 수정할 일은 거의 없습니다.",
        "en": "Watch position in controller space (m). Grab-moving it in VR (wrist edit "
              "mode) saves automatically, so hand-editing is rarely needed.",
        "ja": "コントローラー基準の腕時計位置 (m)。VR内の移動モードで掴んで動かすと"
              "自動保存されるため、手入力はほぼ不要です。",
        "zh": "控制器坐标系中的手表位置（米）。在 VR 中用移动模式抓取调整会自动保存，"
              "一般无需手动修改。"},
    "f.wrist_ui.tilt_deg.tip": {
        "ko": "손목 시계를 얼굴 쪽으로 기울이는 각도(도).",
        "en": "Extra tilt (°) of the watch toward your face.",
        "ja": "腕時計を顔側へ傾ける角度 (°)。",
        "zh": "手表朝面部倾斜的角度（°）。"},
    "f.wrist_ui.roll_deg.tip": {
        "ko": "시계의 면내 회전(도). 비우면 자동(왼손 +90 / 오른손 -90).",
        "en": "In-plane rotation (°). Empty = auto (+90 left hand / -90 right hand).",
        "ja": "面内回転 (°)。空欄で自動 (左手 +90 / 右手 -90)。",
        "zh": "面内旋转（°）。留空为自动（左手 +90 / 右手 -90）。"},
    "f.wrist_ui.pointer_tilt_deg.tip": {
        "ko": "레이저가 컨트롤러 정면에서 아래로 기우는 각도. 레이저가 손목을 못 "
              "가리키면 조정하세요(컨트롤러 기종마다 다름).",
        "en": "How far the laser tilts down from the raw controller forward. Adjust if "
              "the laser doesn't line up with your wrist (varies per controller model).",
        "ja": "レーザーがコントローラー正面から下に傾く角度。手首に合わないときに"
              "調整してください（機種により異なります）。",
        "zh": "激光相对控制器正前方向下倾斜的角度。若激光对不准手腕请调整"
              "（因控制器型号而异）。"},
    "f.wrist_ui.hand.tip": {
        "ko": "손목 시계를 착용할 손.",
        "en": "Which wrist wears the watch menu.",
        "ja": "腕時計メニューを着ける手。",
        "zh": "佩戴手表菜单的手。"},
    "f.ui.lang.tip": {
        "ko": "UI 표시 언어. 비우면 시스템 언어를 따릅니다. Qt 창과 VR 손목 메뉴에 적용됩니다.",
        "en": "UI display language. Empty = follow the system locale. Applies to the Qt "
              "window and the VR wrist menu.",
        "ja": "UI表示言語。空欄でシステム言語に従います。Qtウィンドウと VR 腕時計メニューに適用。",
        "zh": "界面显示语言。留空跟随系统语言。应用于 Qt 窗口和 VR 腕表菜单。"},
}


def detect(pref: str = "") -> str:
    """Resolve a config language preference ("" = auto from system locale)."""
    pref = (pref or "").strip().lower()
    if pref in LANGS:
        return pref
    if pref:  # e.g. "zh-Hans" -> "zh"
        for code in LANGS:
            if pref.startswith(code):
                return code
    try:
        import locale
        loc = (locale.getdefaultlocale()[0] or "").lower()  # e.g. "ko_kr"
        for code in LANGS:
            if loc.startswith(code):
                return code
    except Exception:
        pass
    return "en"


def has(key: str) -> bool:
    """True when a string key exists (tr() returns the raw key otherwise)."""
    return key in STRINGS


def tr(lang: str, key: str) -> str:
    """Look up a UI string; falls back to English, then the key itself."""
    entry = STRINGS.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("en") or key
