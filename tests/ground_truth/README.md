# Ground truth

Every number the product states is compared with a SQL file here, never with a value typed into a test (07 section 2). Each file restates the number from the raw `CLINICAL` tables, independently of the `ANALYTICS` read models that the API serves, and runs under the signed-in user's own role so the row access policy scopes it exactly as it scopes the app.

| File | Number | Compared with |
| --- | --- | --- |
| `worklist_size.sql` | Patients a user may see | `GET /dashboard` `utilization.patients`, as the doctor and as the assistant |
| `s1_utilization.sql` | S1 visits, procedures, billed and approved totals (trailing 365 days) | `GET /patients/{S1}` and `/claims` utilisation |
| `s1_egfr.sql` | S1 latest and previous eGFR | `GET /patients/{S1}` latest labs |
| `s1_active_medications.sql` | S1 active medicines | `GET /patients/{S1}/medications` |

`tests/integration/test_ground_truth.py` holds the registry. A shown number that is added to the registry without a file here fails `test_every_shown_number_has_a_ground_truth_file`, which runs without Snowflake. The comparisons themselves run with `poe test:int`.

To add a number: write the SQL here, add a row to `SHOWN_NUMBERS` and a comparison to the live test.
