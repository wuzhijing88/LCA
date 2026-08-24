import ast
import importlib.util
from pathlib import Path

from tasks import PRIMARY_TASK_MODULES, TASK_CONTRACT_METADATA


def test_primary_task_registry_points_to_modules_with_execute_task():
    failures = []
    for task_name, module_path in dict.items(PRIMARY_TASK_MODULES):
        spec = importlib.util.find_spec(module_path)
        if spec is None or not spec.origin:
            failures.append(f"{task_name}: module not found: {module_path}")
            continue
        source_path = Path(spec.origin)
        tree = ast.parse(source_path.read_text(encoding="utf-8-sig"), filename=str(source_path))
        has_execute_task = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "execute_task"
            for node in tree.body
        )
        if TASK_CONTRACT_METADATA[task_name]["executable"] and not has_execute_task:
            failures.append(f"{task_name}: execute_task missing in {module_path}")

    assert failures == []
