"""Uniform latency for denied versus missing resources (SEC-05).

A policy-hidden row and a nonexistent row both return no rows, but a miss can still return a little faster than
a hit. `pad(started)` waits out the rest of a small floor so a miss is not distinguishable by speed.
"""

import time

FLOOR_SECONDS = 0.35


def pad(started: float, floor: float = FLOOR_SECONDS) -> None:
    remaining = floor - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)
