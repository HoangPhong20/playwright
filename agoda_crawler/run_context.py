"""Stable run identity supplied by an external orchestrator such as Airflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


def path_safe_identifier(value: str) -> str:
    """Encode an identifier so it is safe as one Windows/Linux path segment."""
    if not value:
        raise ValueError("Identifier must not be empty")
    return quote(value, safe="-_.")


@dataclass(frozen=True)
class RunContext:
    airflow_dag_id: str
    airflow_run_id: str
    airflow_try_number: int

    @property
    def batch_id(self) -> str:
        return f"{self.airflow_dag_id}__{self.airflow_run_id}"

    @property
    def path_batch_id(self) -> str:
        return path_safe_identifier(self.batch_id)

    @property
    def path_dag_id(self) -> str:
        return path_safe_identifier(self.airflow_dag_id)

    def output_directory(self, output_root: str | Path) -> Path:
        return self.batch_directory(output_root) / f"attempt={self.airflow_try_number}"

    def batch_directory(self, output_root: str | Path) -> Path:
        """Return the stable directory shared by every crawler attempt in a batch."""
        return (
            Path(output_root)
            / f"dag_id={self.path_dag_id}"
            / f"batch_id={self.path_batch_id}"
        )

    def completion_pointer_path(self, output_root: str | Path) -> Path:
        """Path written only after one crawler attempt has completed."""
        return self.batch_directory(output_root) / "completed_attempt.json"

    def record_metadata(self) -> dict[str, str | int]:
        return {
            "batch_id": self.batch_id,
            "airflow_dag_id": self.airflow_dag_id,
            "airflow_run_id": self.airflow_run_id,
            "airflow_try_number": self.airflow_try_number,
        }


def run_context_from_args(args) -> RunContext:
    dag_id = str(getattr(args, "airflow_dag_id", "") or "").strip()
    run_id = str(getattr(args, "airflow_run_id", "") or "").strip()
    try_number = int(getattr(args, "airflow_try_number", 1))

    if not dag_id or not run_id:
        raise ValueError(
            "--airflow-dag-id and --airflow-run-id are required; "
            "the crawler does not generate run IDs"
        )
    if try_number < 1:
        raise ValueError("--airflow-try-number must be at least 1")
    return RunContext(dag_id, run_id, try_number)
