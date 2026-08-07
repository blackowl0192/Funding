from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def load_runtime_manager() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "runtime_manager.py"
    spec = importlib.util.spec_from_file_location("runtime_manager", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["runtime_manager"] = module
    spec.loader.exec_module(module)
    return module


runtime_manager = load_runtime_manager()


def test_missing_pid_file_returns_none(tmp_path: Path) -> None:
    assert runtime_manager.read_pid_file(tmp_path / "missing.pid") is None


def test_reads_json_pid_file(tmp_path: Path) -> None:
    pid_file = tmp_path / "funding_terminal.pid"
    pid_file.write_text(json.dumps({"pid": 1234}), encoding="utf-8")

    assert runtime_manager.read_pid_file(pid_file) == 1234


def test_stale_pid_file_is_removed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pid_file = tmp_path / "funding_terminal.pid"
    pid_file.write_text("1234", encoding="utf-8")
    monkeypatch.setattr(runtime_manager, "PID_FILE", pid_file)
    monkeypatch.setattr(
        runtime_manager,
        "get_process_info",
        lambda pid: runtime_manager.ProcessInfo(pid=pid, exists=False),
    )

    assert runtime_manager.get_running_pid_from_file() is None
    assert not pid_file.exists()


def test_running_pid_belongs_to_app(monkeypatch: pytest.MonkeyPatch) -> None:
    pid = 1234
    monkeypatch.setattr(
        runtime_manager,
        "get_process_info",
        lambda value: runtime_manager.ProcessInfo(
            pid=value,
            exists=True,
            executable_path=runtime_manager.PYTHON_EXE,
        ),
    )
    monkeypatch.setattr(runtime_manager, "find_pid_by_port", lambda port: pid)
    monkeypatch.setattr(
        runtime_manager,
        "check_health",
        lambda config: runtime_manager.HealthResult(ok=True, status="ok"),
    )

    assert runtime_manager.pid_belongs_to_app(pid) is True


def test_pid_belongs_to_another_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    other_python = tmp_path / "python.exe"
    other_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        runtime_manager,
        "get_process_info",
        lambda pid: runtime_manager.ProcessInfo(
            pid=pid,
            exists=True,
            executable_path=other_python,
        ),
    )

    assert runtime_manager.pid_belongs_to_app(1234) is False


def test_health_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"status":"ok","database":"ok"}'

    monkeypatch.setattr(
        runtime_manager.urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    result = runtime_manager.check_health(runtime_manager.AppConfig("127.0.0.1", 8000))

    assert result.ok is True
    assert result.status == "ok"


def test_health_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_error(*args: Any, **kwargs: Any) -> None:
        raise OSError("connection refused")

    monkeypatch.setattr(runtime_manager.urllib.request, "urlopen", raise_error)

    result = runtime_manager.check_health(runtime_manager.AppConfig("127.0.0.1", 8000))

    assert result.ok is False


def test_port_available() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    assert runtime_manager.is_port_open("127.0.0.1", port) is False


def test_port_occupied() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]

        assert runtime_manager.is_port_open("127.0.0.1", port) is True


def test_missing_env_blocks_start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python_exe = tmp_path / "python.exe"
    python_exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(runtime_manager, "PYTHON_EXE", python_exe)
    monkeypatch.setattr(runtime_manager, "ENV_FILE", tmp_path / ".env")

    with pytest.raises(RuntimeError, match=".env file not found"):
        runtime_manager.ensure_start_requirements()


def test_change_me_blocks_start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python_exe = tmp_path / "python.exe"
    python_exe.write_text("", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql://postgres:CHANGE_ME@127.0.0.1:5432/funding_terminal\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_manager, "PYTHON_EXE", python_exe)
    monkeypatch.setattr(runtime_manager, "ENV_FILE", env_file)

    with pytest.raises(RuntimeError, match="CHANGE_ME"):
        runtime_manager.ensure_start_requirements()


def test_build_popen_kwargs_detaches_stdio_and_environment(tmp_path: Path) -> None:
    log_file = (tmp_path / "funding_terminal.log").open("ab")
    try:
        kwargs = runtime_manager.build_popen_kwargs(log_file)
    finally:
        log_file.close()

    assert kwargs["stdin"] == runtime_manager.subprocess.DEVNULL
    assert kwargs["stdout"] is not runtime_manager.subprocess.PIPE
    assert kwargs["stderr"] == runtime_manager.subprocess.STDOUT
    assert kwargs["cwd"] == runtime_manager.PROJECT_ROOT
    assert isinstance(kwargs["env"], dict)
    assert kwargs["env"] is not runtime_manager.os.environ
    if runtime_manager.os.name == "nt":
        flags = kwargs["creationflags"]
        assert flags & runtime_manager.subprocess.DETACHED_PROCESS
        assert flags & runtime_manager.subprocess.CREATE_NEW_PROCESS_GROUP
        assert flags & runtime_manager.subprocess.CREATE_NO_WINDOW
        assert flags & runtime_manager.subprocess.CREATE_BREAKAWAY_FROM_JOB


def test_launch_server_uses_direct_python_and_does_not_wait(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    class FakePopen:
        pid = 4321

        def __init__(self, command: list[str], **kwargs: Any) -> None:
            captured["command"] = command
            captured["kwargs"] = kwargs

        def wait(self) -> int:
            raise AssertionError("launch_server must not wait for the server process")

    monkeypatch.setattr(runtime_manager, "APP_LOG", tmp_path / "funding_terminal.log")
    monkeypatch.setattr(runtime_manager.subprocess, "Popen", FakePopen)

    process = runtime_manager.launch_server()

    assert process.pid == 4321
    assert captured["command"] == [
        str(runtime_manager.PYTHON_EXE),
        "-m",
        "funding_terminal",
        "run",
    ]
    assert captured["kwargs"]["stdin"] == runtime_manager.subprocess.DEVNULL
    assert captured["kwargs"]["stdout"] is not runtime_manager.subprocess.PIPE


def test_command_line_identity() -> None:
    assert runtime_manager.command_line_belongs_to_app(
        r'C:\Python\python.exe -m funding_terminal run'
    )
    assert not runtime_manager.command_line_belongs_to_app(r"C:\Python\python.exe other.py")


def test_process_command_line_falls_back_to_windows_peb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_manager.os, "name", "nt")
    monkeypatch.setattr(runtime_manager, "process_command_line_from_cim", lambda pid: "")
    monkeypatch.setattr(
        runtime_manager,
        "process_command_line_from_windows_peb",
        lambda pid: r"C:\Python\python.exe -m funding_terminal run",
    )

    assert runtime_manager.process_command_line(1234).endswith("-m funding_terminal run")
