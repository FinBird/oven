"""Backward-compatible alias: implementation lives in ``api.decompiler``."""

from __future__ import annotations

import importlib
import sys

_impl = importlib.import_module("api.decompiler")
sys.modules[__name__] = _impl
