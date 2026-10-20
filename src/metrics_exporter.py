"""Prometheus 文本格式指标导出（零依赖）。

多实例部署时每个实例各自 `/metrics`，由 Prometheus 抓取后按 `instance` 聚合，
不在应用内做跨实例汇总——那会把监控系统的问题变成业务进程的问题。

只暴露能算准的指标：
- 请求数按 behavior/mode 分；
- 延迟直方图（秒）；
- 限流、幂等重放、检索降级次数；
- token 用量；金额只在配置了 `TOKEN_PRICE_PER_1K` 时计算，
  不内置任何供应商价格（价格会变，硬编码就是错误信息）。
"""
from __future__ import annotations

import os
import socket
import threading
from collections import defaultdict

DEFAULT_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")


def _labels(pairs: dict | None) -> str:
    if not pairs:
        return ""
    inner = ",".join(f'{k}="{_escape(v)}"' for k, v in sorted(pairs.items()))
    return "{" + inner + "}"


class Metrics:
    def __init__(self, enabled: bool = True, service: str = "doc-qa"):
        self.enabled = bool(enabled)
        self.service = service
        self.instance = f"{socket.gethostname()}:{os.getpid()}"
        self._counters: dict[tuple[str, tuple], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple], float] = {}
        self._hist: dict[tuple[str, tuple], dict] = {}
        self._lock = threading.Lock()

    def inc(self, name: str, labels: dict | None = None, value: float = 1.0) -> None:
        if not self.enabled:
            return
        key = (name, tuple(sorted((labels or {}).items())))
        with self._lock:
            self._counters[key] += value

    def set_gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        if not self.enabled:
            return
        key = (name, tuple(sorted((labels or {}).items())))
        with self._lock:
            self._gauges[key] = float(value)

    def observe(self, name: str, value: float, labels: dict | None = None) -> None:
        if not self.enabled:
            return
        key = (name, tuple(sorted((labels or {}).items())))
        with self._lock:
            row = self._hist.get(key)
            if row is None:
                row = {"buckets": [0] * len(DEFAULT_BUCKETS), "sum": 0.0, "count": 0}
                self._hist[key] = row
            for i, bound in enumerate(DEFAULT_BUCKETS):
                if value <= bound:
                    row["buckets"][i] += 1
            row["sum"] += float(value)
            row["count"] += 1

    def render(self) -> str:
        if not self.enabled:
            return ""
        lines: list[str] = []
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            hist = {k: {"buckets": list(v["buckets"]), "sum": v["sum"], "count": v["count"]}
                    for k, v in self._hist.items()}

        by_name: dict[str, list] = defaultdict(list)
        for (name, labels), value in counters.items():
            by_name[name].append((dict(labels), value))
        for name in sorted(by_name):
            lines.append(f"# TYPE {name} counter")
            for labels, value in sorted(by_name[name], key=lambda x: sorted(x[0].items())):
                lines.append(f"{name}{_labels(labels)} {value:g}")

        for name in sorted({k[0] for k in gauges}):
            lines.append(f"# TYPE {name} gauge")
            for (gname, labels), value in gauges.items():
                if gname == name:
                    lines.append(f"{name}{_labels(dict(labels))} {value:g}")

        for name in sorted({k[0] for k in hist}):
            lines.append(f"# TYPE {name} histogram")
            for (hname, labels), row in hist.items():
                if hname != name:
                    continue
                base = dict(labels)
                cumulative = 0
                for bound, count in zip(DEFAULT_BUCKETS, row["buckets"]):
                    cumulative = count  # 已按「<= bound」累计
                    lines.append(f"{name}_bucket{_labels({**base, 'le': f'{bound:g}'})} {cumulative}")
                lines.append(f"{name}_bucket{_labels({**base, 'le': '+Inf'})} {row['count']}")
                lines.append(f"{name}_sum{_labels(base)} {row['sum']:.6f}")
                lines.append(f"{name}_count{_labels(base)} {row['count']}")
        return "\n".join(lines) + ("\n" if lines else "")
