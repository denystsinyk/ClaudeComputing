import io
import json
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from build_example_job import build_job
from runner import RunnerError, process_archive, read_input, write_result


def make_job(files: dict[str, str], *, mode: str = "run", timeout: int = 10) -> bytes:
    buffer = io.BytesIO()
    metadata = {"schema_version": 1, "job_id": "test-job", "mode": mode, "timeout_seconds": timeout}
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("job.json", json.dumps(metadata))
        for name, contents in files.items():
            archive.writestr(name, contents)
    return buffer.getvalue()


def test_reference_passes_visible_tests() -> None:
    result = process_archive(build_job("run", "reference", "test-job"))

    assert result["status"] == "COMPLETED"
    assert result["verdict"] == "PASS"
    assert result["summary"]["passed"] == 4
    assert len(result["tests"]) == 4


def test_starter_fails_visible_tests() -> None:
    result = process_archive(build_job("run", "starter", "test-job"))

    assert result["status"] == "COMPLETED"
    assert result["verdict"] == "FAIL"
    assert result["summary"]["failed"] == 4
    assert all(test["message"] for test in result["tests"])


def test_submission_result_does_not_reveal_hidden_test_details() -> None:
    result = process_archive(build_job("submit", "reference", "test-job"))

    assert result["status"] == "COMPLETED"
    assert result["verdict"] == "PASS"
    assert result["summary"]["passed"] == 5
    assert "tests" not in result
    assert "hidden_cases" not in json.dumps(result)


def test_failed_submission_still_hides_hidden_test_details() -> None:
    result = process_archive(build_job("submit", "starter", "test-job"))

    assert result["status"] == "COMPLETED"
    assert result["verdict"] == "FAIL"
    assert result["summary"]["failed"] > 0
    assert "tests" not in result
    assert "hidden_cases" not in json.dumps(result)


def test_archive_path_traversal_is_rejected() -> None:
    archive = make_job(
        {
            "submission/task.py": "pass",
            "tests/cases.py": "def test_ok(): assert True",
            "submission/../escaped.py": "pass",
        }
    )

    with pytest.raises(RunnerError, match="invalid_archive_path"):
        process_archive(archive)


def test_missing_tests_are_rejected() -> None:
    with pytest.raises(RunnerError, match="missing_tests"):
        process_archive(make_job({"submission/task.py": "pass"}))


def test_invalid_job_metadata_is_rejected() -> None:
    archive = make_job(
        {
            "submission/task.py": "pass",
            "tests/cases.py": "def test_ok(): assert True",
        },
        timeout=0,
    )

    with pytest.raises(RunnerError, match="invalid_job_metadata"):
        process_archive(archive)


def test_timeout_is_a_failed_job() -> None:
    archive = make_job(
        {
            "submission/task.py": "pass",
            "tests/cases.py": "def test_hangs():\n    while True:\n        pass\n",
        },
        timeout=1,
    )

    result = process_archive(archive)

    assert result["status"] == "FAILED"
    assert result["error"] == {"code": "timeout"}


def test_user_code_does_not_inherit_host_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "not-for-submitted-code")
    archive = make_job(
        {
            "submission/task.py": "pass",
            "tests/cases.py": (
                "import os\n"
                "def test_environment():\n"
                "    assert 'AWS_SECRET_ACCESS_KEY' not in os.environ\n"
                "    assert 'RUNNER_INPUT' not in os.environ\n"
            ),
        }
    )

    assert process_archive(archive)["verdict"] == "PASS"


def test_https_transport_uses_get_and_json_put(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return io.BytesIO(b"job bytes")

    monkeypatch.setattr("runner.urllib.request.urlopen", fake_urlopen)

    assert read_input("https://example.invalid/input") == b"job bytes"
    write_result("https://example.invalid/output", {"status": "COMPLETED"})

    assert requests[0][0] == "https://example.invalid/input"
    assert requests[1][0].get_method() == "PUT"
    assert requests[1][0].get_header("Content-type") == "application/json"
    assert json.loads(requests[1][0].data) == {"status": "COMPLETED"}
