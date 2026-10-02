"""同步资源链统一使用的绝对 monotonic 截止时刻。"""

import time


def remaining(deadline: float | None, cap: float | None = None) -> float | None:
    if deadline is None:
        return cap
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("Spine 总预算已耗尽")
    return min(value, cap) if cap is not None else value


def from_budget(budget: float | None, deadline: float | None = None) -> float | None:
    if budget is None:
        return deadline
    local = time.monotonic() + max(0.0, budget)
    return min(local, deadline) if deadline is not None else local
