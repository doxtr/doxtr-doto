"""Tests for Markdown <-> Calendar-HTML body conversion and its Google wiring.

doto stores a task ``body`` as Markdown; Google Calendar renders a small HTML
subset. These tests pin the two conversion directions and -- crucially -- that
the full push/pull round-trip (including the ``[doto:...]`` back-reference) is a
*fixed point*, so the inbound/baseline content hashes compare equal and a sync
never reports a spurious conflict.
"""

from __future__ import annotations

from doxtr_doto.calsync.model import (
    BACK_REFERENCE_CLOSE,
    BACK_REFERENCE_OPEN,
    CalendarEvent,
    EventKind,
    make_uid,
)
from doxtr_doto.calsync.providers.google import GoogleCalendarProvider
from doxtr_doto.calsync.richtext import (
    calendar_html_to_markdown,
    markdown_to_calendar_html,
)
from doxtr_doto.cli.config import CalendarConfig


class TestMarkdownToHtml:
    def test_empty_is_empty(self):
        assert markdown_to_calendar_html("") == ""
        assert markdown_to_calendar_html("   \n  ") == ""

    def test_bold_italic(self):
        assert markdown_to_calendar_html("**bold**") == "<b>bold</b>"
        assert markdown_to_calendar_html("*italic*") == "<i>italic</i>"

    def test_link(self):
        out = markdown_to_calendar_html("[text](https://x.y)")
        assert out == '<a href="https://x.y">text</a>'

    def test_unordered_list(self):
        assert markdown_to_calendar_html("- a\n- b") == "<ul><li>a</li><li>b</li></ul>"

    def test_ordered_list(self):
        assert markdown_to_calendar_html("1. one\n2. two") == "<ol><li>one</li><li>two</li></ol>"

    def test_underline_passthrough(self):
        # Markdown has no underline; a raw <u> tag is preserved both ways.
        assert "<u>x</u>" in markdown_to_calendar_html("<u>x</u>")

    def test_plain_text_unchanged(self):
        assert markdown_to_calendar_html("just text") == "just text"


class TestHtmlToMarkdown:
    def test_empty_is_empty(self):
        assert calendar_html_to_markdown("") == ""

    def test_plain_text_fast_path(self):
        assert calendar_html_to_markdown("no tags here") == "no tags here"

    def test_bold_italic(self):
        assert calendar_html_to_markdown("<b>bold</b>") == "**bold**"
        assert calendar_html_to_markdown("<strong>bold</strong>") == "**bold**"
        assert calendar_html_to_markdown("<i>it</i>") == "*it*"
        assert calendar_html_to_markdown("<em>it</em>") == "*it*"

    def test_link(self):
        assert calendar_html_to_markdown('<a href="https://x.y">t</a>') == "[t](https://x.y)"

    def test_lists(self):
        assert calendar_html_to_markdown("<ul><li>a</li><li>b</li></ul>") == "- a\n- b"
        assert calendar_html_to_markdown("<ol><li>a</li><li>b</li></ol>") == "1. a\n2. b"

    def test_underline_preserved(self):
        assert calendar_html_to_markdown("<u>x</u>") == "<u>x</u>"

    def test_br_maps_to_newline(self):
        assert calendar_html_to_markdown("a<br>b") == "a\nb"


class TestRoundTrip:
    """Markdown -> HTML -> Markdown must be a fixed point for supported markup."""

    SAMPLES = [
        "Just plain text, nothing fancy.",
        "**bold only**",
        "*italic only*",
        "- a\n- b\n- c",
        "1. one\n2. two",
        "line1\nline2",
        "para1\n\npara2",
        (
            "I am **bold** and <u>underlined</u> and *italic* my friend!\n\n"
            "1. one\n2. two\n\nAnd then\n\n- another\n- one\n\n"
            "[Great Project](https://github.com/Greenheart/pagecrypt), go see it!"
        ),
    ]

    def test_markdown_html_markdown_is_fixed_point(self):
        for md in self.SAMPLES:
            html = markdown_to_calendar_html(md)
            assert calendar_html_to_markdown(html) == md, md


def _event_with_body(body_md: str) -> CalendarEvent:
    """A timed event whose description mirrors project_task_to_event output."""
    parts: list[str] = []
    if body_md:
        parts.append(body_md)
    parts.append(f"{BACK_REFERENCE_OPEN}noter#DOTO-034{BACK_REFERENCE_CLOSE}")
    return CalendarEvent(
        uid=make_uid("DOTO-034"),
        kind=EventKind.EVENT,
        summary="My Meeting",
        description="\n\n".join(parts),
    )


class TestGoogleBodyRoundTrip:
    """The Google provider converts outbound Markdown -> HTML and inbound back.

    The push description (Markdown + back-reference) must read back as the
    identical string after HTML conversion so ``inbound_hash_of_pushed`` and
    ``remote_content_hash`` match (no spurious conflict).
    """

    BODIES = [
        "",
        "Just plain text",
        "**bold** and *italic* and <u>under</u>",
        "- a\n- b",
        (
            "I am **bold** and <u>underlined</u> and *italic* my friend!\n\n"
            "1. one\n2. two\n\nAnd then\n\n- another\n- one\n\n"
            "[Great Project](https://github.com/Greenheart/pagecrypt), go see it!"
        ),
    ]

    def test_push_html_is_calendar_subset(self):
        prov = GoogleCalendarProvider(CalendarConfig(provider="google"))
        body = prov._body(_event_with_body("**bold**\n\n- a\n- b"))
        html = body["description"]
        assert "<b>bold</b>" in html
        assert "<ul><li>a</li><li>b</li></ul>" in html
        # Back-reference marker preserved on its own line.
        assert "[doto:noter#DOTO-034]" in html
        assert "**" not in html  # Markdown fully rendered, no literal markers.

    def test_description_round_trips_to_identical_string(self):
        prov = GoogleCalendarProvider(CalendarConfig(provider="google"))
        for body_md in self.BODIES:
            event = _event_with_body(body_md)
            pushed = event.description
            html = prov._body(event)["description"]
            # Simulate what Google returns: the stored HTML, mapped back inbound.
            item = {
                "iCalUID": event.uid,
                "id": "gid",
                "summary": event.summary,
                "description": html,
                "start": {"dateTime": "2026-11-04T15:00:00+00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-11-04T16:15:00+00:00", "timeZone": "UTC"},
            }
            remote = GoogleCalendarProvider._to_remote_event(item)
            assert remote.description == pushed, body_md
