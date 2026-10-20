"""
auth.py — Modul Autentikasi & Session Management
Menangani pemuatan cookies, penerapan session ke browser, dan verifikasi status login.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from playwright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Mengelola sesi browser: memuat cookies dari file lokal,
    menerapkannya ke domain target, dan memverifikasi login.
    """

    def __init__(self, config: dict):
        self.cfg = config
        self.session_cfg = config.get("session", {})
        self.cookies_file = Path(self.session_cfg.get("cookies_file", "cookies.json"))
        self.storage_state_file = Path(
            self.session_cfg.get("storage_state_file", "storage_state.json")
        )
        self.base_url = config["target"]["base_url"]

    # ------------------------------------------------------------------ #
    #  Load & Apply                                                        #
    # ------------------------------------------------------------------ #

    async def load_session(self, context: BrowserContext) -> bool:
        """
        Memuat storage state (cookies + localStorage) ke dalam browser context.
        Mengembalikan True jika berhasil, False jika file tidak ditemukan.
        """
        if self.storage_state_file.exists():
            logger.info(f"[AUTH] Memuat storage state dari: {self.storage_state_file}")
            try:
                with open(self.storage_state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                await context.add_cookies(state.get("cookies", []))
                logger.info(
                    f"[AUTH] ✅ {len(state.get('cookies', []))} cookie berhasil diterapkan."
                )
                return True
            except Exception as e:
                logger.error(f"[AUTH] ❌ Gagal memuat storage state: {e}")
                return False

        if self.cookies_file.exists():
            logger.info(f"[AUTH] Memuat cookies dari: {self.cookies_file}")
            try:
                with open(self.cookies_file, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                # Pastikan setiap cookie punya 'domain' yang valid
                sanitized = self._sanitize_cookies(cookies)
                await context.add_cookies(sanitized)
                logger.info(
                    f"[AUTH] ✅ {len(sanitized)} cookie berhasil diterapkan."
                )
                return True
            except Exception as e:
                logger.error(f"[AUTH] ❌ Gagal memuat cookies: {e}")
                return False

        logger.warning("[AUTH] ⚠️  File session tidak ditemukan. Bot akan berjalan tanpa login.")
        return False

    async def verify_login(self, page: Page) -> bool:
        """
        Membuka halaman utama dan memeriksa apakah pengguna sudah login
        dengan mencari elemen yang hanya muncul saat terautentikasi.
        """
        logger.info("[AUTH] Memverifikasi status login...")
        try:
            await page.goto(self.base_url, wait_until="domcontentloaded", timeout=15000)
            # Cari avatar / nama akun sebagai penanda login
            logged_in = await page.locator("[data-testid='icnAccountIcon']").count() > 0
            if logged_in:
                logger.info("[AUTH] ✅ Login terverifikasi.")
            else:
                logger.warning("[AUTH] ⚠️  Belum login. Periksa file cookies.")
            return logged_in
        except Exception as e:
            logger.error(f"[AUTH] ❌ Error saat verifikasi login: {e}")
            return False

    async def save_session(self, context: BrowserContext) -> None:
        """
        Menyimpan storage state saat ini ke file agar bisa digunakan kembali.
        Jalankan ini sekali setelah login manual untuk generate cookies.
        """
        try:
            state = await context.storage_state()
            with open(self.storage_state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            logger.info(f"[AUTH] 💾 Session disimpan ke: {self.storage_state_file}")
        except Exception as e:
            logger.error(f"[AUTH] ❌ Gagal menyimpan session: {e}")

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _sanitize_cookies(self, cookies: list) -> list:
        """Membersihkan dan memvalidasi format cookies sebelum diterapkan."""
        required_fields = {"name", "value", "domain"}
        sanitized = []
        for cookie in cookies:
            if not required_fields.issubset(cookie.keys()):
                logger.debug(f"[AUTH] Cookie dilewati (field tidak lengkap): {cookie.get('name')}")
                continue
            # Playwright memerlukan 'sameSite' dalam format tertentu
            if "sameSite" in cookie:
                mapping = {"no_restriction": "None", "lax": "Lax", "strict": "Strict"}
                cookie["sameSite"] = mapping.get(cookie["sameSite"].lower(), "Lax")
            sanitized.append(cookie)
        return sanitized
