"""Execute one Python test job and write a JSON result.

RUNNER_INPUT and RUNNER_OUTPUT are local absolute paths or HTTPS presigned URLs.
The same entrypoint is used by local Docker runs and an eventual Fargate task.
"""

import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile


MAX_INPUT_BYTES = 2_000_000
MAX_UNCOMPRESSED_BYTES = 4_000_000
MAX_FILES = 64
MAX_MESSAGE_CHARS = 2_000
MAX_TIMEOUT_SECONDS = 30
JOB_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
PYTHON_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class RunnerError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _is_https(location: str) -> bool:
    if location.startswith("https://"):
        return True
    if "://" in location:
        raise RunnerError("unsupported_transport")
    if not Path(location).is_absolute():
        raise RunnerError("local_path_must_be_absolute")
    return False


def read_input(location: str) -> bytes:
    try:
        if _is_https(location):
            with urllib.request.urlopen(location, timeout=15) as response:
                data = response.read(MAX_INPUT_BYTES + 1)
        else:
            with open(location, "rb") as source:
                data = source.read(MAX_INPUT_BYTES + 1)
    except OSError as exc:
        raise RunnerError("input_unavailable") from exc

    if len(data) > MAX_INPUT_BYTES:
        raise RunnerError("input_too_large")
    return data


def write_result(location: str, result: dict) -> None:
    data = json.dumps(result, separators=(",", ":")).encode("utf-8")
    if _is_https(location):
        request = urllib.request.Request(
            location,
            data=data,
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(request, timeout=15):
            pass
    else:
        output = Path(location)
        temporary = output.with_name(output.name + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(output)


def _valid_archive_name(name: str) -> bool:
    parts = name.split("/")
    if name == "job.json":
        return True
    if len(parts) < 2 or len(parts) > 7 or parts[0] not in {"submission", "tests"}:
        return False
    if any(not PYTHON_NAME.fullmatch(part) for part in parts[1:-1]):
        return False
    filename = parts[-1]
    return filename.endswith(".py") and bool(PYTHON_NAME.fullmatch(filename[:-3]))


def _extract_archive(data: bytes, workspace: Path) -> None:
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_FILES:
                raise RunnerError("invalid_archive")

            names: set[str] = set()
            total_size = 0
            for entry in entries:
                if entry.is_dir() or not _valid_archive_name(entry.filename):
                    raise RunnerError("invalid_archive_path")
                if entry.filename in names:
                    raise RunnerError("duplicate_archive_path")
                names.add(entry.filename)
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise RunnerError("invalid_archive_path")
                total_size += entry.file_size
                if total_size > MAX_UNCOMPRESSED_BYTES:
                    raise RunnerError("archive_too_large")

            if "job.json" not in names:
                raise RunnerError("missing_job_metadata")
            if not any(name.startswith("submission/") for name in names):
                raise RunnerError("missing_submission")
            if not any(name.startswith("tests/") for name in names):
                raise RunnerError("missing_tests")

            for entry in entries:
                destination = workspace.joinpath(*entry.filename.split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(entry))
    except (BadZipFile, RuntimeError, ValueError) as exc:
        raise RunnerError("invalid_archive") from exc


def _load_job(workspace: Path) -> tuple[str, str, int]:
    try:
        job = json.loads((workspace / "job.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunnerError("invalid_job_metadata") from exc

    if not isinstance(job, dict) or job.get("schema_version") != 1:
        raise RunnerError("unsupported_job_schema")
    job_id = job.get("job_id")
    mode = job.get("mode")
    timeout = job.get("timeout_seconds")
    if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
        raise RunnerError("invalid_job_metadata")
    if mode not in {"run", "submit"}:
        raise RunnerError("invalid_job_metadata")
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise RunnerError("invalid_job_metadata")
    return job_id, mode, timeout


def _failed_result(job_id: str | None, mode: str | None, code: str) -> dict:
    return {
        "schema_version": 1,
        "job_id": job_id,
        "mode": mode,
        "status": "FAILED",
        "verdict": None,
        "error": {"code": code},
    }


def _parse_report(report: Path, job_id: str, mode: str, duration_ms: int) -> dict:
    try:
        root = ET.parse(report).getroot()
    except (OSError, ET.ParseError) as exc:
        raise RunnerError("missing_test_report") from exc

    cases = list(root.iter("testcase"))
    if not cases:
        raise RunnerError("no_tests_collected")

    summary = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "duration_ms": duration_ms}
    details = []
    for case in cases:
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        if failure is not None:
            status, count_key, detail = "FAILED", "failed", failure
        elif error is not None:
            status, count_key, detail = "ERROR", "errors", error
        elif skipped is not None:
            status, count_key, detail = "SKIPPED", "skipped", skipped
        else:
            status, count_key, detail = "PASSED", "passed", None
        summary[count_key] += 1

        if mode == "run":
            name = ".".join(filter(None, (case.get("classname"), case.get("name"))))
            try:
                seconds = float(case.get("time", "0"))
            except ValueError as exc:
                raise RunnerError("invalid_test_report") from exc
            if not math.isfinite(seconds) or seconds < 0:
                raise RunnerError("invalid_test_report")
            message = "" if detail is None else (detail.text or detail.get("message") or "")
            details.append(
                {
                    "name": name,
                    "status": status,
                    "duration_ms": round(seconds * 1000),
                    "message": message[:MAX_MESSAGE_CHARS],
                }
            )

    failed = any(summary[key] for key in ("failed", "errors", "skipped"))
    verdict = "PASS" if summary["passed"] > 0 and not failed else "FAIL"
    result = {
        "schema_version": 1,
        "job_id": job_id,
        "mode": mode,
        "status": "COMPLETED",
        "verdict": verdict,
        "summary": summary,
    }
    if mode == "run":
        result["tests"] = details
    return result


def process_archive(data: bytes) -> dict:
    if len(data) > MAX_INPUT_BYTES:
        raise RunnerError("input_too_large")

    with tempfile.TemporaryDirectory(prefix="sudosolver-") as directory:
        workspace = Path(directory)
        _extract_archive(data, workspace)
        job_id, mode, timeout = _load_job(workspace)
        tests = sorted((workspace / "tests").rglob("*.py"))
        report = workspace / "report.xml"
        output_log = workspace / "pytest.log"
        environment = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": os.environ.get("HOME", directory),
            "PYTHONPATH": str(workspace / "submission"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "LANG": "C.UTF-8",
        }
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={report}",
            *(str(test) for test in tests),
        ]

        started = time.monotonic()
        with output_log.open("wb") as log:
            process = subprocess.Popen(
                command,
                cwd=workspace / "submission",
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                exit_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                return _failed_result(job_id, mode, "timeout")

        duration_ms = round((time.monotonic() - started) * 1000)
        if exit_code not in {0, 1}:
            return _failed_result(job_id, mode, "test_execution_error")
        try:
            return _parse_report(report, job_id, mode, duration_ms)
        except RunnerError as exc:
            return _failed_result(job_id, mode, exc.code)


def main() -> int:
    input_location = os.environ.pop("RUNNER_INPUT", None)
    output_location = os.environ.pop("RUNNER_OUTPUT", None)
    if not input_location or not output_location:
        print("RUNNER_INPUT and RUNNER_OUTPUT are required", file=sys.stderr)
        return 2

    try:
        result = process_archive(read_input(input_location))
    except RunnerError as exc:
        result = _failed_result(None, None, exc.code)

    try:
        write_result(output_location, result)
    except (OSError, RunnerError) as exc:
        print(f"Could not write result: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
