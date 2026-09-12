"""统一时钟。

必须用 perf_counter 而不是 monotonic：实测本机 time.monotonic() 的分辨率是
16 毫秒，而 time.perf_counter() 是 100 纳秒。耗时是观察目标之一，用 16ms
量化的时钟会让所有时长数据失真（几毫秒的调用会记成 0 或 16）。
墙上时钟仍用 time.time()，用于跨日志对齐，不用于算时长。
"""

import time


def now() -> float:
    return time.perf_counter()


def wall() -> float:
    return time.time()


def ms_since(t0: float) -> int:
    return round((now() - t0) * 1000)
