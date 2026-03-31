"""Backward-compatible alias: implementation lives in ``oven.api.decompiler``."""

from __future__ import annotations

import importlib
import sys

_impl = importlib.import_module("oven.api.decompiler")
sys.modules[__name__] = _impl
