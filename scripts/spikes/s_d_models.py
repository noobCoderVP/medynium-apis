"""Spike S-D: availability and latency of the router and strong models (SNOWFLAKE.CORTEX.COMPLETE)."""

import statistics
import time

from _common import admin

SHORT = "Reply with one word: OK"
LONG = "Write about 700 words explaining how kidney function is monitored in diabetes."


def timed(cur, model: str, prompt: str, max_tokens: int) -> float:
    started = time.time()
    cur.execute(
        "SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, [{'role':'user','content':%s}], {'max_tokens': %s, 'temperature': 0})",
        (model, prompt, max_tokens),
    )
    cur.fetchone()
    return time.time() - started


def main() -> None:
    cur = admin().cursor()
    cur.execute("USE WAREHOUSE MEDYNIUM_WH")
    cur.execute("SELECT 1")
    for model in ("llama3.1-8b", "claude-sonnet-4-6", "claude-haiku-4-5"):
        cold = timed(cur, model, SHORT, 10)
        warm = [timed(cur, model, SHORT, 10) for _ in range(4)]
        long = timed(cur, model, LONG, 1000)
        print(
            f"{model}: first {cold:.1f}s, short p50 {statistics.median(warm):.1f}s, 1000-token {long:.1f}s"
        )


if __name__ == "__main__":
    main()
