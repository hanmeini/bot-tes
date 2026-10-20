"""
utils/time_utils.py — Fungsi konversi & kalkulasi waktu presisi tinggi.
"""

import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo


WIB = ZoneInfo("Asia/Jakarta")


def now_ts() -> float:
    """Timestamp UNIX saat ini (float, presisi microsecond)."""
    return time.time()


def now_ms() -> int:
    """Timestamp milidetik saat ini."""
    return int(time.time() * 1000)


def ms_to_parts(ms: int) -> dict:
    """
    Memecah milidetik menjadi bagian-bagian waktu yang dapat dibaca manusia.

    >>> ms_to_parts(3661500)
    {'hours': 1, 'minutes': 1, 'seconds': 1, 'milliseconds': 500}
    """
    total_seconds, remainder_ms = divmod(ms, 1000)
    total_minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(total_minutes, 60)
    return {
        "hours": int(hours),
        "minutes": int(minutes),
        "seconds": int(seconds),
        "milliseconds": int(remainder_ms),
    }


def format_countdown(remaining_seconds: float) -> str:
    """Mengformat sisa waktu menjadi string 'HH:MM:SS.mmm'."""
    if remaining_seconds < 0:
        return "00:00:00.000"
    parts = ms_to_parts(int(remaining_seconds * 1000))
    return (
        f"{parts['hours']:02d}:"
        f"{parts['minutes']:02d}:"
        f"{parts['seconds']:02d}."
        f"{parts['milliseconds']:03d}"
    )


def parse_iso_to_ts(iso_string: str) -> float:
    """
    Parse string ISO 8601 (dengan timezone) menjadi UNIX timestamp.
    Contoh input: '2026-07-28T20:00:00+07:00'
    """
    dt = datetime.fromisoformat(iso_string)
    return dt.timestamp()


def ts_to_wib(ts: float) -> str:
    """Mengonversi UNIX timestamp ke string waktu WIB yang mudah dibaca."""
    dt = datetime.fromtimestamp(ts, tz=WIB)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f WIB")[:-3]


def elapsed_ms(start: float) -> float:
    """Menghitung waktu yang sudah berlalu dalam milidetik sejak start (perf_counter)."""
    return (time.perf_counter() - start) * 1000
