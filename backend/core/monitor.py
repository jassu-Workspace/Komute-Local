"""Runtime monitoring: engine activity, per-step timing statistics, and a 1-second system sampler.

No personal data is recorded: no request ids, names, images or barcode text. Only counts, timings and sizes.
"""
from __future__ import annotations

import os
import platform
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone

import psutil

MB = 1_048_576


class _Stat:
    __slots__ = ("count", "total", "last", "min", "max")

    def __init__(self) -> None:
        self.count, self.total, self.last, self.min, self.max = 0, 0.0, 0.0, float("inf"), 0.0

    def add(self, ms: float) -> None:
        self.count += 1
        self.total += ms
        self.last = ms
        self.min = min(self.min, ms)
        self.max = max(self.max, ms)

    def view(self) -> dict:
        if not self.count:
            return {"count": 0}
        return {"count": self.count, "last_ms": round(self.last, 1), "mean_ms": round(self.total / self.count, 1),
                "min_ms": round(self.min, 1), "max_ms": round(self.max, 1)}


class EngineMonitor:
    """What the engine is doing now, and aggregate statistics since start. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at = datetime.now(timezone.utc)
        self._busy_since: float | None = None
        self._stage: str | None = None
        self._stage_since: float | None = None
        self._counts = {"verifications": 0, "approved": 0, "rejected": 0, "errors": 0}
        self._steps: dict[str, _Stat] = {}
        self._last: dict | None = None

    def begin(self) -> None:
        with self._lock:
            self._busy_since = self._stage_since = time.monotonic()
            self._stage = "decode"

    def stage(self, name: str) -> None:
        with self._lock:
            self._stage, self._stage_since = name, time.monotonic()

    def done(self, response: dict, step_ms: dict[str, float]) -> None:
        """Record a finished verification. `step_ms` holds per-step timings such as face.detect or vehicle.ocr."""
        timings = response.get("timings_ms") or {}
        trace = response.get("memory_trace") or {}
        with self._lock:
            self._counts["verifications"] += 1
            self._counts["approved" if response.get("decision") == "APPROVED" else "rejected"] += 1
            stages = response.get("stages") or {}
            for name, ms in timings.items():
                if name in stages and not stages[name].get("ran"):
                    continue  # a skipped stage is not a 0 ms run
                self._steps.setdefault(f"stage.{name}", _Stat()).add(float(ms))
            for name, ms in step_ms.items():
                self._steps.setdefault(name, _Stat()).add(float(ms))
            self._last = {
                "finished_at": datetime.now(timezone.utc).isoformat(), "decision": response.get("decision"),
                "reasons": [r.get("code") for r in response.get("reasons") or []],
                "total_ms": timings.get("total"), "timings_ms": timings, "step_ms": step_ms,
                "rss_start_mb": trace.get("start_mb"), "rss_peak_mb": trace.get("peak_mb"), "rss_end_mb": trace.get("end_mb"),
            }
            self._idle()

    def failed(self) -> None:
        with self._lock:
            self._counts["errors"] += 1
            self._idle()

    def abandon(self) -> None:
        """An input error or replay: not a verification, just go idle."""
        with self._lock:
            self._idle()

    def _idle(self) -> None:
        self._busy_since = self._stage = self._stage_since = None

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            return {
                "busy": self._busy_since is not None,
                "stage": self._stage,
                "busy_for_ms": round((now - self._busy_since) * 1000, 1) if self._busy_since else None,
                "stage_for_ms": round((now - self._stage_since) * 1000, 1) if self._stage_since else None,
                "counts": dict(self._counts),
                "steps": {k: v.view() for k, v in sorted(self._steps.items())},
                "last": self._last,
            }


def _versions() -> dict:
    out = {"python": sys.version.split()[0], "psutil": psutil.__version__}
    for mod, key in (("onnxruntime", "onnxruntime"), ("cv2", "opencv"), ("numpy", "numpy"), ("fastapi", "fastapi"),
                     ("uvicorn", "uvicorn"), ("zxingcpp", "zxing-cpp")):
        try:
            out[key] = getattr(__import__(mod), "__version__", "unknown")
        except Exception:  # a missing optional module must not break monitoring
            out[key] = None
    return out


def _cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    elif sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def static_info() -> dict:
    """Facts that do not change while the process runs. Computed once."""
    freq = psutil.cpu_freq()
    vm = psutil.virtual_memory()
    return {
        "os": f"{platform.system()} {platform.release()}", "os_version": platform.version(),
        "machine": platform.machine(), "cpu_model": _cpu_name(),
        "cpu_physical_cores": psutil.cpu_count(logical=False), "cpu_logical_cores": psutil.cpu_count(logical=True),
        "cpu_max_mhz": round(freq.max, 0) if freq and freq.max else None,
        "ram_total_mb": round(vm.total / MB, 1),
        "boot_time": datetime.fromtimestamp(psutil.boot_time(), timezone.utc).isoformat(),
        "pid": os.getpid(), "versions": _versions(),
        "thread_env": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "ORT_INTRA_OP_NUM_THREADS", "ORT_INTER_OP_NUM_THREADS",
                                                       "OPENCV_IO_MAX_IMAGE_PIXELS")},
    }


class SystemSampler:
    """Samples CPU, memory, disk and process figures every `interval_s` into a ring buffer.

    This is the only caller of the psutil CPU-percent counters, so readings are not disturbed by page polls.
    """

    def __init__(self, storage_root: str | os.PathLike, interval_s: float = 1.0, history: int = 900) -> None:
        self._root = str(storage_root)
        self._interval = interval_s
        self._proc = psutil.Process()
        self._hist: deque[dict] = deque(maxlen=history)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = time.monotonic()
        self._peak_rss = 0.0
        self._prev_io = None  # (monotonic time, io counters)
        self.static = static_info()
        self._proc.cpu_percent(None)
        psutil.cpu_percent(None, percpu=True)

    def start(self) -> "SystemSampler":
        self._take()
        self._thread = threading.Thread(target=self._loop, name="komute-sysmon", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._take()
            except Exception:  # a failed sample must never stop the sampler
                pass

    def _take(self) -> None:
        p = self._proc
        now = time.monotonic()
        with p.oneshot():
            mi = p.memory_info()
            cpu_proc = p.cpu_percent(None)
            ct = p.cpu_times()
            threads = p.num_threads()
            handles = p.num_handles() if hasattr(p, "num_handles") else p.num_fds()
            try:
                pio = p.io_counters()
            except (psutil.AccessDenied, AttributeError):
                pio = None
        per_core = psutil.cpu_percent(None, percpu=True)
        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        freq = psutil.cpu_freq()
        rss = mi.rss / MB
        peak_os = getattr(mi, "peak_wset", None)
        if peak_os is None and sys.platform.startswith("linux"):
            import resource

            peak_os = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        self._peak_rss = max(self._peak_rss, rss)
        io_rate = None
        if pio is not None and self._prev_io is not None:
            dt = now - self._prev_io[0]
            if dt > 0:
                io_rate = {"read_kb_s": round((pio.read_bytes - self._prev_io[1].read_bytes) / 1024 / dt, 1),
                           "write_kb_s": round((pio.write_bytes - self._prev_io[1].write_bytes) / 1024 / dt, 1)}
        if pio is not None:
            self._prev_io = (now, pio)
        try:
            du = psutil.disk_usage(self._root)
            disk = {"path": self._root, "total_gb": round(du.total / 1e9, 2), "used_gb": round(du.used / 1e9, 2),
                    "free_gb": round(du.free / 1e9, 2), "percent": du.percent}
        except OSError:
            disk = {"path": self._root, "error": "unavailable"}
        logical = len(per_core) or 1
        sample = {
            "t": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "uptime_s": round(now - self._t0, 1),
            "cpu": {
                "system_percent": round(sum(per_core) / logical, 1), "per_core_percent": per_core,
                "process_percent": round(cpu_proc, 1),  # 100 = one full core
                "process_percent_of_machine": round(cpu_proc / logical, 1),
                "freq_mhz": round(freq.current, 0) if freq else None,
                "process_user_s": round(ct.user, 2), "process_system_s": round(ct.system, 2),
            },
            "memory": {
                "process_rss_mb": round(rss, 1), "process_vms_mb": round(mi.vms / MB, 1),
                "process_private_mb": round(getattr(mi, "private", 0) / MB, 1) if hasattr(mi, "private") else None,
                "process_peak_rss_mb": round(max(self._peak_rss, (peak_os or 0) / MB), 1),
                "process_page_faults": getattr(mi, "num_page_faults", None),
                "system_used_mb": round((vm.total - vm.available) / MB, 1), "system_available_mb": round(vm.available / MB, 1),
                "system_percent": vm.percent,
                "swap_used_mb": round(sw.used / MB, 1), "swap_total_mb": round(sw.total / MB, 1), "swap_percent": sw.percent,
            },
            "process": {"threads": threads, "handles": handles,
                        "io_read_mb": round(pio.read_bytes / MB, 1) if pio else None,
                        "io_write_mb": round(pio.write_bytes / MB, 1) if pio else None, "io_rate": io_rate},
            "disk": disk,
        }
        with self._lock:
            self._hist.append(sample)

    def latest(self) -> dict | None:
        with self._lock:
            return self._hist[-1] if self._hist else None

    def history(self) -> list[dict]:
        """Compact series for charts: [uptime_s, system cpu %, process cpu %, rss MB, system RAM %]."""
        with self._lock:
            return [[s["uptime_s"], s["cpu"]["system_percent"], s["cpu"]["process_percent_of_machine"],
                     s["memory"]["process_rss_mb"], s["memory"]["system_percent"]] for s in self._hist]
