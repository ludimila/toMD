"""Aviso de nova versão: consulta a API pública de releases do GitHub no
startup. Sem nag e sem auto-update — o app apenas mostra uma barra discreta
com um botão que abre a página de download no navegador. Qualquer falha
(sem rede, rate limit, JSON inesperado) é silenciosa: vai para o log e nada
aparece na tela."""
import logging
import re

from PySide6.QtCore import QThread, Signal

from tomd.version import __version__

RELEASES_API_URL = "https://api.github.com/repos/ludimila/toMD/releases/latest"
RELEASES_PAGE_URL = "https://github.com/ludimila/toMD/releases/latest"

log = logging.getLogger(__name__)


def parse_version(text: str) -> tuple:
    """"v1.10" -> (1, 10). Partes não numéricas encerram a leitura;
    uma tag sem número algum vira tupla vazia (tratada como inválida)."""
    text = text.strip().lstrip("vV")
    parts = []
    for piece in text.split("."):
        match = re.match(r"\d+", piece)
        if not match:
            break
        parts.append(int(match.group()))
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    lt, ct = parse_version(latest), parse_version(current)
    if not lt:
        return False
    # Iguala os comprimentos para que "1.1" == "1.1.0".
    size = max(len(lt), len(ct))
    lt += (0,) * (size - len(lt))
    ct += (0,) * (size - len(ct))
    return lt > ct


class UpdateCheckThread(QThread):
    update_available = Signal(str, str)  # (tag, url da página do release)

    def run(self):
        try:
            import requests  # import preguiçoso: os testes rodam sem requests

            response = requests.get(RELEASES_API_URL, timeout=5)
            response.raise_for_status()
            data = response.json()
            tag = data.get("tag_name", "")
            url = data.get("html_url") or RELEASES_PAGE_URL
            if is_newer(tag, __version__):
                self.update_available.emit(tag, url)
        except Exception:
            log.warning("Checagem de nova versão falhou (ignorada)", exc_info=True)
