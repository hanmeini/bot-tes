"""
logger.py — Modul Logging & Error Handling terpusat.

Fitur:
  - Dual output: console (berwarna) + file bot-error.log
  - Rotating file handler agar log tidak membengkak tanpa batas
  - Decorator @catch_errors untuk fungsi async yang bisa gagal
  - Error classifier: network timeout, HTTP 403, stok habis, dll.
  - Structured JSON log untuk analisis post-mortem di VPS/server
"""

import asyncio
import functools
import json
import logging
import os
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo


# ── Konstanta ─────────────────────────────────────────────────────────────────

WIB = ZoneInfo("Asia/Jakarta")
LOG_DIR = Path("logs")
ERROR_LOG_FILE = LOG_DIR / "bot-error.log"
MAIN_LOG_FILE  = LOG_DIR / "bot.log"
JSON_LOG_FILE  = LOG_DIR / "bot-structured.jsonl"

# Max 5 MB per file, simpan 3 backup
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3


# ── ANSI Color Codes (untuk console) ──────────────────────────────────────────

class _Colors:
    RESET   = "\033[0m"
    GREY    = "\033[90m"
    CYAN    = "\033[96m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    RED     = "\033[91m"
    MAGENTA = "\033[95m"
    BOLD    = "\033[1m"


LEVEL_COLORS = {
    "DEBUG":    _Colors.GREY,
    "INFO":     _Colors.CYAN,
    "WARNING":  _Colors.YELLOW,
    "ERROR":    _Colors.RED,
    "CRITICAL": _Colors.MAGENTA + _Colors.BOLD,
}


# ── Formatter berwarna untuk console ──────────────────────────────────────────

class ColoredFormatter(logging.Formatter):
    """Formatter yang menambahkan warna ANSI ke output console."""

    FMT = "{color}[{asctime}] [{levelname:<8}]{reset} {message}"

    def format(self, record: logging.LogRecord) -> str:
        color = LEVEL_COLORS.get(record.levelname, "")
        record.color = color
        record.reset = _Colors.RESET
        formatter = logging.Formatter(
            fmt=self.FMT,
            datefmt="%H:%M:%S.%f",
            style="{",
        )
        # Trim microseconds menjadi milliseconds
        record.asctime = self._format_time(record)
        return formatter.format(record)

    def _format_time(self, record: logging.LogRecord) -> str:
        dt = datetime.fromtimestamp(record.created, tz=WIB)
        return dt.strftime("%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


# ── Structured JSON Handler ────────────────────────────────────────────────────

class JsonLineHandler(logging.Handler):
    """
    Menulis setiap log entry sebagai satu baris JSON ke file .jsonl.
    Format ini ideal untuk analisis post-mortem dengan tools seperti jq atau pandas.
    """

    def __init__(self, filepath: Path):
        super().__init__()
        filepath.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(filepath, "a", encoding="utf-8", buffering=1)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts":      datetime.fromtimestamp(record.created, tz=WIB).isoformat(),
                "level":   record.levelname,
                "logger":  record.name,
                "msg":     record.getMessage(),
                "module":  record.module,
                "line":    record.lineno,
            }
            if record.exc_info:
                entry["exception"] = self.formatException(record.exc_info)
            self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            self.handleError(record)

    def close(self):
        self._file.close()
        super().close()


# ── Setup fungsi utama ─────────────────────────────────────────────────────────

def setup_logger(
    name: str = "bot",
    level: str = "INFO",
    console: bool = True,
    structured: bool = True,
) -> logging.Logger:
    """
    Menginisialisasi dan mengembalikan logger yang sudah dikonfigurasi penuh.

    Args:
        name:       Nama logger (biasanya 'bot' atau nama modul).
        level:      Level minimum: 'DEBUG', 'INFO', 'WARNING', 'ERROR'.
        console:    Tampilkan output berwarna ke terminal.
        structured: Tulis juga ke file JSON Lines untuk analisis.

    Returns:
        logging.Logger yang siap digunakan.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_level = getattr(logging, level.upper(), logging.INFO)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # Hindari duplikasi handler jika dipanggil ulang
    logger.setLevel(log_level)

    plain_fmt = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Handler 1: File utama (rotating) ─────────────────────────────────
    main_handler = RotatingFileHandler(
        MAIN_LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    main_handler.setLevel(log_level)
    main_handler.setFormatter(plain_fmt)
    logger.addHandler(main_handler)

    # ── Handler 2: File error saja (rotating) ─────────────────────────────
    error_handler = RotatingFileHandler(
        ERROR_LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(plain_fmt)
    logger.addHandler(error_handler)

    # ── Handler 3: Console berwarna ────────────────────────────────────────
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        # Windows CMD mungkin tidak support ANSI, nonaktifkan warna jika perlu
        if sys.platform == "win32" and not os.environ.get("TERM"):
            console_handler.setFormatter(plain_fmt)
        else:
            console_handler.setFormatter(ColoredFormatter())
        logger.addHandler(console_handler)

    # ── Handler 4: Structured JSON Lines ──────────────────────────────────
    if structured:
        json_handler = JsonLineHandler(JSON_LOG_FILE)
        json_handler.setLevel(log_level)
        logger.addHandler(json_handler)

    return logger


# ── Error Classifier ──────────────────────────────────────────────────────────

class BotError:
    """
    Mengklasifikasikan exception yang terjadi selama eksekusi bot
    menjadi kategori dengan rekomendasi tindak lanjut.
    """

    CLASSIFICATIONS = {
        "TimeoutError":           ("network_timeout",  True,  "Retry dengan interval lebih panjang"),
        "PlaywrightTimeoutError": ("element_timeout",  True,  "Cek selector atau percepat koneksi"),
        "ConnectionRefusedError": ("conn_refused",     True,  "Target mungkin down, tunggu sebentar"),
        "ConnectionResetError":   ("conn_reset",       True,  "Koneksi di-reset, retry"),
        "403":                    ("forbidden",        False, "IP/session diblokir, ganti proxy/cookies"),
        "429":                    ("rate_limited",     True,  "Rate limit, tambah delay antar request"),
        "StockEmpty":             ("no_stock",         False, "Stok habis, tidak perlu retry"),
        "LoginRequired":          ("auth_error",       False, "Session expired, perbarui cookies"),
    }

    @classmethod
    def classify(cls, exc: Exception) -> dict:
        exc_name = type(exc).__name__
        exc_msg  = str(exc)

        # Cek berdasarkan nama exception
        if exc_name in cls.CLASSIFICATIONS:
            cat, retry, advice = cls.CLASSIFICATIONS[exc_name]
        # Cek berdasarkan string pesan error (HTTP codes)
        elif "403" in exc_msg:
            cat, retry, advice = cls.CLASSIFICATIONS["403"]
        elif "429" in exc_msg:
            cat, retry, advice = cls.CLASSIFICATIONS["429"]
        else:
            cat, retry, advice = ("unknown_error", False, "Periksa log manual")

        return {
            "exception_type": exc_name,
            "category":       cat,
            "should_retry":   retry,
            "advice":         advice,
            "message":        exc_msg,
            "traceback":      traceback.format_exc(),
        }


# ── Decorator: @catch_errors ───────────────────────────────────────────────────

def catch_errors(
    logger: Optional[logging.Logger] = None,
    default_return=None,
    reraise: bool = False,
):
    """
    Decorator untuk fungsi async yang menangkap, mengklasifikasikan, dan mencatat error
    tanpa menghentikan seluruh program. Berguna untuk task worker yang harus tetap hidup.

    Pemakaian:
        @catch_errors(logger=my_logger, default_return=False)
        async def klik_tombol(page):
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            _log = logger or logging.getLogger(func.__module__)
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                info = BotError.classify(exc)
                _log.error(
                    f"[ERROR] ❌ {func.__name__}() → [{info['category']}] "
                    f"{info['exception_type']}: {info['message']}"
                )
                _log.debug(f"[TRACEBACK]\n{info['traceback']}")
                if info["advice"]:
                    _log.warning(f"[ADVICE] 💡 {info['advice']}")
                if reraise:
                    raise
                return default_return
        return wrapper
    return decorator


# ── Shortcut: get logger per modul ───────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    """Shortcut untuk mendapatkan child logger dari root 'bot' logger."""
    return logging.getLogger(f"bot.{name}")
