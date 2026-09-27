"""Run one repository test file against a candidate in a disposable OS sandbox."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import selectors
import shutil
import signal
import stat
import subprocess
import time
from typing import Any
from uuid import uuid4
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 256 * 1024
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
MAX_FILES = 4096
MAX_OUTPUT_BYTES = 256 * 1024
MAX_RESULT_BYTES = 1024 * 1024
MAX_WORK_BYTES = 64 * 1024 * 1024
MAX_SECONDS = 45.0
MAX_RSS_KIB = 512 * 1024
_EXCLUDED = {
    ".git",
    ".cache",
    ".venv",
    "node_modules",
    "data",
    "__pycache__",
    ".pytest_cache",
}


class RepositoryExecutionError(ValueError):
    """The selected files or mandatory execution boundary could not be verified."""


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _manifest_hash(manifest: list[dict[str, Any]]) -> str:
    return _hash(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())


def _root(root: Path) -> Path:
    path = Path(root).absolute()
    if not path.is_dir() or path.is_symlink() or path.resolve() != path:
        raise RepositoryExecutionError(
            "Repository root must be an existing directory without symlink aliases"
        )
    return path


def _relative_file(value: str, directory: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise RepositoryExecutionError(f"Select a relative {directory}/ Python file")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or ".." in path.parts
        or len(path.parts) < 2
        or path.parts[0] != directory
        or path.suffix != ".py"
        or any(part in _EXCLUDED or part.startswith(".env") for part in path.parts)
    ):
        raise RepositoryExecutionError(
            f"Select a relative {directory}/ Python file without traversal or hidden runtime directories"
        )
    return value


def _read_file(root: Path, relative: str) -> bytes:
    """Open every path component without following symlinks."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = PurePosixPath(relative).parts
        for part in parts[:-1]:
            following = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = following
        child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
        try:
            before = os.fstat(child)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
                raise RepositoryExecutionError(
                    f"Snapshot file is not a bounded regular file: {relative}"
                )
            chunks, size = [], 0
            while block := os.read(child, 65536):
                size += len(block)
                if size > MAX_FILE_BYTES:
                    raise RepositoryExecutionError(f"Snapshot file exceeds 2 MiB: {relative}")
                chunks.append(block)
            after = os.fstat(child)
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RepositoryExecutionError(
                    "Repository files changed while being inspected; inspect again"
                )
            return b"".join(chunks)
        finally:
            os.close(child)
    except OSError as exc:
        raise RepositoryExecutionError(
            f"Cannot snapshot {relative}; missing files and symlinks are rejected"
        ) from exc
    finally:
        os.close(descriptor)


def _snapshot_files(root: Path) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    paths: list[str] = ["pyproject.toml"]

    def visit(directory: Path):
        if directory.is_symlink() or not directory.is_dir():
            raise RepositoryExecutionError("Snapshot directories must exist and cannot be symlinks")
        for path in sorted(directory.iterdir()):
            if (
                path.name in _EXCLUDED
                or path.name.startswith(".env")
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            if path.is_symlink():
                raise RepositoryExecutionError(
                    f"Snapshot symlinks are not allowed: {path.relative_to(root)}"
                )
            if path.is_dir():
                visit(path)
            elif path.is_file():
                paths.append(path.relative_to(root).as_posix())
            else:
                raise RepositoryExecutionError(
                    "Snapshot may contain only regular files and directories"
                )
            if len(paths) > MAX_FILES:
                raise RepositoryExecutionError("Repository snapshot exceeds 4096 files")

    for name in ("backend", "tests"):
        visit(root / name)
    files, manifest, size = {}, [], 0
    for relative in sorted(paths):
        content = _read_file(root, relative)
        size += len(content)
        if size > MAX_SNAPSHOT_BYTES:
            raise RepositoryExecutionError("Repository snapshot exceeds 32 MiB")
        files[relative] = content
        manifest.append({"path": relative, "sha256": _hash(content), "bytes": len(content)})
    return files, manifest


def inspect_repository_case(
    relative_file: str, test_path: str, *, root: Path = ROOT
) -> dict[str, Any]:
    """Inspect only this repository, or an explicit controlled root supplied by tests."""
    root = _root(root)
    relative_file = _relative_file(relative_file, "backend")
    test_path = _relative_file(test_path, "tests")
    files, manifest = _snapshot_files(root)
    if relative_file not in files or test_path not in files:
        raise RepositoryExecutionError("Selected source and test files must exist in the snapshot")
    if len(files[relative_file]) > MAX_SOURCE_BYTES or len(files[test_path]) > MAX_SOURCE_BYTES:
        raise RepositoryExecutionError(
            "Selected source and test files must each be at most 256 KiB"
        )
    try:
        source, test_content = (
            files[relative_file].decode("utf-8"),
            files[test_path].decode("utf-8"),
        )
    except UnicodeDecodeError as exc:
        raise RepositoryExecutionError("Selected Python files must be UTF-8") from exc
    return {
        "kind": "repository",
        "repository_root": str(root),
        "relative_file": relative_file,
        "test_path": test_path,
        "source": source,
        "test_content": test_content,
        "source_hash": _hash(files[relative_file]),
        "test_hash": _hash(files[test_path]),
        "snapshot_manifest": manifest,
        "snapshot_hash": _manifest_hash(manifest),
    }


def _runtime() -> tuple[Path, Path, Path]:
    # Controlled fixture repositories use this project's installed test runtime.
    environment = ROOT / ".venv"
    interpreter = environment / "bin" / "python"
    if not interpreter.is_file():
        raise RepositoryExecutionError(
            "Install the project environment with uv sync before running repository checks"
        )
    resolved = interpreter.resolve()
    return interpreter, environment.resolve(), resolved.parent.parent


def _profile(source: Path, work: Path) -> tuple[Path, str]:
    if platform.system() != "Darwin" or not shutil.which("sandbox-exec"):
        raise RepositoryExecutionError(
            "Repository execution requires macOS sandbox-exec; no unisolated fallback is enabled"
        )
    interpreter, environment, runtime = _runtime()
    subpaths = " ".join(
        f"(subpath {json.dumps(str(path))})"
        for path in (
            Path("/System/Library"),
            Path("/usr/lib"),
            environment,
            runtime,
            source,
            work,
        )
    )
    profile = (
        "(version 1)(allow default)(deny network*)(deny file-write*)"
        "(deny process-fork)(deny mach-lookup)(deny signal)(deny process-info*)"
        "(deny process-exec)(allow process-exec (literal "
        + json.dumps(str(interpreter.resolve()))
        + "))"
        "(deny file-read-data (vnode-type REGULAR-FILE))(allow file-read-data " + subpaths + ")"
        "(allow file-write* (subpath " + json.dumps(str(work)) + "))"
    )
    return interpreter, profile


def _terminate(process: subprocess.Popen):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=2)


def _check_work_budget(root: Path):
    size, entries = 0, 0

    def visit(descriptor: int, depth: int):
        nonlocal size, entries
        if depth > 32:
            raise RepositoryExecutionError(
                "Disposable work space exceeds the directory-depth limit"
            )
        with os.scandir(descriptor) as children:
            for child in children:
                entries += 1
                if entries > MAX_FILES:
                    raise RepositoryExecutionError(
                        "Disposable work space exceeded its 4096-entry limit"
                    )
                try:
                    info = child.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    try:
                        following = os.open(
                            child.name,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor,
                        )
                    except FileNotFoundError:
                        continue
                    try:
                        visit(following, depth + 1)
                    finally:
                        os.close(following)
                elif stat.S_ISREG(info.st_mode):
                    size += info.st_size
                    if size > MAX_WORK_BYTES:
                        raise RepositoryExecutionError(
                            "Disposable work space exceeded its 64 MiB threshold"
                        )

    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        visit(descriptor, 0)
    finally:
        os.close(descriptor)


def _invoke(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout: float,
    work: Path | None = None,
) -> dict[str, Any]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    output = {"stdout": bytearray(), "stderr": bytearray()}
    deadline, next_memory = time.monotonic() + timeout, 0.0
    error = None
    try:
        for stream, label in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, label)
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise RepositoryExecutionError(
                    "Repository tests exceeded the wall-time limit; the sandbox was terminated"
                )
            if time.monotonic() >= next_memory and process.poll() is None:
                measured = subprocess.run(
                    ["/bin/ps", "-o", "rss=", "-p", str(process.pid)],
                    capture_output=True,
                    text=True,
                    timeout=0.3,
                    env={"PATH": "/usr/bin:/bin", "LANG": "C"},
                )
                value = measured.stdout.strip()
                if (measured.returncode or not value.isdigit()) and process.poll() is None:
                    raise RepositoryExecutionError(
                        "Resident-memory observation failed; execution was stopped"
                    )
                if value.isdigit() and int(value) > MAX_RSS_KIB:
                    raise RepositoryExecutionError(
                        "Repository tests exceeded the 512 MiB RSS threshold; the sandbox was terminated"
                    )
                if work is not None:
                    _check_work_budget(work)
                next_memory = time.monotonic() + 0.1
            for key, _ in selector.select(timeout=0.05):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                available = MAX_OUTPUT_BYTES - sum(len(value) for value in output.values())
                output[key.data].extend(chunk[:available])
                if len(chunk) > available:
                    raise RepositoryExecutionError(
                        "Repository tests exceeded the 256 KiB output limit; the sandbox was terminated"
                    )
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
    except (OSError, subprocess.SubprocessError, RepositoryExecutionError) as exc:
        error = str(exc)
    finally:
        selector.close()
        _terminate(process)
        for stream in (process.stdout, process.stderr):
            if stream and not stream.closed:
                stream.close()
    return {
        "exit_code": process.returncode,
        "stdout": output["stdout"].decode(errors="replace"),
        "stderr": output["stderr"].decode(errors="replace"),
        "error": error,
    }


_PROBE = r"""
import errno,json,os,socket,sys
def denied(action):
    try:
        result=action()
        if hasattr(result,"close"): result.close()
        return False
    except OSError as exc:
        return exc.errno in (errno.EPERM,errno.EACCES)
def network():
    with socket.socket() as connection: connection.connect(("127.0.0.1",9))
alternate="/System/Volumes/Data/private/etc/passwd"
answer={"host_read_denied":denied(lambda:open("/etc/passwd","rb")),
        "alternate_read_denied":denied(lambda:open(alternate,"rb")) if os.path.exists(alternate) else True,
        "outside_write_denied":denied(lambda:open("/dev/null","wb")),
        "source_write_denied":denied(lambda:open(sys.argv[1],"r+b")),
        "network_denied":denied(network),
        "signal_denied":denied(lambda:os.kill(os.getppid(),0))}
with open(sys.argv[2],"w") as stream: stream.write("sandbox probe")
os.unlink(sys.argv[2])
answer["scratch_write_allowed"]=True
print(json.dumps(answer))
"""

_PYTEST = r"""
import resource,runpy,sys
resource.setrlimit(resource.RLIMIT_CPU,(30,30))
resource.setrlimit(resource.RLIMIT_FSIZE,(4194304,4194304))
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
sys.argv=["pytest",*sys.argv[1:]]
runpy.run_module("pytest",run_name="__main__")
"""


def _checks(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_RESULT_BYTES:
        raise RepositoryExecutionError(
            "Pytest did not produce a bounded test report; success is unconfirmed"
        )
    try:
        document = ET.fromstring(path.read_bytes())
    except ET.ParseError as exc:
        raise RepositoryExecutionError("Pytest returned an invalid test report") from exc
    checks = []
    for case in document.iter("testcase"):
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        issue = failure if failure is not None else error
        status = "failed" if issue is not None else "skipped" if skipped is not None else "passed"
        checks.append(
            {
                "name": f"{case.get('classname', '')}::{case.get('name', '')}"[:500],
                "status": status,
                "passed": status == "passed",
                "detail": (
                    issue.get("message", "")
                    if issue is not None
                    else skipped.get("message", "")
                    if skipped is not None
                    else ""
                )[:2000],
            }
        )
    if not checks:
        raise RepositoryExecutionError("No collected tests were recorded; success is unconfirmed")
    return checks


def run_repository_candidate(
    case: dict[str, Any], code: str, *, root: Path = ROOT
) -> dict[str, Any]:
    """Apply only the chosen file in a fresh snapshot and run the chosen pytest file."""
    start = time.monotonic()
    report: dict[str, Any] = {
        "status": "error",
        "exit_code": None,
        "checks": [],
        "passed": 0,
        "total": 0,
        "skipped": 0,
        "stdout": "",
        "stderr": "",
        "duration_ms": 0,
        "code_hash": _hash(code.encode()) if isinstance(code, str) else None,
        "diff": "",
        "isolation": {"kind": "macos-seatbelt", "enforced": False},
    }
    scratch = None
    try:
        root = _root(root)
        if not isinstance(code, str) or not code.strip() or len(code.encode()) > MAX_SOURCE_BYTES:
            raise RepositoryExecutionError(
                "Candidate source must be nonempty UTF-8 text of at most 256 KiB"
            )
        if not isinstance(case, dict) or case.get("repository_root") != str(root):
            raise RepositoryExecutionError(
                "Repository case does not belong to the explicitly selected root"
            )
        current = inspect_repository_case(
            case.get("relative_file"), case.get("test_path"), root=root
        )
        if any(
            current.get(key) != case.get(key)
            for key in (
                "kind",
                "source",
                "test_content",
                "source_hash",
                "test_hash",
                "snapshot_hash",
                "snapshot_manifest",
            )
        ):
            raise RepositoryExecutionError(
                "The inspected repository snapshot changed; inspect the files again before verification"
            )
        files, manifest = _snapshot_files(root)
        if _manifest_hash(manifest) != case["snapshot_hash"]:
            raise RepositoryExecutionError(
                "Repository changed while creating the snapshot; inspect again"
            )
        report["snapshot_hash"] = case["snapshot_hash"]
        report["diff"] = "".join(
            difflib.unified_diff(
                case["source"].splitlines(keepends=True),
                code.splitlines(keepends=True),
                fromfile="a/" + case["relative_file"],
                tofile="b/" + case["relative_file"],
            )
        )
        cache = root
        for name in (".cache", "repository-runs"):
            cache = cache / name
            if cache.is_symlink():
                raise RepositoryExecutionError("Repository scratch directories cannot be symlinks")
            cache.mkdir(exist_ok=True)
        scratch = cache / str(uuid4())
        source, work = scratch / "source", scratch / "work"
        source.mkdir(parents=True)
        work.mkdir()
        for name in ("home", "tmp"):
            (work / name).mkdir()
        for relative, content in files.items():
            destination = source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        (source / case["relative_file"]).write_text(code, encoding="utf-8")
        interpreter, profile = _profile(source, work)
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(work / "home"),
            "TMPDIR": str(work / "tmp"),
            "TMP": str(work / "tmp"),
            "TEMP": str(work / "tmp"),
            "LANG": "C",
            "LC_ALL": "C",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
        command = [shutil.which("sandbox-exec"), "-p", profile, str(interpreter), "-I", "-B", "-c"]
        probe = _invoke(
            [*command, _PROBE, str(source / case["relative_file"]), str(work / ".probe")],
            cwd=source,
            environment=environment,
            timeout=5,
            work=work,
        )
        try:
            proof = json.loads(probe["stdout"])
        except (json.JSONDecodeError, TypeError):
            proof = {}
        expected_checks = {
            "host_read_denied",
            "alternate_read_denied",
            "outside_write_denied",
            "source_write_denied",
            "network_denied",
            "signal_denied",
            "scratch_write_allowed",
        }
        if (
            probe["exit_code"] != 0
            or probe["error"]
            or not isinstance(proof, dict)
            or set(proof) != expected_checks
            or not all(value is True for value in proof.values())
        ):
            raise RepositoryExecutionError(
                "OS isolation self-check failed; repository tests were not run. No unsafe fallback is enabled"
            )
        report["isolation"] = {
            "kind": "macos-seatbelt",
            "enforced": True,
            "checks": proof,
            "detail": "Snapshot and runtime reads only; writes confined to disposable work space. Network, signals, and child processes denied. CPU/wall/output limits. RSS 512 MiB and scratch 64 MiB thresholds sampled every 100ms; brief allocation spikes remain possible.",
        }
        result_path = work / "pytest-results.xml"
        result = _invoke(
            [
                *command,
                _PYTEST,
                "-q",
                "--tb=short",
                "--disable-warnings",
                "-p",
                "no:cacheprovider",
                "-p",
                "pytest_asyncio.plugin",
                "-c",
                str(source / "pyproject.toml"),
                "--rootdir",
                str(source),
                "--confcutdir",
                str(source),
                "-o",
                "addopts=",
                "-o",
                "pythonpath=backend",
                "--basetemp",
                str(work / "pytest-tmp"),
                "--log-file",
                str(work / "pytest.log"),
                "--junitxml",
                str(result_path),
                "--",
                case["test_path"],
            ],
            cwd=source,
            environment=environment,
            timeout=MAX_SECONDS,
            work=work,
        )
        report.update(result)
        if result["error"]:
            raise RepositoryExecutionError(result["error"])
        checks = _checks(result_path)
        report.update(
            checks=checks,
            total=len(checks),
            passed=sum(item["passed"] for item in checks),
            skipped=sum(item["status"] == "skipped" for item in checks),
        )
        if (
            result["exit_code"] == 0
            and report["passed"]
            and report["passed"] + report["skipped"] == report["total"]
        ):
            report["status"] = "passed"
        elif result["exit_code"] == 1:
            report["status"] = "failed"
        else:
            raise RepositoryExecutionError(
                "Pytest did not confirm an executed passing or failing test run; inspect its output"
            )
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        report["status"] = "error"
        report["error"] = str(exc)[:1500]
    finally:
        if scratch is not None:
            try:
                shutil.rmtree(scratch)
            except OSError:
                report["status"] = "error"
                report["cleanup_error"] = (
                    "Disposable snapshot cleanup failed; inspect .cache/repository-runs before retrying"
                )
        report["duration_ms"] = round((time.monotonic() - start) * 1000, 2)
    return report
