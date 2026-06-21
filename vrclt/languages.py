"""Language catalog for Gemini Live Translation targets."""
from __future__ import annotations

import re


# Google Gemini Live Translation supported languages. Keep this as codes plus
# plain names so UI labels can show the BCP-47 code unambiguously.
SUPPORTED_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("af", "Afrikaans"),
    ("ak", "Akan"),
    ("sq", "Albanian"),
    ("am", "Amharic"),
    ("ar", "Arabic"),
    ("hy", "Armenian"),
    ("az", "Azerbaijani"),
    ("eu", "Basque"),
    ("be", "Belarusian"),
    ("bn", "Bengali"),
    ("bg", "Bulgarian"),
    ("my", "Burmese Myanmar"),
    ("ca", "Catalan"),
    ("zh-Hans", "Simplified Chinese"),
    ("zh-Hant", "Traditional Chinese"),
    ("hr", "Croatian"),
    ("cs", "Czech"),
    ("da", "Danish"),
    ("nl", "Dutch"),
    ("en", "English"),
    ("et", "Estonian"),
    ("fil", "Filipino"),
    ("fi", "Finnish"),
    ("fr", "French"),
    ("gl", "Galician"),
    ("ka", "Georgian"),
    ("de", "German"),
    ("el", "Greek"),
    ("gu", "Gujarati"),
    ("ha", "Hausa"),
    ("he", "Hebrew"),
    ("hi", "Hindi"),
    ("hu", "Hungarian"),
    ("is", "Icelandic"),
    ("id", "Indonesian"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("jv", "Javanese"),
    ("kn", "Kannada"),
    ("kk", "Kazakh"),
    ("km", "Khmer"),
    ("rw", "Kinyarwanda"),
    ("ko", "Korean"),
    ("lo", "Lao"),
    ("lv", "Latvian"),
    ("lt", "Lithuanian"),
    ("mk", "Macedonian"),
    ("ms", "Malay"),
    ("ml", "Malayalam"),
    ("mr", "Marathi"),
    ("mn", "Mongolian"),
    ("ne", "Nepali"),
    ("no", "Norwegian"),
    ("nb", "Norwegian Bokmal"),
    ("fa", "Persian"),
    ("pl", "Polish"),
    ("pt-BR", "Portuguese Brazil"),
    ("pt-PT", "Portuguese Portugal"),
    ("pa", "Punjabi"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("sr", "Serbian"),
    ("sd", "Sindhi"),
    ("si", "Sinhala"),
    ("sk", "Slovak"),
    ("sl", "Slovenian"),
    ("es", "Spanish"),
    ("su", "Sundanese"),
    ("sw", "Swahili"),
    ("sv", "Swedish"),
    ("ta", "Tamil"),
    ("te", "Telugu"),
    ("th", "Thai"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("ur", "Urdu"),
    ("uz", "Uzbek"),
    ("vi", "Vietnamese"),
    ("zu", "Zulu"),
)

# Existing configs may include non-dedicated-model fallback languages.
EXTRA_LANGUAGE_NAMES: dict[str, str] = {
    "yue": "Cantonese",
}

SUPPORTED_LANGUAGE_CODES: tuple[str, ...] = tuple(code for code, _name in SUPPORTED_LANGUAGES)
SUPPORTED_LANGUAGE_NAMES: dict[str, str] = dict(SUPPORTED_LANGUAGES)
KNOWN_LANGUAGE_NAMES: dict[str, str] = {
    **SUPPORTED_LANGUAGE_NAMES,
    **EXTRA_LANGUAGE_NAMES,
}
_CANONICAL_CODES = {code.lower(): code for code in KNOWN_LANGUAGE_NAMES}
_CODE_SUFFIX_RE = re.compile(r"\(([^()]+)\)\s*$")
_BCP47_CODE_RE = re.compile(r"^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$")


def canonical_language_code(value: str) -> str:
    code = str(value or "").strip()
    if not code:
        return ""
    return _CANONICAL_CODES.get(code.lower(), code)


def language_label(code: str) -> str:
    code = canonical_language_code(code)
    name = KNOWN_LANGUAGE_NAMES.get(code)
    if not name:
        return code
    return f"{name} ({code})"


LANG_LABELS: dict[str, str] = {
    code: language_label(code)
    for code in KNOWN_LANGUAGE_NAMES
}

_LABEL_TO_CODE = {label.lower(): code for code, label in LANG_LABELS.items()}
_NAME_TO_CODE = {name.lower(): code for code, name in KNOWN_LANGUAGE_NAMES.items()}

# Compatibility with labels used by older UI builds.
_TEXT_ALIASES = {
    "english": "en",
    "japanese": "ja",
    "korean": "ko",
    "burmese (myanmar)": "my",
    "chinese simplified": "zh-Hans",
    "chinese traditional": "zh-Hant",
    "simplified chinese": "zh-Hans",
    "traditional chinese": "zh-Hant",
}


def supported_language_options() -> list[tuple[str, str]]:
    return [(code, language_label(code)) for code in SUPPORTED_LANGUAGE_CODES]


def language_code_from_text(text: str, fallback_codes=()) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    suffix = _CODE_SUFFIX_RE.search(raw)
    if suffix:
        suffix_text = suffix.group(1).strip()
        suffix_code = canonical_language_code(suffix_text)
        if suffix_code in KNOWN_LANGUAGE_NAMES or _BCP47_CODE_RE.fullmatch(suffix_text):
            return suffix_code

    direct = canonical_language_code(raw)
    if direct in KNOWN_LANGUAGE_NAMES:
        return direct

    lowered = raw.lower()
    if lowered in _LABEL_TO_CODE:
        return _LABEL_TO_CODE[lowered]
    if lowered in _NAME_TO_CODE:
        return _NAME_TO_CODE[lowered]
    if lowered in _TEXT_ALIASES:
        return _TEXT_ALIASES[lowered]

    for code in fallback_codes or ():
        code = canonical_language_code(code)
        if language_label(code).lower() == lowered:
            return code
        if code.lower() == lowered:
            return code
    return raw
