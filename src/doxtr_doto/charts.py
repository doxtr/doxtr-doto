"""SVG chart generation for doto summaries.

This module provides functions for generating charts from task data, used in
doto summary views. Charts can be grouped by status, priority, assignee, or
tags.

Two chart engines are supported:

* ``svg`` (default): dependency-free inline SVG charts (``generate_summary_charts``).
* ``plotly``: richer charts rendered via `plotly <https://plotly.com/python/>`_,
  exported to static images with `kaleido <https://pypi.org/project/kaleido/>`_
  (``generate_summary_charts_plotly``). When plotly or kaleido are unavailable
  the plotly path degrades gracefully back to the inline SVG charts, so the
  build never crashes just because the optional ``charts`` extra is missing.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from doxtr_doto.constants import (
    PRIORITY_COLORS,
    PRIORITY_DISPLAY_ORDER,
    STATUS_COLORS,
    STATUS_DISPLAY_ORDER,
)

if TYPE_CHECKING:
    from datetime import date

    from doxtr_doto.collectors import DotoTask

# Valid chart types across both engines.
VALID_CHART_TYPES: frozenset[str] = frozenset({"bar", "pie", "stacked-bar", "progress", "burndown"})

# Default colors for unknown values. Single source for the chart palette used
# by the SVG, plotly and native-LaTeX engines so they stay visually in sync.
DEFAULT_COLORS = [
    "#0d6efd",
    "#198754",
    "#fd7e14",
    "#dc3545",
    "#6c757d",
    "#6610f2",
    "#d63384",
    "#20c997",
    "#ffc107",
    "#0dcaf0",
]

# Recurring chart brand/axis colors, centralized so SVG and native-LaTeX share
# one palette instead of scattering hex literals across the builders.
CHART_AXIS_COLOR = "#ccc"
CHART_ACCENT_COLOR = "#0d6efd"  # burndown line / bar accent
CHART_PROGRESS_TRACK_COLOR = "#e9ecef"
CHART_PROGRESS_FILL_COLOR = "#198754"


def _color_for(label: str, index: int, color_map: dict[str, str] | None) -> str:
    """Resolve a color for a chart category label.

    Prefers the semantic ``color_map`` (status/priority palette from
    ``constants.py``), falling back to the rotating :data:`DEFAULT_COLORS`.
    """
    if color_map:
        color = color_map.get(str(label).lower())
        if color:
            return color
    return DEFAULT_COLORS[index % len(DEFAULT_COLORS)]


def _get_task_attr(task: Any, attr: str, default: Any = None) -> Any:
    """Get attribute from task, supporting both objects and dicts.

    Args:
        task: DotoTask object or dict.
        attr: Attribute name to get.
        default: Default value if attribute not found.

    Returns:
        Attribute value or default.
    """
    if isinstance(task, dict):
        return task.get(attr, default)
    return getattr(task, attr, default)


def _escape_xml(text: str) -> str:
    """Escape text for safe inclusion in XML/SVG."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def generate_bar_chart(
    data: dict[str, int],
    title: str = "",
    width: int = 400,
    height: int = 250,
    color_map: dict[str, str] | None = None,
) -> str:
    """Generate an SVG bar chart from data.

    Args:
        data: Dictionary mapping labels to values.
        title: Optional chart title.
        width: Chart width in pixels.
        height: Chart height in pixels.
        color_map: Optional mapping of labels to colors.

    Returns:
        SVG string for the bar chart.
    """
    if not data:
        return ""

    color_map = color_map or {}

    # Chart dimensions
    margin_top = 40 if title else 20
    margin_bottom = 60
    margin_left = 50
    margin_right = 20
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom

    # Calculate bar dimensions
    num_bars = len(data)
    bar_gap = 10
    bar_width = max(20, (chart_width - (num_bars - 1) * bar_gap) / num_bars)

    # Find max value for scaling
    max_value = max(data.values()) if data.values() else 1

    # Start building SVG
    svg_parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'class="doto-chart doto-bar-chart" '
            f'viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}">'
        )
    ]

    # Add title
    if title:
        svg_parts.append(
            f'<text x="{width / 2}" y="20" '
            f'text-anchor="middle" class="doto-chart-title" '
            f'font-size="14" font-weight="bold">'
            f"{_escape_xml(title)}</text>"
        )

    # Draw bars
    for i, (label, value) in enumerate(data.items()):
        x = margin_left + i * (bar_width + bar_gap)
        bar_height = (value / max_value) * chart_height if max_value > 0 else 0
        y = margin_top + chart_height - bar_height

        # Get color
        color = _color_for(label, i, color_map)

        # Bar
        svg_parts.append(
            f'<rect x="{x}" y="{y}" width="{bar_width}" height="{bar_height}" '
            f'fill="{color}" class="doto-chart-bar" rx="2" />'
        )

        # Value label on top of bar
        svg_parts.append(
            f'<text x="{x + bar_width / 2}" y="{y - 5}" '
            f'text-anchor="middle" class="doto-chart-value" '
            f'font-size="12">{value}</text>'
        )

        # X-axis label (rotated for long labels)
        label_y = margin_top + chart_height + 15
        svg_parts.append(
            f'<text x="{x + bar_width / 2}" y="{label_y}" '
            f'text-anchor="middle" class="doto-chart-label" '
            f'font-size="11">{_escape_xml(label)}</text>'
        )

    # Y-axis line
    svg_parts.append(
        f'<line x1="{margin_left}" y1="{margin_top}" '
        f'x2="{margin_left}" y2="{margin_top + chart_height}" '
        f'stroke="{CHART_AXIS_COLOR}" stroke-width="1" />'
    )

    # X-axis line
    svg_parts.append(
        f'<line x1="{margin_left}" y1="{margin_top + chart_height}" '
        f'x2="{margin_left + chart_width}" y2="{margin_top + chart_height}" '
        f'stroke="{CHART_AXIS_COLOR}" stroke-width="1" />'
    )

    svg_parts.append("</svg>")

    return "\n".join(svg_parts)


def generate_status_chart(tasks: list[DotoTask], title: str = "Tasks by Status") -> str:
    """Generate a bar chart showing task distribution by status.

    Args:
        tasks: List of DotoTask objects or dicts.
        title: Chart title.

    Returns:
        SVG string for the status chart.
    """
    if not tasks:
        return ""

    # Count tasks by status
    status_counts: dict[str, int] = {}
    for task in tasks:
        status = (_get_task_attr(task, "status") or "open").lower()
        status_counts[status] = status_counts.get(status, 0) + 1

    # Order statuses consistently
    ordered_data: dict[str, int] = {}
    for status in STATUS_DISPLAY_ORDER:
        if status in status_counts:
            ordered_data[status] = status_counts[status]

    # Add any unexpected statuses
    for status, count in status_counts.items():
        if status not in ordered_data:
            ordered_data[status] = count

    return generate_bar_chart(ordered_data, title, color_map=STATUS_COLORS)


def generate_priority_chart(tasks: list[DotoTask], title: str = "Tasks by Priority") -> str:
    """Generate a bar chart showing task distribution by priority.

    Args:
        tasks: List of DotoTask objects or dicts.
        title: Chart title.

    Returns:
        SVG string for the priority chart.
    """
    if not tasks:
        return ""

    # Count tasks by priority
    priority_counts: dict[str, int] = {}
    for task in tasks:
        priority = (_get_task_attr(task, "priority") or "medium").lower()
        priority_counts[priority] = priority_counts.get(priority, 0) + 1

    # Order priorities consistently
    ordered_data: dict[str, int] = {}
    for priority in PRIORITY_DISPLAY_ORDER:
        if priority in priority_counts:
            ordered_data[priority] = priority_counts[priority]

    # Add any unexpected priorities
    for priority, count in priority_counts.items():
        if priority not in ordered_data:
            ordered_data[priority] = count

    return generate_bar_chart(ordered_data, title, color_map=PRIORITY_COLORS)


def generate_assignee_chart(tasks: list[DotoTask], title: str = "Tasks by Assignee") -> str:
    """Generate a bar chart showing task distribution by assignee.

    Args:
        tasks: List of DotoTask objects or dicts.
        title: Chart title.

    Returns:
        SVG string for the assignee chart.
    """
    if not tasks:
        return ""

    # Count tasks by assignee
    assignee_counts: dict[str, int] = {}
    for task in tasks:
        assignee = _get_task_attr(task, "assignee") or "Unassigned"
        assignee_counts[assignee] = assignee_counts.get(assignee, 0) + 1

    # Sort by count descending
    sorted_data = dict(sorted(assignee_counts.items(), key=lambda x: -x[1]))

    return generate_bar_chart(sorted_data, title)


def generate_tags_chart(tasks: list[DotoTask], title: str = "Tasks by Tag") -> str:
    """Generate a bar chart showing task distribution by tags.

    Args:
        tasks: List of DotoTask objects or dicts.
        title: Chart title.

    Returns:
        SVG string for the tags chart.
    """
    if not tasks:
        return ""

    # Count tasks by tag
    tag_counts: dict[str, int] = {}
    for task in tasks:
        tags = _get_task_attr(task, "tags") or []
        if tags:
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        else:
            tag_counts["(no tags)"] = tag_counts.get("(no tags)", 0) + 1

    # Sort by count descending
    sorted_data = dict(sorted(tag_counts.items(), key=lambda x: -x[1]))

    return generate_bar_chart(sorted_data, title)


def generate_pie_chart(
    data: dict[str, int],
    title: str = "",
    width: int = 300,
    height: int = 300,
    color_map: dict[str, str] | None = None,
) -> str:
    """Generate an SVG pie chart from data.

    Uses basic SVG arc math to render wedges. Does not depend on
    any charting library.

    Args:
        data: Dictionary mapping labels to counts.
        title: Optional chart title.
        width: SVG width in pixels.
        height: SVG height in pixels.
        color_map: Optional mapping of labels to hex colors.

    Returns:
        SVG string.
    """
    import math

    if not data:
        return ""

    color_map = color_map or {}
    total = sum(data.values())
    if total == 0:
        return ""

    # Adjust center if title is present
    title_offset = 20 if title else 0
    cx = width / 2
    cy = (height / 2) + (title_offset / 2)
    r = min(width, height) / 2 - 40  # Leave room for legend

    svg_parts: list[str] = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'class="doto-chart doto-pie-chart" '
            f'viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        )
    ]

    if title:
        svg_parts.append(
            f'<text x="{width / 2}" y="16" text-anchor="middle" '
            f'class="doto-chart-title" font-size="14" font-weight="bold">'
            f"{_escape_xml(title)}</text>"
        )

    start_angle = -math.pi / 2  # Start at 12 o'clock
    legend_y = height - len(data) * 18 - 4

    for i, (label, value) in enumerate(data.items()):
        if value == 0:
            continue

        fraction = value / total
        end_angle = start_angle + fraction * 2 * math.pi
        large_arc = 1 if fraction > 0.5 else 0

        x1 = cx + r * math.cos(start_angle)
        y1 = cy + r * math.sin(start_angle)
        x2 = cx + r * math.cos(end_angle)
        y2 = cy + r * math.sin(end_angle)

        color = _color_for(label, i, color_map)

        # Handle full circle case (single item = 100%)
        if fraction >= 0.9999:
            # Draw a full circle instead of an arc
            svg_parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" class="doto-chart-slice" />'
            )
        else:
            svg_parts.append(
                f'<path d="M {cx} {cy} L {x1:.2f} {y1:.2f} '
                f'A {r} {r} 0 {large_arc} 1 {x2:.2f} {y2:.2f} Z" '
                f'fill="{color}" class="doto-chart-slice" />'
            )

        # Legend entry
        lx, ly = 10, legend_y + i * 18
        svg_parts.append(f'<rect x="{lx}" y="{ly - 10}" width="12" height="12" fill="{color}" />')
        pct = round(fraction * 100)
        svg_parts.append(
            f'<text x="{lx + 16}" y="{ly}" font-size="11" class="doto-chart-label">'
            f"{_escape_xml(label)} ({value}, {pct}%)</text>"
        )

        start_angle = end_angle

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _parse_date_attr(value: object) -> date | None:
    """Parse a date from a task attribute (string, date, datetime, or None)."""
    from datetime import date, datetime

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _burndown_daily_counts(
    tasks: list[DotoTask],
) -> tuple[date, list[int]] | None:
    """Compute the shared burndown series (start date + daily remaining counts).

    Walks each task's created date (backlog entry) and its updated date when the
    status is ``done`` (burn-down point), then counts open tasks per day from the
    earliest date through today. Returns ``(start_date, day_counts)`` or ``None``
    when there is insufficient date data (fewer than 2 days), matching the prior
    behavior of both the SVG and plotly burndown paths.

    Both :func:`generate_burndown_chart` (SVG) and :func:`_burndown_series`
    (plotly) call this so the two engines never disagree on burndown semantics.
    """
    from datetime import date, timedelta

    dated = []
    for task in tasks:
        created = _get_task_attr(task, "created")
        status = _get_task_attr(task, "status", "open") or "open"
        updated = _get_task_attr(task, "updated")

        created_date = _parse_date_attr(created)
        if created_date is None:
            continue

        done_date = None
        if status.lower() == "done" and updated:
            done_date = _parse_date_attr(updated)

        dated.append((created_date, done_date))

    if not dated:
        return None

    all_dates = [d for d, _ in dated] + [d for _, d in dated if d]
    start = min(all_dates)
    end = max(all_dates + [date.today()])
    num_days = (end - start).days + 1
    if num_days < 2:
        return None

    day_counts: list[int] = []
    for offset in range(num_days):
        day = start + timedelta(days=offset)
        remaining = sum(
            1 for created, done in dated if created <= day and (done is None or done > day)
        )
        day_counts.append(remaining)
    return start, day_counts


def generate_burndown_chart(
    tasks: list[DotoTask],
    title: str = "Burndown",
    width: int = 500,
    height: int = 280,
) -> str:
    """Generate an SVG burndown chart.

    Plots the count of open (non-done) tasks over time, using each
    task's created date as the point it entered the backlog and its
    updated date (when status became done) as the point it burned down.

    Args:
        tasks: List of DotoTask objects or dicts.
        title: Chart title.
        width: SVG width in pixels.
        height: SVG height in pixels.

    Returns:
        SVG string, or empty string if insufficient date data.
    """
    from datetime import timedelta

    series = _burndown_daily_counts(tasks)
    if series is None:
        return ""
    start, day_counts = series
    num_days = len(day_counts)

    # Render line chart
    margin_top, margin_bottom, margin_left, margin_right = 30, 40, 50, 20
    cw = width - margin_left - margin_right
    ch = height - margin_top - margin_bottom
    max_count = max(day_counts) or 1

    def px(offset: int, count: int) -> tuple[float, float]:
        x = margin_left + offset / (num_days - 1) * cw
        y = margin_top + (1 - count / max_count) * ch
        return x, y

    svg_parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'class="doto-chart doto-burndown-chart" '
            f'viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        )
    ]

    if title:
        svg_parts.append(
            f'<text x="{width / 2}" y="16" text-anchor="middle" '
            f'class="doto-chart-title" font-size="14" font-weight="bold">'
            f"{_escape_xml(title)}</text>"
        )

    # Axes
    svg_parts.append(
        f'<line x1="{margin_left}" y1="{margin_top}" '
        f'x2="{margin_left}" y2="{margin_top + ch}" stroke="{CHART_AXIS_COLOR}" stroke-width="1"/>'
    )
    svg_parts.append(
        f'<line x1="{margin_left}" y1="{margin_top + ch}" '
        f'x2="{margin_left + cw}" y2="{margin_top + ch}" stroke="{CHART_AXIS_COLOR}" stroke-width="1"/>'
    )

    # Line path
    points = [px(i, c) for i, c in enumerate(day_counts)]
    d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in points)
    svg_parts.append(
        f'<path d="{d}" fill="none" stroke="{CHART_ACCENT_COLOR}" stroke-width="2" class="doto-burndown-line"/>'
    )

    # X-axis labels (start, mid, end)
    label_offsets = [0, num_days // 2, num_days - 1]
    for offset in label_offsets:
        x, _ = px(offset, 0)
        label = (start + timedelta(days=offset)).isoformat()
        svg_parts.append(
            f'<text x="{x:.1f}" y="{margin_top + ch + 15}" '
            f'text-anchor="middle" font-size="10" class="doto-chart-label">{label}</text>'
        )

    # Y-axis labels (0, max)
    svg_parts.append(
        f'<text x="{margin_left - 5}" y="{margin_top + ch}" '
        f'text-anchor="end" font-size="10" class="doto-chart-label">0</text>'
    )
    svg_parts.append(
        f'<text x="{margin_left - 5}" y="{margin_top + 4}" '
        f'text-anchor="end" font-size="10" class="doto-chart-label">{max_count}</text>'
    )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _count_by(
    tasks: list[DotoTask],
    field: str,
    display_order: list[str] | None = None,
) -> dict[str, int]:
    """Count tasks by a field value.

    Args:
        tasks: List of DotoTask objects or dicts.
        field: Field name to count by.
        display_order: Optional list to order results.

    Returns:
        Dictionary mapping field values to counts.
    """
    counts: dict[str, int] = {}
    for task in tasks:
        value = (_get_task_attr(task, field) or "unknown").lower()
        counts[value] = counts.get(value, 0) + 1

    if display_order:
        ordered: dict[str, int] = {}
        for key in display_order:
            if key in counts:
                ordered[key] = counts[key]
        # Add any unexpected values
        for key, count in counts.items():
            if key not in ordered:
                ordered[key] = count
        return ordered

    return counts


def generate_progress_chart(
    tasks: list[DotoTask],
    title: str = "Completion",
    width: int = 320,
    height: int = 180,
) -> str:
    """Generate an SVG horizontal progress bar of overall completion.

    Completion is the percentage of tasks whose status is ``done``.

    Args:
        tasks: List of DotoTask objects or dicts.
        title: Chart title.
        width: SVG width in pixels.
        height: SVG height in pixels.

    Returns:
        SVG string, or empty string when there are no tasks.
    """
    if not tasks:
        return ""

    total = len(tasks)
    done = sum(1 for t in tasks if (_get_task_attr(t, "status") or "").lower() == "done")
    pct = round(done / total * 100) if total else 0

    margin = 20
    bar_x = margin
    bar_y = height / 2
    bar_w = width - 2 * margin
    bar_h = 26
    fill_w = bar_w * pct / 100

    svg_parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'class="doto-chart doto-progress-chart" '
            f'viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        )
    ]
    if title:
        svg_parts.append(
            f'<text x="{width / 2}" y="22" text-anchor="middle" '
            f'class="doto-chart-title" font-size="14" font-weight="bold">'
            f"{_escape_xml(title)}</text>"
        )
    # Track
    svg_parts.append(
        f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" '
        f'rx="6" fill="{CHART_PROGRESS_TRACK_COLOR}" class="doto-progress-track" />'
    )
    # Fill
    svg_parts.append(
        f'<rect x="{bar_x}" y="{bar_y}" width="{fill_w:.1f}" height="{bar_h}" '
        f'rx="6" fill="{CHART_PROGRESS_FILL_COLOR}" class="doto-progress-fill" />'
    )
    # Percentage label
    svg_parts.append(
        f'<text x="{width / 2}" y="{bar_y + bar_h + 22}" text-anchor="middle" '
        f'font-size="13" class="doto-chart-label">{pct}% complete '
        f"({done}/{total})</text>"
    )
    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _svg_chart_bar(tasks: list[DotoTask], group_by: list[str]) -> list[str]:
    """Render bar charts (one per group-by field) as SVG snippets."""
    charts: list[str] = []
    for field in group_by:
        field_lower = field.lower()
        if field_lower == "status":
            charts.append(generate_status_chart(tasks))
        elif field_lower == "priority":
            charts.append(generate_priority_chart(tasks))
        elif field_lower == "assignee":
            charts.append(generate_assignee_chart(tasks))
        elif field_lower == "tags":
            charts.append(generate_tags_chart(tasks))
    if not charts:
        charts.append(generate_status_chart(tasks))
    return charts


def _svg_chart_pie(tasks: list[DotoTask], group_by: list[str]) -> list[str]:
    """Render pie charts (one per group-by field) as SVG snippets."""
    charts: list[str] = []
    titles = {
        "status": ("Tasks by Status", STATUS_COLORS),
        "priority": ("Tasks by Priority", PRIORITY_COLORS),
        "assignee": ("Tasks by Assignee", None),
    }
    for field in group_by:
        field_lower = field.lower()
        if field_lower == "tags":
            charts.append(
                generate_pie_chart(
                    _chart_data_for_field(tasks, "tags"),
                    title="Tasks by Tag",
                )
            )
        elif field_lower in titles:
            title, cmap = titles[field_lower]
            charts.append(
                generate_pie_chart(
                    _chart_data_for_field(tasks, field_lower),
                    title=title,
                    color_map=cmap,
                )
            )
    if not charts:
        charts.append(
            generate_pie_chart(
                _chart_data_for_field(tasks, "status"),
                title="Tasks by Status",
                color_map=STATUS_COLORS,
            )
        )
    return charts


def _svg_chart_burndown(tasks: list[DotoTask], group_by: list[str]) -> list[str]:
    """Render a burndown chart, falling back to a status bar chart on no dates."""
    chart = generate_burndown_chart(tasks)
    if chart:
        return [chart]
    return [generate_status_chart(tasks)]


def _svg_chart_progress(tasks: list[DotoTask], group_by: list[str]) -> list[str]:
    """Render an overall completion/progress chart."""
    return [generate_progress_chart(tasks)]


# Registry mapping a chart type to its SVG renderer. Adding a new SVG chart type
# is one entry here plus one render function; ``stacked-bar`` reuses the bar
# renderer (the dependency-free SVG engine draws it as grouped bars).
SVG_CHART_RENDERERS: dict[str, Any] = {
    "bar": _svg_chart_bar,
    "stacked-bar": _svg_chart_bar,
    "pie": _svg_chart_pie,
    "burndown": _svg_chart_burndown,
    "progress": _svg_chart_progress,
}


def generate_summary_charts(
    tasks: list[DotoTask],
    group_by: list[str],
    chart_type: str = "bar",
) -> str:
    """Generate SVG charts based on group_by configuration and chart type.

    This is the built-in, dependency-free ``svg`` engine.

    Args:
        tasks: List of DotoTask objects or dicts.
        group_by: List of fields to group by (status, priority, assignee, tags).
        chart_type: Type of chart to generate. One of ``bar``, ``pie``,
            ``stacked-bar``, ``progress``, or ``burndown``. Unknown/unsupported
            types degrade to a bar chart.

    Returns:
        Combined SVG charts as an HTML string.
    """
    if not tasks:
        return ""

    renderer = SVG_CHART_RENDERERS.get(chart_type, _svg_chart_bar)
    charts = renderer(tasks, group_by)
    return '<div class="doto-charts">' + "\n".join(charts) + "</div>"


# --- plotly engine (Feature 7) -------------------------------------------


def plotly_available() -> bool:
    """Return True when ``plotly`` can be imported.

    Isolated in a helper so tests can monkeypatch it and so the plotly code
    paths degrade gracefully when the optional ``charts`` extra is not
    installed.
    """
    try:
        import plotly  # noqa: F401
    except Exception:
        return False
    return True


def kaleido_available() -> bool:
    """Return True when static image export via ``kaleido`` is possible.

    plotly exports static images (PNG/SVG) through kaleido. Both packages must
    be importable for the static-image path to work; otherwise the caller
    should fall back to the built-in SVG charts.
    """
    if not plotly_available():
        return False
    try:
        import kaleido  # noqa: F401
    except Exception:
        return False
    return True


def _chart_data_for_field(tasks: list[DotoTask], field: str) -> dict[str, int]:
    """Return an ordered count mapping for a single group-by field.

    Mirrors the ordering the SVG charts use (status/priority display order,
    per-tag counting), so the plotly and SVG engines agree on categories.
    """
    field_lower = field.lower()
    if field_lower == "status":
        return _count_by(tasks, "status", STATUS_DISPLAY_ORDER)
    if field_lower == "priority":
        return _count_by(tasks, "priority", PRIORITY_DISPLAY_ORDER)
    if field_lower == "assignee":
        counts: dict[str, int] = {}
        for task in tasks:
            assignee = _get_task_attr(task, "assignee") or "Unassigned"
            counts[assignee] = counts.get(assignee, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))
    if field_lower == "tags":
        tag_counts: dict[str, int] = {}
        for task in tasks:
            tags = _get_task_attr(task, "tags") or []
            if tags:
                for tag in tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            else:
                tag_counts["(no tags)"] = tag_counts.get("(no tags)", 0) + 1
        return dict(sorted(tag_counts.items(), key=lambda x: -x[1]))
    return _count_by(tasks, field_lower)


def _color_map_for_field(field: str) -> dict[str, str] | None:
    """Return the semantic color map for a group-by field, if any."""
    field_lower = field.lower()
    if field_lower == "status":
        return STATUS_COLORS
    if field_lower == "priority":
        return PRIORITY_COLORS
    return None


def _plotly_progress(go: Any, tasks: list[DotoTask], group_by: list[str]) -> Any:
    """Build a plotly completion gauge figure."""
    total = len(tasks)
    done = sum(1 for t in tasks if (_get_task_attr(t, "status") or "").lower() == "done")
    pct = round(done / total * 100) if total else 0
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=pct,
            number={"suffix": "%"},
            title={"text": f"Completion ({done}/{total})"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": CHART_PROGRESS_FILL_COLOR},
            },
        )
    )
    fig.update_layout(width=420, height=300, margin={"l": 30, "r": 30, "t": 60, "b": 20})
    return fig


def _plotly_burndown(go: Any, tasks: list[DotoTask], group_by: list[str]) -> Any:
    """Build a plotly burndown line figure, or None with no dated tasks."""
    series = _burndown_series(tasks)
    if series is None:
        return None
    dates, counts = series
    fig = go.Figure(
        go.Scatter(
            x=dates,
            y=counts,
            mode="lines",
            line={"color": CHART_ACCENT_COLOR, "width": 2},
            name="Remaining",
        )
    )
    fig.update_layout(
        title="Burndown",
        xaxis_title="Date",
        yaxis_title="Open tasks",
        width=560,
        height=320,
        margin={"l": 50, "r": 20, "t": 50, "b": 50},
    )
    return fig


def _plotly_stacked_bar(go: Any, tasks: list[DotoTask], group_by: list[str]) -> Any:
    """Build a plotly stacked-bar composition figure."""
    primary_field = group_by[0] if group_by else "status"
    data = _chart_data_for_field(tasks, primary_field)
    color_map = _color_map_for_field(primary_field) or {}
    fig = go.Figure()
    for label, value in data.items():
        fig.add_bar(
            x=["Tasks"],
            y=[value],
            name=str(label),
            marker_color=color_map.get(str(label).lower()),
        )
    fig.update_layout(
        barmode="stack",
        title=f"Tasks by {primary_field.title()}",
        width=420,
        height=320,
        margin={"l": 50, "r": 20, "t": 50, "b": 40},
    )
    return fig


def _plotly_pie(go: Any, tasks: list[DotoTask], group_by: list[str]) -> Any:
    """Build a plotly pie figure."""
    primary_field = group_by[0] if group_by else "status"
    data = _chart_data_for_field(tasks, primary_field)
    color_map = _color_map_for_field(primary_field) or {}
    labels = [str(k) for k in data.keys()]
    values = list(data.values())
    colors = [color_map.get(lbl.lower()) for lbl in labels]
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            marker={"colors": colors} if any(colors) else None,
        )
    )
    fig.update_layout(
        title=f"Tasks by {primary_field.title()}",
        width=420,
        height=320,
        margin={"l": 20, "r": 20, "t": 50, "b": 20},
    )
    return fig


def _plotly_bar(go: Any, tasks: list[DotoTask], group_by: list[str]) -> Any:
    """Build a plotly bar figure (the default)."""
    primary_field = group_by[0] if group_by else "status"
    data = _chart_data_for_field(tasks, primary_field)
    color_map = _color_map_for_field(primary_field) or {}
    labels = [str(k) for k in data.keys()]
    values = list(data.values())
    colors = [color_map.get(lbl.lower()) for lbl in labels]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker_color=colors if any(colors) else None,
        )
    )
    fig.update_layout(
        title=f"Tasks by {primary_field.title()}",
        width=420,
        height=320,
        margin={"l": 50, "r": 20, "t": 50, "b": 40},
    )
    return fig


# Registry mapping a chart type to its plotly figure builder. Adding a new
# plotly chart type is one entry here plus one builder function.
PLOTLY_CHART_BUILDERS: dict[str, Any] = {
    "progress": _plotly_progress,
    "burndown": _plotly_burndown,
    "stacked-bar": _plotly_stacked_bar,
    "pie": _plotly_pie,
    "bar": _plotly_bar,
}


def _plotly_figure(
    tasks: list[DotoTask],
    group_by: list[str],
    chart_type: str,
) -> Any:
    """Build a plotly Figure for the given tasks / grouping / chart type.

    Returns a ``plotly.graph_objects.Figure`` or ``None`` when a figure cannot
    be produced (e.g. burndown with no dated tasks). Assumes plotly is
    importable; callers must check :func:`plotly_available` first.

    Dispatch is table-driven via :data:`PLOTLY_CHART_BUILDERS`; unknown types
    fall back to the bar builder.

    Args:
        tasks: List of DotoTask objects or dicts.
        group_by: Fields to group by. The first field drives single-series
            charts (pie/bar); ``stacked-bar`` uses the first field as the
            stack category.
        chart_type: One of ``pie``, ``bar``, ``stacked-bar``, ``progress``,
            ``burndown``.
    """
    import plotly.graph_objects as go

    builder = PLOTLY_CHART_BUILDERS.get(chart_type, _plotly_bar)
    return builder(go, tasks, group_by)


def _burndown_series(tasks: list[DotoTask]) -> tuple[list[str], list[int]] | None:
    """Compute the (dates, remaining-count) series used by burndown charts.

    Returns None when there is insufficient date data (fewer than 2 days),
    matching the SVG burndown behavior. Delegates the actual counting to
    :func:`_burndown_daily_counts` so the SVG and plotly engines share one
    implementation.
    """
    from datetime import timedelta

    series = _burndown_daily_counts(tasks)
    if series is None:
        return None
    start, day_counts = series
    dates = [(start + timedelta(days=offset)).isoformat() for offset in range(len(day_counts))]
    return dates, day_counts


def _chart_filename(tasks: list[DotoTask], group_by: list[str], chart_type: str, ext: str) -> str:
    """Build a stable, unique filename for a rendered plotly chart image.

    The name is derived from the chart configuration and task composition so
    identical charts reuse the same file and the build output stays
    deterministic (aiding cleanup and caching).

    Args:
        tasks: Tasks the chart is built from.
        group_by: Group-by fields.
        chart_type: Chart type.
        ext: File extension without the dot (e.g. ``png``, ``svg``).

    Returns:
        A filename like ``doto-chart-<hash>.png``.
    """
    signature_parts = [chart_type, ",".join(group_by)]
    for task in tasks:
        signature_parts.append(
            f"{_get_task_attr(task, 'id', '')}:"
            f"{_get_task_attr(task, 'status', '')}:"
            f"{_get_task_attr(task, 'priority', '')}"
        )
    signature = "|".join(signature_parts)
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
    return f"doto-chart-{digest}.{ext}"


def render_plotly_chart_image(
    tasks: list[DotoTask],
    group_by: list[str],
    chart_type: str,
    output_dir: str,
    image_format: str = "png",
) -> str | None:
    """Render a plotly chart to a static image file in ``output_dir``.

    Requires both plotly and kaleido. Returns the written filename (relative to
    ``output_dir``) on success, or ``None`` when plotly/kaleido are unavailable,
    the chart could not be produced, or the export failed. Callers fall back to
    the SVG engine when ``None`` is returned so the build never crashes.

    Args:
        tasks: List of DotoTask objects or dicts.
        group_by: Group-by fields.
        chart_type: Chart type.
        output_dir: Directory the image is written into (created if missing).
        image_format: ``png`` (default) or ``svg``.

    Returns:
        Basename of the written image, or ``None`` on any failure/unavailability.
    """
    import os

    if not kaleido_available():
        return None
    try:
        fig = _plotly_figure(tasks, group_by, chart_type)
    except Exception:
        return None
    if fig is None:
        return None

    os.makedirs(output_dir, exist_ok=True)
    filename = _chart_filename(tasks, group_by, chart_type, image_format)
    path = os.path.join(output_dir, filename)
    try:
        fig.write_image(path, format=image_format)
    except Exception:
        # kaleido may still fail at runtime (e.g. missing chrome shim); never
        # let that break the build — the caller falls back to SVG.
        return None
    return filename


def generate_summary_charts_plotly_html(
    tasks: list[DotoTask],
    group_by: list[str],
    chart_type: str,
    output_dir: str,
    static_prefix: str = "_static",
) -> str | None:
    """Produce an HTML ``<img>`` snippet referencing a static plotly chart.

    Writes a PNG into ``output_dir`` (typically ``<outdir>/_static``) and
    returns an ``<img>`` tag pointing at ``<static_prefix>/<filename>``. Returns
    ``None`` when the plotly image could not be produced so the HTML visitor
    falls back to the inline SVG engine.

    Args:
        tasks: List of DotoTask objects or dicts.
        group_by: Group-by fields.
        chart_type: Chart type.
        output_dir: Directory to write the PNG into.
        static_prefix: URL/path prefix used in the ``src`` attribute.

    Returns:
        HTML string, or ``None`` on failure/unavailability.
    """
    filename = render_plotly_chart_image(
        tasks, group_by, chart_type, output_dir, image_format="png"
    )
    if filename is None:
        return None
    src = f"{static_prefix}/{filename}"
    return (
        '<div class="doto-charts doto-charts-plotly">'
        f'<img src="{src}" alt="Task {chart_type} chart" '
        'class="doto-chart doto-chart-image" />'
        "</div>"
    )


# --- native-LaTeX engine (no browser / kaleido required) -----------------
#
# The PDF summary must always show a real chart, even when neither plotly nor
# kaleido/Chrome are available (the common case). These renderers emit LaTeX
# that draws the chart via themeable ``\dotochart*`` macros defined in
# ``themes/latex/doto.sty`` (tikz-based bars, pie, progress and burndown line).
# A child theme can override those macros to restyle the charts without
# touching Python. The Python side only computes the grouped data and formats
# macro arguments, keeping presentation in the .sty.


def _latex_chart_escape(text: str) -> str:
    """Escape a chart label for safe inclusion as a LaTeX macro argument."""
    replacements = [
        ("\\", "\\textbackslash{}"),
        ("&", "\\&"),
        ("%", "\\%"),
        ("$", "\\$"),
        ("#", "\\#"),
        ("_", "\\_"),
        ("{", "\\{"),
        ("}", "\\}"),
        ("~", "\\textasciitilde{}"),
        ("^", "\\textasciicircum{}"),
    ]
    out = str(text)
    for old, new in replacements:
        out = out.replace(old, new)
    return out


def _latex_hex(color: str) -> str:
    """Return a 6-hex-digit color (no leading ``#``) for LaTeX ``\\definecolor``."""
    return color.lstrip("#")


def _latex_bar_chart(
    tasks: list[DotoTask], data: dict[str, int], title: str, color_map: dict[str, str] | None
) -> str:
    r"""Emit a native-LaTeX horizontal bar chart via ``\dotochart``/``\dotochartbar``."""
    if not data:
        return ""
    max_value = max(data.values()) or 1
    rows = []
    for i, (label, value) in enumerate(data.items()):
        color = _color_for(label, i, color_map)
        rows.append(
            f"\\dotochartbar{{{_latex_chart_escape(label)}}}{{{value}}}"
            f"{{{max_value}}}{{{_latex_hex(color)}}}"
        )
    body = "\n".join(rows)
    return f"\\begin{{dotochart}}{{{_latex_chart_escape(title)}}}\n{body}\n\\end{{dotochart}}\n"


def _latex_pie_chart(
    tasks: list[DotoTask], data: dict[str, int], title: str, color_map: dict[str, str] | None
) -> str:
    r"""Emit a native-LaTeX pie chart via ``\dotochartpie``."""
    total = sum(data.values())
    if total == 0:
        return ""
    slices = []
    for i, (label, value) in enumerate(data.items()):
        if value == 0:
            continue
        color = _color_for(label, i, color_map)
        pct = round(value / total * 100)
        # color/value/percent/label — the .sty draws wedges from cumulative pct.
        slices.append(
            f"{{{_latex_hex(color)}}}{{{value}}}{{{pct}}}{{{_latex_chart_escape(label)}}}"
        )
    if not slices:
        return ""
    entries = "\n".join(f"\\dotochartslice{s}" for s in slices)
    return (
        f"\\begin{{dotochart}}{{{_latex_chart_escape(title)}}}\n"
        f"\\begin{{dotochartpie}}\n{entries}\n\\end{{dotochartpie}}\n"
        f"\\end{{dotochart}}\n"
    )


def _latex_progress_chart(tasks: list[DotoTask], title: str) -> str:
    r"""Emit a native-LaTeX completion bar via ``\dotochartprogress``."""
    total = len(tasks)
    done = sum(1 for t in tasks if (_get_task_attr(t, "status") or "").lower() == "done")
    pct = round(done / total * 100) if total else 0
    return (
        f"\\begin{{dotochart}}{{{_latex_chart_escape(title)}}}\n"
        f"\\dotochartprogress{{{pct}}}{{{done}}}{{{total}}}\n"
        f"\\end{{dotochart}}\n"
    )


def _latex_burndown_chart(tasks: list[DotoTask], title: str) -> str:
    r"""Emit a native-LaTeX burndown line via ``\dotochartline``.

    Falls back to a status bar chart when there is insufficient date data,
    matching the SVG engine.
    """
    series = _burndown_daily_counts(tasks)
    if series is None:
        data = _chart_data_for_field(tasks, "status")
        return _latex_bar_chart(tasks, data, "Tasks by Status", STATUS_COLORS)
    from datetime import timedelta

    start, counts = series
    num_days = len(counts)
    max_count = max(counts) or 1
    # Normalize to (x,y) coordinate pairs in [0,1] for the .sty tikz plot.
    coords = " ".join(
        f"({i / (num_days - 1):.4f},{c / max_count:.4f})" for i, c in enumerate(counts)
    )
    end = start + timedelta(days=num_days - 1)
    return (
        f"\\begin{{dotochart}}{{{_latex_chart_escape(title)}}}\n"
        f"\\dotochartline{{{coords}}}{{{max_count}}}"
        f"{{{start.isoformat()}}}{{{end.isoformat()}}}\n"
        f"\\end{{dotochart}}\n"
    )


def _latex_chart_bar(tasks: list[DotoTask], group_by: list[str]) -> list[str]:
    """Native-LaTeX bar charts, one per group-by field."""
    charts: list[str] = []
    fields = group_by or ["status"]
    for field in fields:
        data = _chart_data_for_field(tasks, field)
        color_map = _color_map_for_field(field)
        charts.append(
            _latex_bar_chart(
                tasks,
                data,
                f"Tasks by {field.title()}",
                color_map,
            )
        )
    return [c for c in charts if c]


def _latex_chart_pie(tasks: list[DotoTask], group_by: list[str]) -> list[str]:
    """Native-LaTeX pie charts, one per group-by field."""
    charts: list[str] = []
    fields = group_by or ["status"]
    for field in fields:
        data = _chart_data_for_field(tasks, field)
        color_map = _color_map_for_field(field)
        charts.append(
            _latex_pie_chart(
                tasks,
                data,
                f"Tasks by {field.title()}",
                color_map,
            )
        )
    return [c for c in charts if c]


def _latex_chart_progress(tasks: list[DotoTask], group_by: list[str]) -> list[str]:
    """Native-LaTeX overall completion chart."""
    chart = _latex_progress_chart(tasks, "Completion")
    return [chart] if chart else []


def _latex_chart_burndown(tasks: list[DotoTask], group_by: list[str]) -> list[str]:
    """Native-LaTeX burndown chart (falls back to a status bar chart)."""
    chart = _latex_burndown_chart(tasks, "Burndown")
    return [chart] if chart else []


# Registry mapping a chart type to its native-LaTeX renderer. Adding a new
# native-LaTeX chart type is one entry here plus one render function;
# ``stacked-bar`` reuses the bar renderer.
LATEX_CHART_RENDERERS: dict[str, Any] = {
    "bar": _latex_chart_bar,
    "stacked-bar": _latex_chart_bar,
    "pie": _latex_chart_pie,
    "burndown": _latex_chart_burndown,
    "progress": _latex_chart_progress,
}


def generate_summary_charts_latex(
    tasks: list[DotoTask],
    group_by: list[str],
    chart_type: str = "bar",
) -> str:
    r"""Generate native-LaTeX charts (no browser/kaleido) for the PDF summary.

    Emits LaTeX built from the same grouped data the SVG/plotly engines use,
    drawn via the themeable ``\dotochart*`` macros in ``doto.sty``. This is the
    default fallback for PDF output when the plotly engine is unavailable, so
    the PDF always shows a real chart rather than only a textual breakdown.

    Args:
        tasks: List of DotoTask objects or dicts.
        group_by: Group-by fields.
        chart_type: One of ``bar``, ``pie``, ``stacked-bar``, ``progress`` or
            ``burndown``. Unknown types fall back to bar.

    Returns:
        A LaTeX string, or ``""`` when no chart can be produced.
    """
    if not tasks:
        return ""
    renderer = LATEX_CHART_RENDERERS.get(chart_type, _latex_chart_bar)
    charts = renderer(tasks, group_by)
    return "\n".join(c for c in charts if c)
