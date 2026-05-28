import json
from pathlib import Path


def compute() -> int:
    """TODO: model implements this to return a non-negative int."""
    return 0


def write_metrics_file(path: Path) -> None:
    """Write {"metric": compute()} to `path` as JSON."""
    path.write_text(json.dumps({"metric": compute()}))
