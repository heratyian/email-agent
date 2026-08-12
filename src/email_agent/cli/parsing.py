from datetime import date, datetime, timedelta
from datetime import time as datetime_time


def parse_snooze(value: str) -> datetime:
    """Parse `tomorrow`, an ISO date, or an ISO datetime in the local timezone."""
    local_tz = datetime.now().astimezone().tzinfo
    if value.lower() == "tomorrow":
        tomorrow = datetime.now(local_tz).date() + timedelta(days=1)
        return datetime.combine(tomorrow, datetime_time(hour=9), tzinfo=local_tz)
    if "T" not in value and " " not in value:
        try:
            parsed = datetime.combine(date.fromisoformat(value), datetime_time(hour=9))
        except ValueError as exc:
            raise ValueError(
                "--until must be 'tomorrow', YYYY-MM-DD, or an ISO datetime"
            ) from exc
    else:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "--until must be 'tomorrow', YYYY-MM-DD, or an ISO datetime"
            ) from exc
    return parsed.replace(tzinfo=local_tz) if parsed.tzinfo is None else parsed
