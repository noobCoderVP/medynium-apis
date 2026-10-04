#!/usr/bin/env python3
"""Deploy the Medynium API to Cloud Run from your machine.

Same flow as the HelperHub backend script:

    1. build the image with Cloud Build and push it to Artifact Registry
       (tagged ``manual-<UTC timestamp>``)
    2. roll it out to the ``medynium-api`` Cloud Run service with
       ``gcloud run deploy --image ...``

Env vars, secrets and the runtime service account already configured on the
Cloud Run service are left untouched; only the container image changes.
The very first time, add ``--setup`` to enable the APIs, create the registry,
service account and Secret Manager secrets, and set the service's env vars.

Every ``gcloud`` call streams its output straight to your terminal so you see
the full build/deploy logs, not a spinner.

Examples
--------
    python scripts/deploy.py --setup         # first time: bootstrap GCP, test, build, deploy
    python scripts/deploy.py                 # test -> build -> deploy
    python scripts/deploy.py --skip-tests    # skip pytest
    python scripts/deploy.py --source        # one step: gcloud run deploy --source .
    python scripts/deploy.py --no-build --tag manual-20261003120000   # redeploy an image (rollback)
    python scripts/deploy.py --dry-run       # print the commands, run nothing
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import NoReturn

# --- Defaults (override via flags) ---------------------------------------------
PROJECT = "helperhub-502206"
REGION = "asia-south1"  # closest to the Snowflake account
SERVICE = "medynium-api"
AR_REPO = "medynium"  # Artifact Registry repository
AR_IMAGE = "api"  # image name within the repository
RUNTIME_SA = f"medynium-api-sa@{PROJECT}.iam.gserviceaccount.com"
UI_URL = "https://medynium-ui.vercel.app"  # Vercel UI: CORS origin and base of emailed links

APIS = [
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
]
# Secret Manager name -> env var it is mounted as.
SECRETS = {
    "medynium-session-secret": "SESSION_SECRET",
    "medynium-snowflake-api-key-b64": "SNOWFLAKE_API_PRIVATE_KEY_B64",
}
RESEND_SECRET = ("medynium-resend-api-key", "RESEND_API_KEY")
# Plain settings copied from .env into the service on --setup.
PLAIN_FROM_ENV = [
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
    "ROUTER_MODEL",
    "STRONG_MODEL",
    "CORTEX_SEARCH_SERVICE",
    "CORTEX_SEMANTIC_VIEW",
    "CORTEX_AGENT",
    "ROUTER_CONFIDENCE_THRESHOLD",
    "ROUTER_TIMEOUT_SECONDS",
    "AGENT_TIMEOUT_SECONDS",
    "LOG_LEVEL",
    "REFRESH_COOKIE_PATH",
    "LOGIN_OTP_ENABLED",
    "EMAIL_FROM",
]
DEFAULT_KEY = Path.home() / ".medynium" / "keys" / "med_api_svc.p8"

BACKEND_DIR = Path(__file__).resolve().parent.parent

GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"


def _c(txt: str, colour: str) -> str:
    return f"{colour}{txt}{RESET}" if sys.stdout.isatty() else txt


def log(msg: str) -> None:
    print(_c(f"\n=== {msg} ===", GREEN), flush=True)


def die(msg: str, code: int = 1) -> NoReturn:
    print(_c(f"ERROR: {msg}", RED), file=sys.stderr, flush=True)
    raise SystemExit(code)


def run(
    cmd: list[str],
    *,
    dry_run: bool = False,
    capture: bool = False,
    cwd: Path | None = None,
    stdin: str | None = None,
    check: bool = True,
    show: str | None = None,
) -> str:
    """Run a command, streaming output live. Returns stdout when capture=True."""
    printable = show or " ".join(cmd)
    print(_c(f"$ {printable}", DIM), flush=True)
    if dry_run:
        return ""
    cwd_arg = str(cwd) if cwd else None
    if capture:
        res = subprocess.run(cmd, text=True, capture_output=True, cwd=cwd_arg, input=stdin)
        if res.returncode != 0 and check:
            sys.stderr.write(res.stdout)
            sys.stderr.write(res.stderr)
            die(f"command failed ({res.returncode}): {printable}", res.returncode)
        return res.stdout.strip() if res.returncode == 0 else ""
    res = subprocess.run(cmd, text=True, cwd=cwd_arg, input=stdin)
    if res.returncode != 0 and check:
        die(f"command failed ({res.returncode}): {printable}", res.returncode)
    return ""


def gcloud() -> str:
    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not exe:
        die("`gcloud` not found on PATH. Install the Google Cloud SDK first.")
    return exe


def read_env_file() -> dict[str, str]:
    path = BACKEND_DIR / ".env"
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.split(" #", 1)[0].strip().strip("\"'")
    return out


def preflight(project: str, dry_run: bool) -> None:
    log("Preflight")
    gc = gcloud()
    account = run([gc, "config", "get-value", "account"], capture=True) or ""
    active_project = run([gc, "config", "get-value", "project"], capture=True) or ""
    print(f"  account : {account or '(none)'}")
    print(f"  project : {active_project or '(none)'}  ->  deploying to: {project}")
    if not account or account == "(unset)":
        die("no active gcloud account. Run `gcloud auth login`.")
    if not dry_run and active_project and active_project != project:
        print(
            _c(
                f"  note: active gcloud project ({active_project}) != target ({project}); "
                f"--project is passed explicitly so this is fine.",
                YELLOW,
            )
        )


def current_image(gc: str, project: str, region: str, service: str) -> str:
    out = run(
        [
            gc,
            "run",
            "services",
            "describe",
            service,
            "--project",
            project,
            "--region",
            region,
            "--platform",
            "managed",
            "--format",
            "value(spec.template.spec.containers[0].image)",
        ],
        capture=True,
        check=False,
    )
    return out or "(service not found, first deploy?)"


def _exists(gc: str, *args: str) -> bool:
    return subprocess.run([gc, *args], capture_output=True, text=True).returncode == 0


def setup(gc: str, project: str, runtime_sa: str, dry_run: bool) -> None:
    """Idempotent first-time bootstrap: APIs, registry, service account, secrets."""
    log("Setup: APIs")
    run([gc, "services", "enable", *APIS, "--project", project], dry_run=dry_run)

    log("Setup: Artifact Registry")
    if not _exists(
        gc,
        "artifacts",
        "repositories",
        "describe",
        AR_REPO,
        "--project",
        project,
        "--location",
        REGION,
    ):
        run(
            [
                gc,
                "artifacts",
                "repositories",
                "create",
                AR_REPO,
                "--repository-format",
                "docker",
                "--location",
                REGION,
                "--project",
                project,
            ],
            dry_run=dry_run,
        )

    log("Setup: runtime service account")
    if not _exists(gc, "iam", "service-accounts", "describe", runtime_sa, "--project", project):
        run(
            [
                gc,
                "iam",
                "service-accounts",
                "create",
                runtime_sa.split("@")[0],
                "--project",
                project,
                "--display-name",
                "Medynium API runtime",
            ],
            dry_run=dry_run,
        )

    log("Setup: secrets (values are never printed)")
    env = {**read_env_file(), **os.environ}
    values: dict[str, str] = {}
    session = env.get("SESSION_SECRET", "")
    if session in ("", "dev-only-change-me") or len(session) < 32:
        session = secrets.token_urlsafe(48)
        print("  SESSION_SECRET in .env is a dev value; generated a fresh one for the cloud")
    values["medynium-session-secret"] = session

    key_path = Path(env.get("SNOWFLAKE_API_PRIVATE_KEY_PATH") or DEFAULT_KEY)
    if not key_path.exists():
        die(f"service key not found at {key_path}; set SNOWFLAKE_API_PRIVATE_KEY_PATH")
    values["medynium-snowflake-api-key-b64"] = base64.b64encode(key_path.read_bytes()).decode()
    if env.get("RESEND_API_KEY"):
        values[RESEND_SECRET[0]] = env["RESEND_API_KEY"]

    for name, value in values.items():
        have = _exists(gc, "secrets", "describe", name, "--project", project)
        if not have:
            run(
                [
                    gc,
                    "secrets",
                    "create",
                    name,
                    "--replication-policy",
                    "automatic",
                    "--project",
                    project,
                ],
                dry_run=dry_run,
            )
        # Keep the session secret stable across re-runs so signed-in users stay signed in.
        if not have or name != "medynium-session-secret":
            run(
                [gc, "secrets", "versions", "add", name, "--data-file=-", "--project", project],
                dry_run=dry_run,
                stdin=value,
                show=f"{gc} secrets versions add {name} --data-file=- (stdin)",
            )
        run(
            [
                gc,
                "secrets",
                "add-iam-policy-binding",
                name,
                "--project",
                project,
                "--member",
                f"serviceAccount:{runtime_sa}",
                "--role",
                "roles/secretmanager.secretAccessor",
            ],
            dry_run=dry_run,
            capture=True,
        )


def config_flags(gc: str, project: str, cors_origins: str, public_app_url: str) -> list[str]:
    """Env vars and secret mounts. Only passed on --setup; later deploys leave them untouched."""
    env = {**read_env_file(), **os.environ}
    plain = {k: env[k] for k in PLAIN_FROM_ENV if env.get(k)}
    plain.update(
        APP_ENV="production",
        COOKIE_SECURE="true",
        CORS_ORIGINS=cors_origins,
        PUBLIC_APP_URL=public_app_url,
    )
    mounted = dict(SECRETS)
    if _exists(gc, "secrets", "describe", RESEND_SECRET[0], "--project", project):
        mounted[RESEND_SECRET[0]] = RESEND_SECRET[1]
    # A file avoids shell quoting: gcloud.cmd goes through cmd.exe, which eats '^' and ','.
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", prefix="medynium-env-", delete=False, encoding="utf-8"
    ) as f:
        json.dump(plain, f)
    env_file = Path(f.name)
    return [
        "--env-vars-file",
        str(env_file),
        "--update-secrets",
        ",".join(f"{var}={name}:latest" for name, var in mounted.items()),
    ]


def _service_flags(runtime_sa: str) -> list[str]:
    return [
        "--platform",
        "managed",
        "--service-account",
        runtime_sa,
        "--port",
        "8000",
        "--cpu",
        "1",
        "--memory",
        "1Gi",
        "--concurrency",
        "8",
        "--min-instances",
        "1",
        "--max-instances",
        "3",
        "--timeout",
        "300",
        "--no-cpu-throttling",  # the read-model refresh runs after the response is sent (core/refresh.py)
        "--allow-unauthenticated",  # the app enforces auth itself
    ]


def _test_python() -> str:
    """Python used to run the test suite. Prefer the project's virtualenv over whatever
    interpreter launched this script, so dev dependencies are present."""
    candidates = [
        BACKEND_DIR / ".venv" / "Scripts" / "python.exe",  # Windows
        BACKEND_DIR / ".venv" / "bin" / "python",  # POSIX
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    if os.environ.get("VIRTUAL_ENV"):
        venv = Path(os.environ["VIRTUAL_ENV"])
        for sub in ("Scripts/python.exe", "bin/python"):
            if (venv / sub).exists():
                return str(venv / sub)
    return sys.executable


def run_tests() -> None:
    py = _test_python()
    log("Running tests (pytest)")
    if py == sys.executable and "VIRTUAL_ENV" not in os.environ:
        print(
            _c(
                "  note: no .venv found, running pytest with the current "
                "interpreter. If it fails on a missing module, either "
                "`poetry install` / activate the venv, or re-run with --skip-tests.",
                YELLOW,
            )
        )
    run([py, "-m", "pytest", "-q"], cwd=BACKEND_DIR)


def build(gc: str, project: str, region: str, image_uri: str, dry_run: bool) -> None:
    log(f"Building image  ->  {image_uri}")
    run(
        [
            gc,
            "builds",
            "submit",
            "--project",
            project,
            "--region",
            region,
            "--tag",
            image_uri,
            str(BACKEND_DIR),
        ],
        dry_run=dry_run,
    )


def deploy_image(
    gc: str,
    project: str,
    region: str,
    service: str,
    image_uri: str,
    runtime_sa: str,
    extra: list[str],
    dry_run: bool,
) -> None:
    log(f"Deploying to Cloud Run  ->  {service} ({region})")
    run(
        [
            gc,
            "run",
            "deploy",
            service,
            "--project",
            project,
            "--region",
            region,
            "--image",
            image_uri,
            *_service_flags(runtime_sa),
            *extra,
        ],
        dry_run=dry_run,
        show=f"{gc} run deploy {service} --project {project} --region {region} --image {image_uri} ...",
    )


def deploy_from_source(
    gc: str,
    project: str,
    region: str,
    service: str,
    runtime_sa: str,
    extra: list[str],
    dry_run: bool,
) -> None:
    log(f"Deploying from source  ->  {service} ({region})")
    run(
        [
            gc,
            "run",
            "deploy",
            service,
            "--project",
            project,
            "--region",
            region,
            "--source",
            str(BACKEND_DIR),
            *_service_flags(runtime_sa),
            *extra,
        ],
        dry_run=dry_run,
        show=f"{gc} run deploy {service} --project {project} --region {region} --source ... ...",
    )


def service_url(gc: str, project: str, region: str, service: str) -> str:
    return run(
        [
            gc,
            "run",
            "services",
            "describe",
            service,
            "--project",
            project,
            "--region",
            region,
            "--platform",
            "managed",
            "--format",
            "value(status.url)",
        ],
        capture=True,
    )


def health_check(url: str) -> None:
    if not url:
        return
    endpoint = url.rstrip("/") + "/health"
    log(f"Health check  ->  {endpoint}")
    try:
        with urllib.request.urlopen(endpoint, timeout=30) as resp:  # noqa: S310
            body = resp.read(500).decode("utf-8", "replace")
            status = resp.status
    except Exception as exc:  # noqa: BLE001 - report any failure, don't crash
        print(_c(f"  could not reach {endpoint}: {exc}", YELLOW))
        return
    ok = status == 200
    print(_c(f"  HTTP {status}  {body}", GREEN if ok else YELLOW))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--project", default=PROJECT)
    p.add_argument("--region", default=REGION)
    p.add_argument("--service", default=SERVICE)
    p.add_argument(
        "--runtime-sa",
        default=RUNTIME_SA,
        help="runtime service account attached on deploy (prevents identity drift)",
    )
    p.add_argument("--cors-origins", default=UI_URL, help="used with --setup")
    p.add_argument("--public-app-url", default=UI_URL, help="used with --setup")
    p.add_argument("--tag", default=None, help="image tag (default: manual-<UTC timestamp>)")
    p.add_argument(
        "--setup",
        action="store_true",
        help="first time: enable APIs, create registry/SA/secrets, set env vars and secret mounts",
    )
    p.add_argument(
        "--source",
        action="store_true",
        help="one-step `gcloud run deploy --source .` instead of build + deploy --image",
    )
    p.add_argument(
        "--no-build",
        action="store_true",
        help="skip the build; deploy an already-pushed --tag (use for rollback)",
    )
    p.add_argument("--skip-tests", action="store_true", help="don't run pytest first")
    p.add_argument("--yes", "-y", action="store_true", help="don't prompt for confirmation")
    p.add_argument("--dry-run", action="store_true", help="print commands, execute nothing")
    args = p.parse_args(argv)

    gc = gcloud()
    tag = args.tag or f"manual-{_dt.datetime.now(_dt.UTC):%Y%m%d%H%M%S}"
    image_uri = f"{args.region}-docker.pkg.dev/{args.project}/{AR_REPO}/{AR_IMAGE}:{tag}"
    runtime_sa = args.runtime_sa.replace(PROJECT, args.project)

    preflight(args.project, args.dry_run)

    log("Plan")
    live = current_image(gc, args.project, args.region, args.service)
    print(f"  service   : {args.service}")
    print(f"  region    : {args.region}")
    print(f"  live now  : {live}")
    if args.source:
        print("  strategy  : gcloud run deploy --source . (Cloud Build builds from local tree)")
    else:
        print(f"  new image : {image_uri}")
        strategy = "deploy existing image" if args.no_build else "Cloud Build -> deploy"
        print(f"  strategy  : {strategy}")
    print(f"  runtime SA: {runtime_sa}")
    print(f"  setup     : {args.setup}")

    if not args.yes and not args.dry_run:
        reply = input(_c("\nProceed with deploy? [y/N] ", YELLOW)).strip().lower()
        if reply not in {"y", "yes"}:
            print("Aborted.")
            return 130

    extra: list[str] = []
    if args.setup:
        setup(gc, args.project, runtime_sa, args.dry_run)
        extra = config_flags(gc, args.project, args.cors_origins, args.public_app_url)

    if not args.skip_tests and not args.dry_run:
        run_tests()
    elif args.skip_tests:
        print(_c("\n(skipping tests)", YELLOW))

    if args.source:
        deploy_from_source(
            gc, args.project, args.region, args.service, runtime_sa, extra, args.dry_run
        )
    else:
        if not args.no_build:
            build(gc, args.project, args.region, image_uri, args.dry_run)
        else:
            print(_c(f"\n(skipping build; deploying existing {image_uri})", YELLOW))
        deploy_image(
            gc, args.project, args.region, args.service, image_uri, runtime_sa, extra, args.dry_run
        )

    if extra:
        Path(extra[1]).unlink(missing_ok=True)  # the temp env-vars file from config_flags

    if args.dry_run:
        log("Dry run complete. Nothing was executed.")
        return 0

    url = service_url(gc, args.project, args.region, args.service)
    health_check(url)
    log("Done")
    print(f"  {args.service} is live at: {_c(url, GREEN)}")
    if not args.source:
        print("  rollback: python scripts/deploy.py --no-build --skip-tests --tag <previous-tag>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
