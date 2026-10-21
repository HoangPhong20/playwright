import json
from pathlib import Path

from agoda_crawler.utils import debug_artifacts
from agoda_crawler.utils.debug_artifacts import debug_run_context


def test_membership_diagnostics_are_bounded_and_scoped_by_run(tmp_path, monkeypatch) -> None:
    original_debug_directory = debug_artifacts.debug_directory

    def temporary_debug_directory(category: str) -> Path:
        path = original_debug_directory(category)
        relative = Path(*path.parts[1:]) if path.parts[0] == "debug" else path
        return tmp_path / relative

    monkeypatch.setattr(debug_artifacts, "debug_directory", temporary_debug_directory)
    samples = ["https://www.agoda.com/" + ("x" * 600)] + [
        f"https://www.agoda.com/hotel/{index}" for index in range(30)
    ]
    diagnostics = {
        "embedded_candidates_seen": 75,
        "embedded_nonmember_unique": 40,
        "embedded_unmatched_at_end": 12,
        "sample_urls": samples,
    }

    with debug_run_context("batch_one", "Vung Tau", "2026-11-01"):
        first_path = debug_artifacts.save_membership_diagnostics(1, diagnostics)
    with debug_run_context("batch_two", "Da Nang", "2026-11-01"):
        second_path = debug_artifacts.save_membership_diagnostics(1, diagnostics)

    first = json.loads(first_path.read_text(encoding="utf-8"))
    second = json.loads(second_path.read_text(encoding="utf-8"))

    assert first_path != second_path
    assert first_path.parent.parts[-4:] == (
        "batch_one",
        "vung-tau",
        "2026-11-01",
        "membership",
    )
    assert second_path.parent.parts[-4:] == (
        "batch_two",
        "da-nang",
        "2026-11-01",
        "membership",
    )
    assert first["embedded_candidates_seen"] == 75
    assert first["embedded_nonmember_unique"] == 40
    assert first["embedded_unmatched_at_end"] == 12
    assert len(first["sample_urls"]) == 25
    assert all(len(url) <= 500 for url in first["sample_urls"])
    assert second["sample_urls"] == first["sample_urls"]
