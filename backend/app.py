#!/usr/bin/env python3
"""兼容入口，保留 `uvicorn backend.app:app` 用法。"""

from backend.api.app import app

__all__ = ['app']
