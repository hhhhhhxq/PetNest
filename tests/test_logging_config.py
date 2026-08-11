"""进程级诊断日志的回归测试。"""

from __future__ import annotations

import logging
import sys
import threading

from petnest.logging_config import install_diagnostic_hooks


def test_uncaught_exception_hook_logs_and_delegates(caplog, monkeypatch) -> None:
    delegated: list[tuple[type[BaseException], BaseException]] = []

    def previous_hook(exc_type, exc_value, _traceback) -> None:
        delegated.append((exc_type, exc_value))

    monkeypatch.setattr(sys, "excepthook", previous_hook)
    caplog.set_level(logging.CRITICAL, logger="petnest")

    install_diagnostic_hooks(install_qt=False)
    error = RuntimeError("uncaught-main-test")
    sys.excepthook(type(error), error, error.__traceback__)

    assert delegated == [(RuntimeError, error)]
    assert "未捕获的主线程异常" in caplog.text
    assert "uncaught-main-test" in caplog.text


def test_thread_exception_hook_logs_thread_name(caplog, monkeypatch) -> None:
    delegated: list[str] = []

    def previous_hook(args) -> None:
        delegated.append(args.thread.name)

    monkeypatch.setattr(threading, "excepthook", previous_hook)
    caplog.set_level(logging.CRITICAL, logger="petnest")

    install_diagnostic_hooks(install_qt=False)
    error = RuntimeError("uncaught-thread-test")
    args = threading.ExceptHookArgs((RuntimeError, error, error.__traceback__, threading.current_thread()))
    threading.excepthook(args)

    assert delegated == [threading.current_thread().name]
    assert "未捕获的后台线程异常" in caplog.text
    assert "uncaught-thread-test" in caplog.text
