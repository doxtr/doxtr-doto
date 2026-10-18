"""Markdown <-> HTML conversion for calendar event descriptions.

doto stores a task ``body`` as **Markdown** (that is what the user types locally
and what the RST/JSON store carries). Google Calendar, however, renders a small
subset of **HTML** in an event's description and returns that HTML on read. If
we pushed Markdown verbatim it would show up as literal ``**bold**`` text in the
calendar, and if we pulled the HTML verbatim it would pollute the local body
with raw tags (as seen on DOTO-034: ``I am <b>bold</b> ... <ol><li>one</li>``).

This module bridges the two representations so the body round-trips cleanly:

* :func:`markdown_to_calendar_html` -- outbound (push): render the local
  Markdown body to the limited HTML subset Google Calendar understands.
* :func:`calendar_html_to_markdown` -- inbound (pull/merge): convert that HTML
  back into Markdown for the local store.

Only the elements Google Calendar actually renders are supported, so a
round-trip is stable (Markdown -> HTML -> Markdown is a fixed point for the
supported constructs):

    **bold**            <->  <b>bold</b>
    *italic*            <->  <i>italic</i>
    <u>underline</u>    <->  <u>underline</u>   (Markdown has no underline;
                                                 the raw tag is preserved)
    [text](url)         <->  <a href="url">text</a>
    - item / 1. item    <->  <ul>/<ol> with <li>
    paragraphs / breaks <->  <br> separated lines

The conversion is dependency-light: Markdown rendering uses the already-present
``markdown`` package when available (falling back to a tiny inline renderer for
the supported subset), and HTML parsing uses ``bs4`` when available (falling
back to a regex/``HTMLParser`` path). Neither optional import failing ever
raises -- the functions degrade to returning the input unchanged so a sync is
never broken by a formatting edge case.
"""

from __future__ import annotations

import re

#: Inline HTML tags Google Calendar renders that map onto Markdown emphasis.
#: ``u`` has no Markdown equivalent, so it is preserved as a raw tag on the way
#: back to Markdown (and passed through untouched on the way out).
_INLINE_TAGS = {"b", "strong", "i", "em", "u", "a"}

#: Block tags Google Calendar renders.
_BLOCK_TAGS = {"ul", "ol", "li", "p", "br", "div"}


# ---------------------------------------------------------------------------
# Markdown -> HTML (outbound / push)
# ---------------------------------------------------------------------------
def markdown_to_calendar_html(text: str) -> str:
    """Render a Markdown body to the HTML subset Google Calendar renders.

    Args:
        text: The local Markdown body (may be empty).

    Returns:
        HTML using only ``<b> <i> <u> <a> <ul> <ol> <li> <br>`` (and nested
        combinations). An empty/whitespace input returns ``""``. Any rendering
        error degrades to returning the input unchanged (never raises), so a
        push is never blocked by a formatting edge case.
    """
    if not text or not text.strip():
        return ""
    try:
        html = _render_markdown(text)
        return _tidy_calendar_html(html)
    except Exception:  # pragma: no cover - defensive; never break a push
        return text


def _render_markdown(text: str) -> str:
    """Render Markdown to HTML, preferring the ``markdown`` package."""
    try:
        import markdown as _md

        # ``nl2br`` turns single newlines into ``<br>`` (matching how a user
        # expects calendar line breaks); ``sane_lists`` keeps ordered/unordered
        # lists from bleeding together.
        return str(_md.markdown(text, extensions=["nl2br", "sane_lists"]))
    except Exception:
        return _render_markdown_fallback(text)


def _render_markdown_fallback(text: str) -> str:
    """Tiny Markdown renderer for the supported subset (no dependency).

    Handles ``**bold**``, ``*italic*``/``_italic_``, ``[text](url)`` links, and
    ``-``/``*``/``1.`` lists. Everything else is passed through with lines
    joined by ``<br>``. This exists only so the conversion still works when the
    ``markdown`` package is unavailable; the packaged renderer is preferred.
    """
    lines = text.splitlines()
    out: list[str] = []
    list_stack: list[str] = []  # "ul" / "ol" currently open

    def close_lists() -> None:
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    for raw in lines:
        line = raw.rstrip()
        ol = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        ul = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if ol:
            if not list_stack or list_stack[-1] != "ol":
                close_lists()
                list_stack.append("ol")
                out.append("<ol>")
            out.append(f"<li>{_render_inline(ol.group(1))}</li>")
        elif ul:
            if not list_stack or list_stack[-1] != "ul":
                close_lists()
                list_stack.append("ul")
                out.append("<ul>")
            out.append(f"<li>{_render_inline(ul.group(1))}</li>")
        else:
            close_lists()
            if line.strip():
                out.append(_render_inline(line))
            else:
                out.append("")
    close_lists()
    # Join non-list top-level lines with <br>; list markup stays as-is.
    return "\n".join(out)


def _render_inline(text: str) -> str:
    """Render inline Markdown emphasis/links to HTML (fallback path)."""
    # Links first so their text can still be emphasized.
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"_([^_]+)_", r"<i>\1</i>", text)
    return text


def _tidy_calendar_html(html: str) -> str:
    """Normalize rendered HTML to the compact form Google Calendar expects.

    * Unwrap ``<p>`` paragraphs into ``<br>``-separated lines (Calendar shows
      each paragraph on its own line but keeps no ``<p>`` wrappers of its own).
    * Normalize ``<strong>``/``<em>`` to the ``<b>``/``<i>`` Calendar emits so a
      pull round-trips to the same Markdown.
    * Collapse redundant whitespace between block tags.
    """
    html = html.strip()
    # Normalize emphasis tags to the b/i Calendar uses.
    html = re.sub(r"(?i)<(/?)strong>", r"<\1b>", html)
    html = re.sub(r"(?i)<(/?)em>", r"<\1i>", html)
    # Convert paragraph boundaries to <br>. An empty line between paragraphs
    # becomes a double <br> (a blank visual line), matching calendar rendering.
    paragraphs = re.split(r"(?i)</p>\s*<p>", html)
    paragraphs = [re.sub(r"(?i)</?p>", "", p).strip() for p in paragraphs]
    paragraphs = [p for p in paragraphs if p != ""]
    joined = "<br><br>".join(paragraphs) if paragraphs else ""
    # Remove whitespace between adjacent block tags so lists are compact
    # (``<ul>\n<li>`` -> ``<ul><li>``), matching Google's stored shape.
    joined = re.sub(r">\s+<", "><", joined)
    return joined.strip()


# ---------------------------------------------------------------------------
# HTML -> Markdown (inbound / pull + merge)
# ---------------------------------------------------------------------------
def calendar_html_to_markdown(text: str) -> str:
    """Convert Google Calendar description HTML into a Markdown body.

    The inverse of :func:`markdown_to_calendar_html` for the supported subset.
    Plain text with no HTML tags is returned unchanged (so a body the user
    never formatted is untouched). Any parse error degrades to returning the
    input unchanged (never raises), so a pull is never blocked.

    Args:
        text: The remote description HTML (may be empty).

    Returns:
        A Markdown body. Underline (no Markdown equivalent) is preserved as a
        raw ``<u>...</u>`` tag so a subsequent push round-trips it.
    """
    if not text or not text.strip():
        return ""
    # Normalize whitespace that renderers emit around a ``<br>`` (e.g. the
    # ``markdown`` package's ``nl2br`` writes ``<br />\n``): collapse the tag
    # plus any adjacent source newline into a single ``<br>`` so a soft line
    # break maps back to exactly one newline (keeping the round-trip a fixed
    # point). Google's own stored HTML has no such source newlines, so this is
    # a no-op there.
    text = re.sub(r"(?i)\s*<br\s*/?>\s*", "<br>", text)
    # Fast path: nothing that looks like a tag -> already plain/Markdown.
    if "<" not in text:
        return text.strip()
    try:
        return _html_to_markdown(text)
    except Exception:  # pragma: no cover - defensive; never break a pull
        return text


def _html_to_markdown(text: str) -> str:
    """Convert HTML to Markdown, preferring ``bs4`` for robust parsing."""
    try:
        from bs4 import BeautifulSoup, NavigableString, Tag  # type: ignore[attr-defined]
    except Exception:
        return _html_to_markdown_fallback(text)

    soup = BeautifulSoup(text, "html.parser")

    def render(node: object) -> str:
        if isinstance(node, NavigableString):
            return str(node)
        if not isinstance(node, Tag):
            return ""
        name = (node.name or "").lower()
        inner = "".join(render(c) for c in node.children)
        if name in ("b", "strong"):
            return f"**{inner.strip()}**" if inner.strip() else ""
        if name in ("i", "em"):
            return f"*{inner.strip()}*" if inner.strip() else ""
        if name == "u":
            return f"<u>{inner.strip()}</u>" if inner.strip() else ""
        if name == "a":
            href = str(node.get("href", "") or "")
            label = inner.strip() or href
            return f"[{label}]({href})" if href else label
        if name == "br":
            return "\n"
        if name == "li":
            return inner.strip()
        if name == "ul":
            items = [render(c) for c in node.children if _is_tag(c, "li")]
            return "\n".join(f"- {it.strip()}" for it in items if it.strip())
        if name == "ol":
            items = [render(c) for c in node.children if _is_tag(c, "li")]
            return "\n".join(f"{i}. {it.strip()}" for i, it in enumerate(items, 1) if it.strip())
        if name in ("p", "div"):
            return inner.strip()
        # Unknown tag: keep its text content.
        return inner

    # Render top-level nodes, separating block-level pieces with blank lines so
    # paragraphs and lists stay distinct, matching the Markdown a user writes.
    parts: list[str] = []
    for child in soup.children:
        piece = render(child)
        if piece is None:
            continue
        if isinstance(child, Tag) and (child.name or "").lower() in ("ul", "ol", "p", "div"):
            # Surround a block with blank lines so adjacent inline text (e.g. a
            # trailing link right after ``</ul>``) is separated by a blank line,
            # matching the Markdown a user writes and keeping the round-trip a
            # fixed point. Redundant blank lines collapse below.
            parts.append("\n\n" + piece.strip("\n") + "\n\n")
        else:
            parts.append(piece)
    joined = "".join(parts)
    return _collapse_blank_lines(joined).strip()


def _is_tag(node: object, name: str) -> bool:
    """Whether ``node`` is a bs4 Tag with the given (case-insensitive) name."""
    try:
        from bs4 import Tag
    except Exception:  # pragma: no cover
        return False
    return isinstance(node, Tag) and (node.name or "").lower() == name


def _html_to_markdown_fallback(text: str) -> str:
    """Regex HTML->Markdown for the supported subset (no bs4 dependency)."""
    s = text
    # Lists: convert items, then wrap list containers with newlines.
    s = re.sub(r"(?is)<ol[^>]*>(.*?)</ol>", _convert_ordered, s)
    s = re.sub(r"(?is)<ul[^>]*>(.*?)</ul>", _convert_unordered, s)
    # Inline emphasis.
    s = re.sub(r"(?is)<(?:b|strong)>(.*?)</(?:b|strong)>", r"**\1**", s)
    s = re.sub(r"(?is)<(?:i|em)>(.*?)</(?:i|em)>", r"*\1*", s)
    # Links.
    s = re.sub(r'(?is)<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", s)
    # Line breaks and paragraphs.
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p>\s*<p>", "\n\n", s)
    s = re.sub(r"(?i)</?p[^>]*>", "", s)
    s = re.sub(r"(?i)</?div[^>]*>", "\n", s)
    # Drop any remaining tags except the preserved <u>.
    s = re.sub(r"(?is)<(?!/?u\b)[^>]+>", "", s)
    return _collapse_blank_lines(s).strip()


def _convert_ordered(match: re.Match[str]) -> str:
    items = re.findall(r"(?is)<li[^>]*>(.*?)</li>", match.group(1))
    body = "\n".join(f"{i}. {it.strip()}" for i, it in enumerate(items, 1))
    return f"\n{body}\n"


def _convert_unordered(match: re.Match[str]) -> str:
    items = re.findall(r"(?is)<li[^>]*>(.*?)</li>", match.group(1))
    body = "\n".join(f"- {it.strip()}" for it in items)
    return f"\n{body}\n"


def _collapse_blank_lines(text: str) -> str:
    """Collapse 3+ consecutive newlines into a single blank line."""
    return re.sub(r"\n{3,}", "\n\n", text)
