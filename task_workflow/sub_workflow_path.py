# -*- coding: utf-8 -*-
"""Utilities for resolving sub-workflow file paths."""

from __future__ import annotations

import os
from typing import Optional


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


def _existing_file(path_text: str) -> Optional[str]:
    if not path_text:
        return None
    normalized = os.path.abspath(os.path.normpath(path_text))
    if os.path.isfile(normalized):
        return normalized
    return None


def resolve_sub_workflow_path(
    raw_path: object,
    parent_workflow_file: object = None,
) -> Optional[str]:
    """Resolve a sub-workflow path as stored, or relative to the parent workflow directory."""
    path_text = _clean_path_text(raw_path)
    if not path_text:
        return None

    existing = _existing_file(path_text)
    if existing:
        return existing

    base_dir = get_workflow_base_dir(parent_workflow_file)
    if not base_dir:
        return None
    if os.path.isabs(path_text):
        # Workflows are portable between machines. If a historical absolute
        # path no longer exists, recover by its basename beside the parent.
        return _existing_file(os.path.join(base_dir, os.path.basename(path_text)))
    return _existing_file(os.path.join(base_dir, path_text))
