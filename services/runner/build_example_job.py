"""Make a local runner job from the trusted task-store fixture."""

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "task-store"


def build_job(mode: str, solution: str, job_id: str) -> bytes:
    if mode not in {"run", "submit"}:
        raise ValueError("mode must be run or submit")
    if solution not in {"starter", "reference"}:
        raise ValueError("solution must be starter or reference")

    manifest = json.loads((EXAMPLE / "manifest.json").read_text())
    test_key = "visible_tests" if mode == "run" else "hidden_tests"
    job = {"schema_version": 1, "job_id": job_id, "mode": mode, "timeout_seconds": 10}

    from io import BytesIO

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("job.json", json.dumps(job))
        for starter_path in manifest["starter_files"]:
            source_path = (
                manifest["reference_files"].get(starter_path, starter_path)
                if solution == "reference"
                else starter_path
            )
            workspace_path = Path(starter_path).relative_to("starter")
            archive.write(EXAMPLE / source_path, f"submission/{workspace_path.as_posix()}")
        for test_path in manifest[test_key]:
            archive.write(EXAMPLE / test_path, test_path)
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("run", "submit"), default="run")
    parser.add_argument("--solution", choices=("starter", "reference"), default="starter")
    parser.add_argument("--job-id", default="local-task-store")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(build_job(args.mode, args.solution, args.job_id))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
