"""Module boundaries that keep each feature folder analysable on its own (see AGENTS.md)."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "medynium_api"
MAX_LINES = 300


def _modules() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _feature(path: Path) -> str | None:
    rel = path.relative_to(SRC).parts
    return rel[1] if rel[0] == "features" and len(rel) > 2 else None


def test_features_do_not_import_each_other() -> None:
    for path in _modules():
        own = _feature(path)
        if own is None:
            continue
        for name in _imports(path):
            parts = name.split(".")
            if parts[:2] == ["medynium_api", "features"] and len(parts) > 2:
                assert parts[2] == own, f"{path.relative_to(SRC)} imports feature {parts[2]}"


def test_core_does_not_import_features() -> None:
    for path in (SRC / "core").rglob("*.py"):
        for name in _imports(path):
            assert not name.startswith("medynium_api.features"), path.name


def test_only_repositories_touch_snowflake() -> None:
    for path in _modules():
        allowed = path.name == "repository.py" or "core" in path.relative_to(SRC).parts
        if allowed:
            continue
        for name in _imports(path):
            assert name.split(".")[0] != "snowflake", f"{path.relative_to(SRC)} imports snowflake"


def test_routers_do_not_import_repositories() -> None:
    for path in _modules():
        if path.name != "router.py":
            continue
        for name in _imports(path):
            assert not name.endswith(".repository"), f"{path.relative_to(SRC)} skips the service"


def test_files_stay_small() -> None:
    for path in _modules():
        lines = len(path.read_text(encoding="utf-8").splitlines())
        assert lines <= MAX_LINES, f"{path.relative_to(SRC)} has {lines} lines; split it"


def test_no_runtime_code_uses_the_admin_role_or_setup_credentials() -> None:
    """Q-A7, SEC-06: MED_ADMIN creates objects during setup and is never a runtime role. Setup credentials live
    in scripts/ and data/ only, so the deployed API cannot reach them."""
    forbidden = ("MED_ADMIN", "ACCOUNTADMIN", "SNOWFLAKE_ADMIN")
    for path in _modules():
        text = path.read_text(encoding="utf-8")
        for word in forbidden:
            assert word not in text, f"{path.relative_to(SRC)} mentions {word}"
