# -*- coding: utf-8 -*-
"""Utilities for resolving sub-workflow file paths."""

from __future__ import annotations

import os
from typing import List, Optional, Set


def _clean_path_text(raw_path: object) -> str:
    text = str(raw_path or "").strip()
    if not text:
        return ""
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        text = text[1:-1].strip()
    return text


def get_workflow_base_dir(parent_workflow_file: object) -> Optional[str]:
    """Return base directory for sub-workflow lookup."""
    parent_text = _clean_path_text(parent_workflow_file)
    if not parent_text:
        return None

    normalized = os.path.abspath(os.path.normpath(parent_text))
    if os.path.isdir(normalized):
        return normalized
    return os.path.dirname(normalized) or None


def _split_tail_parts(path_text: str) -> List[str]:
    normalized = os.path.normpath(path_text)
    drive, tail = os.path.splitdrive(normalized)
    if drive:
        normalized = tail

    normalized = normalized.replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part and part not in (".", "..")]
    return parts


def _existing_file(path_text: str) -> Optional[str]:
    if not path_text:
        return None
    normalized = os.path.abspath(os.path.normpath(path_text))
    if os.path.isfile(normalized):
        return normalized
    return None


def _iter_candidate_paths(raw_path: str, base_dir: Optional[str]) -> List[str]:
    candidates: List[str] = []
    seen: Set[str] = set()

    def _push(candidate: str) -> None:
        normalized = os.path.normcase(os.path.normpath(candidate))
        if normalized in seen:
            return
        seen.add(normalized)
        candidates.append(candidate)

    _push(raw_path)
    _push(os.path.normpath(raw_path))

    if base_dir:
        base_dir = os.path.abspath(os.path.normpath(base_dir))

        if not os.path.isabs(raw_path):
            _push(os.path.join(base_dir, raw_path))
            _push(os.path.join(base_dir, os.path.normpath(raw_path)))

        tail_parts = _split_tail_parts(raw_path)
        if tail_parts:
            max_levels = min(4, len(tail_parts))
            for level in range(max_levels, 0, -1):
                suffix = os.path.join(*tail_parts[-level:])
                _push(os.path.join(base_dir, suffix))

            basename = tail_parts[-1]
            _push(os.path.join(base_dir, basename))

    return candidates


def _search_same_name_in_base(raw_path: str, base_dir: str) -> Optional[str]:
    basename = os.path.basename(os.path.normpath(raw_path))
    if not basename:
        return None

    matches: List[str] = []
    scanned_dirs = 0
    max_scan_dirs = 2000
    for root, _, files in os.walk(base_dir):
        scanned_dirs += 1
        if scanned_dirs > max_scan_dirs:
            break
        if basename in files:
            matches.append(os.path.join(root, basename))

    if not matches:
        return None
    if len(matches) == 1:
        return _existing_file(matches[0])

    matches.sort(
        key=lambda path: (
            path.count(os.sep),
            len(path),
            os.path.normcase(path),
        )
    )
    return _existing_file(matches[0])


def resolve_sub_workflow_path(
    raw_path: object,
    parent_workflow_file: object = None,
) -> Optional[str]:
    """
    Resolve a sub-workflow path.

    Resolution order:
    1. Original path (absolute/relative)
    2. Paths derived from parent workflow directory
    3. Recursive same-name search under parent workflow directory
    """
    path_text = _clean_path_text(raw_path)
    if not path_text:
        return None

    base_dir = get_workflow_base_dir(parent_workflow_file)
    for candidate in _iter_candidate_paths(path_text, base_dir):
        existing = _existing_file(candidate)
        if existing:
            return existing

    if base_dir:
        return _search_same_name_in_base(path_text, base_dir)

    return None

