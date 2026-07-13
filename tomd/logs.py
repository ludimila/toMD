"""Log em arquivo para diagnóstico pós-morte: quando um advogado reporta
"não funcionou", o log é a única testemunha do que aconteceu na máquina dele."""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_configured = False


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "toMD" / "logs"
    # Fora do Windows (desenvolvimento em macOS/Linux) não existe LOCALAPPDATA.
    return Path.home() / ".tomd" / "logs"


def log_file() -> Path:
    return log_dir() / "tomd.log"


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    path = log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    _configured = True
