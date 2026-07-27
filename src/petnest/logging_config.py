"""隐私友好的用户目录日志配置。"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def default_log_directory(app_name: str = "PetNest") -> Path:
    """返回当前平台惯用的日志目录，不写入安装目录。"""
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Logs"
    else:
        root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / app_name / "logs"


def configure_logging(log_directory: Path | None = None) -> Path:
    """设置轮转日志；重复调用不会重复添加处理器。"""
    directory = log_directory or default_log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("petnest")
    logger.setLevel(logging.INFO)
    log_path = directory / "petnest.log"
    if not any(isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == log_path for handler in logger.handlers):
        handler = RotatingFileHandler(log_path, encoding="utf-8", maxBytes=1_000_000, backupCount=3)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    return log_path
