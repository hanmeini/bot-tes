"""
utils/user_agent.py — Generator string User-Agent acak yang realistis.
Meniru distribusi browser nyata untuk menghindari deteksi pola UA statis.
"""

import random
import string


# ── Database UA komponen ─────────────────────────────────────────────────────

_CHROME_VERSIONS = [
    "124.0.0.0", "125.0.0.0", "126.0.0.0",
    "127.0.0.0", "128.0.0.0", "129.0.0.0", "130.0.0.0",
]

_WINDOWS_VERSIONS = [
    "Windows NT 10.0; Win64; x64",
    "Windows NT 10.0; WOW64",
    "Windows NT 11.0; Win64; x64",
]

_MACOS_VERSIONS = [
    "Macintosh; Intel Mac OS X 10_15_7",
    "Macintosh; Intel Mac OS X 11_0_0",
    "Macintosh; Intel Mac OS X 13_0_0",
]

_LINUX_VERSIONS = [
    "X11; Linux x86_64",
    "X11; Ubuntu; Linux x86_64",
]

_ANDROID_VERSIONS = [
    "Linux; Android 13; Pixel 7",
    "Linux; Android 14; SM-S918B",
    "Linux; Android 12; M2102J20SG",
]

_FIREFOX_VERSIONS = ["126.0", "127.0", "128.0", "129.0", "130.0"]

_SAFARI_VERSIONS = ["605.1.15", "604.1", "537.36"]

_PLATFORMS = {
    "windows": _WINDOWS_VERSIONS,
    "macos":   _MACOS_VERSIONS,
    "linux":   _LINUX_VERSIONS,
    "android": _ANDROID_VERSIONS,
}


# ── Generators ───────────────────────────────────────────────────────────────

def random_chrome_ua(platform: str = "windows") -> str:
    """
    Menghasilkan User-Agent Chrome yang realistis untuk platform tertentu.

    Args:
        platform: 'windows' | 'macos' | 'linux' | 'android'
    """
    plat_list = _PLATFORMS.get(platform, _WINDOWS_VERSIONS)
    plat = random.choice(plat_list)
    chrome_ver = random.choice(_CHROME_VERSIONS)

    if platform == "android":
        return (
            f"Mozilla/5.0 ({plat}) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome_ver} Mobile Safari/537.36"
        )
    return (
        f"Mozilla/5.0 ({plat}) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{chrome_ver} Safari/537.36"
    )


def random_firefox_ua(platform: str = "windows") -> str:
    """Menghasilkan User-Agent Firefox yang realistis."""
    plat_list = _PLATFORMS.get(platform, _WINDOWS_VERSIONS)
    plat = random.choice(plat_list)
    ff_ver = random.choice(_FIREFOX_VERSIONS)
    return f"Mozilla/5.0 ({plat}; rv:{ff_ver}) Gecko/20100101 Firefox/{ff_ver}"


def random_ua(prefer_platform: str = "windows") -> str:
    """
    Menghasilkan UA acak — 80% Chrome, 20% Firefox.
    Ini merefleksikan distribusi browser nyata di Indonesia.
    """
    if random.random() < 0.80:
        return random_chrome_ua(prefer_platform)
    return random_firefox_ua(prefer_platform)


def random_session_id(length: int = 32) -> str:
    """Menghasilkan session ID acak berformat hex (untuk header X-Session-Id)."""
    return "".join(random.choices(string.hexdigits.lower(), k=length))


def random_device_id() -> str:
    """Menghasilkan device ID acak berformat UUID v4."""
    def seg(n): return "".join(random.choices(string.hexdigits.lower(), k=n))
    return f"{seg(8)}-{seg(4)}-4{seg(3)}-{random.choice('89ab')}{seg(3)}-{seg(12)}"


def random_headers_extra() -> dict:
    """
    Menghasilkan sekumpulan HTTP header tambahan yang menyerupai browser nyata.
    Bisa dipakai untuk request langsung (httpx/requests) maupun diinjeksi via Playwright.
    """
    return {
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": random.choice(["id-ID,id;q=0.9,en-US;q=0.8", "id-ID,id;q=0.8,en;q=0.6"]),
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Sec-Fetch-Dest":  "document",
        "Sec-Fetch-Mode":  "navigate",
        "Sec-Fetch-Site":  "none",
        "Upgrade-Insecure-Requests": "1",
    }
