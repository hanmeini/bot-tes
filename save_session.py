"""
save_session.py — Utilitas Sekali-Pakai untuk Generate cookies.json / storage_state.json
Jalankan SEKALI setelah login manual, lalu bot utama bisa pakai session tersebut.

Cara pakai:
  python save_session.py
  → Login manual di browser yang terbuka
  → Tekan Enter di terminal
  → File storage_state.json akan tersimpan otomatis
"""

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


async def save_session_interactive():
    print("=" * 50)
    print("  SESSION SAVER — Login Manual Helper")
    print("=" * 50)

    # Baca config
    cfg_path = Path("config.json")
    if cfg_path.exists():
        with open(cfg_path) as f:
            config = json.load(f)
        base_url = config["target"]["base_url"]
        storage_file = config["session"]["storage_state_file"]
        headless = False
    else:
        base_url = "https://www.tokopedia.com"
        storage_file = "storage_state.json"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(base_url)

        print(f"\n➡️  Browser dibuka di: {base_url}")
        print("➡️  Silakan login secara manual di browser...")
        print("➡️  Setelah berhasil login, kembali ke sini dan tekan Enter.\n")
        input("   [Tekan Enter setelah login] > ")

        # Simpan state
        state = await context.storage_state()
        with open(storage_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Session tersimpan di: {storage_file}")
        print(f"   Total cookies: {len(state.get('cookies', []))}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(save_session_interactive())
