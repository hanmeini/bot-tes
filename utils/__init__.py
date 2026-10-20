"""
utils/__init__.py — Package initializer, re-export semua fungsi utilitas.
"""

from .time_utils import (
    now_ts, now_ms, ms_to_parts,
    format_countdown, parse_iso_to_ts, ts_to_wib, elapsed_ms,
)
from .response_parser import (
    safe_json_parse, extract_json_from_text,
    get_nested, parse_http_status, parse_flash_sale_status,
)
from .user_agent import (
    random_chrome_ua, random_firefox_ua, random_ua,
    random_session_id, random_device_id, random_headers_extra,
)

__all__ = [
    # time
    "now_ts", "now_ms", "ms_to_parts",
    "format_countdown", "parse_iso_to_ts", "ts_to_wib", "elapsed_ms",
    # parser
    "safe_json_parse", "extract_json_from_text",
    "get_nested", "parse_http_status", "parse_flash_sale_status",
    # user-agent
    "random_chrome_ua", "random_firefox_ua", "random_ua",
    "random_session_id", "random_device_id", "random_headers_extra",
]
