"""轻量运行指标：进程内计数器与直方图，``/api/metrics`` 输出 Prometheus 文本。

只采集运行状态（请求量、延迟、失败、队列长度、编译耗时），
**不采集 token 用量或费用**——这是项目的明确非目标。
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import defaultdict
from collections.abc import AsyncIterator

# 延迟直方图桶（秒）。覆盖 LLM 冷启动的长尾。
LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)


class _Histogram:
    __slots__ = ("buckets", "counts", "count", "total")

    def __init__(self) -> None:
        self.buckets = LATENCY_BUCKETS
        self.counts = [0] * len(self.buckets)
        self.count = 0
        self.total = 0.0

    def observe(self, value: float) -> None:
        value = max(0.0, float(value))
        self.count += 1
        self.total += value
        for i, edge in enumerate(self.buckets):
            if value <= edge:
                self.counts[i] += 1


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._histograms: dict[
            tuple[str, tuple[tuple[str, str], ...]], _Histogram
        ] = {}

    @staticmethod
    def _labels(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((str(k), str(v)) for k, v in (labels or {}).items()))

    def inc(
        self, name: str, labels: dict[str, str] | None = None, amount: float = 1.0
    ) -> None:
        key = (name, self._labels(labels))
        with self._lock:
            self._counters[key] += float(amount)

    def observe(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        key = (name, self._labels(labels))
        with self._lock:
            hist = self._histograms.get(key)
            if hist is None:
                hist = self._histograms[key] = _Histogram()
            hist.observe(value)

    @staticmethod
    def _render_labels(labels: tuple[tuple[str, str], ...], extra: str = "") -> str:
        items = [f'{k}="{v}"' for k, v in labels]
        if extra:
            items.append(extra)
        return "{" + ",".join(items) + "}" if items else ""

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            counters = sorted(self._counters.items())
            histograms = sorted(self._histograms.items())
        typed_counters: set[str] = set()
        typed_histograms: set[str] = set()
        for (name, labels), value in counters:
            if name not in typed_counters:
                lines.append(f"# TYPE {name} counter")
                typed_counters.add(name)
            lines.append(f"{name}{self._render_labels(labels)} {value:g}")
        for (name, labels), hist in histograms:
            base = name
            if not base.endswith("_seconds"):
                base = f"{base}_seconds"
            if base not in typed_histograms:
                lines.append(f"# TYPE {base} histogram")
                typed_histograms.add(base)
            for edge, count in zip(hist.buckets, hist.counts):
                lines.append(
                    f"{base}_bucket{self._render_labels(labels, f'le=\"{edge:g}\"')} {count}"
                )
            lines.append(
                f"{base}_bucket{self._render_labels(labels, 'le=\"+Inf\"')} {hist.count}"
            )
            lines.append(f"{base}_sum{self._render_labels(labels)} {hist.total:.6f}")
            lines.append(f"{base}_count{self._render_labels(labels)} {hist.count}")
        return "\n".join(lines) + ("\n" if lines else "")

    def snapshot(self) -> dict:
        """给健康页用的可读摘要。"""
        with self._lock:
            counters = {
                name: sum(v for (n, _), v in self._counters.items() if n == name)
                for name in {n for n, _ in self._counters}
            }
            histograms = {}
            for (name, labels), hist in self._histograms.items():
                if labels:
                    continue
                histograms[name] = {
                    "count": hist.count,
                    "avg_seconds": round(hist.total / hist.count, 4) if hist.count else 0,
                    "max_bucket": hist.buckets[
                        max((i for i, c in enumerate(hist.counts) if c), default=0)
                    ],
                }
        return {"counters": counters, "histograms": histograms}


metrics = MetricsRegistry()


@contextlib.asynccontextmanager
async def llm_call(model: str) -> AsyncIterator[None]:
    """记录一次 LLM 调用的延迟与成败（不记录 token / 费用）。"""
    started = time.perf_counter()
    outcome = "error"
    try:
        yield
        outcome = "ok"
    finally:
        metrics.observe(
            "kiwi_llm_latency_seconds",
            time.perf_counter() - started,
            {"model": model or "unknown"},
        )
        metrics.inc(
            "kiwi_llm_requests_total",
            {"model": model or "unknown", "outcome": outcome},
        )


@contextlib.asynccontextmanager
async def compile_job() -> AsyncIterator[None]:
    """记录一次 Wiki 编译的耗时与结果。"""
    started = time.perf_counter()
    outcome = "error"
    try:
        yield
        outcome = "ok"
    finally:
        metrics.observe(
            "kiwi_compile_duration_seconds", time.perf_counter() - started
        )
        metrics.inc("kiwi_compile_total", {"outcome": outcome})


__all__ = ["compile_job", "llm_call", "metrics"]
