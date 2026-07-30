import subprocess
import socket
import time
import os
import stat
import tarfile
from pathlib import Path
from typing import Union
from utils import run_command, wait_for_port, kill_port


class FileBrowser:
    """Runs filebrowser as a local background server."""

    DEFAULT_PORT   = 8080
    SERVER_TIMEOUT = 60   # seconds to wait for filebrowser port to open


    def __init__(self):
        self.base_dir = Path("/kaggle/working")
        self.filebrowser_bin = self.base_dir / "filebrowser"

        self.filebrowser_process: Union[subprocess.Popen, None] = None

    # -----------------------------------------------------------------------
    # Private Helpers
    # -----------------------------------------------------------------------

    # def _run_command(self, command: list) -> None:
    #     """Run a filebrowser CLI command."""
    #     subprocess.run(command, check=True, capture_output=True, text=True)
    #     time.sleep(1)

    # def _wait_for_port(self, port: int, host: str = "127.0.0.1", timeout: int = SERVER_TIMEOUT) -> bool:
    #     """Wait until a port accepts connections or timeout elapses."""
    #     start_time = time.time()
    #     while True:
    #         try:
    #             with socket.create_connection((host, port), timeout=1):
    #                 return True
    #         except (ConnectionRefusedError, socket.timeout):
    #             if time.time() - start_time > timeout:
    #                 return False
    #             time.sleep(1)

    def _download_filebrowser(self) -> None:
        """Download and make the filebrowser binary executable."""
        if not self.filebrowser_bin.exists():
            release_url = (
                "https://github.com/filebrowser/filebrowser/releases/latest"
                "/download/linux-amd64-filebrowser.tar.gz"
            )
            archive_path = self.base_dir / "linux-amd64-filebrowser.tar.gz"

            os.system(f"wget -q {release_url} -O {archive_path}")

            with tarfile.open(archive_path) as tar:
                tar.extract("filebrowser", path=self.base_dir, filter="data")

            archive_path.unlink(missing_ok=True)

        st = os.stat(self.filebrowser_bin)
        os.chmod(self.filebrowser_bin, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    def _configure_filebrowser(self, port: int) -> None:
        """Initialize the DB (once) and apply runtime config."""
        db_path = self.base_dir / "filebrowser.db"

        if not db_path.exists():
            self.run_command([str(self.filebrowser_bin), "-d", str(db_path), "config", "init"])

            self.run_command(
            [str(self.filebrowser_bin), "-d", str(db_path), "users", "add",
             "admin", "admin12345678", "--perm.admin"]
            )

        self.run_command(
            [str(self.filebrowser_bin), "-d", str(db_path), "config", "set",
             "--auth.method=noauth",
             "--address=0.0.0.0",
             f"--port={port}",
             f"--root={self.base_dir}",
             f"--tokenExpirationTime=24h",
             f"--disableExec=false",
            ]
        )


    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def start(self, port: int = DEFAULT_PORT) -> Union[subprocess.Popen, None]:
        """Download (if needed), configure, and launch filebrowser as a background process."""
        self._download_filebrowser()

        # Ensure no leftover filebrowser process is still holding a lock on the db
        os.system("pkill -f filebrowser > /dev/null 2>&1")
        kill_port(port)

        self._configure_filebrowser(port)

        command = [
            str(self.filebrowser_bin),
            "-d", str(self.base_dir / "filebrowser.db"),
        ]


        self.filebrowser_process = subprocess.Popen(
            command,
            cwd=self.base_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        if wait_for_port(port, timeout=self.SERVER_TIMEOUT, process=self.filebrowser_process):
            print(f"\nFile Explorer running on port {port}\n")
            return self.filebrowser_process

        self.filebrowser_process.terminate()
        self.filebrowser_process = None
        raise RuntimeError(f"filebrowser did not start within {self.SERVER_TIMEOUT}s.")

    def stop(self) -> None:
        """Stop filebrowser."""
        if self.filebrowser_process and self.filebrowser_process.poll() is None:
            self.filebrowser_process.terminate()
            self.filebrowser_process.wait()
        self.filebrowser_process = None
        print("File Explorer stopped.")

    def is_active(self) -> bool:
        """Return True if filebrowser is currently running, False otherwise."""
        return self.filebrowser_process is not None and self.filebrowser_process.poll() is None


if __name__ == "__main__":
    fb = FileBrowser()
    fb.start()
 