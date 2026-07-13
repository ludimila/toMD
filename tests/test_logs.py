import logging
import os
from pathlib import Path

from tomd.logs import log_dir, log_file, setup_logging


def test_log_dir_usa_localappdata_no_windows(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert log_dir() == tmp_path / "toMD" / "logs"
    assert log_file() == tmp_path / "toMD" / "logs" / "tomd.log"


def test_log_dir_tem_fallback_fora_do_windows(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert log_dir() == Path.home() / ".tomd" / "logs"


def test_setup_logging_escreve_no_arquivo(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = logging.getLogger()
    handlers_antes = list(root.handlers)
    setup_logging()
    try:
        logging.getLogger("tomd.teste").info("olá, log")
        for h in root.handlers:
            h.flush()
        conteudo = (tmp_path / "toMD" / "logs" / "tomd.log").read_text(encoding="utf-8")
        assert "olá, log" in conteudo
    finally:
        for h in root.handlers[len(handlers_antes):]:
            root.removeHandler(h)
            h.close()
