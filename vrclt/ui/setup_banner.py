"""First-run setup checklist banner for the dashboard.

Shown while the selected provider has no API key (config or env var), which
is the same predicate the controller uses for its "API key required" status.
It disappears on its own the moment a key is saved — no dismissed flag.
"""
import logging

from PySide6 import QtCore, QtWidgets

log = logging.getLogger(__name__)

KEY_URLS = {
    "gemini": "https://aistudio.google.com/apikey",
    "qwen": "https://modelstudio.console.alibabacloud.com/?tab=model#/api-key",
    "qwen_beijing": "https://bailian.console.aliyun.com/?tab=model#/api-key",
    "openai": "https://platform.openai.com/api-keys",
}


class SetupBanner(QtWidgets.QFrame):
    """Mirrors the UpdateBanner pattern: a bar in the dashboard root layout
    with sync()/retranslate() hooks, styled via #setupBar."""

    def __init__(self, tr, *, on_open_settings, on_open_url):
        super().__init__()
        self._tr = tr
        self._on_open_settings = on_open_settings
        self._on_open_url = on_open_url
        self._last_sync = None
        self._provider = "gemini"
        self._endpoint = ""

        self.setObjectName("setupBar")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        self._title = QtWidgets.QLabel("")
        self._title.setObjectName("setupTitle")
        self._intro = QtWidgets.QLabel("")
        self._intro.setObjectName("setupText")
        self._intro.setWordWrap(True)
        self._steps = QtWidgets.QLabel("")
        self._steps.setObjectName("setupText")
        self._steps.setWordWrap(True)
        buttons = QtWidgets.QHBoxLayout()
        self._btn_get_key = QtWidgets.QPushButton("")
        self._btn_get_key.clicked.connect(self._open_key_page)
        self._btn_settings = QtWidgets.QPushButton("")
        self._btn_settings.clicked.connect(lambda: self._on_open_settings())
        buttons.addWidget(self._btn_get_key)
        buttons.addWidget(self._btn_settings)
        buttons.addStretch(1)
        layout.addWidget(self._title)
        layout.addWidget(self._intro)
        layout.addWidget(self._steps)
        layout.addLayout(buttons)
        self.hide()
        self.retranslate()

    def sync(self, provider: str, key_present: bool, endpoint: str = "") -> None:
        """Called from the 250 ms refresh tick — diff before touching
        widgets so quiet ticks cause no repaints."""
        signature = (provider, key_present, endpoint)
        if signature == self._last_sync:
            return
        self._last_sync = signature
        self._provider = provider
        self._endpoint = endpoint
        self.setVisible(not key_present)
        if not key_present:
            self._render()

    def _render(self) -> None:
        self._title.setText(self._tr("setup_title"))
        self._intro.setText(self._tr("setup_intro"))
        self._steps.setText("\n".join((
            self._tr("setup_step_engine").format(provider=self._provider),
            self._tr("setup_step_key"),
            self._tr("setup_step_devices"),
        )))
        self._btn_get_key.setText(self._tr("setup_btn_get_key"))
        self._btn_settings.setText(self._tr("setup_btn_open_settings"))

    def retranslate(self) -> None:
        self._render()

    def _open_key_page(self) -> None:
        if self._provider == "qwen":
            url = KEY_URLS["qwen_beijing"] if self._endpoint == "beijing" \
                else KEY_URLS["qwen"]
        else:
            url = KEY_URLS.get(self._provider, KEY_URLS["gemini"])
        self._on_open_url(QtCore.QUrl(url))
