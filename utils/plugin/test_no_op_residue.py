from pathlib import Path

FORBIDDEN = (
    "utils.op",
    "from utils import op",
    "OpClient",
    "op_c_api",
    "LCA_OP_DIR",
    "tools/op",
    "is_op_screenshot_engine",
    "capture_window_op",
    "OpDxInput",
    "YOLO_BACKEND_PLUGIN",
)

ROOTS = ("app_core", "tasks", "task_workflow", "ui", "utils", "services", "build_assets")
SKIP_PARTS = {"test_no_op_residue.py"}


def test_no_op_runtime_residue():
    root = Path(__file__).resolve().parents[2]
    hits = []
    for folder in ROOTS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix.lower() not in {".py", ".md", ".json", ".bat", ".iss"}:
                continue
            if path.name in SKIP_PARTS:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in FORBIDDEN:
                if token in text:
                    hits.append(f"{path.relative_to(root)}: {token}")
    assert hits == []
    assert not (root / "utils" / "op").exists()
    assert not (root / "utils" / "capture" / "op_capture.py").exists()
