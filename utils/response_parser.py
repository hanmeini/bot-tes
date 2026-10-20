"""
utils/response_parser.py — Fungsi parser untuk mengekstrak dan memvalidasi
respons JSON dari server/API maupun dari DOM halaman.
"""

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


def safe_json_parse(raw: str, label: str = "") -> Optional[dict]:
    """
    Parse string JSON secara aman. Mengembalikan dict atau None jika gagal.

    Args:
        raw:   String mentah yang akan di-parse.
        label: Label untuk logging agar mudah diidentifikasi sumbernya.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"[PARSER] ⚠️  JSON decode error [{label}]: {e} | Raw: {raw[:120]!r}")
        return None


def extract_json_from_text(text: str) -> Optional[dict]:
    """
    Mengekstrak JSON pertama yang ditemukan di dalam teks campuran
    (berguna untuk halaman yang menyisipkan JSON di dalam HTML/script tag).
    """
    pattern = re.compile(r"\{.*?\}", re.DOTALL)
    matches = pattern.findall(text)
    for match in matches:
        result = safe_json_parse(match, label="embedded")
        if result:
            return result
    logger.debug("[PARSER] Tidak ada JSON valid ditemukan dalam teks.")
    return None


def get_nested(data: dict, *keys: str, default: Any = None) -> Any:
    """
    Mengambil nilai nested dari dict secara aman tanpa KeyError.

    Contoh:
        get_nested(resp, "data", "user", "id", default=0)
        # setara dengan resp["data"]["user"]["id"] tapi tidak crash
    """
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
        if current is default:
            return default
    return current


def parse_http_status(status_code: int) -> dict:
    """
    Mengklasifikasikan HTTP status code menjadi kategori dan rekomendasi aksi.
    Berguna untuk menentukan apakah harus retry atau abort.
    """
    categories = {
        range(200, 300): ("success",  False, "Lanjutkan"),
        range(400, 410): ("client_error", False, "Cek request parameter"),
        range(429, 430): ("rate_limited", True,  "Tunggu sebelum retry"),
        range(500, 600): ("server_error", True,  "Retry dengan backoff"),
    }
    for code_range, (category, should_retry, advice) in categories.items():
        if status_code in code_range:
            return {
                "code": status_code,
                "category": category,
                "should_retry": should_retry,
                "advice": advice,
            }
    return {
        "code": status_code,
        "category": "unknown",
        "should_retry": False,
        "advice": "Periksa manual",
    }


def parse_flash_sale_status(page_data: dict) -> dict:
    """
    Mengekstrak status flash sale dari respons API Tokopedia (struktur umum).
    Sesuaikan key-nya dengan respons API aktual target.
    """
    return {
        "is_active":   get_nested(page_data, "flash_sale", "is_active", default=False),
        "stock":       get_nested(page_data, "flash_sale", "stock", default=0),
        "sold":        get_nested(page_data, "flash_sale", "sold", default=0),
        "price":       get_nested(page_data, "flash_sale", "price", default=0),
        "end_time":    get_nested(page_data, "flash_sale", "end_time", default=""),
        "product_id":  get_nested(page_data, "product", "id", default=""),
        "product_name": get_nested(page_data, "product", "name", default=""),
    }
