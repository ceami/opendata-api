# Copyright 2025 Team Aeris
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import json
import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from loguru import logger as loguru_logger


class StreamingFileHandler(logging.Handler):
    def __init__(
        self,
        log_dir: str = "/tmp/logs",
        max_file_size: int = 10 * 1024 * 1024,
        backup_count: int = 5,
        service_name: str = "",
        flush_interval: float = 1.0,
    ):
        super().__init__()
        self.log_dir = Path(log_dir)
        self.max_file_size = max_file_size
        self.backup_count = backup_count
        self.service_name = service_name
        self.flush_interval = flush_interval

        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.current_file = self._get_log_file_path()
        self.file_handler = None
        self._open_file()

        self.buffer = []
        self.buffer_lock = threading.Lock()

        self.flush_thread = threading.Thread(
            target=self._flush_worker, daemon=True
        )
        self.flush_thread.start()

    def _get_log_file_path(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d")
        if self.service_name:
            filename = f"{self.service_name}_{timestamp}.log"
        else:
            filename = f"app_{timestamp}.log"
        return self.log_dir / filename

    def _open_file(self):
        if self.file_handler:
            self.file_handler.close()

        self.file_handler = open(self.current_file, "a", encoding="utf-8")

    def _rotate_file(self):
        if not self.current_file.exists():
            return

        file_size = self.current_file.stat().st_size
        if file_size >= self.max_file_size:
            for i in range(self.backup_count - 1, 0, -1):
                old_file = self.current_file.with_suffix(f".{i}")
                new_file = self.current_file.with_suffix(f".{i + 1}")
                if old_file.exists():
                    if new_file.exists():
                        new_file.unlink()
                    old_file.rename(new_file)

            backup_file = self.current_file.with_suffix(".1")
            if backup_file.exists():
                backup_file.unlink()
            self.current_file.rename(backup_file)

            self.current_file = self._get_log_file_path()
            self._open_file()

    def _flush_worker(self):
        while True:
            time.sleep(self.flush_interval)
            self._flush_buffer()

    def _flush_buffer(self):
        with self.buffer_lock:
            if not self.buffer:
                return

            logs_to_write = self.buffer.copy()
            self.buffer.clear()

        try:
            for log_entry in logs_to_write:
                if self.file_handler:
                    self.file_handler.write(log_entry + "\n")
                    self.file_handler.flush()

            self._rotate_file()

        except Exception as e:
            print(f"로그 파일 쓰기 실패: {e}")

    def emit(self, record: logging.LogRecord):
        try:
            structured_log = {
                "timestamp": datetime.fromtimestamp(record.created).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "service": self.service_name,
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
            }

            if record.exc_info:
                structured_log["exception"] = self.formatException(
                    record.exc_info
                )

            with self.buffer_lock:
                self.buffer.append(
                    json.dumps(structured_log, ensure_ascii=False)
                )

            if record.levelno >= logging.ERROR:
                self._flush_buffer()

        except Exception as e:
            print(f"로그 처리 실패: {e}")

    def close(self):
        self._flush_buffer()
        if self.file_handler:
            self.file_handler.close()
        super().close()


def setup_logger(
    name: str = "ml_server_logs",
    log_level: str = "INFO",
    service_name: str = "",
    log_dir: str = "/tmp/logs",
    backup_dir: str = "/tmp/logs",
    force: bool = True,
) -> logging.Logger:
    loguru_logger.remove()

    loguru_logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{file}:{line}:{function}</cyan> | "
        "<level>{message}</level>",
        level=log_level.upper(),
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    if log_dir:
        log_dir_path = Path(log_dir)
        log_dir_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d")
        if service_name:
            filename = f"{service_name}_{timestamp}.log"
        else:
            filename = f"app_{timestamp}.log"

        log_file = log_dir_path / filename

        loguru_logger.add(
            str(log_file),
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{file}:{line}:{function} | {message}",
            level=log_level.upper(),
            rotation="10 MB",
            retention="30 days",
            compression="zip",
            backtrace=True,
            diagnose=True,
        )

    class InterceptHandler(logging.Handler):
        def emit(self, record):
            try:
                level = loguru_logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            loguru_logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    return logger


def get_logger(name: str = "app") -> logging.Logger:
    return setup_logger(name=name)
