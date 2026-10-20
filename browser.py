"""
browser.py — Modul Navigasi & Interaksi Elemen
Berisi fungsi-fungsi inti untuk berinteraksi dengan halaman web:
menunggu elemen, klik, scroll, dan penanganan pop-up.
"""

import asyncio
import logging
from typing import Optional

from playwright.async_api import Page, Locator, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


class BrowserActions:
    """
    Kumpulan fungsi high-level untuk navigasi dan interaksi elemen DOM.
    Semua method bersifat async dan memiliki built-in retry/fallback.
    """

    def __init__(self, config: dict):
        self.cfg = config
        self.selectors = config.get("selectors", {})
        self.timeout = config["timing"].get("element_wait_timeout_ms", 5000)
        self.retry_cfg = config.get("retry", {})
        self.max_retries = self.retry_cfg.get("max_retries", 3)
        self.retry_delay = self.retry_cfg.get("retry_delay_ms", 100) / 1000

    # ------------------------------------------------------------------ #
    #  Navigasi                                                            #
    # ------------------------------------------------------------------ #

    async def navigate(self, page: Page, url: str, wait_until: str = "domcontentloaded") -> bool:
        """Navigasi ke URL dengan error handling."""
        try:
            logger.info(f"[NAV] ➡️  Menuju: {url}")
            response = await page.goto(
                url,
                wait_until=wait_until,
                timeout=self.cfg["timing"].get("page_load_timeout_ms", 10000),
            )
            status = response.status if response else -1
            logger.info(f"[NAV] ✅ Halaman dimuat (HTTP {status})")
            return True
        except PlaywrightTimeout:
            logger.error(f"[NAV] ❌ Timeout saat memuat: {url}")
            return False
        except Exception as e:
            logger.error(f"[NAV] ❌ Error navigasi: {e}")
            return False

    async def refresh_page(self, page: Page) -> None:
        """Reload halaman saat ini."""
        logger.info("[NAV] 🔄 Refresh halaman...")
        await page.reload(wait_until="domcontentloaded")

    # ------------------------------------------------------------------ #
    #  Wait                                                                #
    # ------------------------------------------------------------------ #

    async def wait_for_element(
        self,
        page: Page,
        selector: str,
        timeout_ms: Optional[int] = None,
        state: str = "visible",
    ) -> Optional[Locator]:
        """
        Menunggu elemen muncul di DOM dengan timeout yang dikonfigurasi.
        Mengembalikan Locator jika berhasil, None jika timeout.
        """
        _timeout = timeout_ms or self.timeout
        try:
            locator = page.locator(selector).first
            await locator.wait_for(state=state, timeout=_timeout)
            logger.debug(f"[WAIT] ✅ Elemen ditemukan: {selector}")
            return locator
        except PlaywrightTimeout:
            logger.warning(f"[WAIT] ⚠️  Timeout ({_timeout}ms) menunggu: {selector}")
            return None
        except Exception as e:
            logger.error(f"[WAIT] ❌ Error wait_for_element: {e}")
            return None

    async def wait_for_any(self, page: Page, selectors: list[str], timeout_ms: int = 5000) -> Optional[str]:
        """
        Menunggu elemen PERTAMA yang muncul dari daftar selector.
        Berguna untuk mendeteksi kondisi berbeda (tombol beli vs. stok habis).
        Mengembalikan selector yang ditemukan pertama.
        """
        tasks = [
            asyncio.create_task(
                page.wait_for_selector(sel, state="visible", timeout=timeout_ms)
            )
            for sel in selectors
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for i, task in enumerate(tasks):
            if task in done and not task.exception():
                logger.debug(f"[WAIT] ✅ Pertama muncul: {selectors[i]}")
                return selectors[i]
        return None

    # ------------------------------------------------------------------ #
    #  Klik                                                                #
    # ------------------------------------------------------------------ #

    async def click(
        self,
        page: Page,
        selector: str,
        force: bool = False,
        use_js: bool = False,
    ) -> bool:
        """
        Klik elemen. Mendukung mode normal, force-click, dan JavaScript click
        sebagai fallback untuk elemen yang dilindungi overlay.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                locator = page.locator(selector).first
                await locator.wait_for(state="visible", timeout=self.timeout)

                if use_js:
                    await page.eval_on_selector(selector, "el => el.click()")
                    logger.info(f"[CLICK] 🖱️  JS click: {selector}")
                else:
                    await locator.click(force=force, timeout=self.timeout)
                    logger.info(f"[CLICK] 🖱️  Click: {selector}")
                return True

            except PlaywrightTimeout:
                logger.warning(f"[CLICK] ⚠️  Attempt {attempt}/{self.max_retries} timeout: {selector}")
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay)
            except Exception as e:
                logger.error(f"[CLICK] ❌ Error klik attempt {attempt}: {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay)

        logger.error(f"[CLICK] ❌ Gagal klik setelah {self.max_retries} percobaan: {selector}")
        return False

    async def fast_click(self, page: Page, selector: str) -> bool:
        """
        Mode klik ultra-cepat via JavaScript — tanpa menunggu visibility.
        Digunakan saat detik-detik flash sale dimulai.
        """
        try:
            result = await page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    if (el) { el.click(); return true; }
                    return false;
                }""",
                selector,
            )
            if result:
                logger.info(f"[FAST_CLICK] ⚡ Fast-click berhasil: {selector}")
            else:
                logger.warning(f"[FAST_CLICK] ⚠️  Elemen tidak ditemukan: {selector}")
            return result
        except Exception as e:
            logger.error(f"[FAST_CLICK] ❌ Error: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  Scroll                                                              #
    # ------------------------------------------------------------------ #

    async def scroll_to_element(self, page: Page, selector: str) -> bool:
        """Scroll halaman hingga elemen terlihat di viewport."""
        try:
            await page.locator(selector).first.scroll_into_view_if_needed(timeout=self.timeout)
            logger.debug(f"[SCROLL] 📜 Scroll ke: {selector}")
            return True
        except Exception as e:
            logger.warning(f"[SCROLL] ⚠️  Gagal scroll: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  Pop-up & Alert                                                      #
    # ------------------------------------------------------------------ #

    async def dismiss_popup(self, page: Page) -> bool:
        """
        Mencoba menutup pop-up modal yang mungkin menghalangi interaksi.
        Menggunakan selector dari config.
        """
        popup_sel = self.selectors.get("popup_close", "")
        if not popup_sel:
            return False
        try:
            popup = page.locator(popup_sel).first
            if await popup.is_visible():
                await popup.click(timeout=2000)
                logger.info("[POPUP] ✅ Pop-up ditutup.")
                return True
        except Exception:
            pass
        return False

    def handle_dialog(self, page: Page) -> None:
        """
        Mendaftarkan listener untuk menangani dialog/alert browser secara otomatis.
        Panggil ini sebelum action yang berpotensi memunculkan alert.
        """
        async def _on_dialog(dialog):
            logger.info(f"[DIALOG] 📢 Dialog: {dialog.type} — '{dialog.message}' → Accept")
            await dialog.accept()

        page.on("dialog", _on_dialog)
        logger.debug("[DIALOG] Listener dialog terdaftar.")

    # ------------------------------------------------------------------ #
    #  Form                                                                #
    # ------------------------------------------------------------------ #

    async def set_quantity(self, page: Page, quantity: int) -> bool:
        """Mengisi field jumlah produk."""
        sel = self.selectors.get("quantity_input", "")
        if not sel:
            return False
        try:
            locator = page.locator(sel).first
            await locator.triple_click()  # Select all
            await locator.type(str(quantity), delay=0)
            logger.info(f"[FORM] ✏️  Jumlah diset ke: {quantity}")
            return True
        except Exception as e:
            logger.error(f"[FORM] ❌ Gagal mengisi quantity: {e}")
            return False
