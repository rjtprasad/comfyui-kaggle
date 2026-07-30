"""
dependency_installer.py

Standalone dependency-resolution logic for ComfyUI custom nodes.

Scans requirements.txt files (ComfyUI core + custom nodes), compares them
against currently installed packages, and installs only what's missing or
mismatched — using `pip install --target <dir> --no-deps` so heavy
pre-installed packages (torch, CUDA, numpy, etc.) are never re-pulled.
Nested sub-dependencies are resolved recursively the same way.
"""

from pathlib import Path
import subprocess
import shutil
import re
import importlib.metadata

from packaging import version as pkg_version
from packaging.specifiers import SpecifierSet


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_command(command: list, cwd=None) -> None:
    """Runs a shell command and raises on failure."""
    result = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True
    )

    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, command, output=result.stdout
        )


def _normalize_name(name: str) -> str:
    """
    Normalizes a package name per PEP 503 so that hyphens, underscores,
    and dots are treated as equivalent (e.g. 'comfyui-frontend-package'
    and 'comfyui_frontend_package' compare equal).
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def _get_installed_packages() -> dict[str, str]:
    """
    Takes a snapshot of all currently installed packages in the environment.

    Returns: dict[str, str]
    """
    installed: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        if name:
            installed[_normalize_name(name)] = dist.version
    return installed


def _discover_requirement_files(comfy_root: Path, custom_nodes_dir: Path) -> list[dict]:
    """
    Scans the ComfyUI root and all custom node folders for requirements.txt files.

    Nodes without a requirements.txt (e.g. those using a custom install.py-style
    setup) are skipped and logged, not treated as errors.

    Returns:
        list[dict]: Each entry is {"source": str, "path": Path} where
                    "source" identifies where the file came from
                    (e.g. "ComfyUI" or the custom node's folder name).
    """
    discovered: list[dict] = []

    # 1. ComfyUI core requirements
    core_req = comfy_root / "requirements.txt"
    if core_req.exists():
        discovered.append({"source": "ComfyUI", "path": core_req})
    else:
        print(f"ComfyUI : (skipped) requirements.txt not found")

    # 2. Custom nodes
    if custom_nodes_dir.exists():
        for node_dir in custom_nodes_dir.iterdir():
            if not node_dir.is_dir():
                continue

            if node_dir.name.startswith("__") or node_dir.name.startswith("."):
                continue  # skip __pycache__, .git, etc.

            req_file = node_dir / "requirements.txt"
            if req_file.exists():
                discovered.append({"source": node_dir.name, "path": req_file})
            else:
                print(f"{node_dir.name} :  (skipped) requirements.txt not found")

    return discovered


def _parse_requirements_file(req_path: Path) -> list[dict]:
    """
    Parses a single requirements.txt file into a list of package specs.

    Args:
        req_path (Path): Path to the requirements.txt file.

    Returns:
        list[dict]: Each entry is {"name": str, "constraint": str | None, "version": str | None}
    """
    parsed: list[dict] = []

    with open(req_path, "r") as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()

        # Skip empty lines and full-line comments
        if not line or line.startswith("#"):
            continue

        # Strip inline comments
        line = line.split("#")[0].strip()
        if not line:
            continue

        match = re.match(
            r"^([A-Za-z0-9_\-\.]+)\s*(==|>=|<=|>|<|~=)?\s*([A-Za-z0-9_\.\+]*)$",
            line
        )

        if match:
            parsed.append({
                "name": match.group(1).lower(),
                "constraint": match.group(2),
                "version": match.group(3) if match.group(3) else None
            })
        else:
            print(f"Unparseable line skipped : {line} (in {req_path})")

    return parsed


def _categorize_packages(parsed_reqs: list[dict], installed_packages: dict[str, str]) -> dict[str, list]:
    """
    Compares parsed requirements against currently installed packages
    and sorts them into three categories.

    Args:
        parsed_reqs (list[dict]): Output of _parse_requirements_file().
        installed_packages (dict[str, str]): Output of _get_installed_packages().

    Returns:
        dict[str, list]: {"skip": [...], "missing": [...], "mismatch": [...]}
    """
    result = {"skip": [], "missing": [], "mismatch": []}

    for req in parsed_reqs:
        name = req["name"]
        constraint = req["constraint"]
        req_version = req["version"]

        installed_version = installed_packages.get(_normalize_name(name))

        if installed_version is None:
            result["missing"].append(req)
            continue

        if not constraint or not req_version:
            result["skip"].append(req)
            continue

        try:
            spec = SpecifierSet(f"{constraint}{req_version}")
            if pkg_version.parse(installed_version) in spec:
                result["skip"].append(req)
            else:
                result["mismatch"].append(req)
        except Exception as e:
            print(f"Version check failed for {name} : {e}")
            result["mismatch"].append(req)

    return result


def _install_packages(packages: list[dict], target_dir: Path) -> None:
    """
    Installs the given packages into target_dir using --target and --no-deps,
    so already-installed dependencies (like torch/CUDA) are never re-pulled.

    Args:
        packages (list[dict]): Packages to install (missing + mismatch category).
        target_dir (Path): Directory to install packages into (e.g. comfy_env).
    """
    target_dir.mkdir(parents=True, exist_ok=True)

    if not packages:
        return

    for pkg in packages:
        name = pkg["name"]
        constraint = pkg["constraint"] or ""
        version = pkg["version"] or ""
        pkg_spec = f"{name}{constraint}{version}"

        normalized = _normalize_name(name).replace("-", "_")
        for existing in target_dir.glob(f"{normalized}-*.dist-info"):
            shutil.rmtree(existing, ignore_errors=True)

        try:
            _run_command(
                ["python", "-m", "pip", "install",
                 "--target", str(target_dir),
                 "--no-deps", "--no-cache-dir",
                 "--quiet", "--progress-bar", "off",
                 pkg_spec]
            )
            print(f"Installed : {pkg_spec}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to install {pkg_spec} : {e}")


def _parse_dependency_string(req_str: str) -> dict | None:
    """
    Parses a single dependency string from importlib.metadata's `requires`
    format (e.g. "numpy (>=1.19)" or "pytest>=7.0.0; extra == 'dev'")
    into the standard package-spec format.

    Optional/extra-only dependencies (e.g. dev, build extras) are skipped
    since they aren't needed for a normal install.

    Returns:
        dict | None: {"name": str, "constraint": str | None, "version": str | None}
                     or None if the dependency should be skipped.
    """
    # Skip conditional "extra" dependencies (dev/build/optional-only)
    if ";" in req_str:
        condition = req_str.split(";", 1)[1]
        if "extra ==" in condition:
            return None
        req_str = req_str.split(";")[0].strip()

    match = re.match(
        r"^([A-Za-z0-9_\-\.]+)\s*\(?\s*(==|>=|<=|>|<|~=)?\s*([A-Za-z0-9_\.\+]*)\)?$",
        req_str.strip()
    )
    if match:
        return {
            "name": match.group(1).lower(),
            "constraint": match.group(2),
            "version": match.group(3) if match.group(3) else None
        }
    return None


def _resolve_dependencies(initial_packages: list[dict], installed_packages: dict[str, str], target_dir: Path) -> None:
    """
    Recursively resolves and installs a package list and all of their
    nested dependencies, until no new missing/mismatched packages remain.

    Args:
        initial_packages (list[dict]): Starting package specs (from a requirements.txt).
        installed_packages (dict[str, str]): Snapshot of currently installed packages.
        target_dir (Path): Directory to install missing/mismatched packages into.
    """
    to_process = initial_packages
    already_checked: set[str] = set()
    round_num = 1

    while to_process:
        current_batch = [r for r in to_process if r["name"] not in already_checked]
        if not current_batch:
            break

        for r in current_batch:
            already_checked.add(r["name"])

        categorized = _categorize_packages(current_batch, installed_packages)
        to_install = categorized["missing"] + categorized["mismatch"]

        if not to_install:
            break

        print(f"  Round {round_num}: installing {len(to_install)} package(s)")
        _install_packages(to_install, target_dir)

        importlib.invalidate_caches()

        next_batch = []
        for r in to_install:
            try:
                dist = importlib.metadata.distribution(r["name"])
                for req_str in (dist.requires or []):
                    parsed_dep = _parse_dependency_string(req_str)
                    if parsed_dep and parsed_dep["name"] not in already_checked:
                        next_batch.append(parsed_dep)
            except importlib.metadata.PackageNotFoundError:
                print(f"  Metadata not found for {r['name']}, dependency check skipped")

        to_process = next_batch
        round_num += 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def install(comfy_root: Path, custom_nodes_dir: Path, target_dir: Path) -> None:
    """
    Sweeps through the ComfyUI root and all custom nodes, installing
    any requirements.txt files it finds in one unified batch.

    Args:
        comfy_root (Path): Path to the ComfyUI installation root (e.g. paths.ComfyUI).
        custom_nodes_dir (Path): Path to the custom_nodes directory (e.g. paths.custom_nodes).
        target_dir (Path): Directory to install missing/mismatched packages into
                            (e.g. paths.comfy_env).
    """
    import sys
    target_dir_str = str(target_dir)
    if target_dir_str not in sys.path:
        sys.path.insert(0, target_dir_str)

    installed = _get_installed_packages()
    files = _discover_requirement_files(comfy_root, custom_nodes_dir)

    for f in files:
        parsed = _parse_requirements_file(f["path"])
        print(f"\n{f['source']}:")
        _resolve_dependencies(parsed, installed, target_dir)