"""
main.py — Entry Point / Orchestrator
Menghubungkan semua modul: config → session → browser → monitoring loop → eksekusi klik → log hasil.
"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

import ntplib
from playwright.async_api import async_playwright, BrowserContext, Page

from auth import SessionManager
from browser import BrowserActions
from logger import setup_logger, get_logger, catch_errors
from utils import format_countdown, parse_iso_to_ts, elapsed_ms, random_ua

# Logger diinisialisasi setelah config dibaca
logger = None

# ======================================================================== #
#  CONFIG LOADER                                                             #
# ======================================================================== #

def load_config(path: str = "config.json") -> dict:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"File konfigurasi tidak ditemukan: {path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    print(f"[CONFIG] ✅ Konfigurasi dimuat dari: {path}")
    return config

# ======================================================================== #
#  NTP SYNC                                                                  #
# ======================================================================== #

def get_accurate_time(ntp_server: str = "time.google.com") -> float:
    """
    Mengambil waktu akurat dari server NTP.
    Mengembalikan timestamp UNIX float.
    Fallback ke waktu lokal jika NTP tidak tersedia.
    """
    try:
        client = ntplib.NTPClient()
        response = client.request(ntp_server, version=3)
        ntp_time = response.tx_time
        offset_ms = response.offset * 1000
        logger.info(f"[NTP] ✅ Sinkronisasi NTP berhasil | Offset: {offset_ms:+.2f}ms")
        return ntp_time
    except Exception as e:
        logger.warning(f"[NTP] ⚠️  Gagal koneksi NTP ({e}). Menggunakan waktu lokal.")
        return time.time()

# ======================================================================== #
#  COUNTDOWN MONITOR                                                          #
# ======================================================================== #

async def wait_until_sale(target_dt: datetime, ntp_server: str, pre_load_seconds: int) -> None:
    """
    Loop pemantauan yang menghitung mundur hingga waktu flash sale.
    Akan berhenti dan lanjut setelah melewati (target - pre_load_seconds).
    """
    logger.info(f"[TIMER] 🎯 Target waktu mulai: {target_dt.isoformat()}")
    logger.info(f"[TIMER] ⏳ Pre-load {pre_load_seconds}s sebelum sale dimulai...")

    action_time = target_dt.timestamp() - pre_load_seconds

    while True:
        now = get_accurate_time(ntp_server)
        remaining = action_time - now

        if remaining <= 0:
            logger.info("[TIMER] 🟢 Waktunya! Memulai eksekusi...")
            break

        countdown_str = format_countdown(remaining)
        if remaining > 60:
            logger.info(f"[TIMER] ⏱  Hitung mundur: {countdown_str}")
            await asyncio.sleep(10)
        elif remaining > 10:
            logger.info(f"[TIMER] ⏱  Hitung mundur: {countdown_str}")
            await asyncio.sleep(1)
        else:
            # Detik-detik terakhir: polling sangat cepat
            logger.info(f"[TIMER] ⚡ T-{countdown_str}")
            await asyncio.sleep(0.05)

# ======================================================================== #
#  FLASH SALE EXECUTION                                                       #
# ======================================================================== #

async def execute_purchase(page: Page, actions: BrowserActions, config: dict) -> dict:
    """
    Urutan klik utama untuk menyelesaikan pembelian flash sale.
    Mengembalikan dict hasil {'success': bool, 'step': str, 'error': str|None}.
    """
    selectors = config.get("selectors", {})
    qty = config.get("quantity", 1)
    result = {"success": False, "step": "init", "error": None}

    # --- Langkah 1: Tutup pop-up jika ada ---
    logger.info("[EXEC] Langkah 1: Cek dan tutup pop-up...")
    await actions.dismiss_popup(page)
    result["step"] = "popup_dismissed"

    # --- Langkah 2: Set jumlah produk ---
    logger.info(f"[EXEC] Langkah 2: Mengatur jumlah → {qty}")
    await actions.set_quantity(page, qty)
    result["step"] = "quantity_set"

    # --- Langkah 3: Klik tombol Beli / Add to Cart ---
    logger.info("[EXEC] Langkah 3: Klik tombol Beli...")
    buy_sel = selectors.get("buy_button", "")
    atc_sel = selectors.get("atc_button", "")

    # Coba tombol Beli Sekarang dulu, fallback ke Add to Cart
    clicked = await actions.fast_click(page, buy_sel)
    if not clicked and atc_sel:
        logger.warning("[EXEC] Tombol Beli tidak ditemukan, coba Add to Cart...")
        clicked = await actions.fast_click(page, atc_sel)

    if not clicked:
        result["error"] = "Tombol beli tidak dapat diklik"
        logger.error(f"[EXEC] ❌ {result['error']}")
        return result
    result["step"] = "buy_clicked"

    # --- Langkah 4: Tunggu halaman checkout & klik ---
    logger.info("[EXEC] Langkah 4: Menunggu halaman checkout...")
    checkout_sel = selectors.get("checkout_button", "")
    checkout_locator = await actions.wait_for_element(page, checkout_sel, timeout_ms=8000)

    if not checkout_locator:
        result["error"] = "Halaman checkout tidak muncul"
        logger.error(f"[EXEC] ❌ {result['error']}")
        return result

    await checkout_locator.click()
    result["step"] = "checkout_clicked"

    # --- Langkah 5: Klik Bayar ---
    logger.info("[EXEC] Langkah 5: Klik tombol Bayar...")
    pay_sel = selectors.get("payment_button", "")
    pay_locator = await actions.wait_for_element(page, pay_sel, timeout_ms=10000)

    if pay_locator:
        await pay_locator.click()
        result["step"] = "payment_clicked"
        result["success"] = True
        logger.info("[EXEC] 🎉 SUKSES! Pembelian berhasil diproses.")
    else:
        result["error"] = "Tombol bayar tidak ditemukan"
        logger.warning(f"[EXEC] ⚠️  {result['error']}")

    return result

# ======================================================================== #
#  MAIN                                                                       #
# ======================================================================== #

async def main():
    global logger
    # ── 1. Baca konfigurasi ──────────────────────────────────────────────
    config = load_config("config.json")
    log_cfg = config.get("logging", {})

    # ── 2. Setup logger terpusat (dari logger.py) ────────────────────────
    setup_logger(
        name="bot",
        level=log_cfg.get("level", "INFO"),
        console=log_cfg.get("console_output", True),
        structured=True,
    )
    logger = get_logger("main")

    logger.info("=" * 60)
    logger.info("  🤖 BOT FLASH SALE — MULAI")
    logger.info("=" * 60)

    timing = config["timing"]
    browser_cfg = config["browser"]
    target = config["target"]

    # ── 2. Parse waktu target ─────────────────────────────────────────────
    sale_start_iso = timing["sale_start_time"]
    target_dt = datetime.fromisoformat(sale_start_iso)
    logger.info(f"[MAIN] Target sale: {target_dt}")

    # ── 3. Sinkronisasi NTP ───────────────────────────────────────────────
    if timing.get("ntp_sync_enabled", True):
        get_accurate_time(timing.get("ntp_server", "time.google.com"))

    # ── 4. Inisialisasi modul ─────────────────────────────────────────────
    session_mgr = SessionManager(config)
    actions = BrowserActions(config)

    # ── 5. Buka browser ───────────────────────────────────────────────────
    async with async_playwright() as pw:
        browser_type = getattr(pw, browser_cfg.get("browser_type", "chromium"))
        browser = await browser_type.launch(
            headless=browser_cfg.get("headless", False),
            slow_mo=browser_cfg.get("slow_mo_ms", 0),
            args=["--disable-blink-features=AutomationControlled"],
        )

        # Gunakan UA acak dari utils jika config tidak ada UA spesifik
        ua = browser_cfg.get("user_agent") or random_ua("windows")
        logger.debug(f"[MAIN] User-Agent: {ua[:60]}...")

        context: BrowserContext = await browser.new_context(
            viewport=browser_cfg.get("viewport", {"width": 1366, "height": 768}),
            user_agent=ua,
            locale=browser_cfg.get("locale", "id-ID"),
            timezone_id=browser_cfg.get("timezone_id", "Asia/Jakarta"),
        )

        page: Page = await context.new_page()

        # ── 6. Muat sesi / cookies ────────────────────────────────────────
        logger.info("[MAIN] Memuat session...")
        loaded = await session_mgr.load_session(context)
        await actions.navigate(page, target["base_url"])

        if loaded:
            is_logged_in = await session_mgr.verify_login(page)
            if not is_logged_in:
                logger.warning("[MAIN] ⚠️  Session invalid. Lanjut tanpa login.")
        else:
            logger.warning("[MAIN] ⚠️  Tidak ada session. Pastikan cookies.json tersedia.")

        # ── 7. Pre-load halaman produk ────────────────────────────────────
        product_url = target.get("product_url") or target.get("flash_sale_url")
        logger.info(f"[MAIN] Pre-load halaman produk: {product_url}")
        await actions.navigate(page, product_url)

        # Daftarkan dialog handler sebelum loop eksekusi
        actions.handle_dialog(page)

        # ── 8. Countdown monitoring loop ──────────────────────────────────
        await wait_until_sale(
            target_dt=target_dt,
            ntp_server=timing.get("ntp_server", "time.google.com"),
            pre_load_seconds=timing.get("pre_load_seconds", 30),
        )

        # Refresh halaman sesaat sebelum sale untuk mendapat DOM terbaru
        logger.info("[MAIN] 🔄 Refresh halaman menjelang sale...")
        await actions.refresh_page(page)
        await asyncio.sleep(0.2)  # Beri waktu DOM render

        # ── 9. Eksekusi pembelian ─────────────────────────────────────────
        start_ts = time.perf_counter()
        result = await execute_purchase(page, actions, config)
        elapsed_ms = (time.perf_counter() - start_ts) * 1000

        # ── 10. Log hasil akhir ───────────────────────────────────────────
        logger.info("=" * 60)
        if result["success"]:
            logger.info(f"  ✅ HASIL: BERHASIL | Langkah terakhir: {result['step']}")
        else:
            logger.error(f"  ❌ HASIL: GAGAL    | Langkah: {result['step']} | Error: {result['error']}")
        logger.info(f"  ⏱  Total waktu eksekusi: {elapsed_ms:.2f}ms")
        logger.info("=" * 60)

        # Jangan langsung tutup browser agar bisa lihat hasil
        if not browser_cfg.get("headless", False):
            logger.info("[MAIN] Browser tetap terbuka. Tekan Ctrl+C untuk keluar.")
            await asyncio.sleep(60)

        await browser.close()

# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n[MAIN] 🛑 Dihentikan oleh pengguna.")
