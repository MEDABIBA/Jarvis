"""Locale-driven speech normalization and bounded streaming sentence extraction."""

import re
from collections.abc import Iterator

_URL = re.compile(r"https?://[^\s<>()]+|www\.[^\s<>()]+", re.IGNORECASE)
_EMAIL = re.compile(r"([\w.%+-]+)@([\w.-]+)\.([a-zA-Z]{2,})")
_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_LARGE_NUMBER = re.compile(r"\b\d{5,}\b")
_BOUNDARY = re.compile(r"[.!?]+[\"'”’\)\]*_]*\s")  # noqa: RUF001
_ABBREVIATIONS = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
    "st",
    "vs",
    "etc",
    "e.g",
    "i.e",
    "np",
    "itd",
    "itp",
    "m.in",
    "ul",
    "inż",
    "mgr",
    "г",  # noqa: RUF001 -- Russian year/city abbreviation.
    "ул",
    "т.д",
    "т.п",
    "им",
}
_WORDS = {
    "en": ("dot", "slash", "at"),
    "pl": ("kropka", "ukośnik", "małpa"),
    "ru": ("точка", "слэш", "собака"),
}


class _MarkdownFilter:
    """Retain delimiter counts and line state, never marker runs or fenced code.

    Line-start fences require a closing line with at most three leading spaces
    and only whitespace after the delimiter. Inline opening fences deliberately
    retain the permissive fallback, so malformed/inline blocks stay unspoken.
    Counts are exact integers: saturating them could let a shorter run close an
    extremely long opening fence. Storage grows only with the integer bit length.
    """

    def __init__(self) -> None:
        self.fence: str | None = None
        self.fence_length = 0
        self.marker = ""
        self.count = 0
        self._block_fence = False
        self._run_at_line_start = False
        self._indent: int | None = 0
        self._closing = False

    def _close_fence(self) -> str:
        self.fence = None
        self.fence_length = 0
        self._block_fence = False
        self._closing = False
        return " "

    def _finish_marker(self) -> str:
        visible = ""
        if self.count >= 3:
            if self.fence is None:
                self.fence = self.marker
                self.fence_length = self.count
                self._block_fence = self._run_at_line_start
                visible = " "
            elif self.fence == self.marker and self.count >= self.fence_length:
                if not self._block_fence:
                    visible = self._close_fence()
                elif self._run_at_line_start:
                    # Do not expose anything until the closing line is confirmed.
                    self._closing = True
        self.marker = ""
        self.count = 0
        return visible

    def feed(self, delta: str) -> Iterator[str]:
        for char in delta:
            if self.marker and char != self.marker:
                yield from self._finish_marker()
            if self._closing:
                if char in "\r\n":
                    yield from self._close_fence()
                elif char not in " \t":
                    self._closing = False
            if char in "`~":
                if not self.marker:
                    self.marker = char
                    self._run_at_line_start = self._indent is not None
                self.count += 1
            elif self.fence is None:
                yield char
            if char in "\r\n":
                self._indent = 0
            elif self._indent is not None:
                self._indent = (
                    self._indent + 1 if char == " " and self._indent < 3 else None
                )

    def flush(self) -> str:
        visible = self._finish_marker()
        if self._closing:
            visible += self._close_fence()
        return visible


def _inline(text: str) -> str:
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}\s+|>\s*|[-*+]\s+)", "", text)
    text = re.sub(r"(?<!\w)_+(.+?)_+(?!\w)", r"\1", text)
    return " ".join(text.replace("*", "").replace("`", "").split())


def to_speech(text: str, locale: str = "en-GB") -> str:
    """Normalize using the explicit locale, never script/language heuristics.

    English is the fallback vocabulary for locales outside en/pl/ru. This does
    not select a voice; providers must still require an exact locale match.
    """
    markdown = _MarkdownFilter()
    text = _inline("".join(markdown.feed(text)) + markdown.flush())
    dot, slash, at = _WORDS.get(locale.split("-", 1)[0].lower(), _WORDS["en"])

    def url(match: re.Match[str]) -> str:
        value = match.group().rstrip(".,!?;:")
        suffix = match.group()[len(value) :]
        value = re.sub(r"^https?://(?:www\.)?|^www\.", "", value, flags=re.I)
        value = value.replace(".", f" {dot} ").replace("/", f" {slash} ")
        return value.replace("_", " ").replace("-", " ") + suffix

    def email(match: re.Match[str]) -> str:
        user, domain, tld = match.groups()
        return (
            user.replace(".", f" {dot} ")
            + f" {at} "
            + domain.replace(".", f" {dot} ")
            + f" {dot} "
            + tld
        )

    text = _URL.sub(url, text)
    text = _EMAIL.sub(email, text)
    text = _DATE.sub(r"\1 \2 \3", text)
    text = _TIME.sub(r"\1 \2", text)
    text = _LARGE_NUMBER.sub(lambda m: " ".join(m.group()), text)
    text = text.replace("_", " ")
    text = "".join(
        char for char in text if char.isalnum() or char.isspace() or char in ".,!?;:-'"
    )
    return " ".join(text.split())


class SentenceBuffer:
    """One instance per turn. Feed deltas, then flush the final unpunctuated tail.

    Whitespace confirms punctuation (possibly in the next delta). Common
    abbreviations, decimal points and internal URL punctuation are retained.
    At max_length, split at a nearby word boundary or, as a last resort, inside
    a long token. Thus even punctuation-free streams have bounded storage and
    segment length; this is deliberately a heuristic, not a language parser.
    """

    def __init__(self, max_length: int = 300) -> None:
        if max_length < 16:
            raise ValueError("max_length must be at least 16")
        self.max_length = max_length
        self._markdown = _MarkdownFilter()
        self._pending = ""

    def _protected(self, end: int) -> bool:
        prefix = self._pending[:end].rstrip()
        token = prefix.split()[-1].rstrip("\"'”’)]*_")  # noqa: RUF001
        if not token.endswith("."):
            return "://" in token or token.startswith("www.") or "@" in token
        word = token.rstrip(".").lower()
        return (
            word in _ABBREVIATIONS
            or bool(re.fullmatch(r"(?:[^\W\d_]\.)+[^\W\d_]?", word))
            or (len(word) == 1 and word.isalpha())
        )

    def _emit(self, end: int) -> str:
        sentence = _inline(self._pending[:end])
        self._pending = self._pending[end:].lstrip()
        return sentence

    def feed(self, delta: str) -> list[str]:
        sentences: list[str] = []
        for char in self._markdown.feed(delta):
            self._pending += char
            boundary = next(
                (
                    m.end()
                    for m in _BOUNDARY.finditer(self._pending)
                    if not self._protected(m.end())
                ),
                None,
            )
            if boundary is not None:
                sentence = self._emit(boundary)
                if sentence:
                    sentences.append(sentence)
            if len(self._pending) >= self.max_length:
                end = self._pending.rfind(" ", self.max_length // 2)
                sentence = self._emit(end if end > 0 else self.max_length)
                if sentence:
                    sentences.append(sentence)
        return sentences

    def flush(self) -> list[str]:
        sentences = self.feed(self._markdown.flush())
        tail = self._emit(len(self._pending))
        if tail:
            sentences.append(tail)
        return sentences
