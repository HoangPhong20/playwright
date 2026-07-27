"""Stable Unity Catalog Volume paths shared by Airflow upload and trigger tasks."""

from pathlib import PurePosixPath

from agoda_crawler.run_context import RunContext


def validated_volume_root(value: str) -> PurePosixPath:
    root = PurePosixPath(value.rstrip("/"))
    if len(root.parts) != 5 or root.parts[1] != "Volumes":
        raise ValueError(
            "DATABRICKS_UC_VOLUME_PATH must be /Volumes/<catalog>/<schema>/<volume>"
        )
    return root


def remote_attempt_directory(
    volume_root: PurePosixPath, context: RunContext
) -> PurePosixPath:
    return (
        volume_root
        / f"dag_id={context.path_dag_id}"
        / f"batch_id={context.path_batch_id}"
        / f"attempt={context.airflow_try_number}"
    )
