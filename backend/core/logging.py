#!/usr/bin/env python3
"""Shared logging setup."""

import logging

from backend.core.config import LOG_LEVEL

_CONFIGURED = False


def configure_logging():
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
    )
    _CONFIGURED = True


def get_logger(name):
    configure_logging()
    return logging.getLogger(name)
