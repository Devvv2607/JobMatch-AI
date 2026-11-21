"""Untrusted HTML to plain text, and the normalised keys used for dedup."""

import html
import re
import unicodedata
from html.parser import HTMLParser

_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "tr",
        "section",
        "article",
        "header",
        "footer",
        "blockquote",
        "pre",
        "table",
    }
)
_SKIP_TAGS = frozenset({"script", "style", "noscript", "iframe", "svg", "template", "head"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
            if tag == "li":
                self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    """Plain text from untrusted HTML. Scripts, styles and all markup are dropped; only
    text survives, so nothing in a posting can render or execute later.

    Handles Greenhouse's double encoding (HTML whose tags arrive as entities).
    """
    if "&lt;" in raw and "<" not in raw:
        raw = html.unescape(raw)
    parser = _TextExtractor()
    parser.feed(raw)
    parser.close()
    text = "".join(parser.parts)
    text = unicodedata.normalize("NFKC", text).replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def normalise_key(value: str) -> str:
    """Lower-case, accents removed, punctuation collapsed: for exact-duplicate keys."""
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9+#]+", " ", folded.lower()).split())


_TITLE_NOISE = re.compile(
    r"\s*(?:\(|\[|-|–|—|\|)\s*(?:remote|hybrid|on-?site|contract|full[- ]time|part[- ]time|"
    r"m/f/d|f/m/d|m/w/d)\s*(?:\)|\])?\s*$",
    re.I,
)


def normalise_title(title: str) -> str:
    previous = None
    while previous != title:
        previous, title = title, _TITLE_NOISE.sub("", title)
    return normalise_key(title)
