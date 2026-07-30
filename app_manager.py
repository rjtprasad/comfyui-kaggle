"""
AppManager
==========
Ek single class jo ComfyUI aur FileBrowser dono ko manage karti hai,
saath hi dono ke liye Cloudflare Quick Tunnel bhi banati hai taaki
public URL mil sake.

Assumption: teeno original classes teen alag files me hain isi folder ke
andar (ya PYTHONPATH me available hain):
    - comfy.py            -> class ComfyUI
    - filebrowser.py       -> class FileBrowser
    - cloudflare_tunnel.py -> class CloudflareTunnel

Agar tumhare paas file names/paths alag hain to bas neeche wale
import statements update kar dena.

Usage:
    from app_manager import AppManager

    manager = AppManager()

    manager.start_all()              # ComfyUI + FileBrowser + dono tunnels
    print(manager.status())

    manager.restart_comfyui()        # sirf ComfyUI restart
    manager.stop_filebrowser()       # sirf FileBrowser stop

    manager.stop_all()               # sab kuch band
"""

from pathlib import Path
from typing import Union

from comfy_ui import ComfyUI
from file_browser import FileBrowser
from cloudflare_tunnel import CloudflareTunnel


class AppManager:
    """
    Orchestrates ComfyUI + FileBrowser + unke Cloudflare tunnels.
    Har service individually start/stop/restart ho sakti hai,
    aur ek status() method se pata chal jaata hai kya-kya chal raha hai.
    """

    def __init__(self, base_dir: Path = Path("/kaggle/working")):
        self.base_dir = Path(base_dir)

        # Core services
        self.comfy = ComfyUI()
        self.filebrowser = FileBrowser()

        # Ek tunnel har service ke liye (do alag ports, isliye do instances)
        self.comfy_tunnel = CloudflareTunnel(base_dir=self.base_dir)
        self.filebrowser_tunnel = CloudflareTunnel(base_dir=self.base_dir)

        self._comfy_port = ComfyUI.DEFAULT_PORT
        self._filebrowser_port = FileBrowser.DEFAULT_PORT

    # -----------------------------------------------------------------------
    # ComfyUI
    # -----------------------------------------------------------------------

    def start_comfyui(self, reinstall: bool = False, *extra_args) -> None:
        """ComfyUI ko start karo aur uska public tunnel bhi khol do."""
        print("── Starting ComfyUI ──")
        self.comfy.start(reinstall, *extra_args)

        if not self.comfy.is_active():
            print("ComfyUI start nahi ho paya, tunnel skip kar rahe hain.")
            return

        try:
            self.comfy_tunnel.start(port=self._comfy_port)
            print(f"ComfyUI public URL  :  {self.comfy_tunnel.public_url}")
        except RuntimeError as e:
            print(f"ComfyUI tunnel fail ho gaya : {e}")

    def stop_comfyui(self) -> None:
        """ComfyUI aur uska tunnel dono band karo."""
        print("── Stopping ComfyUI ──")
        self.comfy_tunnel.stop()
        self.comfy.stop()

    def restart_comfyui(self, reinstall: bool = False, *extra_args) -> None:
        """
        Sirf ComfyUI service ko stop+start karta hai.
        Tunnel ko touch nahi karta — agar tunnel pehle se active tha to
        wahi public URL restart ke baad bhi kaam karega.
        """
        print("── Restarting ComfyUI ──")
        self.comfy.stop()
        self.comfy.start(reinstall, *extra_args)

        if not self.comfy.is_active():
            print("ComfyUI restart nahi ho paya.")
            return

        if self.comfy_tunnel.is_active():
            print(f"ComfyUI public URL (unchanged)  :  {self.comfy_tunnel.public_url}")
        else:
            # Tunnel pehle se chal hi nahi raha tha, to naya khol do
            try:
                self.comfy_tunnel.start(port=self._comfy_port)
                print(f"ComfyUI public URL  :  {self.comfy_tunnel.public_url}")
            except RuntimeError as e:
                print(f"ComfyUI tunnel fail ho gaya : {e}")

    # -----------------------------------------------------------------------
    # FileBrowser
    # -----------------------------------------------------------------------

    def start_filebrowser(self, port: int = FileBrowser.DEFAULT_PORT) -> None:
        """FileBrowser ko start karo aur uska public tunnel bhi khol do."""
        print("── Starting FileBrowser ──")
        self._filebrowser_port = port
        self.filebrowser.start(port)

        if not self.filebrowser.is_active():
            print("FileBrowser start nahi ho paya, tunnel skip kar rahe hain.")
            return

        try:
            self.filebrowser_tunnel.start(port=port)
            print(f"FileBrowser public URL  :  {self.filebrowser_tunnel.public_url}")
        except RuntimeError as e:
            print(f"FileBrowser tunnel fail ho gaya : {e}")

    def stop_filebrowser(self) -> None:
        """FileBrowser aur uska tunnel dono band karo."""
        print("── Stopping FileBrowser ──")
        self.filebrowser_tunnel.stop()
        self.filebrowser.stop()

    def restart_filebrowser(self, port: Union[int, None] = None) -> None:
        """
        Sirf FileBrowser service ko stop+start karta hai.
        Tunnel ko touch nahi karta — agar tunnel pehle se active tha to
        wahi public URL restart ke baad bhi kaam karega.
        """
        print("── Restarting FileBrowser ──")
        port = port or self._filebrowser_port
        self._filebrowser_port = port

        self.filebrowser.stop()
        self.filebrowser.start(port)

        if not self.filebrowser.is_active():
            print("FileBrowser restart nahi ho paya.")
            return

        if self.filebrowser_tunnel.is_active():
            print(f"FileBrowser public URL (unchanged)  :  {self.filebrowser_tunnel.public_url}")
        else:
            # Tunnel pehle se chal hi nahi raha tha, to naya khol do
            try:
                self.filebrowser_tunnel.start(port=port)
                print(f"FileBrowser public URL  :  {self.filebrowser_tunnel.public_url}")
            except RuntimeError as e:
                print(f"FileBrowser tunnel fail ho gaya : {e}")

    # -----------------------------------------------------------------------
    # Combined controls
    # -----------------------------------------------------------------------

    def start_all(
        self,
        reinstall: bool = False,
        filebrowser_port: int = FileBrowser.DEFAULT_PORT,
        *comfy_extra_args,
    ) -> None:
        """Dono services (ComfyUI + FileBrowser) ek saath start karo, dono ke tunnels ke saath."""
        self.start_comfyui(reinstall, *comfy_extra_args)
        print()
        self.start_filebrowser(filebrowser_port)

    def stop_all(self) -> None:
        """Dono services aur unke tunnels band karo."""
        self.stop_comfyui()
        print()
        self.stop_filebrowser()

    def restart_all(
        self,
        reinstall: bool = False,
        filebrowser_port: Union[int, None] = None,
        *comfy_extra_args,
    ) -> None:
        """Dono services restart karo — tunnels touch nahi honge, URLs same rahenge."""
        self.restart_comfyui(reinstall, *comfy_extra_args)
        print()
        self.restart_filebrowser(filebrowser_port)

    # -----------------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------------

    def status(self) -> dict:
        """
        Dictionary return karta hai jisme har service ki running state
        aur (agar active hai to) uska public URL hota hai.
        """
        return {
            "comfyui": {
                "running": self.comfy.is_active(),
                "port": self._comfy_port,
                "public_url": self.comfy_tunnel.public_url if self.comfy_tunnel.is_active() else None,
            },
            "filebrowser": {
                "running": self.filebrowser.is_active(),
                "port": self._filebrowser_port,
                "public_url": self.filebrowser_tunnel.public_url if self.filebrowser_tunnel.is_active() else None,
            },
        }

    def print_status(self) -> None:
        """status() ko human-readable format me console pe print karta hai."""
        s = self.status()
        print("── Status ──")
        for name, info in s.items():
            state = "RUNNING" if info["running"] else "STOPPED"
            url = info["public_url"] or "-"
            print(f"{name:<12} : {state:<8} : port {info['port']:<5} : {url}")


if __name__ == "__main__":
    manager = AppManager()
    manager.start_all()
    manager.print_status()
 