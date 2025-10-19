#!/usr/bin/env python3
"""!
********************************************************************************
@file   logger.py
@brief  Professional logging system with rsyslog-style formatting and rotation
@author Mahesvara ( https://github.com/Oratorian )
@copyright Mahesvara ( https://github.com/Oratorian )
********************************************************************************
"""

import logging
import sys
import os
from datetime import datetime
import glob
import config

# Global flag to ensure log rotation only happens once per application run
_log_rotated = False


class SizeRotatingFileHandler(logging.FileHandler):
    """
    Custom file handler that rotates log files when they reach maximum size.
    """

    def __init__(self, filename, max_size=None, **kwargs):
        super().__init__(filename, **kwargs)
        self.max_size = max_size or getattr(
            config, "LOG_MAX_SIZE", 10 * 1024 * 1024
        )  # 10MB default
        self.baseFilename = os.path.abspath(filename)

    def emit(self, record):
        """
        Emit a record, rotating the file if necessary.
        """
        try:
            if self.should_rotate():
                self.rotate()
        except Exception:
            pass  # Don't let rotation errors stop logging

        super().emit(record)

    def should_rotate(self):
        """
        Check if the log file should be rotated based on size.
        """
        try:
            if os.path.exists(self.baseFilename):
                return os.path.getsize(self.baseFilename) >= self.max_size
        except OSError:
            pass
        return False

    def rotate(self):
        """
        Rotate the log file using copy-and-truncate method.
        This works even when the file is open by our handler.
        """
        try:
            # Flush any pending writes
            if self.stream:
                self.stream.flush()

            # Rotate using copy-and-truncate (works with open handles)
            rotate_log_file(self.baseFilename, force=False)  # Size-based rotation

            # No need to reopen - the existing handle now points to truncated file
        except Exception:
            pass  # Don't let rotation errors stop logging


def rotate_log_file(log_file_path, force=False):
    """
    Rotate existing log file by copying it with a number suffix and truncating original.
    This method works on Windows even when the file is open by handlers.

    Args:
        log_file_path: Path to the log file to rotate
        force: Force rotation even if file is small (used for app restart)
    """
    if not os.path.exists(log_file_path):
        return  # No existing log file to rotate

    # Check file size for rotation (unless forced)
    if not force:
        try:
            file_size = os.path.getsize(log_file_path)
            max_size = getattr(config, "LOG_MAX_SIZE", 10 * 1024 * 1024)  # Default 10MB
            if file_size < max_size:
                return  # File not large enough for rotation
        except OSError:
            return  # Can't check size, skip rotation

    # Get the directory and base name
    log_dir = os.path.dirname(log_file_path)
    log_name = os.path.basename(log_file_path)

    # Find existing rotated files to determine next number
    pattern = os.path.join(log_dir, f"{log_name}.*")
    existing_files = glob.glob(pattern)

    # Extract numbers from existing rotated files
    numbers = []
    for file_path in existing_files:
        suffix = file_path.split(f"{log_file_path}.")[-1]
        try:
            numbers.append(int(suffix))
        except ValueError:
            # Ignore files with non-numeric suffixes
            continue

    # Determine next number (start from 1 if no rotated files exist)
    next_number = max(numbers) + 1 if numbers else 1

    # Rotate the current log file using copy-and-truncate method
    # This works on Windows even when file handles are open
    rotated_path = f"{log_file_path}.{next_number}"
    try:
        import shutil

        # Copy the current log to rotated name
        shutil.copy2(log_file_path, rotated_path)

        # Truncate the original file (this works even with open handles)
        with open(log_file_path, "w") as f:
            pass  # Truncate to 0 bytes

        print(f"Rotated log file: {log_file_path} -> {rotated_path}")
    except OSError as e:
        print(f"Warning: Could not rotate log file {log_file_path}: {e}")


def setup_logger(name="app", log_file=None, log_level=None):
    """
    Setup logger with rsyslog-style formatting

    Args:
        name: Logger name
        log_file: Path to log file (None for console only)
        log_level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Get configuration
    level = log_level or config.LOG_LEVEL
    file_path = log_file or config.LOG_FILE
    format_style = getattr(config, "LOG_FORMAT", "rsyslog")

    # Convert string level to logging constant
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(numeric_level)

    # Clear existing handlers
    logger.handlers.clear()

    # Create formatter based on style
    if format_style == "rsyslog":
        # rsyslog style: Jan 1 12:34:56 hostname program[pid]: level: message
        formatter = RsyslogFormatter()
    else:
        # Simple style: 2025-01-01 12:34:56 - LEVEL - message
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

    # File handler (if specified)
    if file_path:
        try:
            # Ensure log directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Rotate existing log file ONLY once per application startup
            global _log_rotated
            if not _log_rotated:
                rotate_log_file(file_path, force=True)  # Force rotation on app startup
                _log_rotated = True

            file_handler = SizeRotatingFileHandler(file_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

            # When file logging is active, minimize console output
            console_level = getattr(config, "CONSOLE_LOG_LEVEL", "CRITICAL")
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(getattr(logging, console_level, logging.CRITICAL))
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

        except Exception as e:
            # If file logging fails, fall back to console
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
            logger.warning(f"Failed to setup file logging to {file_path}: {e}")
    else:
        # No file specified, use console only
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


class RsyslogFormatter(logging.Formatter):
    """
    Custom formatter that mimics rsyslog format:
    Jan  1 12:34:56 hostname wakestation[1234]: info: User admin logged in
    """

    def __init__(self):
        super().__init__()
        self.hostname = self._get_hostname()
        self.pid = os.getpid()

    def _get_hostname(self):
        """Get hostname, fallback to localhost"""
        try:
            import socket

            return socket.gethostname().split(".")[0]  # Short hostname
        except:
            return "localhost"

    def format(self, record):
        # Convert timestamp to rsyslog format
        dt = datetime.fromtimestamp(record.created)
        timestamp = dt.strftime("%b %d %H:%M:%S")

        # Ensure day is padded correctly (rsyslog uses space padding for single digit days)
        day = dt.strftime("%d")
        if day.startswith("0"):
            day = " " + day[1:]
        timestamp = dt.strftime("%b ") + day + dt.strftime(" %H:%M:%S")

        # Format level name to lowercase
        level = record.levelname.lower()

        # Get program name from logger name
        program = record.name

        # Build rsyslog-style message
        # Format: timestamp hostname program[pid]: level: message
        message = f"{timestamp} {self.hostname} {program}[{self.pid}]: {level}: {record.getMessage()}"

        # Add exception info if present
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)

        return message


def get_logger(name=None):
    """
    Get or create a logger instance

    Args:
        name: Logger name (defaults to calling module name)
    """
    if name is None:
        # Get caller's module name
        frame = sys._getframe(1)
        name = frame.f_globals.get("__name__", "app")
        if name == "__main__":
            name = "wakestation"

    # Check if logger already exists and is configured
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger = setup_logger(name)

    return logger


# Convenience functions for quick logging
def debug(msg, logger_name=None):
    get_logger(logger_name).debug(msg)


def info(msg, logger_name=None):
    get_logger(logger_name).info(msg)


def warning(msg, logger_name=None):
    get_logger(logger_name).warning(msg)


def error(msg, logger_name=None):
    get_logger(logger_name).error(msg)


def critical(msg, logger_name=None):
    get_logger(logger_name).critical(msg)
