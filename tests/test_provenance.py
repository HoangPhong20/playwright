"""Tests for safe run provenance capture."""

import hashlib
import json
import subprocess
from types import SimpleNamespace

from agoda_crawler import orchestration


def _provenance_module():
    module = getattr(orchestration, "_provenance", None)
    assert module is not None, "run provenance helper has not been added"
    return module


def _args(**changes):
    values = {
        "max_pages": 3,
        "headless": True,
        "workers": 2,
        "detail_concurrency": 2,
        "total_detail_concurrency": 3,
        "destinations": "Vung Tau",
        "destination": "Vung Tau",
        "date": "2026-06-10",
        "airflow_run_id": "run-one",
        "airflow_dag_id": "dag-one",
        "airflow_try_number": 1,
        "run_id": "run-one",
        "batch_id": "batch-one",
        "try_number": 1,
        "attempt": 1,
        "timestamp": "run-one-time",
        "started_at": "run-one-start",
        "finished_at": "run-one-end",
        "output_dir": "data/attempt-one",
        "output_path": "data/attempt-one/output.jsonl",
        "attempt_dir": "data/attempt-one",
        "manifest_path": "data/attempt-one/run_manifest.json",
        "api_token": "CLI_SECRET_VALUE",
        "metadata": {"nested_secret": "PRIVATE_NESTED_SECRET"},
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _fake_git_runner(
    tracked_paths,
    *,
    head_paths=None,
    head_error=False,
    status=b" M main.py\0",
    diff=b"private diff contents",
):
    head_paths = tracked_paths if head_paths is None else head_paths

    def run(command, **_kwargs):
        args = list(command)
        if args[1:3] == ["rev-parse", "HEAD"]:
            stdout = b"0123456789abcdef\n"
        elif args[1:3] == ["status", "--porcelain=v1"]:
            stdout = status
        elif args[1:4] == ["ls-files", "--cached", "-z"]:
            assert args[4:] == ["--", "main.py", "agoda_crawler", "requirements.txt"]
            stdout = b"\0".join(path.encode() for path in tracked_paths) + b"\0"
        elif args[1:5] == ["ls-tree", "-r", "--name-only", "-z"]:
            assert args[5:] == ["HEAD", "--", "main.py", "agoda_crawler", "requirements.txt"]
            if head_error:
                raise subprocess.CalledProcessError(1, args, stderr=b"head lookup failed")
            stdout = b"\0".join(path.encode() for path in head_paths) + b"\0"
        elif args[1:4] == ["diff", "--binary", "HEAD"]:
            ignored_directories = {
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
            expected_diff_paths = sorted(
                path
                for path in set(tracked_paths) | set(head_paths)
                if (path in {"main.py", "requirements.txt"}
                    or path.startswith("agoda_crawler/") and path.endswith(".py"))
                and not ignored_directories.intersection(path.split("/"))
            )
            if not expected_diff_paths:
                raise AssertionError("unscoped git diff must not run without source paths")
            assert args[4:] == ["--", *expected_diff_paths]
            stdout = diff
        else:
            raise AssertionError(f"unexpected git command: {args}")
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr=b"")

    return run


def _fake_config(**changes):
    values = {
        "CONFIG_ENV_KEYS": {
            "AGODA_MAX_PAGES",
            "AGODA_WORKERS",
            "AGODA_HEADLESS",
            "AGODA_DESTINATIONS",
            "AGODA_MAX_SCROLL_ROUNDS",
            "AGODA_BLOCK_RESOURCE_TYPES",
            "AGODA_API_TOKEN",
        },
        "ENV_PATH": ".env",
        "MAX_SCROLL_ROUNDS": 80,
        "BLOCK_RESOURCE_TYPES": ("image", "font"),
        "API_TOKEN": "MODULE_SECRET_VALUE",
        "_ENV": ("ENV_SECRET_VALUE",),
        "UNAPPROVED_CONSTANT": "UNAPPROVED_VALUE",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _capture(module, root, args, *, git_runner, config_module=None):
    return module.capture_run_provenance(
        args,
        ["Vung Tau"],
        [("2026-06-10", "2026-06-11")],
        project_root=root,
        git_runner=git_runner,
        config_module=config_module or _fake_config(),
        captured_at="2026-10-20T00:00:00+00:00",
    )


def test_source_fingerprint_is_sorted_and_repeatable(tmp_path):
    provenance_module = _provenance_module()
    (tmp_path / "main.py").write_text("print('main')\n", encoding="utf-8")
    package = tmp_path / "agoda_crawler"
    package.mkdir()
    (package / "a.py").write_text("A = 1\n", encoding="utf-8")
    (package / "z.py").write_text("Z = 1\n", encoding="utf-8")
    paths = ["agoda_crawler/z.py", "main.py", "agoda_crawler/a.py"]

    first = _capture(
        provenance_module,
        tmp_path,
        _args(),
        git_runner=_fake_git_runner(paths),
    )
    second = _capture(
        provenance_module,
        tmp_path,
        _args(
            airflow_run_id="run-two",
            airflow_dag_id="dag-two",
            output_dir="data/attempt-two",
            run_id="run-two",
            batch_id="batch-two",
            try_number=2,
            attempt=2,
            timestamp="run-two-time",
            started_at="run-two-start",
            finished_at="run-two-end",
            output_path="data/attempt-two/output.jsonl",
            attempt_dir="data/attempt-two",
            manifest_path="data/attempt-two/run_manifest.json",
            destinations=" Vung Tau ",
            date="2026/06/10",
        ),
        git_runner=_fake_git_runner(list(reversed(paths))),
    )

    expected_paths = ["agoda_crawler/a.py", "agoda_crawler/z.py", "main.py"]
    assert [item["path"] for item in first["source"]["files"]] == expected_paths
    assert first["source"]["sha256"] == second["source"]["sha256"]
    assert first["config"]["fingerprint_sha256"] == second["config"]["fingerprint_sha256"]


def test_effective_config_fingerprint_changes_with_resolved_setting(
    tmp_path,
):
    provenance_module = _provenance_module()
    (tmp_path / "main.py").write_text("print('main')\n", encoding="utf-8")
    git_runner = _fake_git_runner(["main.py"])

    first = _capture(provenance_module, tmp_path, _args(workers=2), git_runner=git_runner)
    second = _capture(provenance_module, tmp_path, _args(workers=4), git_runner=git_runner)

    assert first["config"]["fingerprint_sha256"] != second["config"]["fingerprint_sha256"]
    assert first["config"]["cli"]["workers"] == 2
    assert second["config"]["cli"]["workers"] == 4

    changed_constant = _capture(
        provenance_module,
        tmp_path,
        _args(workers=2),
        git_runner=git_runner,
        config_module=_fake_config(MAX_SCROLL_ROUNDS=81),
    )
    assert first["config"]["fingerprint_sha256"] != changed_constant["config"]["fingerprint_sha256"]


def test_dirty_diff_and_untracked_runtime_sources_are_fingerprinted(
    tmp_path,
):
    provenance_module = _provenance_module()
    package = tmp_path / "agoda_crawler"
    package.mkdir()
    (package / "added.py").write_text("VALUE = 'untracked'\n", encoding="utf-8")
    for relative_path in (
        "debug/trace.py",
        "output/generated.py",
        ".venv/site.py",
        ".git/hook.py",
    ):
        excluded_path = package / relative_path
        excluded_path.parent.mkdir(parents=True, exist_ok=True)
        excluded_path.write_text("excluded runtime artifact\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("not runtime source\n", encoding="utf-8")
    ignored_files = {
        ".env": "AGODA_TOKEN=DO_NOT_READ\n",
        "data/current.jsonl": "{}\n",
        "debug/runtime.log": "diagnostic output\n",
        ".venv/lib/site-packages/ignored.py": "not crawler source\n",
        "docs/RUNBOOK.md": "operator documentation\n",
        "openspec/change/tasks.md": "planning artifact\n",
    }
    for relative_path, contents in ignored_files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    raw_diff = b"diff --git a/main.py b/main.py\nsecret-like diff payload"
    result = _capture(
        provenance_module,
        tmp_path,
        _args(),
        git_runner=_fake_git_runner(
                [
                    "main.py",
                    "agoda_crawler/debug/trace.py",
                    "docs/RUNBOOK.md",
                ],
            status=b" M main.py\0?? agoda_crawler/added.py\0?? notes.md\0",
            diff=raw_diff,
        ),
    )

    assert result["git"]["dirty"] is True
    assert result["git"]["source_diff_sha256"] == hashlib.sha256(raw_diff).hexdigest()
    assert result["git"]["untracked_sources"] == [
        {
            "path": "agoda_crawler/added.py",
            "sha256": hashlib.sha256((package / "added.py").read_bytes()).hexdigest(),
        }
    ]
    assert [item["path"] for item in result["source"]["files"]] == [
        "agoda_crawler/added.py"
    ]
    assert "secret-like diff payload" not in json.dumps(result)
    assert "DO_NOT_READ" not in json.dumps(result)


def test_staged_deleted_runtime_file_remains_in_scoped_diff_fingerprint(tmp_path):
    provenance_module = _provenance_module()
    (tmp_path / "main.py").write_text("print('main')\n", encoding="utf-8")
    raw_diff = b"staged deletion of agoda_crawler/deleted.py"

    result = _capture(
        provenance_module,
        tmp_path,
        _args(),
        git_runner=_fake_git_runner(
            ["main.py"],
            head_paths=["main.py", "agoda_crawler/deleted.py"],
            diff=raw_diff,
        ),
    )

    assert result["git"]["source_diff_sha256"] == hashlib.sha256(raw_diff).hexdigest()
    assert result["git"]["untracked_sources"] == []


def test_empty_runtime_source_path_set_skips_git_diff(tmp_path):
    provenance_module = _provenance_module()
    result = _capture(
        provenance_module,
        tmp_path,
        _args(),
        git_runner=_fake_git_runner(["docs/RUNBOOK.md"], head_paths=["docs/RUNBOOK.md"]),
    )

    assert result["git"]["source_diff_status"] == "no_eligible_sources"
    assert result["git"]["source_diff_sha256"] == hashlib.sha256(b"").hexdigest()


def test_head_source_lookup_failure_is_explicit(tmp_path):
    provenance_module = _provenance_module()
    (tmp_path / "main.py").write_text("print('main')\n", encoding="utf-8")
    result = _capture(
        provenance_module,
        tmp_path,
        _args(),
        git_runner=_fake_git_runner(["main.py"], head_error=True),
    )

    assert result["git"]["source_diff_sha256"] is None
    assert result["git"]["source_diff_status"] == "unavailable"
    assert result["git"]["errors"]["head_sources"] == "CalledProcessError"


def test_provenance_uses_resolved_allowlisted_config_and_versions(
    tmp_path, monkeypatch
):
    provenance_module = _provenance_module()
    (tmp_path / "main.py").write_text("print('main')\n", encoding="utf-8")
    monkeypatch.setattr(provenance_module.platform, "python_version", lambda: "3.13.1")
    monkeypatch.setattr(provenance_module.platform, "system", lambda: "TestOS")
    monkeypatch.setattr(provenance_module.platform, "release", lambda: "test-release")
    monkeypatch.setattr(provenance_module.platform, "version", lambda: "test-version")
    monkeypatch.setattr(provenance_module.platform, "machine", lambda: "test-machine")
    monkeypatch.setattr(
        provenance_module.metadata,
        "version",
        lambda package: "1.55.0" if package == "playwright" else "unknown",
    )
    result = _capture(
        provenance_module,
        tmp_path,
        _args(),
        git_runner=_fake_git_runner(["main.py"]),
        config_module=_fake_config(),
    )
    assert result["versions"]["chromium"]["actual_version"] is None
    assert result["versions"]["chromium"]["actual_version_status"] == "not_launched"
    provenance_module.record_browser_version(
        result["versions"]["chromium"], SimpleNamespace(version="140.0.7339.0")
    )
    serialized = json.dumps(result)
    log_entry = json.dumps(provenance_module.log_summary(result))

    assert result["git"]["commit_sha"] == "0123456789abcdef"
    assert result["versions"]["python"] == "3.13.1"
    assert result["versions"]["playwright"] == "1.55.0"
    assert result["versions"]["chromium"]["actual_version"] == "140.0.7339.0"
    assert result["versions"]["os"]["system"] == "TestOS"
    assert "CLI_SECRET_VALUE" not in serialized
    assert "PRIVATE_NESTED_SECRET" not in serialized
    assert "metadata" not in result["config"]["cli"]
    assert "MODULE_SECRET_VALUE" not in serialized
    assert "ENV_SECRET_VALUE" not in serialized
    assert "AGODA_API_TOKEN" not in serialized
    assert "_ENV" not in serialized
    assert "UNAPPROVED_VALUE" not in serialized
    assert "SECRET" not in log_entry
    assert "private diff" not in log_entry
    assert result["config"]["resolved_agoda"]["AGODA_MAX_SCROLL_ROUNDS"] == 80
    assert result["config"]["resolved_agoda"]["AGODA_BLOCK_RESOURCE_TYPES"] == [
        "image",
        "font",
    ]


def test_browser_versions_merge_without_losing_observations(tmp_path):
    provenance_module = _provenance_module()
    (tmp_path / "main.py").write_text("print('main')\n", encoding="utf-8")
    result = _capture(
        provenance_module,
        tmp_path,
        _args(),
        git_runner=_fake_git_runner(["main.py"]),
    )
    chromium = result["versions"]["chromium"]

    provenance_module.record_browser_version(
        chromium, SimpleNamespace(version="141.0.worker-one")
    )
    provenance_module.record_browser_version(
        chromium, SimpleNamespace(version="142.0.worker-two")
    )

    assert chromium["observed_versions"] == [
        "141.0.worker-one",
        "142.0.worker-two",
    ]
    assert chromium["actual_version"] is None
    assert chromium["actual_version_status"] == "inconsistent"

    class BrokenBrowser:
        @property
        def version(self):
            raise RuntimeError("browser metadata unavailable")

    provenance_module.record_browser_version(chromium, BrokenBrowser())
    assert chromium["observed_versions"] == [
        "141.0.worker-one",
        "142.0.worker-two",
    ]
    assert chromium["actual_version"] is None
    assert chromium["actual_version_status"] == "inconsistent"

    one_browser = _capture(
        provenance_module,
        tmp_path,
        _args(),
        git_runner=_fake_git_runner(["main.py"]),
    )["versions"]["chromium"]
    provenance_module.record_browser_version(
        one_browser, SimpleNamespace(version="141.0.worker-one")
    )
    provenance_module.record_browser_version(one_browser, BrokenBrowser())
    assert one_browser["actual_version"] == "141.0.worker-one"
    assert one_browser["actual_version_status"] == "partial"


def test_git_unavailable_leaves_source_and_config_fingerprints_available(tmp_path):
    provenance_module = _provenance_module()
    (tmp_path / "main.py").write_text("print('main')\n", encoding="utf-8")

    def git_missing(*_args, **_kwargs):
        raise FileNotFoundError("git executable not found")

    result = _capture(
        provenance_module,
        tmp_path,
        _args(),
        git_runner=git_missing,
    )

    assert result["git"]["status"] == "partial"
    assert result["git"]["commit_sha"] is None
    assert result["git"]["dirty"] is None
    assert result["git"]["source_diff_status"] == "unavailable"
    assert result["git"]["untracked_source_status"] == "unavailable"
    assert result["git"]["errors"]["commit"] == "FileNotFoundError"
    assert result["source"]["sha256"]
    assert result["config"]["fingerprint_sha256"]
