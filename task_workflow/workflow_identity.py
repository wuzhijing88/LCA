# -*- coding: utf-8 -*-
"""Shared workflow identity helpers."""

from __future__ import annotations

import os
from typing import Optional


def normalize_workflow_id(workflow_id: Optional[str]) -> str:
    text = str(workflow_id or "").strip()
    return text or "default"


def normalize_workflow_filepath(workflow_filepath: Optional[str]) -> Optional[str]:
    text = str(workflow_filepath or "").strip()
    if not text:
        return None
    return os.path.abspath(os.path.normpath(text))

