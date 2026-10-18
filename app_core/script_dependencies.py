"""Resolve known script imports before executing any user code."""

from __future__ import annotations

import ast

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from app_core.script_environments import normalize_environment


# Import names and distribution names are different namespaces. Only use an
# explicit relationship; an unknown module must never become a guessed install.
IMPORT_DISTRIBUTIONS = {
    "cv2": (
        "opencv-python",
        "opencv-python-headless",
        "opencv-contrib-python",
        "opencv-contrib-python-headless",
    ),
    "numpy": ("numpy",),
    "PIL": ("Pillow",),
    "requests": ("requests",),
    "httpx": ("httpx",),
    "aiohttp": ("aiohttp",),
    "yaml": ("PyYAML",),
    "bs4": ("beautifulsoup4",),
    "lxml": ("lxml",),
    "pandas": ("pandas",),
    "scipy": ("scipy",),
    "sklearn": ("scikit-learn",),
    "matplotlib": ("matplotlib",),
    "openpyxl": ("openpyxl",),
    "docx": ("python-docx",),
    "pptx": ("python-pptx",),
    "dateutil": ("python-dateutil",),
    "serial": ("pyserial",),
    "psutil": ("psutil",),
    "pyautogui": ("PyAutoGUI",),
    "pyperclip": ("pyperclip",),
    "mss": ("mss",),
    "win32api": ("pywin32",),
    "win32con": ("pywin32",),
    "win32gui": ("pywin32",),
    "win32process": ("pywin32",),
    "win32com": ("pywin32",),
}


def script_imports(tree):
    """Find imports, including nested imports and literal dynamic import calls."""
    modules = set()
    importlib_names = set()
    import_functions = {"__import__"}
    sdk_names = set()
    needs_frame = False
    image_names = {"图像"}
    needs_image = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
                if alias.name == "importlib":
                    importlib_names.add(alias.asname or alias.name)
                elif alias.name == "lca_sdk":
                    sdk_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
            if node.module == "importlib":
                import_functions.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "import_module"
                )
            elif node.module == "lca_sdk":
                needs_frame |= any(alias.name in {"截帧", "*"} for alias in node.names)
                for alias in node.names:
                    if alias.name == "图像":
                        image_names.add(alias.asname or alias.name)
                        needs_image = True
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in image_names:
                needs_image = True
            elif (
                node.attr == "图像"
                and isinstance(node.value, ast.Name)
                and node.value.id in sdk_names
            ):
                needs_image = True
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in sdk_names
            and node.attr == "截帧"
        ):
            needs_frame = True
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_import = (
            isinstance(func, ast.Name) and func.id in import_functions
        ) or (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in importlib_names
            and func.attr == "import_module"
        )
        if not is_import:
            continue
        name = node.args[0] if node.args else next(
            (keyword.value for keyword in node.keywords if keyword.arg == "name"), None
        )
        if isinstance(name, ast.Constant) and isinstance(name.value, str):
            if name.value and not name.value.startswith("."):
                modules.add(name.value.split(".")[0])
    if needs_frame:
        modules.add("numpy")
    if needs_image:
        modules.update({"numpy", "cv2"})
    return modules


def resolve_script_environment(settings, tree, *, progress=None):
    """Merge inferred dependencies without mutating the card's saved settings."""
    resolved = normalize_environment(settings)
    if resolved["mode"] != "isolated":
        return resolved
    declared = {
        canonicalize_name(Requirement(item).name) for item in resolved["requirements"]
    }
    additions = []
    for module in sorted(script_imports(tree)):
        providers = IMPORT_DISTRIBUTIONS.get(module)
        if providers is None or any(
            canonicalize_name(provider) in declared for provider in providers
        ):
            continue
        distribution = providers[0]
        declared.add(canonicalize_name(distribution))
        resolved["requirements"].append(distribution)
        additions.append(f"{module} → {distribution}")
    resolved["requirements"].sort()
    if additions and progress is not None:
        progress("已从脚本导入识别依赖：" + "、".join(additions))
    return resolved
