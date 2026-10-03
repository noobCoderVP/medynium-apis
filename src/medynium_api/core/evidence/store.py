"""Persist and read answers and their evidence under the caller's role (A-7, NFR-05).

ANSWER and ANSWER_EVIDENCE carry the own-rows-and-entitled policy, so a user can only ever read their own answers
for patients they are still entitled to; anything else is simply not found.
"""

import json
from typing import Any

from medynium_api.core.evidence.models import (
    AnswerObject,
    EvidenceBundle,
    EvidenceResponse,
    PatientEvidence,
    RouteInfo,
    SourceEvidence,
    SqlEvidence,
)
from medynium_api.core.session import Session
from medynium_api.core.snowflake.queries import fetch_all, fetch_one, json_value
from medynium_api.core.snowflake.role_session import user_cursor


def save_answer(
    session: Session,
    answer: AnswerObject,
    bundle: EvidenceBundle,
    *,
    question: str | None,
    model: str | None,
    prompt_hash: str | None,
    dropped: list[dict[str, str]],
) -> None:
    route = answer.route
    with user_cursor(session.snowflake_role) as cur:
        cur.execute(
            "INSERT INTO ANALYTICS.ANSWER (ANSWER_ID, PATIENT_ID, USER_ID, KIND, QUESTION, ROUTE, MODEL, CONFIDENCE, PROMPT_HASH, "
            "ANSWER_JSON, DROPPED_STATEMENTS, CREATED_AT) SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, PARSE_JSON(%s), PARSE_JSON(%s), SYSDATE()",
            (answer.answer_id, answer.patient_id, session.user_id, answer.kind, question, route.route if route else None,
             model, route.confidence if route else None, prompt_hash, answer.model_dump_json(), json.dumps(dropped)),
        )  # fmt: skip
        rows: list[tuple[Any, ...]] = []

        def text(value: Any) -> str | None:
            return None if value is None else str(value)

        for p in bundle.patient_records:
            rows.append((answer.answer_id, p.evidence_id, session.user_id, answer.patient_id, "PATIENT_RECORD", p.record_type,
                         p.record_id, p.table, text(p.date), p.value, None, None, None, None, None, None, None, None))  # fmt: skip
        for q in bundle.sql:
            rows.append((answer.answer_id, q.sql_id, session.user_id, answer.patient_id, "SQL", None, None, None, None, None,
                         q.text, q.role, text(q.row_count), text(q.ran_at), None, None, None, None))  # fmt: skip
        for src in bundle.sources:
            snapshot = json.dumps(
                {"title": src.title, "source": src.source, "section": src.section, "version": src.version,
                 "effective_date": str(src.effective_date or ""), "retrieved_date": str(src.retrieved_date or ""), "text": src.text}
            )  # fmt: skip
            rows.append((answer.answer_id, src.evidence_id, session.user_id, answer.patient_id, "SOURCE_CHUNK", None, None, None,
                         None, None, None, None, None, None, src.chunk_id, src.document_id, snapshot, "true" if src.matched else "false"))  # fmt: skip
        if rows:  # one round trip for all evidence rows
            marks = ", ".join(["(" + ", ".join(["%s"] * 18) + ")"] * len(rows))
            cur.execute(
                "INSERT INTO ANALYTICS.ANSWER_EVIDENCE (ANSWER_ID, EVIDENCE_ID, USER_ID, PATIENT_ID, EVIDENCE_KIND, RECORD_TYPE, RECORD_ID, "
                "RECORD_TABLE, RECORD_DATE, VALUE_TEXT, SQL_TEXT, SQL_ROLE, ROW_COUNT, RAN_AT, CHUNK_ID, DOCUMENT_ID, SOURCE_SNAPSHOT, MATCHED) "
                "SELECT column1::VARCHAR, column2::VARCHAR, column3::VARCHAR, column4::VARCHAR, column5::VARCHAR, column6::VARCHAR, "
                "column7::VARCHAR, column8::VARCHAR, TRY_TO_DATE(column9::VARCHAR), column10::VARCHAR, column11::VARCHAR, "
                "column12::VARCHAR, TRY_TO_NUMBER(column13::VARCHAR), TRY_TO_TIMESTAMP_NTZ(column14::VARCHAR), column15::VARCHAR, "
                "column16::VARCHAR, TRY_PARSE_JSON(column17::VARCHAR), "
                f"TRY_TO_BOOLEAN(column18::VARCHAR) FROM VALUES {marks}",
                [value for row in rows for value in row],
            )


def load_evidence(session: Session, answer_id: str) -> EvidenceResponse | None:
    with user_cursor(session.snowflake_role) as cur:
        head = fetch_one(
            cur,
            "SELECT ANSWER_ID, PATIENT_ID, CREATED_AT, ROUTE, MODEL, CONFIDENCE, ANSWER_JSON, DROPPED_STATEMENTS "
            "FROM ANALYTICS.ANSWER WHERE ANSWER_ID = %s",
            (answer_id,),
        )
        if not head:
            return None
        rows = fetch_all(
            cur,
            "SELECT * FROM ANALYTICS.ANSWER_EVIDENCE WHERE ANSWER_ID = %s ORDER BY EVIDENCE_ID",
            (answer_id,),
        )
    answer = json_value(head["answer_json"]) or {}
    bundle = EvidenceBundle()
    for r in rows:
        if r["evidence_kind"] == "PATIENT_RECORD":
            bundle.patient_records.append(PatientEvidence(
                evidence_id=r["evidence_id"], record_type=r["record_type"] or "", record_id=r["record_id"],
                table=r["record_table"] or "", value=r["value_text"] or "", date=r["record_date"]))  # fmt: skip
        elif r["evidence_kind"] == "SQL":
            bundle.sql.append(SqlEvidence(
                sql_id=r["evidence_id"], role=r["sql_role"] or "", text=r["sql_text"] or "",
                row_count=int(r["row_count"] or 0), ran_at=r["ran_at"]))  # fmt: skip
        else:
            snap = json_value(r["source_snapshot"]) or {}
            bundle.sources.append(SourceEvidence(
                evidence_id=r["evidence_id"], chunk_id=r["chunk_id"], document_id=r["document_id"], title=snap.get("title", ""),
                source=snap.get("source", ""), section=snap.get("section", ""), version=snap.get("version"),
                effective_date=snap.get("effective_date") or None, retrieved_date=snap.get("retrieved_date") or None,
                text=snap.get("text", ""), matched=bool(r["matched"])))  # fmt: skip
    statement_map = {
        c["id"]: [*c.get("patient_evidence", []), *c.get("source_evidence", [])]
        for c in answer.get("considerations", [])
    }
    route = RouteInfo(route=head["route"], model=head["model"], confidence=float(head["confidence"]) if head["confidence"] is not None else None) if head["route"] else None  # fmt: skip
    limits = answer.get("limits") or {}
    return EvidenceResponse(
        answer_id=head["answer_id"], patient_id=head["patient_id"], created_at=head["created_at"], route=route,
        patient_records=bundle.patient_records, sql=bundle.sql, sources=bundle.sources, statement_map=statement_map,
        dropped_statements=json_value(head["dropped_statements"]) or [], snapshot_date=limits.get("snapshot_date"),
    )  # fmt: skip
