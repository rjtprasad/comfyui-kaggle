import subprocess
import socket
import time
from typing import Union
from pathlib import Path


def run_command(command: list, cwd: Union[Path, str, None] = None) -> subprocess.CompletedProcess:
    """
    Runs a shell command and raises CalledProcessError on failure.
    Captures stdout+stderr merged as text.
    """
    return subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=True,
    )


def wait_for_port(
    port: int,
    host: str = "127.0.0.1",
    timeout: int = 60,
    process: Union[subprocess.Popen, None] = None,
) -> bool:
    """
    Polls a TCP port until it becomes available or the timeout expires.
    If `process` is given, also bails out early if that process exits.
    """
    start_time = time.time()

    while True:
        if process is not None and process.poll() is not None:
            print(f"Process exited early (code {process.returncode}) before server started.")
            return False

        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            if time.time() - start_time > timeout:
                print(f"Timeout  :  server did not start within {timeout}s on port {port}.")
                return False
            time.sleep(1)


def kill_port(port: int, host: str = "127.0.0.1", wait: float = 2.0) -> None:
    """
    Checks if the given port is busy, and force-kills whatever is using it.
    """
    import os
    try:
        with socket.create_connection((host, port), timeout=1):
            os.system(f"fuser -k {port}/tcp > /dev/null 2>&1")
            time.sleep(wait)
    except (ConnectionRefusedError, socket.timeout, OSError):
        pass