#!/usr/bin/env python3
"""!
********************************************************************************
@file   __init__.py
@brief  Logger package initialization for WakeStation logging system
@author Mahesvara ( https://github.com/Oratorian )
@copyright Mahesvara ( https://github.com/Oratorian )
********************************************************************************
"""

from .logger import get_logger, setup_logger, info, debug, warning, error, critical

__all__ = [
    "get_logger",
    "setup_logger",
    "info",
    "debug",
    "warning",
    "error",
    "critical",
]
