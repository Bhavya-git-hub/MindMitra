"""Plain-language summary and CSV of group figures, built only from already-safe figures.

Input is a ``cohort.Analytics`` (which has been through the privacy rules), so nothing here can
reveal more than the dashboard does.
"""

import csv
import io

from app.domain.wellness.cohort import Analytics, Share, WeekCell

CSV_HEADER = [
    "week_start",
    "students_reporting",
    "mood_1_to_5",
    "energy_1_to_5",
    "stress_1_to_5",
    "sleep_hours",
    "sleep_quality_1_to_5",
    "checked_in",
    "academic_stress",
    "signs_of_strain",
]


def share_text(value: Share) -> str:
    """A share as words a person can read."""
    if value.state == "shown":
        return f"about {value.percent}%"
    return {
        "few": "a few students",
        "most": "nearly all students",
        "hidden": "not enough students to show",
    }[value.state]


def _num(value: float | None) -> str:
    return "" if value is None else f"{value:g}"


def headline(analytics: Analytics) -> list[str]:
    """Short sentences about the latest week, or why there is nothing to say."""
    if analytics.state == "too_small" or not analytics.weeks:
        return [
            "Too few students have chosen to share anonymous figures for this group to be shown "
            "without risking that anyone could be recognised."
        ]
    latest: WeekCell = analytics.weeks[-1]
    lines: list[str] = []
    if latest.mood is not None:
        lines.append(f"Average mood this week: {latest.mood} out of 5.")
    if latest.stress is not None:
        lines.append(f"Average stress this week: {latest.stress} out of 5.")
    if latest.sleep_hours is not None:
        lines.append(f"Average sleep: {latest.sleep_hours} hours a night.")
    if latest.academic_stress.state != "hidden":
        lines.append(
            f"Students naming study pressure as a stressor: {share_text(latest.academic_stress)}."
        )
    if latest.strain.state != "hidden":
        lines.append(f"Students showing signs of strain: {share_text(latest.strain)}.")
    if not lines:
        lines.append("Not enough students reported this week for any figure to be shown.")
    return lines


def to_csv(analytics: Analytics) -> str:
    """Weekly figures as CSV. Every cell is a number, a fixed word or empty, never free text, so
    nothing in it can be read as a spreadsheet formula. A withheld figure is an empty cell."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for cell in analytics.weeks:
        writer.writerow(
            [
                cell.week_start.isoformat(),
                cell.reporting_band or "",
                _num(cell.mood),
                _num(cell.energy),
                _num(cell.stress),
                _num(cell.sleep_hours),
                _num(cell.sleep_quality),
                share_cell(cell.check_in),
                share_cell(cell.academic_stress),
                share_cell(cell.strain),
            ]
        )
    return out.getvalue()


def share_cell(value: Share) -> str:
    if value.state == "shown":
        return f"{value.percent}%"
    return {"few": "few", "most": "nearly all", "hidden": ""}[value.state]
