"""Shared UI-language strings for the Qt app and VR wrist menu.

Display language is held in AppState.ui_lang so a change in any UI propagates
live to the others.

This is the *display* language (chrome), separate from the translation target
languages (those keep their native names via LANG_LABELS in each UI).
"""
import logging

log = logging.getLogger(__name__)

# supported UI display languages
LANGS = ["en", "ko", "ja", "zh"]
UI_LANG_LABELS = {"en": "English", "ko": "한국어", "ja": "日本語", "zh": "中文"}

# key -> {lang: text}.  "f.*" keys are settings-field labels.
STRINGS = {
    # ---- header / connection ----
    "app_subtitle": {"ko": "VRChat Live Translator — 제어 · 자막 · 설정",
                     "en": "VRChat Live Translator — control · subtitles · settings",
                     "ja": "VRChat Live Translator — 操作 · 字幕 · 設定",
                     "zh": "VRChat Live Translator — 控制 · 字幕 · 设置"},
    "conn_on": {"ko": "연결됨", "en": "Connected", "ja": "接続済み", "zh": "已连接"},
    "conn_off": {"ko": "대기", "en": "Idle", "ja": "待機", "zh": "待机"},
    # ---- control ----
    "card_control": {"ko": "제어", "en": "Control", "ja": "操作", "zh": "控制"},
    "ctl_my_translate": {"ko": "내 말 번역", "en": "Translate my speech",
                         "ja": "自分の発話を翻訳", "zh": "翻译我的发言"},
    "ctl_their_sub": {"ko": "상대 말 자막", "en": "Subtitles for others",
                      "ja": "相手の字幕", "zh": "对方字幕"},
    "btn_trans_on": {"ko": "번역 ON", "en": "Translate ON", "ja": "翻訳 ON", "zh": "翻译 开"},
    "btn_trans_off": {"ko": "원음 송출", "en": "Passthrough", "ja": "原音送出", "zh": "原声直传"},
    "btn_sub_on": {"ko": "자막 ON", "en": "Subtitles ON", "ja": "字幕 ON", "zh": "字幕 开"},
    "btn_sub_off": {"ko": "자막 OFF", "en": "Subtitles OFF", "ja": "字幕 OFF", "zh": "字幕 关"},
    "card_subs": {"ko": "자막 (상대 말)", "en": "Subtitles (others)",
                  "ja": "字幕 (相手)", "zh": "字幕 (对方)"},
    # ---- wrist menu captions / buttons ----
    "out_lang": {"ko": "출력 언어", "en": "Output lang", "ja": "出力言語", "zh": "输出语言"},
    "sub_lang": {"ko": "자막 언어", "en": "Subtitle lang", "ja": "字幕言語", "zh": "字幕语言"},
    "my_to_other": {"ko": "내 말 → 상대", "en": "Me → others", "ja": "自分 → 相手", "zh": "我 → 对方"},
    "other_to_sub": {"ko": "상대 말 → 자막", "en": "Others → subs",
                     "ja": "相手 → 字幕", "zh": "对方 → 字幕"},
    "edit_mode": {"ko": "이동 모드", "en": "Move mode", "ja": "移動モード", "zh": "移动模式"},
    "edit_moving": {"ko": "이동 중", "en": "Moving", "ja": "移動中", "zh": "移动中"},
    "edit_done": {"ko": "이동 완료", "en": "Done", "ja": "完了", "zh": "完成"},
    "pos_reset": {"ko": "위치 리셋", "en": "Reset pos", "ja": "位置リセット", "zh": "重置位置"},
    "sub_move": {"ko": "자막 이동", "en": "Move subs", "ja": "字幕移動", "zh": "移动字幕"},
    "ui_lang": {"ko": "UI 언어", "en": "UI lang", "ja": "UI言語", "zh": "界面语言"},
    "sub_placeholder": {"ko": "⠿ 자막 위치 (드래그)", "en": "⠿ subtitle area (drag)",
                        "ja": "⠿ 字幕の位置 (ドラッグ)", "zh": "⠿ 字幕位置 (拖动)"},
    # ---- settings ----
    "settings_summary": {"ko": "설정",
                         "en": "Settings",
                         "ja": "設定",
                         "zh": "设置"},
    "grp_out_langs": {"ko": "출력 언어 목록 (내 말 번역)", "en": "Output languages (my speech)",
                      "ja": "出力言語リスト (自分の発話)", "zh": "输出语言列表 (我的发言)"},
    "grp_sub_langs": {"ko": "자막 언어 목록 (상대 말)", "en": "Subtitle languages (others)",
                      "ja": "字幕言語リスト (相手)", "zh": "字幕语言列表 (对方)"},
    "ph_out_add": {"ko": "언어코드 (예: vi, th, it)", "en": "lang code (e.g. vi, th, it)",
                   "ja": "言語コード (例: vi, th, it)", "zh": "语言代码 (例: vi, th, it)"},
    "ph_sub_add": {"ko": "언어코드 (예: en, ja)", "en": "lang code (e.g. en, ja)",
                   "ja": "言語コード (例: en, ja)", "zh": "语言代码 (例: en, ja)"},
    "btn_add": {"ko": "추가", "en": "Add", "ja": "追加", "zh": "添加"},
    "grp_api": {"ko": "기본 / API", "en": "General / API", "ja": "基本 / API", "zh": "基本 / API"},
    "grp_app": {"ko": "앱 모드", "en": "App mode", "ja": "アプリモード", "zh": "应用模式"},
    "grp_dev": {"ko": "장치", "en": "Devices", "ja": "デバイス", "zh": "设备"},
    "grp_audio": {"ko": "오디오 / 게이팅", "en": "Audio / gating",
                  "ja": "オーディオ / ゲーティング", "zh": "音频 / 门控"},
    "grp_inbound": {"ko": "자막 (인바운드)", "en": "Subtitles (inbound)",
                    "ja": "字幕 (受信)", "zh": "字幕 (接收)"},
    "grp_overlay": {"ko": "VR 오버레이", "en": "VR overlay", "ja": "VR オーバーレイ", "zh": "VR 叠加层"},
    "grp_uilang": {"ko": "표시 언어", "en": "Display language", "ja": "表示言語", "zh": "显示语言"},
    "btn_save": {"ko": "설정 저장", "en": "Save settings", "ja": "設定を保存", "zh": "保存设置"},
    "default_device": {"ko": "(기본)", "en": "(default)", "ja": "(既定)", "zh": "(默认)"},
    # ---- settings field labels ----
    "f.api_key": {"ko": "API 키", "en": "API key", "ja": "APIキー", "zh": "API 密钥"},
    "f.model": {"ko": "모델", "en": "Model", "ja": "モデル", "zh": "模型"},
    "f.app.mode": {"ko": "기본 실행 대상", "en": "Default app target",
                   "ja": "既定の実行対象", "zh": "默认应用目标"},
    "f.app.profiles.discord.process": {"ko": "Discord 캡처 프로세스", "en": "Discord capture process",
                                        "ja": "Discordキャプチャプロセス", "zh": "Discord 捕获进程"},
    "f.outbound.target_language": {"ko": "기본 출력 언어", "en": "Default output language",
                                   "ja": "既定の出力言語", "zh": "默认输出语言"},
    "f.inbound.target_language": {"ko": "기본 자막 언어", "en": "Default subtitle language",
                                  "ja": "既定の字幕言語", "zh": "默认字幕语言"},
    "f.outbound.mic_device": {"ko": "마이크 (입력)", "en": "Microphone (input)",
                              "ja": "マイク (入力)", "zh": "麦克风 (输入)"},
    "f.outbound.tts_device": {"ko": "번역음성 출력 (케이블)", "en": "Translated voice out (cable)",
                              "ja": "翻訳音声出力 (ケーブル)", "zh": "翻译语音输出 (虚拟线)"},
    "f.outbound.monitor_device": {"ko": "번역음성 모니터 (내 헤드폰)", "en": "Voice monitor (my headphones)",
                                  "ja": "音声モニター (自分のヘッドホン)", "zh": "语音监听 (我的耳机)"},
    "f.inbound.audio_device": {"ko": "인바운드 음성 출력", "en": "Inbound voice output",
                               "ja": "受信音声の出力", "zh": "接收语音输出"},
    "f.audio.voice_rms_threshold": {"ko": "음성 감지 임계값", "en": "Voice detection threshold",
                                    "ja": "音声検出しきい値", "zh": "语音检测阈值"},
    "f.audio.voice_hangover_sec": {"ko": "발화 유지(초)", "en": "Speech hold (s)",
                                   "ja": "発話保持 (秒)", "zh": "语音保持 (秒)"},
    "f.audio.echo_guard_multiplier": {"ko": "에코 가드 배수", "en": "Echo guard multiplier",
                                      "ja": "エコーガード倍率", "zh": "回声防护倍数"},
    "f.audio.send_interval_ms": {"ko": "전송 주기(ms)", "en": "Send interval (ms)",
                                 "ja": "送信間隔 (ms)", "zh": "发送间隔 (ms)"},
    "f.audio.finalize_silence_sec": {"ko": "문장 확정 침묵(초)", "en": "Finalize silence (s)",
                                     "ja": "文確定の無音 (秒)", "zh": "断句静音 (秒)"},
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
    "f.osc.show_source": {"ko": "챗박스에 원문 표시", "en": "Show source in chatbox",
                          "ja": "チャットボックスに原文表示", "zh": "聊天框显示原文"},
    "f.overlay.font_size": {"ko": "자막 글자크기", "en": "Subtitle font size",
                            "ja": "字幕の文字サイズ", "zh": "字幕字号"},
    "f.overlay.distance_m": {"ko": "거리(m)", "en": "Distance (m)", "ja": "距離 (m)", "zh": "距离 (m)"},
    "f.overlay.below_m": {"ko": "아래 오프셋(m)", "en": "Below offset (m)",
                          "ja": "下オフセット (m)", "zh": "向下偏移 (m)"},
    "f.overlay.tilt_deg": {"ko": "기울기(°)", "en": "Tilt (°)", "ja": "傾き (°)", "zh": "倾斜 (°)"},
    "f.overlay.lines": {"ko": "표시 줄수", "en": "Lines shown", "ja": "表示行数", "zh": "显示行数"},
    "f.overlay.show_source": {"ko": "자막에 원문 표시", "en": "Show source in subtitles",
                              "ja": "字幕に原文表示", "zh": "字幕显示原文"},
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


def tr(lang: str, key: str) -> str:
    """Look up a UI string; falls back to English, then the key itself."""
    entry = STRINGS.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("en") or key
