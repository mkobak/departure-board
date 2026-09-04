"""Pickup reminders shown on the screensaver (compost / trash / cardboard).

A reminder is active from REMINDER_START_HOUR on the evening before a pickup
until REMINDER_END_HOUR on the pickup day itself.

This module is stdlib-only so it can be unit-tested without the matrix library.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional

# Show reminders from this hour on the evening before a pickup ...
REMINDER_START_HOUR = 20
# ... until this hour on the pickup day (exclusive).
REMINDER_END_HOUR = 9

# Python weekday numbering: Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
COMPOST_DAYS = {3}        # every Thursday
TRASH_DAYS = {1, 4}       # every Tuesday and Friday

# Cardboard: every 4th Wednesday. Anchor on a known pickup date.
CARDBOARD_ANCHOR = date(2026, 9, 9)
CARDBOARD_PERIOD_DAYS = 28


def pickups_on(day: date) -> List[str]:
    """Return the pickup labels for the given calendar day (may be empty)."""
    labels: List[str] = []
    wd = day.weekday()
    if wd in COMPOST_DAYS:
        labels.append("Compost")
    if wd in TRASH_DAYS:
        labels.append("Trash")
    if (day - CARDBOARD_ANCHOR).days % CARDBOARD_PERIOD_DAYS == 0:
        labels.append("Cardboard")
    return labels


def active_reminders(now: datetime) -> List[str]:
    """Pickups to remind about at the given moment (evening before / morning of)."""
    if now.hour >= REMINDER_START_HOUR:
        return pickups_on(now.date() + timedelta(days=1))
    if now.hour < REMINDER_END_HOUR:
        return pickups_on(now.date())
    return []


def reminder_text(now: Optional[datetime] = None) -> Optional[str]:
    """Full reminder line for the screensaver, or None when nothing is due."""
    labels = active_reminders(now or datetime.now())
    if not labels:
        return None
    return "Reminder: " + " + ".join(labels)
