"""Safe, per-run crawler provenance capture."""

import hashlib
import json
import platform
import subprocess
from contextlib import nullcontext
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Iterable, Optional

from agoda_crawler import config


_RUNTIME_SOURCE_PREFIXES = ("agoda_crawler/",)
_RUNTIME_SOURCE_FILES = {"main.py", "requirements.txt"}
_GIT_SOURCE_PATHS = ["main.py", "agoda_crawler", "requirements.txt"]
_EXCLUDED_SOURCE_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "debug",
    "data",
    "output",
    "outputs",
    "logs",
    "__pycache__",
}
_CONFIG_IDENTITY_KEYS = {
    "airflow_dag_id",
    "airflow_run_id",
    "airflow_try_number",
    "run_id",
    "batch_id",
    "try_number",
    "attempt",
    "timestamp",
    "started_at",
    "finished_at",
    "date",
    "destination",
    "destinations",
    "output_dir",
    "output_path",
    "attempt_dir",
    "manifest_path",
}
_RUNTIME_CLI_KEYS = {
    "max_pages",
    "headless",
    "adults",
    "rooms",
    "children",
    "locale",
    "enrich_details",
    "max_detail_pages",
    "enrich_missing_only",
    "detail_timeout",
    "field_retry_timeout",
    "field_retry_count",
    "detail_fields",
    "max_scroll_rounds",
    "stable_rounds",
    "scroll_wait_ms",
    "workers",
    "detail_concurrency",
    "total_detail_concurrency",
    "print_records",
}
_SENSITIVE_NAME_PARTS = (
    "api_key",
    "auth",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)


def capture_run_provenance(
    args: Any,
    destinations: Iterable[str],
    stays: Iterable[tuple[str, str]],
    *,
    project_root: Optional[Path] = None,
    git_runner: Optional[Callable[..., Any]] = None,
    config_module: Any = config,
    captured_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Capture source, effective config, and runtime versions without secrets."""
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    destination_list = list(destinations)
    stay_list = [
        {"check_in": check_in, "check_out": check_out}
        for check_in, check_out in stays
    ]
    config_values = _effective_config(args, destination_list, stay_list, config_module)
    return {
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "git": _git_provenance(root, git_runner),
        "source": _source_provenance(root),
        "config": config_values,
        "versions": _runtime_versions(),
    }


def record_browser_version(
    chromium_metadata: Dict[str, Any], browser: Any, lock: Optional[Any] = None
) -> None:
    """Record the version from an already-launched Playwright browser."""
    guard = lock if lock is not None else nullcontext()
    with guard:
        observed = chromium_metadata.setdefault("observed_versions", [])
        errors = chromium_metadata.setdefault("observation_errors", [])
        unavailable_count = chromium_metadata.setdefault("unavailable_count", 0)
        try:
            version = getattr(browser, "version")
            if callable(version):
                version = version()
        except Exception as error:
            errors.append(type(error).__name__)
            chromium_metadata["unavailable_count"] = unavailable_count + 1
            _refresh_browser_version_status(chromium_metadata)
            return

        if version:
            normalized_version = str(version)
            if normalized_version not in observed:
                observed.append(normalized_version)
                observed.sort()
        else:
            chromium_metadata["unavailable_count"] = unavailable_count + 1
        _refresh_browser_version_status(chromium_metadata)


def _refresh_browser_version_status(chromium_metadata: Dict[str, Any]) -> None:
    observed = chromium_metadata.get("observed_versions", [])
    unavailable_count = chromium_metadata.get("unavailable_count", 0)
    if len(observed) > 1:
        chromium_metadata["actual_version"] = None
        chromium_metadata["actual_version_status"] = "inconsistent"
    elif observed:
        chromium_metadata["actual_version"] = observed[0]
        chromium_metadata["actual_version_status"] = (
            "partial" if unavailable_count else "observed"
        )
    elif unavailable_count:
        chromium_metadata["actual_version"] = None
        chromium_metadata["actual_version_status"] = (
            "unavailable"
            if chromium_metadata.get("observation_errors")
            else "not_exposed"
        )


def log_summary(provenance: Dict[str, Any]) -> Dict[str, Any]:
    """Return a compact, safe provenance summary for crawler logs."""
    git = provenance.get("git", {})
    source = provenance.get("source", {})
    config_values = provenance.get("config", {})
    versions = provenance.get("versions", {})
    chromium = versions.get("chromium", {})
    return {
        "commit_sha": git.get("commit_sha"),
        "dirty": git.get("dirty"),
        "source_sha256": source.get("sha256"),
        "config_sha256": config_values.get("fingerprint_sha256"),
        "python": versions.get("python"),
        "playwright": versions.get("playwright"),
        "chromium": chromium.get("actual_version"),
        "os": versions.get("os", {}).get("system"),
    }


def _effective_config(
    args: Any,
    destinations: list[str],
    stays: list[Dict[str, str]],
    config_module: Any,
) -> Dict[str, Any]:
    raw_args = vars(args) if hasattr(args, "__dict__") else dict(args)
    config_keys = _agoda_config_keys(config_module)
    approved_cli_keys = {
        key.removeprefix("AGODA_").lower()
        for key in config_keys
    } & _RUNTIME_CLI_KEYS
    cli = {
        key: _json_value(value)
        for key, value in sorted(raw_args.items())
        if key in approved_cli_keys
        and key not in _CONFIG_IDENTITY_KEYS
        and not _is_sensitive_name(key)
    }
    constants = _module_constants(config_module, config_keys)
    resolved_agoda = {f"AGODA_{name}": value for name, value in constants.items()}
    resolved_agoda.update(
        {
            f"AGODA_{key.upper()}": value
            for key, value in cli.items()
            if f"AGODA_{key.upper()}" in config_keys
        }
    )
    if "AGODA_DESTINATIONS" in config_keys:
        resolved_agoda["AGODA_DESTINATIONS"] = destinations

    fingerprint_payload = {
        "cli": cli,
        "resolved_agoda": resolved_agoda,
        "module_constants": constants,
        "destinations": destinations,
        "stays": stays,
    }
    return {
        **fingerprint_payload,
        "fingerprint_sha256": _json_sha256(fingerprint_payload),
    }


def _agoda_config_keys(config_module: Any) -> set[str]:
    return {
        key
        for key in getattr(config_module, "CONFIG_ENV_KEYS", ())
        if isinstance(key, str)
        and key.startswith("AGODA_")
        and not _is_sensitive_name(key)
    }


def _module_constants(config_module: Any, config_keys: set[str]) -> Dict[str, Any]:
    values = {}
    for config_key in config_keys:
        name = config_key.removeprefix("AGODA_")
        if not hasattr(config_module, name):
            continue
        value = getattr(config_module, name)
        if isinstance(value, (bool, int, float, str, tuple, list, set)):
            values[name] = _json_value(value)
    return dict(sorted(values.items()))


def _is_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in _SENSITIVE_NAME_PARTS)


def _json_value(value: Any) -> Any:
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_value(item) for item in value)
    return value


def _json_sha256(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _runtime_source_paths(root: Path) -> list[Path]:
    paths = {root / name for name in _RUNTIME_SOURCE_FILES}
    package_root = root / "agoda_crawler"
    if package_root.is_dir():
        paths.update(
            path
            for path in package_root.rglob("*.py")
            if path.is_file() and _is_runtime_source_path(path.relative_to(root).as_posix())
        )
    return sorted(
        (path for path in paths if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _source_provenance(root: Path) -> Dict[str, Any]:
    files = []
    for path in _runtime_source_paths(root):
        relative_path = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({"path": relative_path, "sha256": digest})
    return {
        "sha256": _json_sha256(files),
        "files": files,
        "status": "complete",
    }


def _is_runtime_source_path(path: str) -> bool:
    pure_path = PurePosixPath(path)
    if any(
        part.lower() in _EXCLUDED_SOURCE_DIRECTORIES for part in pure_path.parts
    ):
        return False
    normalized = pure_path.as_posix()
    return normalized in _RUNTIME_SOURCE_FILES or any(
        normalized.startswith(prefix) and normalized.endswith(".py")
        for prefix in _RUNTIME_SOURCE_PREFIXES
    )


def _git_output(
    command: list[str],
    root: Path,
    git_runner: Callable[..., Any],
) -> bytes:
    result = git_runner(
        ["git", *command],
        cwd=root,
        capture_output=True,
        check=True,
        timeout=3,
    )
    output = result.stdout or b""
    return output.encode("utf-8") if isinstance(output, str) else output


def _git_provenance(
    root: Path,
    git_runner: Optional[Callable[..., Any]],
) -> Dict[str, Any]:
    run_git = git_runner or subprocess.run
    errors: Dict[str, str] = {}

    def read(command: list[str], name: str) -> Optional[bytes]:
        try:
            return _git_output(command, root, run_git)
        except (OSError, subprocess.SubprocessError) as error:
            errors[name] = type(error).__name__
            return None

    commit = read(["rev-parse", "HEAD"], "commit")
    status = read(["status", "--porcelain=v1", "-z", "--untracked-files=all"], "status")
    index_sources = read(
        ["ls-files", "--cached", "-z", "--", *_GIT_SOURCE_PATHS],
        "tracked_sources",
    )
    head_sources = read(
        ["ls-tree", "-r", "--name-only", "-z", "HEAD", "--", *_GIT_SOURCE_PATHS],
        "head_sources",
    )
    index_paths = None
    if index_sources is not None:
        index_path_values = {
            item.decode("utf-8", errors="surrogateescape")
            for item in index_sources.split(b"\0")
            if item
        }
        index_paths = {
            path for path in index_path_values if _is_runtime_source_path(path)
        }
    head_paths = None
    if head_sources is not None:
        head_path_values = {
            item.decode("utf-8", errors="surrogateescape")
            for item in head_sources.split(b"\0")
            if item
        }
        head_paths = {
            path for path in head_path_values if _is_runtime_source_path(path)
        }

    diff_status = "unavailable"
    if index_paths is not None and head_paths is not None:
        diff_paths = sorted(index_paths | head_paths)
        if diff_paths:
            diff = read(["diff", "--binary", "HEAD", "--", *diff_paths], "source_diff")
            if diff is not None:
                diff_status = "available"
        else:
            diff = b""
            diff_status = "no_eligible_sources"
    else:
        diff = None
        errors["source_diff"] = "SourcePathsUnavailable"

    untracked_sources = None
    if index_paths is not None:
        untracked_sources = []
        for path in _runtime_source_paths(root):
            relative_path = path.relative_to(root).as_posix()
            if relative_path not in index_paths:
                untracked_sources.append(
                    {
                        "path": relative_path,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )

    return {
        "commit_sha": commit.decode("utf-8", errors="replace").strip() or None
        if commit is not None
        else None,
        "dirty": bool(status) if status is not None else None,
        "dirty_status": "available" if status is not None else "unavailable",
        "source_diff_sha256": hashlib.sha256(diff).hexdigest() if diff is not None else None,
        "source_diff_status": diff_status,
        "untracked_sources": untracked_sources,
        "untracked_source_status": "available" if index_paths is not None else "unavailable",
        "head_source_status": "available" if head_paths is not None else "unavailable",
        "status": "available" if not errors else "partial",
        "errors": errors,
    }


def _runtime_versions() -> Dict[str, Any]:
    versions: Dict[str, Any] = {
        "python": _version_value(platform.python_version),
        "playwright": _playwright_version(),
        "chromium": {
            "expected_version": None,
            "expected_version_source": None,
            "actual_version": None,
            "actual_version_status": "not_launched",
            "observed_versions": [],
            "unavailable_count": 0,
            "observation_errors": [],
        },
        "os": {
            "system": _version_value(platform.system),
            "release": _version_value(platform.release),
            "version": _version_value(platform.version),
            "machine": _version_value(platform.machine),
        },
    }
    return versions


def _version_value(getter: Callable[[], str]) -> Optional[str]:
    try:
        return str(getter())
    except Exception:
        return None


def _playwright_version() -> Optional[str]:
    try:
        return metadata.version("playwright")
    except metadata.PackageNotFoundError:
        return None
    except Exception:
        return None
