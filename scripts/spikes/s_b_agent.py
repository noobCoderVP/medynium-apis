"""Spike S-A step 5 and S-B: Cortex Agent run under a per-user role. Reuses scratch objects of s_b_cortex_rest."""

import json
import sys
import time

import httpx
from _common import admin
from s_b_cortex_rest import HOST, headers

SPEC = """
models:
  orchestration: claude-sonnet-4-6
instructions:
  response: "Answer briefly. Use only tool results."
  orchestration: "Use the patients tool for any question about patients."
tools:
  - tool_spec:
      type: "cortex_analyst_text_to_sql"
      name: "patients"
      description: "Patient names and eGFR values"
tool_resources:
  patients:
    semantic_view: "MEDYNIUM.SPIKE.PAT_SV"
    execution_environment:
      type: "warehouse"
      warehouse: "MEDYNIUM_WH"
"""


def main() -> None:
    cur = admin().cursor()
    cur.execute(f"CREATE OR REPLACE AGENT MEDYNIUM.SPIKE.SPIKE_AGENT FROM SPECIFICATION $${SPEC}$$")
    cur.execute("GRANT USAGE ON AGENT MEDYNIUM.SPIKE.SPIKE_AGENT TO ROLE MED_DOCTOR")
    url = f"https://{HOST}/api/v2/databases/MEDYNIUM/schemas/SPIKE/agents/SPIKE_AGENT:run"
    for role in ("U_SPIKE_A", "U_SPIKE_B"):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "List every patient name you can see."}],
                }
            ]
        }
        h = headers(role)
        h["Accept"] = "text/event-stream"
        started = time.time()
        events: list[tuple[str, str]] = []
        with httpx.stream("POST", url, headers=h, json=body, timeout=120) as r:
            print(f"agent {role}: HTTP {r.status_code}")
            if r.status_code != 200:
                print(r.read().decode()[:600])
                continue
            event = ""
            for line in r.iter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    events.append((event, line[5:].strip()))
        print(
            f"  {len(events)} events in {time.time() - started:.1f}s; types:",
            sorted({e for e, _ in events}),
        )
        text = "".join(
            json.loads(d).get("text", "")
            for e, d in events
            if e == "response.text.delta" and d.startswith("{")
        )
        print("  final text:", text[:300].replace("\n", " "))
        for e, d in events:
            if e in ("response.tool_result", "response.status") or "sql" in d.lower()[:200]:
                print("  ", e, d[:300].replace("\n", " "))
                break


if __name__ == "__main__":
    sys.exit(main())
