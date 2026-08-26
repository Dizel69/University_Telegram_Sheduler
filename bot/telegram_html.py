"""Санитайзер HTML для parse_mode=HTML в Telegram Bot API."""
from __future__ import annotations

import html
from html.parser import HTMLParser

_INLINE = {
    "b": "b",
    "strong": "b",
    "i": "i",
    "em": "i",
    "u": "u",
    "ins": "u",
    "s": "s",
    "strike": "s",
    "del": "s",
    "code": "code",
    "tg-spoiler": "tg-spoiler",
}

_SAFE_HREF = ("http://", "https://", "tg://")


class _TelegramHtmlSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_d = {(k or "").lower(): v for k, v in attrs}

        if tag == "br":
            self.parts.append("\n")
            return

        if tag in _INLINE:
            out = _INLINE[tag]
            if out == "code":
                if "code" in self.stack:
                    self.stack.append(None)
                    return
            elif self._in_fixed_width():
                self.stack.append(None)
                return
            self.parts.append(f"<{out}>")
            self.stack.append(out)
            return

        if tag == "span" and "tg-spoiler" in (attrs_d.get("class") or "").split():
            if self._in_fixed_width():
                self.stack.append(None)
                return
            self.parts.append("<tg-spoiler>")
            self.stack.append("tg-spoiler")
            return

        if tag == "a":
            href = (attrs_d.get("href") or "").strip()
            if href.startswith(_SAFE_HREF) and not self._in_fixed_width():
                self.parts.append(f'<a href="{html.escape(href, quote=True)}">')
                self.stack.append("a")
            else:
                self.stack.append(None)
            return

        if tag == "blockquote":
            expandable = any(k == "expandable" for k, _v in attrs)
            self.parts.append("<blockquote expandable>" if expandable else "<blockquote>")
            self.stack.append("blockquote")
            return

        if tag == "pre":
            self.parts.append("<pre>")
            self.stack.append("pre")
            return

        if tag in ("p", "div"):
            if self.parts and not str(self.parts[-1]).endswith("\n"):
                self.parts.append("\n")
            self.stack.append("_block")
            return

        self.stack.append(None)

    def _in_fixed_width(self) -> bool:
        return any(item in {"code", "pre"} for item in self.stack)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        opened = self.stack.pop()
        if opened == "_block":
            if self.parts and not str(self.parts[-1]).endswith("\n"):
                self.parts.append("\n")
            return
        if opened:
            self.parts.append(f"</{opened}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(html.escape(data, quote=False))

    def get_html(self) -> str:
        while self.stack:
            opened = self.stack.pop()
            if opened and opened != "_block":
                self.parts.append(f"</{opened}>")
        return "".join(self.parts).strip()


def sanitize_telegram_html(raw: str | None) -> str:
    """Оставляет только теги Telegram HTML и экранирует остальной текст."""
    if not raw:
        return ""
    parser = _TelegramHtmlSanitizer()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return html.escape(raw, quote=False)
    return parser.get_html()
