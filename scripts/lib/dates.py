"""US Eastern date helpers shared by every Diamond Ledger NFL script."""
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def now_et():
    return datetime.now(ET)


def today_et_str():
    return now_et().strftime("%Y-%m-%d")


def weekday_et(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%A")


def et_date_of_iso(iso_utc):
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return dt.astimezone(ET).strftime("%Y-%m-%d")
