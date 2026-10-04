"""Which registered tool a routed step runs. Phase A keeps today's routing (route label plus the question's shape);
phase B replaces this with the planner naming tools directly."""

from medynium_api.features.copilot.handlers import Ctx
from medynium_api.features.copilot.handlers.lookup import CHANGED, classify
from medynium_api.features.copilot.tools import Tool, get


def resolve(ctx: Ctx) -> Tool:
    route = ctx.step.route
    if route == "lookup":
        kind = classify(ctx.question)
        if kind == "CHANGED":
            return get("detect_changes")
        if kind:
            ctx.step = ctx.step.model_copy(update={"params": {**ctx.step.params, "kind": kind}})
            return get("get_patient_record")
        return get("query_structured")
    if route == "analyst":
        if CHANGED.search(ctx.question):
            return get("detect_changes")
        if (
            classify(ctx.question) == "UTIL"
        ):  # visit and claim counts have a fixed, checked read model; use it
            ctx.step = ctx.step.model_copy(update={"params": {**ctx.step.params, "kind": "UTIL"}})
            return get("get_patient_record")
        return get("query_structured")
    if route == "knowledge":
        return get("lookup_label_live" if ctx.step.params.get("live") else "search_labels")
    if route == "panel":  # one answer for the whole set of panel calls the step carries
        return get("list_my_patients")
    return get("run_safety_review")
