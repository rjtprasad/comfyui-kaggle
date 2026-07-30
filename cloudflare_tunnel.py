import os
import re
import time
import subprocess
import threading
from pathlib import Path
from typing import Union


class CloudflareTunnel:
    """
    Manages a Cloudflare Quick Tunnel (cloudflared) pointing at a local port.
    Handles binary download, process lifecycle, and URL extraction.

    Usage:
        tunnel = CloudflareTunnel(base_dir=Path("/kaggle/working"))
        tunnel.start(port=8188)
        print(tunnel.public_url)
        tunnel.stop()
    """

    TUNNEL_TIMEOUT = 40  # seconds to wait for Cloudflare URL

    def __init__(self, base_dir: Path = Path("/kaggle/working")):
        self.base_dir = Path(base_dir)
        self.cloudflared_bin = self.base_dir / "cloudflared"

        self.tunnel_process: Union[subprocess.Popen, None] = None
        self.public_url: str = ""
        self._port: Union[int, None] = None

    # -----------------------------------------------------------------------
    # Private Helpers
    # -----------------------------------------------------------------------

    def _download_binary(self) -> None:
        """Download the cloudflared binary if it isn't already present."""
        if not self.cloudflared_bin.exists():
            os.system(
                "wget -q https://github.com/cloudflare/cloudflared/releases/latest"
                f"/download/cloudflared-linux-amd64 -O {self.cloudflared_bin}"
            )
        os.system(f"chmod +x {self.cloudflared_bin}")

    def _drain_output(self, url_found: threading.Event) -> None:
        """Keep reading cloudflared's stdout for its whole lifetime so the
        PIPE buffer never fills up and blocks the process."""
        for line in self.tunnel_process.stdout:
            if not url_found.is_set() and ".trycloudflare.com" in line:
                url_match = re.search(r"https://[a-zA-Z0-9-]+.trycloudflare.com", line)
                if url_match:
                    self.public_url = url_match.group(0)
                    url_found.set()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def start(self, port: int, timeout: int = TUNNEL_TIMEOUT) -> subprocess.Popen:
        """Kill any existing tunnel on this port, then launch a fresh one."""
        self._port = port
        os.system(f"pkill -f 'cloudflared tunnel --url http://127.0.0.1:{port}' > /dev/null 2>&1")
        self.public_url = ""
        time.sleep(2)

        self._download_binary()

        self.tunnel_process = subprocess.Popen(
            [str(self.cloudflared_bin), "tunnel", "--url", f"http://127.0.0.1:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        url_found = threading.Event()
        threading.Thread(target=self._drain_output, args=(url_found,), daemon=True).start()

        if url_found.wait(timeout=timeout):
            return self.tunnel_process

        self.tunnel_process.terminate()
        self.tunnel_process = None
        raise RuntimeError("Tunnel timed out : no URL received.")

    def stop(self) -> None:
        """Terminate the tunnel process (if running) and clean up."""
        if self.tunnel_process and self.tunnel_process.poll() is None:
            self.tunnel_process.terminate()
            self.tunnel_process.wait()
        self.tunnel_process = None
        self.public_url = ""
        os.system("pkill -f cloudflared > /dev/null 2>&1")

    def is_active(self) -> bool:
        return self.tunnel_process is not None and self.tunnel_process.poll() is None


if __name__ == "__main__":
    tunnel = CloudflareTunnel()
    tunnel.start(port=8188)
    print(tunnel.public_url)
 