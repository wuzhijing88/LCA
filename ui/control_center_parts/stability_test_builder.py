from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from task_workflow.thread_start import THREAD_START_TASK_TYPE
from task_workflow.workflow_payload import save_workflow_file

REQUIRED_TASK_TYPES = {
    THREAD_START_TASK_TYPE,
    "模拟鼠标操作",
    "模拟键盘操作",
    "延迟",
    "条件控制",
    "随机跳转",
    "线程控制",
    "线程窗口限制",
    "OCR文字识别",
    "点阵字库OCR",
    "YOLO目标检测",
    "录制回放",
    "附加条件",
    "子工作流",
    "自定义脚本",
    "图片点击",
}

# 长压枢纽只走失败后仍会「执行下一步」的任务。YOLO / 找图缺素材时会硬停，改走子工作流探针。
LOOP_SAFE_TASK_TYPES = {
    "模拟鼠标操作",
    "模拟键盘操作",
    "延迟",
    "条件控制",
    "自定义脚本",
    "线程控制",
    "子工作流",
    "录制回放",
    "OCR文字识别",
    "点阵字库OCR",
}
HARD_STOP_PROBE_TYPES = ("YOLO目标检测", "图片点击")

IMAGE_EXTENSIONS = {".png", ".bmp", ".jpg", ".jpeg", ".webp"}
MODEL_EXTENSIONS = {".onnx"}
MAX_HOLD_SECONDS = 0.12


def _looks_like_dict_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in {".dic", ".dict"}:
        return True
    if suffix != ".txt":
        return False
    name = path.name.lower()
    return "dict" in name or "ocr" in name or "字库" in name


@dataclass
class StabilityAssets:
    images: List[str] = field(default_factory=list)
    models: List[str] = field(default_factory=list)
    dicts: List[str] = field(default_factory=list)


def scan_stability_assets(roots: Optional[Iterable[Any]] = None) -> StabilityAssets:
    assets = StabilityAssets()
    search_roots = [Path(root) for root in (roots or []) if root]
    if not search_roots:
        search_roots = _default_asset_roots()
    seen_images = set()
    seen_models = set()
    seen_dicts = set()
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            resolved = str(path)
            if suffix in IMAGE_EXTENSIONS and resolved not in seen_images:
                seen_images.add(resolved)
                assets.images.append(resolved)
            elif suffix in MODEL_EXTENSIONS and resolved not in seen_models:
                seen_models.add(resolved)
                assets.models.append(resolved)
            elif _looks_like_dict_file(path) and resolved not in seen_dicts:
                seen_dicts.add(resolved)
                assets.dicts.append(resolved)
    return assets


def _default_asset_roots() -> List[Path]:
    roots: List[Path] = []
    try:
        from utils.app_paths import get_images_dir, get_workflows_dir, get_user_data_dir

        roots.extend(
            [
                Path(get_images_dir("LCA")),
                Path(get_workflows_dir("LCA")),
                Path(get_user_data_dir("LCA")) / "models",
            ]
        )
    except Exception:
        pass
    repo_root = Path(__file__).resolve().parents[2]
    roots.extend(
        [
            repo_root / "resources" / "icon_candidates",
            repo_root / "resources",
        ]
    )
    return roots


def _pick(items: Sequence[str], rng: random.Random, offset: int = 0) -> str:
    if not items:
        return ""
    return items[(offset + rng.randint(0, max(0, len(items) - 1))) % len(items)]


def _chaos_point(rng: random.Random) -> tuple[int, int]:
    return rng.randint(-400, 4200), rng.randint(-400, 4200)


def _chaos_region(rng: random.Random) -> Dict[str, int]:
    x, y = _chaos_point(rng)
    return {
        "region_x": x,
        "region_y": y,
        "region_width": rng.randint(1, 2400),
        "region_height": rng.randint(1, 1800),
    }


class _Graph:
    def __init__(self) -> None:
        self.cards: List[Dict[str, Any]] = []
        self.connections: List[Dict[str, Any]] = []
        self._next_id = 1

    def add(self, task_type: str, parameters: Optional[Mapping[str, Any]] = None, name: str = "") -> int:
        card_id = self._next_id
        self._next_id += 1
        column = (card_id - 1) % 6
        row = (card_id - 1) // 6
        self.cards.append(
            {
                "id": card_id,
                "task_type": task_type,
                "custom_name": name or task_type,
                "pos_x": 80 + column * 220,
                "pos_y": 80 + row * 140,
                "parameters": dict(parameters or {}),
            }
        )
        return card_id

    def connect(self, start_id: int, end_id: int, line_type: str = "sequential") -> None:
        self.connections.append(
            {
                "start_card_id": start_id,
                "end_card_id": end_id,
                "type": line_type,
            }
        )

    def to_workflow(self) -> Dict[str, Any]:
        return {
            "cards": self.cards,
            "connections": self.connections,
            "metadata": {"stability_test": True},
        }


def build_probe_workflow(task_type: str, parameters: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    graph = _Graph()
    start_id = graph.add(THREAD_START_TASK_TYPE, {}, "探起点")
    feature_id = graph.add(task_type, parameters, "探卡")
    graph.connect(start_id, feature_id, "sequential")
    return graph.to_workflow()


def build_stability_workflow(
    window_id: str,
    script_index: int,
    assets: Optional[StabilityAssets] = None,
    seed: int = 0,
    sub_workflow_file: str = "",
    probe_files: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    rng = random.Random(f"{seed}:{window_id}:{script_index}")
    assets = assets or StabilityAssets()
    probe_files = dict(probe_files or {})
    graph = _Graph()
    salt = abs(hash((window_id, script_index, seed))) % 1000

    limit_id = graph.add("线程窗口限制", {"bound_window_index": None}, "窗口限制")
    start_a = graph.add(THREAD_START_TASK_TYPE, {}, "线程A")
    start_b = graph.add(THREAD_START_TASK_TYPE, {}, "线程B")
    hub_a = graph.add("随机跳转", {"random_weights": {}}, "枢纽A")
    hub_b = graph.add("随机跳转", {"random_weights": {}}, "枢纽B")
    graph.connect(limit_id, start_a, "sequential")
    graph.connect(start_a, hub_a, "sequential")
    graph.connect(start_b, hub_b, "sequential")

    mouse_id = graph.add("模拟鼠标操作", _mouse_params(rng), "乱点")
    key_id = graph.add("模拟键盘操作", _keyboard_params(rng), "乱键")
    delay_id = graph.add("延迟", _delay_params(rng), "乱延迟")
    cond_id = graph.add("条件控制", _condition_params(rng), "乱条件")
    ocr_id = graph.add("OCR文字识别", _ocr_params(rng), "乱OCR")
    dict_ocr_id = graph.add("点阵字库OCR", _dict_ocr_params(rng, assets, salt), "乱点阵")
    yolo_id = graph.add("YOLO目标检测", _yolo_params(rng, assets, salt), "乱YOLO")
    graph.add("图片点击", _image_click_params(rng, assets, salt), "乱找图")
    replay_id = graph.add("录制回放", {"loop_count": 1, "speed": rng.choice([0.5, 1.0, 2.0]), "recorded_actions": ""}, "乱回放")
    script_id = graph.add("自定义脚本", {"script_source": _script_source(rng)}, "乱脚本")
    sub_id = graph.add(
        "子工作流",
        {
            "workflow_file": sub_workflow_file,
            "inherit_window": True,
            "on_success": "执行下一步",
            "on_failure": "执行下一步",
        },
        "乱子流",
    )
    thread_ctrl_id = graph.add(
        "线程控制",
        {"control_action": "恢复线程", "target_thread": "当前线程"},
        "乱线程控制",
    )
    watchdog_id = graph.add(
        "附加条件",
        {
            "monitor_type": "监控失败",
            "monitor_mode": "按次数",
            "count_threshold": rng.randint(8, 30),
            "action_on_trigger": "跳转到指定卡片",
            "jump_target_card_id": hub_a,
        },
        "乱看门狗",
    )

    probe_ids: List[int] = []
    for task_type in HARD_STOP_PROBE_TYPES:
        probe_path = str(probe_files.get(task_type) or "").strip()
        if not probe_path:
            continue
        probe_ids.append(
            graph.add(
                "子工作流",
                {
                    "workflow_file": probe_path,
                    "inherit_window": True,
                    "on_success": "执行下一步",
                    "on_failure": "执行下一步",
                },
                f"乱{task_type}探针",
            )
        )
    hub_features = [
        mouse_id,
        key_id,
        delay_id,
        cond_id,
        ocr_id,
        dict_ocr_id,
        replay_id,
        script_id,
        sub_id,
        thread_ctrl_id,
        *probe_ids,
    ]
    weights_a: Dict[str, int] = {}
    weights_b: Dict[str, int] = {}
    for feature_id in hub_features:
        graph.connect(hub_a, feature_id, "random")
        graph.connect(hub_b, feature_id, "random")
        graph.connect(feature_id, hub_a if rng.random() < 0.5 else hub_b, "sequential")
        weights_a[str(feature_id)] = 3
        weights_b[str(feature_id)] = 3
    _card_by_id(graph, hub_a)["parameters"]["random_weights"] = weights_a
    _card_by_id(graph, hub_b)["parameters"]["random_weights"] = weights_b
    graph.connect(cond_id, hub_a, "success")
    graph.connect(cond_id, hub_b, "failure")
    graph.connect(watchdog_id, mouse_id, "sequential")
    return graph.to_workflow()


def build_sub_workflow(seed: int = 0) -> Dict[str, Any]:
    rng = random.Random(seed + 99)
    graph = _Graph()
    start_id = graph.add(THREAD_START_TASK_TYPE, {}, "子起点")
    delay_id = graph.add("延迟", _delay_params(rng), "子延迟")
    graph.connect(start_id, delay_id, "sequential")
    return graph.to_workflow()


def generate_stability_pack(
    window_ids: Sequence[str],
    output_dir: Any,
    assets: Optional[StabilityAssets] = None,
    seed: int = 0,
) -> Dict[str, List[str]]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    assets = assets or scan_stability_assets()
    assets = _ensure_fallback_image(assets, destination)
    child_path = save_workflow_file(destination / "stability_child.lca", build_sub_workflow(seed))
    probe_rng = random.Random(seed + 101)
    probe_files = {
        "YOLO目标检测": str(
            save_workflow_file(
                destination / "stability_probe_yolo.lca",
                build_probe_workflow("YOLO目标检测", _yolo_params(probe_rng, assets, 1)),
            )
        ),
        "图片点击": str(
            save_workflow_file(
                destination / "stability_probe_image.lca",
                build_probe_workflow("图片点击", _image_click_params(probe_rng, assets, 2)),
            )
        ),
    }
    pack: Dict[str, List[str]] = {}
    for window_index, window_id in enumerate(window_ids):
        safe_id = _safe_token(window_id) or f"window{window_index + 1}"
        script_count = 2 + ((seed + window_index) % 2)
        paths: List[str] = []
        for script_index in range(script_count):
            workflow = build_stability_workflow(
                window_id,
                script_index,
                assets=assets,
                seed=seed + window_index * 17,
                sub_workflow_file=str(child_path),
                probe_files=probe_files,
            )
            file_path = save_workflow_file(
                destination / f"stability_{safe_id}_{script_index + 1}.lca",
                workflow,
            )
            paths.append(str(file_path))
        pack[str(window_id)] = paths
    return pack


def _safe_token(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(value or "")).strip("_")


def _card_by_id(graph: _Graph, card_id: int) -> Dict[str, Any]:
    for card in graph.cards:
        if card["id"] == card_id:
            return card
    raise KeyError(card_id)


def _ensure_fallback_image(assets: StabilityAssets, output_dir: Path) -> StabilityAssets:
    if assets.images:
        return assets
    source = Path(__file__).resolve().parents[2] / "resources" / "icon_candidates" / "A_flat_blue.png"
    fallback = Path(output_dir) / "soak_template.png"
    if source.is_file():
        fallback.write_bytes(source.read_bytes())
        assets.images.append(str(fallback))
    return assets


def _window_point(rng: random.Random) -> tuple[int, int]:
    return rng.randint(20, 360), rng.randint(24, 220)


def _mouse_params(rng: random.Random) -> Dict[str, Any]:
    x, y = _window_point(rng)
    return {
        "operation_mode": rng.choice(["坐标点击", "鼠标移动", "鼠标滚轮"]),
        "coordinate_source_mode": "手动输入",
        "coordinate_x": x,
        "coordinate_y": y,
        "coordinate_mode": "客户区坐标",
        "mouse_button": rng.choice(["左键", "右键", "中键"]),
        "on_success": "执行下一步",
        "on_failure": "执行下一步",
    }


def _keyboard_params(rng: random.Random) -> Dict[str, Any]:
    if rng.random() < 0.2:
        return {
            "input_type": "文本输入",
            "text_input_mode": "单组文本",
            "text_to_type": "".join(rng.choice("abcxyz0127") for _ in range(rng.randint(1, 3))),
            "delay_between_keystrokes": round(rng.uniform(0.0, MAX_HOLD_SECONDS), 3),
            "press_enter_after_text": False,
            "on_success": "执行下一步",
            "on_failure": "执行下一步",
        }
    combo = rng.choice(["esc", "f12", "ctrl+shift+a", "shift+f10", "ctrl+a", "ctrl+c"])
    return {
        "input_type": "键盘按键",
        "combo_key_sequence_text": combo,
        "combo_key_action": "完整执行",
        "combo_hold_duration": round(rng.uniform(0.02, MAX_HOLD_SECONDS), 3),
        "on_success": "执行下一步",
        "on_failure": "执行下一步",
    }


def _delay_params(rng: random.Random) -> Dict[str, Any]:
    low = round(rng.uniform(0.02, 0.2), 3)
    high = round(low + rng.uniform(0.02, 0.35), 3)
    return {
        "delay_mode": "随机延迟",
        "min_delay": low,
        "max_delay": high,
        "on_success": "执行下一步",
        "on_failure": "执行下一步",
    }


def _condition_params(rng: random.Random) -> Dict[str, Any]:
    return {
        "condition_type": "计数器判断",
        "target_execution_count": rng.randint(1, 4),
        "counter_comparison": rng.choice([">=", "==", "!=", "<"]),
        "enable_counter_reset": True,
        "counter_reset_timing": "条件满足时",
        "on_success": "执行下一步",
        "on_failure": "执行下一步",
    }


def _ocr_params(rng: random.Random) -> Dict[str, Any]:
    params = {
        "region_mode": "指定区域",
        "on_success": "执行下一步",
        "on_failure": "执行下一步",
    }
    params.update(_window_region(rng))
    return params


def _window_region(rng: random.Random) -> Dict[str, int]:
    return {
        "region_x": rng.randint(0, 32),
        "region_y": rng.randint(0, 32),
        "region_width": rng.randint(160, 380),
        "region_height": rng.randint(80, 200),
    }


def _dict_ocr_params(rng: random.Random, assets: StabilityAssets, salt: int) -> Dict[str, Any]:
    params = _ocr_params(rng)
    params["dict_file"] = _pick(assets.dicts, rng, salt)
    return params


def _yolo_params(rng: random.Random, assets: StabilityAssets, salt: int) -> Dict[str, Any]:
    params = {
        "yolo_backend": "原生",
        "model_path": _pick(assets.models, rng, salt),
        "confidence_threshold": round(rng.uniform(0.1, 0.9), 2),
        "iou_threshold": round(rng.uniform(0.2, 0.8), 2),
        "use_region": True,
        "on_success": "执行下一步",
        "on_failure": "执行下一步",
    }
    params.update(_window_region(rng))
    return params


def _image_click_params(rng: random.Random, assets: StabilityAssets, salt: int) -> Dict[str, Any]:
    return {
        "image_path": _pick(assets.images, rng, salt),
        "on_success": "执行下一步",
        "on_failure": "执行下一步",
    }


def _script_source(rng: random.Random) -> str:
    x, y = _window_point(rng)
    return (
        f"延时({round(rng.uniform(0.02, 0.08), 3)})\n"
        f"点击({x}, {y})\n"
    )
