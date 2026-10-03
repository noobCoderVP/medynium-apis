# Access and safety checks (Q-2, Q-3)

Each check from `07-quality-and-evals.md` section 3, the test that proves it, and where the evidence is. Tests marked live run against the real Snowflake account as the seeded users (`poetry run poe test:int`). The last full live run is recorded in [test-report.md](test-report.md).

## Access

| ID | Check | Test | Kind | Status |
| --- | --- | --- | --- | --- |
| Q-A1 | Assistant denied S3 in SQL | `test_access_sql.py::test_assistant_sees_nothing_of_s3_in_any_table` (seven tables) | live | pass |
| Q-A2 | Denied equals missing in the API: 404, identical body, similar latency | `test_patients.py::test_denied_is_byte_identical_to_missing` (eight paths), `::test_denied_and_missing_take_similar_time` (median within 0.25 s) | live | pass |
| Q-A3 | Denied through the assistant, audited | `test_copilot.py::test_s3_is_denied_to_the_assistant_on_every_route_with_identical_responses` (ask, safety review, two actions, audit outcome `DENIED`); golden case G08 | live | pass |
| Q-A4 | Cross-doctor isolation | `test_access_sql.py::test_doctors_are_isolated_from_each_other`, `test_patients.py::test_other_doctors_patient_is_also_not_found` | live | pass |
| Q-A5 | No role leakage under load | `test_access_sql.py::test_no_role_leakage_under_concurrent_load`: 200 alternating requests from two roles on 8 threads, plus the sequential `test_role_switch_leaks_nothing_between_requests` | live | pass |
| Q-A6 | Policy coverage on every patient-keyed table | `poe db:check` (`snowflake/90_checks.sql`, 17 checks) | live | pass at last run |
| Q-A7 | Least privilege | `tests/test_architecture.py::test_no_runtime_code_uses_the_admin_role_or_setup_credentials`; `test_access_sql.py::test_service_role_alone_cannot_read_patient_data`, `::test_an_unknown_role_is_refused`. **Not written:** the listing of effective grants per role compared with the reviewed table | unit and live | partly done |

## Safety

| ID | Check | Test | Kind | Status |
| --- | --- | --- | --- | --- |
| Q-S1 | Allowlist | `test_copilot.py::test_an_unlisted_action_is_refused_and_audited`; `test_router_is_not_a_boundary.py::test_an_action_outside_the_list_is_refused_even_when_the_router_proposes_it` | live | pass |
| Q-S2 | Injection not followed, not echoed | Golden G10, [injection set](../../evals/injection_set.yaml) I01 to I12 (report: [injection-report.md](injection-report.md)); `test_copilot.py::test_the_injected_instruction_is_ignored_and_not_echoed`. **Not covered:** payloads planted in label (chunk) text | live | see report |
| Q-S3 | Refusal: prescribing, dosing, cross-patient, record change | `test_copilot.py::test_refusals_are_decided_by_server_rules_whatever_the_router_says` (five prompts), `::test_prescribing_refusal_still_shows_documented_considerations`; golden G11, G12 | live | pass |
| Q-S4 | The router is not a boundary | `test_router_is_not_a_boundary.py` (router forced to say `lookup` for a denied patient, `open_patient` for a denied name, an unlisted action); `test_copilot.py::test_router_failure_treats_a_request_as_a_question_never_an_action` | live | pass |
| Q-S5 | Streamed steps equal the audit row | `test_copilot.py::test_the_stream_shows_real_steps_and_they_equal_the_audit_entry` | live | pass |
| Q-S6 | No secrets, tokens, patient names or question text in logs | `test_logs_are_clean.py::test_logs_hold_no_secrets_names_or_question_text` (failed sign-in, sign-in, a question, a patient read, a missing patient; checks passwords, the access token, a patient name, the question, any JWT shape, argon2 hashes) | live | pass |

## What this does and does not prove

- The access checks prove the row access policies and the API's 404 behaviour for the seeded scenarios. They do not prove every future table is covered: that is what `db:check` Q-A6 is for, and it should run after every data change.
- The injection and refusal checks are behavioural: they show these prompts were handled safely on these runs. A model can behave differently on the next phrasing, which is why the server rules (guard, allowlist, entitlement, validator) do not depend on the model and are tested with the router forced wrong.
