"""Load and validate prebuilt Python problem packages."""

import json
import re
from dataclasses import dataclass
from pathlib import Path


PROBLEM_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
PYTHON_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
MAX_SOURCE_BYTES = 64_000
MAX_INSTRUCTIONS_BYTES = 32_000


class PackageError(Exception):
    pass


@dataclass(frozen=True)
class ProblemPackage:
    id: str
    title: str
    difficulty: str
    estimated_minutes: int
    instructions: str
    starter_files: dict[str, str]
    visible_tests: dict[str, bytes]
    hidden_tests: dict[str, bytes]

    def catalog_entry(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "difficulty": self.difficulty,
            "estimatedMinutes": self.estimated_minutes,
            "language": "python",
        }

    def public_detail(self) -> dict:
        return {
            **self.catalog_entry(),
            "instructions": self.instructions,
            "files": self.starter_files.copy(),
            "visibleTests": {
                path.removeprefix("tests/"): content.decode("utf-8")
                for path, content in self.visible_tests.items()
            },
        }


def _file_path(root: Path, raw: object, prefix: str, suffix: str) -> Path:
    if not isinstance(raw, str):
        raise PackageError("invalid package path")
    parts = raw.split("/")
    if len(parts) < 2 or len(parts) > 7 or parts[0] != prefix:
        raise PackageError("invalid package path")
    if any(not PYTHON_NAME.fullmatch(part) for part in parts[1:-1]):
        raise PackageError("invalid package path")
    if not parts[-1].endswith(suffix):
        raise PackageError("invalid package path")
    if not PYTHON_NAME.fullmatch(parts[-1][: -len(suffix)]):
        raise PackageError("invalid package path")
    path = root.joinpath(*parts)
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise PackageError("missing or unsafe package file")
    return path


def _paths(manifest: dict, key: str) -> list[str]:
    value = manifest.get(key)
    if not isinstance(value, list) or not value or len(value) > 20:
        raise PackageError(f"invalid {key}")
    if any(not isinstance(path, str) for path in value) or len(set(value)) != len(value):
        raise PackageError(f"invalid {key}")
    return value


def _read_text(path: Path, limit: int) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PackageError("unreadable package file") from exc
    if len(data) > limit:
        raise PackageError("package file too large")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackageError("package file is not UTF-8") from exc


def load_problem(examples_root: Path, problem_id: str) -> ProblemPackage:
    if not PROBLEM_ID.fullmatch(problem_id):
        raise PackageError("unknown problem")
    root = examples_root / problem_id
    if not root.is_dir() or root.is_symlink():
        raise PackageError("unknown problem")
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackageError("invalid manifest") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise PackageError("unsupported package schema")
    if manifest.get("id") != problem_id or manifest.get("language") != "python":
        raise PackageError("invalid package identity")
    title = manifest.get("title")
    difficulty = manifest.get("difficulty")
    minutes = manifest.get("estimated_minutes")
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise PackageError("invalid package title")
    if difficulty not in {"easy", "medium", "hard"}:
        raise PackageError("invalid package difficulty")
    if type(minutes) is not int or not 1 <= minutes <= 240:
        raise PackageError("invalid estimated duration")

    instructions_name = manifest.get("instructions")
    if instructions_name != "instructions.md":
        raise PackageError("invalid instructions path")
    instructions_file = root / instructions_name
    if instructions_file.is_symlink() or not instructions_file.is_file():
        raise PackageError("missing instructions")
    instructions = _read_text(instructions_file, MAX_INSTRUCTIONS_BYTES)

    starter_paths = _paths(manifest, "starter_files")
    visible_paths = _paths(manifest, "visible_tests")
    hidden_paths = _paths(manifest, "hidden_tests")
    starter_files: dict[str, str] = {}
    visible_tests: dict[str, bytes] = {}
    hidden_tests: dict[str, bytes] = {}
    for raw in starter_paths:
        path = _file_path(root, raw, "starter", ".py")
        workspace_name = raw.removeprefix("starter/")
        starter_files[workspace_name] = _read_text(path, MAX_SOURCE_BYTES)
    for raw in visible_paths:
        path = _file_path(root, raw, "tests", ".py")
        visible_tests[raw] = _read_text(path, MAX_SOURCE_BYTES).encode("utf-8")
    for raw in hidden_paths:
        path = _file_path(root, raw, "tests", ".py")
        hidden_tests[raw] = _read_text(path, MAX_SOURCE_BYTES).encode("utf-8")
    if set(visible_paths) & set(hidden_paths):
        raise PackageError("visible and hidden tests overlap")

    references = manifest.get("reference_files")
    if not isinstance(references, dict) or not set(references).issubset(starter_paths):
        raise PackageError("invalid reference files")
    for raw in references.values():
        _read_text(_file_path(root, raw, "reference", ".py"), MAX_SOURCE_BYTES)

    return ProblemPackage(
        id=problem_id,
        title=title,
        difficulty=difficulty,
        estimated_minutes=minutes,
        instructions=instructions,
        starter_files=starter_files,
        visible_tests=visible_tests,
        hidden_tests=hidden_tests,
    )


def list_problems(examples_root: Path) -> list[ProblemPackage]:
    return [
        load_problem(examples_root, path.name)
        for path in sorted(examples_root.iterdir())
        if path.is_dir() and not path.name.startswith(".")
    ]
