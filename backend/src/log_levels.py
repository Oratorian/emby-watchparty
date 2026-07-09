"""Live log-level application.

The logger is built once at startup, and LOG_LEVEL / CONSOLE_LOG_LEVEL are
runtime (admin-panel) settings. Persisting them to config.json is not enough:
the running logger keeps its boot-time levels until these are re-applied.

A logger discards records below its own level before any handler sees them,
so the logger must sit at the most verbose of the two levels and let each
handler apply its own threshold:

  - file handler    -> LOG_LEVEL
  - console handler -> CONSOLE_LOG_LEVEL
  - logger          -> min(LOG_LEVEL, CONSOLE_LOG_LEVEL)

This makes "set CONSOLE_LOG_LEVEL=DEBUG" actually surface debug on stdout
without also flooding the log file, and vice versa. Safe to call repeatedly.
"""

import logging

# Loggers we own / want to track. rsyslog_logger attaches the file + console
# handlers to "emby-watchparty"; the others are adjusted for parity so their
# handlers (if any) follow the console threshold.
LOGGER_NAMES = ("emby-watchparty", "socketio", "uvicorn")


def apply_log_levels(config) -> None:
    """Re-apply LOG_LEVEL / CONSOLE_LOG_LEVEL to the live loggers in place."""
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    console_level = getattr(logging, config.CONSOLE_LOG_LEVEL.upper(), logging.WARNING)
    logger_level = min(level, console_level)

    for name in LOGGER_NAMES:
        lg = logging.getLogger(name)
        lg.setLevel(logger_level)
        for handler in lg.handlers:
            # SizeRotatingFileHandler subclasses logging.FileHandler; the
            # console handler is a plain StreamHandler (not a FileHandler).
            if isinstance(handler, logging.FileHandler):
                handler.setLevel(level)
            else:
                handler.setLevel(console_level)
