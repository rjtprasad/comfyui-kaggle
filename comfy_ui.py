from dataclasses import dataclass
from pathlib import Path
from typing import Union
import subprocess
import shutil
import socket
import json
import time
import os
import dependency_installer
from utils import run_command, wait_for_port, kill_port


COMFYUI_GITHUB_URL = "https://github.com/comfyanonymous/ComfyUI"


# Custom Nodes
DEFAULT_CUSTOM_NODES = [
    "https://github.com/ltdrdata/ComfyUI-Manager",
    "https://github.com/rgthree/rgthree-comfy",
    "https://github.com/chrisgoringe/cg-use-everywhere",
]


UI_SETTINGS = {
            "Comfy.TutorialCompleted": True,
            "Comfy.Minimap.Visible": False,
            "Comfy.ColorPalette": "github",
            "Comfy.Appearance.DisableAnimations": True,
            "Comfy.NodeLibrary.NewDesign": True,
            "Comfy.TextareaWidget.Spellcheck": True,
            "Comfy.Workflow.AutoSave": "after delay",
            "Comfy.Workflow.AutoSaveDelay": 3000,
            "Comfy.Workflow.SortNodeIdOnSave": True
        }


EXTRA_MODEL_PATHS_CONFIG = """
comfyui:
    base_path: /kaggle/input/models/rjprasad
    is_default: false
    checkpoints: checkpoints/other
    background_removal: background_removal/other
    text_encoders: |
         text_encoders/other
         clip/other 
    clip_vision: clip_vision/other
    configs: configs/other
    controlnet: controlnet/other
    diffusion_models: |
                 diffusion_models/other
                 unet/other
    embeddings: embeddings/other
    loras: loras/other
    upscale_models: upscale_models/other
    vae: vae/other
    ipadapter : ipadapter/other
    audio_encoders: audio_encoders/other
    model_patches: model_patches/other
    seedvr2: SEEDVR2/other
"""


# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------

@dataclass
class ComfyPaths:
    """
    Central config for all ComfyUI-related paths.
    Change base_dir once — everything else adjusts automatically.

    Usage:
        paths = ComfyPaths()                              # Kaggle (default)
        paths = ComfyPaths(base_dir=Path("/content"))     # Google Colab
    """
    base_dir: Path = Path("/kaggle/working")

    @property
    def comfyenv(self) -> Path:
        return self.base_dir / "comfyenv"
    
    @property
    def ComfyUI(self) -> Path:
        return self.base_dir / "ComfyUI"

    @property
    def custom_nodes(self) -> Path:
        return self.ComfyUI / "custom_nodes"
        
     
# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------

class ComfyUI:
    """
    Orchestrates the ComfyUI lifecycle on cloud notebook environments
    (Kaggle, Colab, etc.): installation, launch, and status checks.
    """

    DEFAULT_PORT    = 8188
    DEFAULT_HOST    = "0.0.0.0"
    SERVER_TIMEOUT  = 90   # seconds to wait for ComfyUI port to open

    def __init__(self):
        self.paths = ComfyPaths()

        self.comfy_process: Union[subprocess.Popen, None] = None
        self._saved_extra_args = ()

        self._clone(COMFYUI_GITHUB_URL, self.paths.base_dir)


    # -----------------------------------------------------------------------
    # Private Helpers
    # -----------------------------------------------------------------------

    
    def _clone(
        self,
        git_url: str,
        target_dir: Union[str, Path],
        reinstall: bool = False
    ) -> None:
        """
        Clones a Git repository into target_dir.
        """
        target_dir  = Path(target_dir)
        repo_name   = Path(git_url.rstrip("/")).stem
        target_path = target_dir/repo_name
    
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
    
            if reinstall and target_path.exists():
                shutil.rmtree(target_path, ignore_errors=True)
                print(f"Removed  :  {repo_name}")
    
            if not (target_path/".git").exists():
                run_command(["git", "clone", git_url, str(target_path)])
                print(f"{repo_name} ✅")
            else:
                print(f"{repo_name} Already Present.")
    
        except subprocess.CalledProcessError as e:
            print(f"Failed  :  {repo_name}  :  {e.output}")
            if target_path.exists():
                shutil.rmtree(target_path, ignore_errors=True)
                print(f"Removed incomplete download  :  {repo_name}")
            raise RuntimeError(f"Cloning failed for {repo_name}. Check your internet connection.") from e
        except Exception as e:
            print(f"Unexpected error  :  {repo_name}  :  {e}")
            raise


    def _configure_extra_model_paths(self) -> None:
        """
        Sets up the extra_model_paths.yaml config inside the ComfyUI root directory.
        """
        extra_model_paths_yaml = self.paths.ComfyUI/"extra_model_paths.yaml"

        try:
            extra_model_paths_yaml.parent.mkdir(parents=True, exist_ok=True)
            extra_model_paths_yaml.write_text(EXTRA_MODEL_PATHS_CONFIG.strip(), encoding="utf-8")
            print(f"Configured extra model paths. ✅")
        except Exception as e:
            print(f"Failed to write extra model paths configuration  :  {e}")


    def _ui_settings(self) -> None:
        """
        Injects predefined web UI settings directly into ComfyUI.
        """
        settings_dir = self.paths.ComfyUI / "user" / "default"
        settings_file = settings_dir / "comfy.settings.json"
        
        try:
            settings_dir.mkdir(parents=True, exist_ok=True)
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(UI_SETTINGS, f, indent=4)
            print("Applied UI Settings. ✅")
        except Exception as e:
            print(f"Failed to write user settings : {e}")
            

    def _build_subprocess_env(self) -> dict:
        """
        Builds an environment dict for launching ComfyUI as a subprocess,
        ensuring the pylibs directory is on PYTHONPATH so packages installed
        there (via --target) are importable inside that subprocess.
    
        Returns:
            dict: A copy of the current environment with PYTHONPATH updated.
        """
        env = os.environ.copy()
        pylibs_path = str(self.paths.comfyenv)
        existing_pythonpath = env.get("PYTHONPATH", "")
    
        env["PYTHONPATH"] = (
            pylibs_path + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
        )
        return env


    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def install_dependencies(self) -> None:
        """
        Sweeps through the ComfyUI root and all custom nodes, installing
        any requirements.txt files it finds in one unified batch.
        """
        dependency_installer.install(
            self.paths.ComfyUI, self.paths.custom_nodes, self.paths.comfyenv
        )
                    

    def apply_configuration(self) -> None:
        """
        Runs all configuration setup steps before launching the server.
        """
        self._configure_extra_model_paths()
        self._ui_settings()


    def download_custom_nodes(self, node_urls: Union[str, list], reinstall: bool = False) -> None:
        """
        Installs one or more custom nodes into the custom_nodes directory.
        """
        if isinstance(node_urls, str):
            node_urls = [node_urls]

        if not isinstance(node_urls, list):
            print("Invalid input  :  node_urls must be a string or a list of strings.")
            return

        print(f"Processing {len(node_urls)} custom node(s)...")
        for url in node_urls:
            self._clone(url, self.paths.custom_nodes, reinstall=reinstall)
        print("All custom nodes installed.")


    def comfyui_server(self, *extra_args) -> Union[subprocess.Popen, None]:
        """
        Launches ComfyUI as a background process and tracks it inside the instance.
        """
        self._saved_extra_args = extra_args
        port = self.DEFAULT_PORT
        host = self.DEFAULT_HOST

        kill_port(port)

        print(f"Starting ComfyUI  :  {host}:{port}")

        command = [
            "python", "main.py",
            "--listen", host,
            "--port", str(port),
            "--preview-method", "auto",
            *extra_args,
        ]

        try:
            self.comfy_process = subprocess.Popen(
                command,
                cwd=self.paths.ComfyUI,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env = self._build_subprocess_env()
            )

            if wait_for_port(port, timeout=self.SERVER_TIMEOUT, process=self.comfy_process):
                # print(f"ComfyUI running  :  PID {self.comfy_process.pid}")
                # print("\n")
                return self.comfy_process

            self.comfy_process.terminate()
            self.comfy_process = None
            return None

        except Exception as e:
            print(f"Failed to start ComfyUI  :  {e}")
            self.comfy_process = None
            return None


    def start(self, reinstall: bool = False, *extra_args) -> None:
        """
        One-click method to install components, apply configuration,
        and launch the server.
        """
        self.download_custom_nodes(DEFAULT_CUSTOM_NODES)
        print()
        self.install_dependencies()
        print()
        self.apply_configuration()
        print()
        self.comfyui_server(*extra_args)


    def stop(self) -> None:
        """
        Safely shuts down the ComfyUI server.
        """
        print("Stopping ComfyUI")

        if self.comfy_process and self.comfy_process.poll() is None:
            self.comfy_process.terminate()
            self.comfy_process.wait()
        else:
            print("ComfyUI is not active.")
        self.comfy_process = None


    def is_active(self) -> bool:
        """Return True if the ComfyUI server process is currently running, False otherwise."""
        return self.comfy_process is not None and self.comfy_process.poll() is None


if __name__ == "__main__":
    comfy = ComfyUI()
    comfy.start()