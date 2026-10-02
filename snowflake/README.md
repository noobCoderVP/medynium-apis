# snowflake/

Idempotent setup SQL, numbered in run order (`00_bootstrap.sql`, `01_schemas.sql`, ...). `00_bootstrap.sql` is run by a person as ACCOUNTADMIN; the rest run as `MED_ADMIN`. Nothing here is executed by the deployed API.

Empty until Slice 0. See [../docs/external-dependencies.md](../docs/external-dependencies.md).
