from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "Funding Terminal"
PID_FILE = PROJECT_ROOT / "runtime" / "funding_terminal.pid"
APP_LOG = PROJECT_ROOT / "logs" / "funding_terminal.log"
MANAGER_LOG = PROJECT_ROOT / "logs" / "runtime_manager.log"
PYTHON_EXE = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
BASE_PYTHON_EXE = Path(getattr(sys, "_base_executable", sys.executable))
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
STARTUP_TIMEOUT_SECONDS = 15
STOP_TIMEOUT_SECONDS = 10
DETACHED_CREATION_FLAGS = (
    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    | getattr(subprocess, "DETACHED_PROCESS", 0)
    | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
)


@dataclass(frozen=True, slots=True)
class AppConfig:
    host: str
    port: int

    @property
    def url(self) -> str:
        return f"http://{self.browser_host}:{self.port}"

    @property
    def health_url(self) -> str:
        return f"{self.url}/health"

    @property
    def socket_host(self) -> str:
        return "127.0.0.1" if self.host == "0.0.0.0" else self.host

    @property
    def browser_host(self) -> str:
        return "127.0.0.1" if self.host == "0.0.0.0" else self.host


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    pid: int
    exists: bool
    executable_path: Path | None = None


@dataclass(frozen=True, slots=True)
class HealthResult:
    ok: bool
    status: str = "ERROR"
    payload: dict[str, Any] | None = None
    error: str = ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Funding Terminal runtime manager")
    parser.add_argument("command", choices=["start", "stop", "restart", "status", "open-browser"])
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args(argv)

    ensure_runtime_dirs()
    write_manager_log(f"command={args.command}")

    try:
        if args.command == "start":
            return start(open_browser=args.open_browser)
        if args.command == "stop":
            return stop()
        if args.command == "restart":
            return restart(open_browser=args.open_browser)
        if args.command == "status":
            return status()
        if args.command == "open-browser":
            return open_browser()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        write_manager_log(f"error={exc}")
        return 1
    return 1


def start(*, open_browser: bool = False) -> int:
    ensure_start_requirements()
    config = load_app_config()
    running_pid = get_running_pid_from_file()

    if running_pid is not None:
        health = check_health(config)
        print("Funding Terminal is already running.")
        print(f"PID: {running_pid}")
        print(f"URL: {config.url}")
        if open_browser:
            open_url(config.url)
        return 0 if health.ok else 1

    remove_stale_pid_if_needed()
    health = check_health(config)
    if health.ok:
        port_pid = find_pid_by_port(config.port)
        if port_pid is not None and pid_belongs_to_app(port_pid):
            write_pid_file(port_pid, config)
        print("Funding Terminal is already running, but PID file is missing.")
        print(f"PID: {port_pid or 'unknown'}")
        print(f"URL: {config.url}")
        if open_browser:
            open_url(config.url)
        return 0

    if is_port_open(config.socket_host, config.port):
        print(f"Port {config.port} is already in use.")
        print("It is not responding as Funding Terminal. Start aborted.")
        return 1

    db_check = run_cli(["check-db"])
    if db_check.returncode != 0:
        print("Database check failed. Start aborted.")
        print_cli_output(db_check)
        return 1

    append_start_separator()
    process = launch_server()
    write_pid_file(process.pid, config)

    if wait_for_health(config, process.pid, STARTUP_TIMEOUT_SECONDS):
        server_pid = find_pid_by_port(config.port) or process.pid
        write_pid_file(server_pid, config)
        print("Funding Terminal started successfully.")
        print(f"PID: {server_pid}")
        print(f"URL: {config.url}")
        if open_browser:
            open_url(config.url)
        return 0

    print("Startup failed.")
    if not process_is_running(process.pid):
        delete_pid_file()
    else:
        terminate_process_tree(process.pid)
        delete_pid_file()
    print_log_tail(APP_LOG, line_count=40)
    return 1


def stop() -> int:
    config = load_app_config()
    pid = read_pid_file()
    if pid is None:
        health = check_health(config)
        if not health.ok:
            print("Funding Terminal is not running.")
            return 0
        port_pid = find_pid_by_port(config.port)
        if port_pid is None or not pid_belongs_to_app(port_pid):
            print("Funding Terminal appears to be running, but no safe PID was found.")
            print("Stop aborted to avoid terminating an unrelated process.")
            return 1
        pid = port_pid

    info = get_process_info(pid)
    if not info.exists:
        delete_pid_file()
        print("Funding Terminal is not running.")
        return 0

    if not pid_belongs_to_app(pid):
        delete_pid_file()
        port_pid = find_pid_by_port(config.port)
        if port_pid is None or not pid_belongs_to_app(port_pid):
            print(f"Stale PID file removed. PID {pid} does not belong to Funding Terminal.")
            return 0
        pid = port_pid

    graceful_shutdown(pid)
    if wait_until_stopped(pid, STOP_TIMEOUT_SECONDS):
        if not ensure_health_stopped(config, original_pid=pid):
            print("Stop failed. Health endpoint is still responding.")
            return 1
        delete_pid_file()
        print("Funding Terminal stopped.")
        return 0

    print("Graceful shutdown timed out. Stopping process tree by PID.")
    terminate_process_tree(pid)
    port_pid = find_pid_by_port(config.port)
    if port_pid is not None and port_pid != pid and pid_belongs_to_app(port_pid):
        terminate_process_tree(port_pid)
    wait_until_stopped(pid, STOP_TIMEOUT_SECONDS)
    if not ensure_health_stopped(config, original_pid=pid):
        print("Stop failed. Health endpoint is still responding.")
        return 1
    delete_pid_file()
    print("Funding Terminal stopped.")
    return 0


def restart(*, open_browser: bool = False) -> int:
    print("Stopping Funding Terminal...")
    stop_code = stop()
    if stop_code != 0:
        return stop_code
    time.sleep(1)
    print()
    print("Starting Funding Terminal...")
    return start(open_browser=open_browser)


def status() -> int:
    config = load_app_config()
    pid = get_running_pid_from_file()
    if pid is None:
        pid = find_pid_by_port(config.port)
        if pid is not None and not pid_belongs_to_app(pid):
            pid = None

    health = check_health(config)
    process_state = "RUNNING" if pid is not None and process_is_running(pid) else "STOPPED"
    if process_state == "STOPPED" and health.ok:
        process_state = "RUNNING"

    print("Funding Terminal")
    print(f"Process: {process_state}")
    print(f"PID: {pid if pid is not None else '-'}")
    print(f"HTTP: {'OK' if health.ok else 'ERROR'}")
    print(f"URL: {config.url}")

    app_status = run_cli(["status"])
    dependency_lines = extract_dependency_lines(app_status.stdout + app_status.stderr)
    if dependency_lines:
        for line in dependency_lines:
            print(line)
    else:
        print("Database: ERROR")
        print("Binance Spot: ERROR")
        print("Binance Futures: ERROR")
    return 0


def open_browser() -> int:
    config = load_app_config()
    open_url(config.url)
    print(f"Opened {config.url}")
    return 0


def ensure_runtime_dirs() -> None:
    (PROJECT_ROOT / "runtime").mkdir(exist_ok=True)
    (PROJECT_ROOT / "logs").mkdir(exist_ok=True)


def ensure_start_requirements() -> None:
    if not PYTHON_EXE.exists():
        raise RuntimeError("Virtual environment not found. Run scripts\\setup_local.ps1 first.")
    if not ENV_FILE.exists():
        raise RuntimeError(".env file not found. Run scripts\\setup_local.ps1 first.")
    env = load_env()
    database_url = env.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is missing in .env.")
    if "CHANGE_ME" in database_url:
        raise RuntimeError("DATABASE_URL contains CHANGE_ME. Edit .env first.")


def load_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def load_app_config() -> AppConfig:
    env = load_env()
    host = env.get("APP_HOST", DEFAULT_HOST) or DEFAULT_HOST
    raw_port = env.get("APP_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_port)
    except ValueError:
        port = DEFAULT_PORT
    return AppConfig(host=host, port=port)


def windows_creation_flags() -> int:
    return DETACHED_CREATION_FLAGS if os.name == "nt" else 0


def build_popen_kwargs(log_file) -> dict[str, Any]:  # noqa: ANN001
    return {
        "cwd": PROJECT_ROOT,
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "creationflags": windows_creation_flags(),
        "close_fds": True,
        "env": os.environ.copy(),
    }


def launch_server() -> subprocess.Popen[bytes]:
    with APP_LOG.open("ab") as log_file:
        return subprocess.Popen(
            launch_command(),
            **build_popen_kwargs(log_file),
        )


def process_command_line(pid: int) -> str:
    if os.name != "nt":
        return ""
    command_line = process_command_line_from_cim(pid)
    if command_line:
        return command_line
    return process_command_line_from_windows_peb(pid)


def process_command_line_from_cim(pid: int) -> str:
    command = (
        "$p = Get-CimInstance Win32_Process -Filter "
        f"'ProcessId = {pid}' -ErrorAction SilentlyContinue; "
        "if ($p) { $p.CommandLine }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def process_command_line_from_windows_peb(pid: int) -> str:
    try:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        process_vm_read = 0x0010

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll")

        class ProcessBasicInformation(ctypes.Structure):
            _fields_ = [
                ("reserved1", ctypes.c_void_p),
                ("peb_base_address", ctypes.c_void_p),
                ("reserved2", ctypes.c_void_p * 2),
                ("unique_process_id", ctypes.c_void_p),
                ("reserved3", ctypes.c_void_p),
            ]

        class UnicodeString(ctypes.Structure):
            _fields_ = [
                ("length", wintypes.USHORT),
                ("maximum_length", wintypes.USHORT),
                ("buffer", ctypes.c_void_p),
            ]

        open_process = kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE

        read_process_memory = kernel32.ReadProcessMemory
        read_process_memory.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        read_process_memory.restype = wintypes.BOOL

        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        nt_query_information_process = ntdll.NtQueryInformationProcess
        nt_query_information_process.argtypes = [
            wintypes.HANDLE,
            wintypes.ULONG,
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        ]
        nt_query_information_process.restype = ctypes.c_long

        handle = open_process(process_query_limited_information | process_vm_read, False, pid)
        if not handle:
            return ""
        try:

            def read_memory(address: int, size: int) -> bytes | None:
                buffer = (ctypes.c_ubyte * size)()
                bytes_read = ctypes.c_size_t()
                ok = read_process_memory(
                    handle,
                    ctypes.c_void_p(address),
                    buffer,
                    size,
                    ctypes.byref(bytes_read),
                )
                if not ok:
                    return None
                return bytes(buffer[: bytes_read.value])

            process_info = ProcessBasicInformation()
            returned_length = wintypes.ULONG()
            status = nt_query_information_process(
                handle,
                0,
                ctypes.byref(process_info),
                ctypes.sizeof(process_info),
                ctypes.byref(returned_length),
            )
            if status != 0 or not process_info.peb_base_address:
                return ""

            pointer_size = ctypes.sizeof(ctypes.c_void_p)
            process_parameters_offset = 0x20 if pointer_size == 8 else 0x10
            command_line_offset = 0x70 if pointer_size == 8 else 0x40

            process_parameters_data = read_memory(
                process_info.peb_base_address + process_parameters_offset,
                pointer_size,
            )
            if not process_parameters_data:
                return ""
            process_parameters_address = int.from_bytes(process_parameters_data, "little")
            if not process_parameters_address:
                return ""

            command_line_data = read_memory(
                process_parameters_address + command_line_offset,
                ctypes.sizeof(UnicodeString),
            )
            if not command_line_data:
                return ""
            command_line = UnicodeString.from_buffer_copy(command_line_data)
            if not command_line.length or not command_line.buffer:
                return ""

            raw_command_line = read_memory(command_line.buffer, command_line.length)
            if not raw_command_line:
                return ""
            return raw_command_line.decode("utf-16-le", errors="replace").strip()
        finally:
            close_handle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return ""


def command_line_belongs_to_app(command_line: str) -> bool:
    normalized = " ".join(command_line.lower().split())
    return "-m funding_terminal run" in normalized or "-m funding_terminal.main" in normalized


def launch_command() -> list[str]:
    return [str(PYTHON_EXE), "-m", "funding_terminal", "run"]


def run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PYTHON_EXE), "-m", "funding_terminal", *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def print_cli_output(result: subprocess.CompletedProcess[str]) -> None:
    output = (result.stdout + result.stderr).strip()
    if output:
        print(output)


def read_pid_file(pid_file: Path | None = None) -> int | None:
    pid_file = pid_file or PID_FILE
    if not pid_file.exists():
        return None
    content = pid_file.read_text(encoding="utf-8").strip()
    if not content:
        return None
    try:
        if content.startswith("{"):
            payload = json.loads(content)
            return int(payload["pid"])
        return int(content)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def write_pid_file(pid: int, config: AppConfig, pid_file: Path | None = None) -> None:
    pid_file = pid_file or PID_FILE
    payload = {
        "pid": pid,
        "started_at": datetime.now(UTC).isoformat(),
        "command": f"{PYTHON_EXE} -m funding_terminal run",
        "cwd": str(PROJECT_ROOT),
        "url": config.url,
    }
    pid_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def delete_pid_file(pid_file: Path | None = None) -> None:
    pid_file = pid_file or PID_FILE
    pid_file.unlink(missing_ok=True)


def get_running_pid_from_file() -> int | None:
    pid = read_pid_file()
    if pid is None:
        return None
    if not process_is_running(pid):
        delete_pid_file()
        return None
    if not pid_belongs_to_app(pid):
        delete_pid_file()
        return None
    return pid


def remove_stale_pid_if_needed() -> None:
    pid = read_pid_file()
    if pid is None:
        return
    if not process_is_running(pid) or not pid_belongs_to_app(pid):
        delete_pid_file()


def process_is_running(pid: int) -> bool:
    return get_process_info(pid).exists


def get_process_info(pid: int) -> ProcessInfo:
    if pid <= 0:
        return ProcessInfo(pid=pid, exists=False)
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return ProcessInfo(pid=pid, exists=False)
        return ProcessInfo(pid=pid, exists=True)

    command = (
        "$p = Get-Process -Id "
        f"{pid} "
        "-ErrorAction SilentlyContinue; if ($p) { $p.Path }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    output = result.stdout.strip()
    if not output:
        return ProcessInfo(pid=pid, exists=False)
    return ProcessInfo(pid=pid, exists=True, executable_path=Path(output))


def pid_belongs_to_app(pid: int) -> bool:
    info = get_process_info(pid)
    if not info.exists or info.executable_path is None:
        return False
    try:
        executable = info.executable_path.resolve()
        allowed_paths = {PYTHON_EXE.resolve(), BASE_PYTHON_EXE.resolve()}
    except OSError:
        return False
    if executable not in allowed_paths:
        return False
    command_line = process_command_line(pid)
    if command_line and not command_line_belongs_to_app(command_line):
        return False
    config = load_app_config()
    return find_pid_by_port(config.port) == pid and check_health(config).ok


def find_pid_by_port(port: int) -> int | None:
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local_address, state, pid_text = parts[1], parts[3], parts[4]
        if state.upper() != "LISTENING":
            continue
        if not local_address.endswith(f":{port}"):
            continue
        try:
            return int(pid_text)
        except ValueError:
            return None
    return None


def check_health(config: AppConfig, timeout: float = 5.0) -> HealthResult:
    try:
        with urllib.request.urlopen(config.health_url, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            payload = json.loads(body)
            if response.status == 200 and isinstance(payload, dict):
                return HealthResult(
                    ok=True,
                    status=str(payload.get("status", "ok")),
                    payload=payload,
                )
            return HealthResult(ok=False, error=f"HTTP {response.status}")
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return HealthResult(ok=False, error=str(exc))


def wait_for_health(config: AppConfig, pid: int, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if check_health(config).ok:
            return True
        if not process_is_running(pid) and find_pid_by_port(config.port) is None:
            return False
        time.sleep(0.75)
    return False


def wait_until_health_down(config: AppConfig, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not check_health(config, timeout=0.5).ok:
            return True
        time.sleep(0.5)
    return not check_health(config, timeout=0.5).ok


def ensure_health_stopped(config: AppConfig, *, original_pid: int) -> bool:
    if wait_until_health_down(config, timeout_seconds=5):
        return True
    port_pid = find_pid_by_port(config.port)
    if port_pid is not None and port_pid != original_pid and pid_belongs_to_app(port_pid):
        terminate_process_tree(port_pid)
    return wait_until_health_down(config, timeout_seconds=5)


def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def graceful_shutdown(pid: int) -> None:
    if os.name == "nt":
        try:
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        except OSError:
            return
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return


def terminate_process_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if process_is_running(pid):
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Stop-Process -Id {pid} -Force",
                ],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return


def wait_until_stopped(pid: int, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not process_is_running(pid):
            return True
        time.sleep(0.5)
    return not process_is_running(pid)


def extract_dependency_lines(output: str) -> list[str]:
    labels = {
        "database:": "Database:",
        "binance_spot:": "Binance Spot:",
        "binance_futures:": "Binance Futures:",
    }
    lines: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        for prefix, label in labels.items():
            if stripped.startswith(prefix):
                value = stripped.split(":", 1)[1].strip()
                lines.append(f"{label} {value}")
    return lines


def append_start_separator() -> None:
    timestamp = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    with APP_LOG.open("a", encoding="utf-8") as log_file:
        log_file.write("\n================================\n")
        log_file.write("Funding Terminal START\n")
        log_file.write(f"{timestamp}\n")
        log_file.write("================================\n")


def print_log_tail(path: Path, line_count: int) -> None:
    if not path.exists():
        print("Log file does not exist.")
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"Last {min(line_count, len(lines))} log lines from {path}:")
    for line in lines[-line_count:]:
        print(line)


def write_manager_log(message: str) -> None:
    ensure_runtime_dirs()
    timestamp = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    with MANAGER_LOG.open("a", encoding="utf-8") as log_file:
        log_file.write(f"{timestamp} {message}\n")


def open_url(url: str) -> None:
    if os.name == "nt":
        os.startfile(url)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", url], cwd=PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
