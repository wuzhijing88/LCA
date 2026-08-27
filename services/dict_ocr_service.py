# -*- coding: utf-8 -*-
"""点阵字库 OCR：兼容大漠文本字库、OP 文本字库和 OP 二进制 .dict。"""

from __future__ import annotations

import logging
import os
import re
import struct
import threading
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import cv2

    _CV2_AVAILABLE = True
except Exception:
    cv2 = None
    _CV2_AVAILABLE = False

DM_DEFAULT_HEIGHT = 11
DICT_INFO_STRUCT = struct.Struct("<hhi")
WORD1_INFO_STRUCT = struct.Struct("<BBH16s")
WORD0_STRUCT = struct.Struct("<8shhI32I")

_HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")
_OP_META_RE = re.compile(r"^(\d+)\s*,\s*(\d+)\s*,\s*(\d+)$")
_DM_META_RE = re.compile(r"^(-?\d+)\.(-?\d+)\.(-?\d+)$")
_DM_COUNT_RE = re.compile(r"^-?\d+$")
_COLOR_PART_RE = re.compile(
    r"^#?(?P<rgb>[0-9A-Fa-f]{6})(?:-(?P<delta>[0-9A-Fa-f]{6}))?$"
)

_CACHE_LOCK = threading.RLock()
_DICT_CACHE: Dict[str, Tuple[Tuple[int, int, int], "DictLibrary"]] = {}


@dataclass(frozen=True)
class Glyph:
    text: str
    width: int
    height: int
    bit_count: int
    bitmap: np.ndarray

    @property
    def area(self) -> int:
        return int(self.width) * int(self.height)


@dataclass
class DictLibrary:
    path: str
    glyphs: List[Glyph] = field(default_factory=list)
    format_name: str = ""

    def __len__(self) -> int:
        return len(self.glyphs)

    @property
    def texts(self) -> List[str]:
        return [glyph.text for glyph in self.glyphs]


@dataclass(frozen=True)
class GlyphHit:
    text: str
    x: int
    y: int
    w: int
    h: int
    score: float


def _hex_nibble(char: str) -> int:
    code = ord(char)
    if 48 <= code <= 57:
        return code - 48
    if 65 <= code <= 70:
        return code - 55
    if 97 <= code <= 102:
        return code - 87
    raise ValueError(f"非法十六进制字符: {char!r}")


def _is_hex(text: str) -> bool:
    return bool(text) and _HEX_RE.fullmatch(text) is not None


def _decode_wchar_name(raw: bytes) -> str:
    try:
        return raw.decode("utf-16-le", errors="ignore").split("\x00", 1)[0].strip()
    except Exception:
        return ""


def _bits_from_hex_msb(hex_text: str) -> List[int]:
    bits: List[int] = []
    for char in hex_text:
        value = _hex_nibble(char)
        bits.extend(((value >> shift) & 1) for shift in (3, 2, 1, 0))
    return bits


def _bitmap_from_column_bits(bits: Sequence[int], width: int, height: int) -> np.ndarray:
    bitmap = np.zeros((height, width), dtype=np.uint8)
    limit = min(len(bits), width * height)
    index = 0
    for x in range(width):
        for y in range(height):
            if index >= limit:
                return bitmap
            if bits[index]:
                bitmap[y, x] = 1
            index += 1
    return bitmap


def _bitmap_from_op_bytes(data: bytes, width: int, height: int) -> np.ndarray:
    bitmap = np.zeros((height, width), dtype=np.uint8)
    index = 0
    total = width * height
    data_len = len(data)
    for x in range(width):
        for y in range(height):
            if index >= total:
                return bitmap
            byte_index = index >> 3
            if byte_index >= data_len:
                return bitmap
            if (data[byte_index] >> (index & 7)) & 1:
                bitmap[y, x] = 1
            index += 1
    return bitmap


def _dm_width_for_height(total_bits: int, height: int) -> int:
    if height <= 0 or total_bits < height:
        return 0
    if total_bits % height:
        return (total_bits - 1) // height
    return total_bits // height


def _choose_dm_height(total_bits: int, declared_height: int) -> int:
    def _valid(height: int) -> bool:
        width = _dm_width_for_height(total_bits, height)
        return 1 <= height <= 255 and 0 < width <= 255

    if _valid(declared_height):
        return declared_height
    if _valid(DM_DEFAULT_HEIGHT):
        return DM_DEFAULT_HEIGHT
    if 1 <= declared_height <= 255:
        return declared_height
    return DM_DEFAULT_HEIGHT


def _make_glyph(text: str, bitmap: np.ndarray, bit_count: int = 0) -> Optional[Glyph]:
    if bitmap is None or bitmap.size == 0:
        return None
    height, width = bitmap.shape[:2]
    if width <= 0 or height <= 0 or width > 255 or height > 255:
        return None
    ones = int(np.count_nonzero(bitmap))
    if ones <= 0:
        return None
    name = str(text or "").strip()
    if not name:
        return None
    return Glyph(
        text=name,
        width=int(width),
        height=int(height),
        bit_count=int(bit_count or ones),
        bitmap=np.ascontiguousarray(bitmap, dtype=np.uint8),
    )


def parse_op_text_entry(line: str) -> Optional[Glyph]:
    parts = [part.strip() for part in str(line or "").split("$")]
    if len(parts) != 3:
        return None
    name, meta, hex_data = parts
    match = _OP_META_RE.match(meta)
    if not match or not name or not _is_hex(hex_data) or len(hex_data) % 2:
        return None
    height = int(match.group(1))
    width = int(match.group(2))
    bit_count = int(match.group(3))
    if height <= 0 or width <= 0 or height > 255 or width > 255:
        return None
    expected_bytes = (width * height + 7) // 8
    if len(hex_data) != expected_bytes * 2:
        return None
    if bit_count <= 0 or bit_count > width * height:
        return None
    data = bytes(int(hex_data[index : index + 2], 16) for index in range(0, len(hex_data), 2))
    bitmap = _bitmap_from_op_bytes(data, width, height)
    return _make_glyph(name, bitmap, bit_count)


def parse_dm_text_entry(line: str) -> Optional[Glyph]:
    parts = [part.strip() for part in str(line or "").split("$")]
    if len(parts) != 4:
        return None
    hex_data, name, meta, height_text = parts
    if not name or not _is_hex(hex_data):
        return None
    if not (_DM_META_RE.match(meta) or _DM_COUNT_RE.match(meta)):
        return None
    try:
        declared_height = int(height_text, 10)
    except ValueError:
        return None
    total_bits = len(hex_data) * 4
    height = _choose_dm_height(total_bits, declared_height)
    width = _dm_width_for_height(total_bits, height)
    if width <= 0 or width > 255:
        return None
    bits = _bits_from_hex_msb(hex_data)
    bitmap = _bitmap_from_column_bits(bits, width, height)
    return _make_glyph(name, bitmap)


def parse_simple_text_entry(line: str) -> Optional[Glyph]:
    parts = [part.strip() for part in str(line or "").split("$")]
    if len(parts) != 2:
        return None
    left, right = parts
    if _is_hex(left) and not _is_hex(right):
        hex_data, name = left, right
    elif _is_hex(right) and not _is_hex(left):
        name, hex_data = left, right
    else:
        return None
    if not name:
        return None
    total_bits = len(hex_data) * 4
    height = _choose_dm_height(total_bits, DM_DEFAULT_HEIGHT)
    width = _dm_width_for_height(total_bits, height)
    if width <= 0 or width > 255:
        return None
    bits = _bits_from_hex_msb(hex_data)
    bitmap = _bitmap_from_column_bits(bits, width, height)
    return _make_glyph(name, bitmap)


def parse_text_dict_entry(line: str) -> Optional[Glyph]:
    text = str(line or "").strip()
    if not text or text.startswith("#") or text.startswith("//"):
        return None
    dollar_count = text.count("$")
    if dollar_count == 3:
        return parse_dm_text_entry(text)
    if dollar_count == 2:
        return parse_op_text_entry(text)
    if dollar_count == 1:
        return parse_simple_text_entry(text)
    return None


def _read_text_lines(raw: bytes) -> List[str]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1"):
        try:
            return raw.decode(encoding).splitlines()
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="ignore").splitlines()


def parse_text_dict_bytes(raw: bytes) -> List[Glyph]:
    glyphs: List[Glyph] = []
    for line in _read_text_lines(raw):
        glyph = parse_text_dict_entry(line)
        if glyph is not None:
            glyphs.append(glyph)
    return glyphs


def _is_op_binary_dict(raw: bytes) -> bool:
    if not raw or len(raw) < DICT_INFO_STRUCT.size:
        return False
    try:
        version, word_count, check_code = DICT_INFO_STRUCT.unpack_from(raw, 0)
    except struct.error:
        return False
    if word_count <= 0 or check_code != (version ^ word_count):
        return False
    offset = DICT_INFO_STRUCT.size
    if version == 0:
        return offset + word_count * WORD0_STRUCT.size == len(raw)
    if version != 1:
        return False
    for _ in range(word_count):
        if offset + WORD1_INFO_STRUCT.size > len(raw):
            return False
        width, height, bit_count, _name = WORD1_INFO_STRUCT.unpack_from(raw, offset)
        offset += WORD1_INFO_STRUCT.size
        if width <= 0 or height <= 0 or bit_count <= 0 or bit_count > width * height:
            return False
        data_size = (width * height + 7) // 8
        offset += data_size
        if offset > len(raw):
            return False
    return offset == len(raw)


def _glyph_from_v0_word(payload: Tuple) -> Optional[Glyph]:
    name = _decode_wchar_name(payload[0])
    width = int(payload[1])
    height = int(payload[2])
    bit_count = int(payload[3])
    columns = payload[4:]
    if width <= 0 or height <= 0 or width > 255 or height > 255:
        return None
    bitmap = np.zeros((height, width), dtype=np.uint8)
    for x in range(width):
        column = int(columns[x])
        for y in range(height):
            if (column >> (31 - y)) & 1:
                bitmap[y, x] = 1
    return _make_glyph(name, bitmap, bit_count)


def parse_op_binary_dict(raw: bytes) -> List[Glyph]:
    if not _is_op_binary_dict(raw):
        return []
    version, word_count, _check = DICT_INFO_STRUCT.unpack_from(raw, 0)
    offset = DICT_INFO_STRUCT.size
    glyphs: List[Glyph] = []
    if version == 0:
        for _ in range(word_count):
            payload = WORD0_STRUCT.unpack_from(raw, offset)
            offset += WORD0_STRUCT.size
            glyph = _glyph_from_v0_word(payload)
            if glyph is not None:
                glyphs.append(glyph)
        return glyphs
    for _ in range(word_count):
        width, height, bit_count, name_raw = WORD1_INFO_STRUCT.unpack_from(raw, offset)
        offset += WORD1_INFO_STRUCT.size
        data_size = (width * height + 7) // 8
        data = raw[offset : offset + data_size]
        offset += data_size
        name = _decode_wchar_name(name_raw)
        bitmap = _bitmap_from_op_bytes(data, int(width), int(height))
        glyph = _make_glyph(name, bitmap, int(bit_count))
        if glyph is not None:
            glyphs.append(glyph)
    return glyphs


def parse_dict_bytes(raw: bytes, path: str = "") -> DictLibrary:
    glyphs: List[Glyph] = []
    format_name = ""
    if _is_op_binary_dict(raw):
        glyphs = parse_op_binary_dict(raw)
        format_name = "op_binary"
    if not glyphs:
        glyphs = parse_text_dict_bytes(raw)
        if glyphs:
            sample = raw.find(b"$")
            format_name = "text"
            if sample >= 0:
                preview = raw[sample : sample + 80]
                if preview.count(b"$") >= 3:
                    format_name = "damo_text"
                elif preview.count(b"$") == 2:
                    format_name = "op_text"
    glyphs.sort(key=lambda item: (-item.height, -item.width, item.bit_count, item.text))
    return DictLibrary(path=path, glyphs=glyphs, format_name=format_name)


def encode_dm_text_entry(glyph: Glyph) -> str:
    bits: List[int] = []
    for x in range(glyph.width):
        for y in range(glyph.height):
            bits.append(1 if glyph.bitmap[y, x] else 0)
    while len(bits) % 4:
        bits.append(0)
    hex_chars = []
    digits = "0123456789ABCDEF"
    for index in range(0, len(bits), 4):
        nibble = (bits[index] << 3) | (bits[index + 1] << 2) | (bits[index + 2] << 1) | bits[index + 3]
        hex_chars.append(digits[nibble])
    return f"{''.join(hex_chars)}${glyph.text}$0.0.{glyph.bit_count}${glyph.height}"


def encode_op_text_entry(glyph: Glyph) -> str:
    total = glyph.width * glyph.height
    data = bytearray((total + 7) // 8)
    index = 0
    for x in range(glyph.width):
        for y in range(glyph.height):
            if glyph.bitmap[y, x]:
                data[index >> 3] |= 1 << (index & 7)
            index += 1
    return f"{glyph.text}${glyph.height},{glyph.width},{glyph.bit_count}${data.hex().upper()}"


def rgb_to_damo_color(red: int, green: int, blue: int, delta: int = 16) -> str:
    offset = max(0, min(255, int(delta)))
    return f"{int(red):02X}{int(green):02X}{int(blue):02X}-{offset:02X}{offset:02X}{offset:02X}"


def merge_damo_colors(existing: str, new_color: str) -> str:
    parts = []
    seen = set()
    for raw in f"{existing}|{new_color}".replace("；", "|").split("|"):
        token = raw.strip().upper()
        if not token or token in seen:
            continue
        seen.add(token)
        parts.append(token)
    return "|".join(parts)


@dataclass
class ExtractedGlyph:
    bitmap: np.ndarray
    x: int
    y: int
    width: int
    height: int
    bit_count: int
    text: str = ""

    def to_glyph(self) -> Optional[Glyph]:
        return _make_glyph(self.text, self.bitmap, self.bit_count)


def _ink_ranges(values: np.ndarray, max_gap: int, min_run: int = 1) -> List[Tuple[int, int]]:
    active = np.asarray(values) > 0
    if active.size == 0 or not bool(active.any()):
        return []
    ranges: List[Tuple[int, int]] = []
    start = None
    gap = 0
    for index, ink in enumerate(active.tolist()):
        if ink:
            if start is None:
                start = index
            gap = 0
            continue
        if start is None:
            continue
        gap += 1
        if gap > max(0, int(max_gap)):
            end = index - gap
            if end - start + 1 >= min_run:
                ranges.append((start, end))
            start = None
            gap = 0
    if start is not None:
        end = len(active) - 1
        if end - start + 1 >= min_run:
            ranges.append((start, end))
    return ranges


def _trim_binary_box(mask: np.ndarray) -> Optional[Tuple[np.ndarray, int, int]]:
    if mask is None or mask.size == 0:
        return None
    rows = np.any(mask > 0, axis=1)
    cols = np.any(mask > 0, axis=0)
    if not bool(rows.any()) or not bool(cols.any()):
        return None
    y_index = np.flatnonzero(rows)
    x_index = np.flatnonzero(cols)
    top, bottom = int(y_index[0]), int(y_index[-1])
    left, right = int(x_index[0]), int(x_index[-1])
    crop = mask[top : bottom + 1, left : right + 1].copy()
    return crop, left, top


def _glyph_from_mask_box(
    mask: np.ndarray,
    left: int,
    top: int,
    right: int,
    bottom: int,
    *,
    min_width: int,
    min_height: int,
    min_area: int,
) -> Optional[ExtractedGlyph]:
    height, width = mask.shape[:2]
    x1 = max(0, min(width - 1, int(left)))
    y1 = max(0, min(height - 1, int(top)))
    x2 = max(x1, min(width - 1, int(right)))
    y2 = max(y1, min(height - 1, int(bottom)))
    trimmed = _trim_binary_box(mask[y1 : y2 + 1, x1 : x2 + 1])
    if trimmed is None:
        return None
    crop, dx, dy = trimmed
    box_h, box_w = crop.shape[:2]
    area = int(crop.sum())
    if box_w < min_width or box_h < min_height or area < min_area:
        return None
    if box_w > 255 or box_h > 255:
        return None
    return ExtractedGlyph(
        bitmap=crop,
        x=x1 + dx,
        y=y1 + dy,
        width=box_w,
        height=box_h,
        bit_count=area,
    )


def extract_single_glyph(
    binary: np.ndarray,
    *,
    min_width: int = 1,
    min_height: int = 1,
    min_area: int = 2,
) -> List[ExtractedGlyph]:
    if binary is None or binary.size == 0:
        return []
    mask = (binary > 0).astype(np.uint8)
    height, width = mask.shape[:2]
    glyph = _glyph_from_mask_box(
        mask,
        0,
        0,
        width - 1,
        height - 1,
        min_width=min_width,
        min_height=min_height,
        min_area=min_area,
    )
    return [glyph] if glyph is not None else []


def extract_glyphs_from_binary(
    binary: np.ndarray,
    *,
    mode: str = "multiple",
    row_gap: int = 4,
    col_gap: int = 8,
    min_width: int = 1,
    min_height: int = 1,
    min_area: int = 2,
) -> List[ExtractedGlyph]:
    """按大漠方式切字：整框单个，或多个时用行列投影，框内笔画整块收取。"""
    if binary is None or binary.size == 0:
        return []
    if str(mode or "").strip() in {"single", "单个", "单个提取"}:
        return extract_single_glyph(
            binary,
            min_width=min_width,
            min_height=min_height,
            min_area=min_area,
        )

    mask = (binary > 0).astype(np.uint8)
    height, width = mask.shape[:2]
    row_ranges = _ink_ranges(mask.sum(axis=1), max_gap=int(row_gap), min_run=max(1, min_height))
    if not row_ranges:
        return extract_single_glyph(
            mask,
            min_width=min_width,
            min_height=min_height,
            min_area=min_area,
        )

    items: List[ExtractedGlyph] = []
    for top, bottom in row_ranges:
        band = mask[top : bottom + 1]
        col_ranges = _ink_ranges(band.sum(axis=0), max_gap=int(col_gap), min_run=max(1, min_width))
        if not col_ranges:
            glyph = _glyph_from_mask_box(
                mask,
                0,
                top,
                width - 1,
                bottom,
                min_width=min_width,
                min_height=min_height,
                min_area=min_area,
            )
            if glyph is not None:
                items.append(glyph)
            continue
        for left, right in col_ranges:
            glyph = _glyph_from_mask_box(
                mask,
                left,
                top,
                right,
                bottom,
                min_width=min_width,
                min_height=min_height,
                min_area=min_area,
            )
            if glyph is not None:
                items.append(glyph)
    if not items:
        return extract_single_glyph(
            mask,
            min_width=min_width,
            min_height=min_height,
            min_area=min_area,
        )
    return sort_glyphs_reading_order(items)


def sort_glyphs_reading_order(items: Sequence[ExtractedGlyph]) -> List[ExtractedGlyph]:
    """同一行按从左到右排。用竖直中心判断同行，避免高一点的字被排到最前。"""
    glyphs = [item for item in items if item is not None]
    if len(glyphs) <= 1:
        return list(glyphs)

    def center_y(item: ExtractedGlyph) -> float:
        return float(item.y) + float(item.height) * 0.5

    ordered = sorted(glyphs, key=lambda item: (center_y(item), item.x))
    rows: List[List[ExtractedGlyph]] = []
    row_centers: List[float] = []
    for item in ordered:
        cy = center_y(item)
        threshold = max(6.0, float(item.height) * 0.45)
        if rows and abs(cy - row_centers[-1]) <= threshold:
            rows[-1].append(item)
            count = len(rows[-1])
            row_centers[-1] = (row_centers[-1] * (count - 1) + cy) / count
        else:
            rows.append([item])
            row_centers.append(cy)
    result: List[ExtractedGlyph] = []
    for row in rows:
        row.sort(key=lambda item: item.x)
        result.extend(row)
    return result


def write_dict_text_file(path: str, glyphs: Sequence[Glyph], *, append: bool = True, fmt: str = "damo") -> int:
    encoder = encode_op_text_entry if str(fmt).lower() in {"op", "op_text"} else encode_dm_text_entry
    lines = []
    existing = set()
    if append and os.path.isfile(path):
        with open(path, "rb") as handle:
            raw = handle.read()
        for line in _read_text_lines(raw):
            text = line.strip()
            if not text:
                continue
            lines.append(text)
            existing.add(text)
    added = 0
    for glyph in glyphs:
        if glyph is None or not str(glyph.text or "").strip() or str(glyph.text).startswith("?"):
            continue
        line = encoder(glyph)
        if line in existing:
            continue
        lines.append(line)
        existing.add(line)
        added += 1
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
        if lines:
            handle.write("\n")
    with _CACHE_LOCK:
        _DICT_CACHE.pop(os.path.normcase(os.path.abspath(path)), None)
    return added


def resolve_dict_path(raw_path: str) -> Optional[str]:
    text = str(raw_path or "").strip().strip('"')
    if not text:
        return None
    if os.path.isfile(text):
        return os.path.abspath(text)

    basename = os.path.basename(text.replace("\\", "/"))
    search_roots: List[str] = []
    try:
        from utils.app_paths import get_app_root, get_dicts_dir, get_images_dir, get_user_data_dir, get_workflows_dir

        images_dir = get_images_dir("LCA")
        user_dir = get_user_data_dir("LCA")
        search_roots.extend(
            [
                os.getcwd(),
                images_dir,
                get_dicts_dir("LCA"),
                os.path.join(user_dir, "dicts"),
                get_workflows_dir("LCA"),
                os.path.join(get_app_root(), "dicts"),
            ]
        )
    except Exception:
        search_roots.append(os.getcwd())

    candidates = []
    for root in search_roots:
        candidates.append(os.path.join(root, text))
        candidates.append(os.path.join(root, basename))
        normalized = text.replace("\\", "/").lstrip("./")
        if normalized.startswith("images/"):
            try:
                from utils.app_paths import get_images_dir

                candidates.append(os.path.join(get_images_dir("LCA"), normalized[len("images/") :]))
            except Exception:
                pass

    try:
        from utils.image_paths import get_image_path_resolver

        resolved = get_image_path_resolver().resolve(text)
        if resolved:
            candidates.append(resolved)
    except Exception:
        pass

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


def load_dict_library(raw_path: str) -> DictLibrary:
    path = resolve_dict_path(raw_path)
    if not path:
        raise FileNotFoundError(f"找不到字库文件: {raw_path}")
    stat = os.stat(path)
    cache_key = os.path.normcase(path)
    fingerprint = (int(stat.st_mtime_ns), int(stat.st_size))
    with _CACHE_LOCK:
        cached = _DICT_CACHE.get(cache_key)
        if cached and cached[0] == fingerprint:
            return cached[1]
    with open(path, "rb") as handle:
        raw = handle.read()
    library = parse_dict_bytes(raw, path=path)
    if not library.glyphs:
        raise ValueError(f"字库为空或格式无法识别: {path}")
    with _CACHE_LOCK:
        _DICT_CACHE[cache_key] = (fingerprint, library)
    logger.info("[字库OCR] 已加载 %s，共 %s 个字形，格式=%s", path, len(library), library.format_name)
    return library


def _parse_hex_color(text: str) -> Tuple[int, int, int]:
    value = int(text, 16)
    return (value >> 16) & 255, (value >> 8) & 255, value & 255


def parse_color_format(color_format: str) -> List[Tuple[Tuple[int, int, int], Tuple[int, int, int]]]:
    text = str(color_format or "").strip()
    if not text:
        return []
    colors: List[Tuple[Tuple[int, int, int], Tuple[int, int, int]]] = []
    for part in text.replace("；", "|").replace(";", "|").split("|"):
        token = part.strip()
        if not token:
            continue
        match = _COLOR_PART_RE.match(token)
        if not match:
            raise ValueError(f"无法解析颜色格式: {token}")
        rgb = _parse_hex_color(match.group("rgb"))
        delta_text = match.group("delta")
        delta = _parse_hex_color(delta_text) if delta_text else (0, 0, 0)
        colors.append((rgb, delta))
    return colors


def binarize_image(image: np.ndarray, color_format: str = "") -> np.ndarray:
    if image is None or image.size == 0:
        raise ValueError("识别图像为空")
    colors = parse_color_format(color_format)
    if colors:
        if image.ndim == 2:
            pixels = np.repeat(image[:, :, None], 3, axis=2)
        else:
            pixels = image
        # 截图为 BGR，大漠颜色串是 RRGGBB。
        blue = pixels[:, :, 0].astype(np.int16)
        green = pixels[:, :, 1].astype(np.int16)
        red = pixels[:, :, 2].astype(np.int16)
        mask = np.zeros(pixels.shape[:2], dtype=bool)
        for (cr, cg, cb), (dr, dg, db) in colors:
            mask |= (
                (np.abs(red - cr) <= dr)
                & (np.abs(green - cg) <= dg)
                & (np.abs(blue - cb) <= db)
            )
        return mask.astype(np.uint8)

    if image.ndim == 3:
        if _CV2_AVAILABLE:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = (
                0.114 * image[:, :, 0]
                + 0.587 * image[:, :, 1]
                + 0.299 * image[:, :, 2]
            ).astype(np.uint8)
    else:
        gray = image
    if _CV2_AVAILABLE:
        _, binary = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    else:
        threshold = int(np.mean(gray))
        binary = (gray > threshold).astype(np.uint8)
    if int(binary.sum()) > binary.size // 2:
        binary = 1 - binary
    return binary.astype(np.uint8)


def _match_scores(binary: np.ndarray, glyph: Glyph) -> Optional[np.ndarray]:
    height, width = binary.shape[:2]
    if height < glyph.height or width < glyph.width:
        return None
    if _CV2_AVAILABLE:
        scores = cv2.matchTemplate(
            binary.astype(np.float32),
            glyph.bitmap.astype(np.float32),
            cv2.TM_CCORR,
        )
        return scores / float(max(glyph.bit_count, 1))

    ones = glyph.bitmap.astype(np.float32)
    window = np.lib.stride_tricks.sliding_window_view(binary.astype(np.float32), ones.shape)
    hits = np.einsum("ijkl,kl->ij", window, ones)
    return hits / float(max(glyph.bit_count, 1))


def find_glyph_hits(
    binary: np.ndarray,
    library: DictLibrary,
    similarity: float,
    texts: Optional[Iterable[str]] = None,
) -> List[GlyphHit]:
    wanted = None
    if texts is not None:
        wanted = {str(item) for item in texts if str(item)}
    hits: List[GlyphHit] = []
    threshold = min(1.0, max(0.1, float(similarity)))
    for glyph in library.glyphs:
        if wanted is not None and glyph.text not in wanted:
            continue
        scores = _match_scores(binary, glyph)
        if scores is None:
            continue
        rows, cols = np.where(scores >= threshold)
        if rows.size == 0:
            continue
        for row, col in zip(rows.tolist(), cols.tolist()):
            hits.append(
                GlyphHit(
                    text=glyph.text,
                    x=int(col),
                    y=int(row),
                    w=glyph.width,
                    h=glyph.height,
                    score=float(scores[row, col]),
                )
            )
    return hits


def _nms_hits(hits: Sequence[GlyphHit], overlap: float = 0.35) -> List[GlyphHit]:
    if not hits:
        return []
    ordered = sorted(hits, key=lambda item: (-item.score, -(item.w * item.h), item.y, item.x))
    kept: List[GlyphHit] = []
    for hit in ordered:
        blocked = False
        for other in kept:
            inter_x1 = max(hit.x, other.x)
            inter_y1 = max(hit.y, other.y)
            inter_x2 = min(hit.x + hit.w, other.x + other.w)
            inter_y2 = min(hit.y + hit.h, other.y + other.h)
            if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
                continue
            inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
            if inter / float(max(hit.w * hit.h, 1)) >= overlap:
                blocked = True
                break
        if not blocked:
            kept.append(hit)
    return kept


def _bbox(x1: int, y1: int, x2: int, y2: int) -> List[List[int]]:
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def group_hits_as_lines(hits: Sequence[GlyphHit]) -> List[Dict[str, object]]:
    if not hits:
        return []
    ordered = sorted(hits, key=lambda item: (item.y, item.x))
    lines: List[List[GlyphHit]] = []
    for hit in ordered:
        placed = False
        for line in lines:
            ref = line[0]
            tolerance = max(3, int(max(ref.h, hit.h) * 0.6))
            if abs(hit.y - ref.y) <= tolerance:
                line.append(hit)
                placed = True
                break
        if not placed:
            lines.append([hit])

    results: List[Dict[str, object]] = []
    for line in lines:
        line.sort(key=lambda item: item.x)
        text = "".join(item.text for item in line)
        x1 = min(item.x for item in line)
        y1 = min(item.y for item in line)
        x2 = max(item.x + item.w for item in line)
        y2 = max(item.y + item.h for item in line)
        score = min(item.score for item in line)
        results.append(
            {
                "text": text,
                "confidence": float(score),
                "bbox": _bbox(x1, y1, x2, y2),
            }
        )
    return results


def recognize_text(
    image: np.ndarray,
    library: DictLibrary,
    color_format: str = "",
    similarity: float = 0.9,
) -> List[Dict[str, object]]:
    binary = binarize_image(image, color_format)
    hits = _nms_hits(find_glyph_hits(binary, library, similarity))
    return group_hits_as_lines(hits)


def _split_find_targets(target_text: str) -> List[str]:
    text = str(target_text or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[|｜]", text) if part.strip()]


def _link_string_hits(hits: Sequence[GlyphHit], target: str) -> Optional[Tuple[List[GlyphHit], float]]:
    if not target:
        return None
    by_char: Dict[str, List[GlyphHit]] = {}
    for hit in hits:
        by_char.setdefault(hit.text, []).append(hit)
    first = target[0]
    starts = by_char.get(first) or []
    best: Optional[Tuple[List[GlyphHit], float]] = None
    for start in starts:
        chain = [start]
        cursor = start
        failed = False
        for char in target[1:]:
            gap = max(2, cursor.w)
            matched = None
            for candidate in by_char.get(char) or []:
                if candidate.x < cursor.x + max(1, cursor.w - 2):
                    continue
                if candidate.x > cursor.x + cursor.w + gap:
                    continue
                if abs(candidate.y - cursor.y) > max(3, cursor.h // 2):
                    continue
                if matched is None or candidate.x < matched.x or (
                    candidate.x == matched.x and candidate.score > matched.score
                ):
                    matched = candidate
            if matched is None:
                failed = True
                break
            chain.append(matched)
            cursor = matched
        if failed:
            continue
        score = min(item.score for item in chain)
        if best is None or score > best[1]:
            best = (chain, score)
    return best


def find_strings(
    image: np.ndarray,
    library: DictLibrary,
    target_text: str,
    color_format: str = "",
    similarity: float = 0.9,
) -> List[Dict[str, object]]:
    targets = _split_find_targets(target_text)
    if not targets:
        return recognize_text(image, library, color_format, similarity)
    binary = binarize_image(image, color_format)
    needed = set("".join(targets))
    needed.update(targets)
    hits = find_glyph_hits(binary, library, similarity, texts=needed)
    results: List[Dict[str, object]] = []
    for target in targets:
        exact_hits = [item for item in hits if item.text == target]
        if exact_hits:
            best = max(exact_hits, key=lambda item: (item.score, item.w * item.h))
            results.append(
                {
                    "text": target,
                    "confidence": float(best.score),
                    "bbox": _bbox(best.x, best.y, best.x + best.w, best.y + best.h),
                }
            )
            continue
        linked = _link_string_hits(hits, target)
        if linked is None:
            continue
        chain, score = linked
        x1 = min(item.x for item in chain)
        y1 = min(item.y for item in chain)
        x2 = max(item.x + item.w for item in chain)
        y2 = max(item.y + item.h for item in chain)
        results.append(
            {
                "text": target,
                "confidence": float(score),
                "bbox": _bbox(x1, y1, x2, y2),
            }
        )
    return results


def recognize_or_find(
    image: np.ndarray,
    library: DictLibrary,
    target_text: str = "",
    color_format: str = "",
    similarity: float = 0.9,
) -> List[Dict[str, object]]:
    if str(target_text or "").strip():
        return find_strings(image, library, target_text, color_format, similarity)
    return recognize_text(image, library, color_format, similarity)
