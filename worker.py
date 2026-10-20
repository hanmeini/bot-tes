"""
worker.py — Modul Concurrency / Worker untuk Skala Besar

Mengelola banyak akun atau request secara paralel menggunakan:
  - asyncio TaskGroup (Python 3.11+) / gather untuk multi-akun
  - Semaphore untuk membatasi konkurensi
  - Task Queue berbasis asyncio.Queue untuk distribusi kerja
  - Jitter delay untuk menghindari pola request yang identik antar worker

Arsitektur:
    WorkerPool
        ├── [Worker-1] akun_A → Browser → execute_purchase()
        ├── [Worker-2] akun_B → Browser → execute_purchase()
        └── [Worker-N] akun_N → Browser → execute_purchase()
    
    Semaphore → max N worker aktif bersamaan
    ResultAggregator → kumpulkan & ringkaskan semua hasil
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

from playwright.async_api import async_playwright, BrowserContext, Page

from auth import SessionManager
from browser import BrowserActions
from logger import get_logger

logger = get_logger("worker")


# ── Data Structures ───────────────────────────────────────────────────────────

@dataclass
class WorkerTask:
    """Satu unit pekerjaan yang akan dieksekusi oleh sebuah worker."""
    worker_id:    int
    account_name: str
    cookies_file: str
    product_url:  str
    config:       dict
    priority:     int = 0  # Angka lebih kecil = prioritas lebih tinggi


@dataclass
class WorkerResult:
    """Hasil eksekusi satu worker."""
    worker_id:    int
    account_name: str
    success:      bool
    step:         str
    error:        Optional[str]
    elapsed_ms:   float
    timestamp:    str = field(default_factory=lambda: time.strftime("%H:%M:%S"))


# ── Result Aggregator ─────────────────────────────────────────────────────────

class ResultAggregator:
    """Mengumpulkan dan meringkaskan hasil dari semua worker."""

    def __init__(self):
        self._results: list[WorkerResult] = []
        self._lock = asyncio.Lock()

    async def add(self, result: WorkerResult) -> None:
        async with self._lock:
            self._results.append(result)
            status = "✅ SUKSES" if result.success else "❌ GAGAL"
            logger.info(
                f"[RESULT] Worker-{result.worker_id} ({result.account_name}) "
                f"→ {status} | {result.elapsed_ms:.0f}ms | step={result.step}"
            )

    def summary(self) -> dict:
        """Meringkaskan semua hasil menjadi statistik."""
        total   = len(self._results)
        success = sum(1 for r in self._results if r.success)
        failed  = total - success
        avg_ms  = (
            sum(r.elapsed_ms for r in self._results) / total if total else 0
        )
        return {
            "total":       total,
            "success":     success,
            "failed":      failed,
            "success_rate": f"{success / total * 100:.1f}%" if total else "0%",
            "avg_ms":      f"{avg_ms:.0f}ms",
            "results":     [r.__dict__ for r in self._results],
        }

    def print_summary(self) -> None:
        s = self.summary()
        logger.info("=" * 60)
        logger.info(f"  📊 RINGKASAN SEMUA WORKER")
        logger.info(f"  Total   : {s['total']} worker")
        logger.info(f"  Sukses  : {s['success']} ({s['success_rate']})")
        logger.info(f"  Gagal   : {s['failed']}")
        logger.info(f"  Rata-rata eksekusi: {s['avg_ms']}")
        logger.info("=" * 60)


# ── Single Worker ──────────────────────────────────────────────────────────────

class BotWorker:
    """
    Satu unit worker yang mengelola satu browser + satu akun.
    Berjalan secara async dan independen dari worker lain.
    """

    def __init__(
        self,
        task: WorkerTask,
        aggregator: ResultAggregator,
        execute_fn: Callable,
        jitter_ms: tuple[int, int] = (0, 200),
    ):
        self.task        = task
        self.aggregator  = aggregator
        self.execute_fn  = execute_fn  # Fungsi execute_purchase dari main.py
        self.jitter_ms   = jitter_ms

    async def run(self) -> WorkerResult:
        """Menjalankan satu siklus pembelian penuh untuk satu akun."""
        t = self.task
        logger.info(
            f"[WORKER-{t.worker_id}] 🚀 Mulai | Akun: {t.account_name}"
        )

        # Jitter: sedikit delay acak agar pola click tidak identik
        jitter = random.randint(*self.jitter_ms) / 1000
        if jitter > 0:
            logger.debug(f"[WORKER-{t.worker_id}] Jitter: {jitter*1000:.0f}ms")
            await asyncio.sleep(jitter)

        start = time.perf_counter()
        result_data = {"success": False, "step": "init", "error": "Worker belum dieksekusi"}

        try:
            async with async_playwright() as pw:
                browser_cfg = t.config.get("browser", {})
                browser = await pw.chromium.launch(
                    headless=browser_cfg.get("headless", True),
                    args=["--disable-blink-features=AutomationControlled"],
                )

                # Override cookies file per-akun
                cfg_copy = dict(t.config)
                cfg_copy["session"] = dict(t.config.get("session", {}))
                cfg_copy["session"]["storage_state_file"] = t.cookies_file

                context: BrowserContext = await browser.new_context(
                    viewport=browser_cfg.get("viewport", {"width": 1366, "height": 768}),
                    locale=browser_cfg.get("locale", "id-ID"),
                    timezone_id=browser_cfg.get("timezone_id", "Asia/Jakarta"),
                )

                page: Page = await context.new_page()

                # Load session
                session_mgr = SessionManager(cfg_copy)
                await session_mgr.load_session(context)

                # Navigasi ke produk
                actions = BrowserActions(cfg_copy)
                await actions.navigate(page, t.product_url)
                actions.handle_dialog(page)

                # Eksekusi pembelian (fungsi dari main.py)
                result_data = await self.execute_fn(page, actions, cfg_copy)
                await browser.close()

        except Exception as exc:
            logger.error(f"[WORKER-{t.worker_id}] ❌ Exception: {exc}")
            result_data = {"success": False, "step": "exception", "error": str(exc)}

        elapsed = (time.perf_counter() - start) * 1000
        result = WorkerResult(
            worker_id=    t.worker_id,
            account_name= t.account_name,
            success=      result_data.get("success", False),
            step=         result_data.get("step", "unknown"),
            error=        result_data.get("error"),
            elapsed_ms=   elapsed,
        )
        await self.aggregator.add(result)
        return result


# ── Worker Pool ────────────────────────────────────────────────────────────────

class WorkerPool:
    """
    Mengelola banyak BotWorker secara paralel dengan Semaphore
    untuk membatasi jumlah browser yang aktif bersamaan.
    """

    def __init__(
        self,
        tasks: list[WorkerTask],
        execute_fn: Callable,
        max_concurrent: int = 3,
        jitter_ms: tuple[int, int] = (0, 500),
    ):
        self.tasks          = sorted(tasks, key=lambda t: t.priority)
        self.execute_fn     = execute_fn
        self.max_concurrent = max_concurrent
        self.jitter_ms      = jitter_ms
        self.aggregator     = ResultAggregator()
        self._semaphore     = asyncio.Semaphore(max_concurrent)

    async def _run_with_semaphore(self, worker: BotWorker) -> WorkerResult:
        async with self._semaphore:
            return await worker.run()

    async def run_all(self) -> ResultAggregator:
        """
        Menjalankan semua task secara paralel (dibatasi semaphore).
        Menunggu SEMUA selesai sebelum mengembalikan aggregator.
        """
        workers = [
            BotWorker(
                task=task,
                aggregator=self.aggregator,
                execute_fn=self.execute_fn,
                jitter_ms=self.jitter_ms,
            )
            for task in self.tasks
        ]

        logger.info(
            f"[POOL] 🏊 Memulai {len(workers)} worker "
            f"(max {self.max_concurrent} concurrent)..."
        )

        coroutines = [self._run_with_semaphore(w) for w in workers]
        await asyncio.gather(*coroutines, return_exceptions=True)

        self.aggregator.print_summary()
        return self.aggregator


# ── Task Queue (untuk skala sangat besar / streaming tasks) ──────────────────

class TaskQueue:
    """
    Antrian task async berbasis asyncio.Queue.
    Berguna jika task dihasilkan secara dinamis (bukan batch di awal).
    """

    def __init__(self, num_consumers: int = 3):
        self.queue      = asyncio.Queue()
        self.consumers  = num_consumers
        self.aggregator = ResultAggregator()

    async def enqueue(self, task: WorkerTask) -> None:
        await self.queue.put(task)

    async def _consumer(self, consumer_id: int, execute_fn: Callable) -> None:
        while True:
            try:
                task: WorkerTask = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.1)
                continue

            logger.info(f"[QUEUE] Consumer-{consumer_id} mengambil task: {task.account_name}")
            worker = BotWorker(task, self.aggregator, execute_fn)
            await worker.run()
            self.queue.task_done()

    async def start_consumers(self, execute_fn: Callable) -> None:
        """Menjalankan N consumer secara paralel sampai queue kosong."""
        consumers = [
            asyncio.create_task(self._consumer(i, execute_fn))
            for i in range(self.consumers)
        ]
        await self.queue.join()  # Tunggu semua item diproses
        for c in consumers:
            c.cancel()
        self.aggregator.print_summary()
