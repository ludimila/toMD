import mimetypes
import os
import re
from io import BytesIO
from urllib.parse import urlparse

from tomd.formats import is_supported_file

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def is_url(text: str) -> bool:
    return bool(_URL_RE.match(text.strip()))


def normalize_url(text: str) -> str:
    text = text.strip()
    return text if is_url(text) else "https://" + text


# Muitos sites (inclusive orgãos do governo, como planalto.gov.br) recusam
# conexões sem um User-Agent de navegador de verdade — sem isso a requisição
# cai com "Connection aborted" / "RemoteDisconnected" antes de responder.
URL_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def _detect_html_encoding(raw: bytes, content_type_header: str) -> str:
    """Determina o encoding real da página. Páginas antigas (comuns em sites
    de governo) costumam não declarar charset algum — nesse caso, o padrão
    ISO-8859-1/Windows-1252 é a aposta certa para conteúdo em português."""
    match = re.search(r"charset=([\w-]+)", content_type_header or "", re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', raw[:4096], re.IGNORECASE)
    if match:
        return match.group(1).decode("ascii", "ignore")
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "windows-1252"


def _html_needs_repair(html_text: str) -> bool:
    """Detecta o sinal específico do bug: uma tag </body> ou </html> fechada
    com uma quantidade substancial de conteúdo real ainda depois dela (sinal
    de que foi fechada cedo demais por engano). Um percentual do tamanho
    total não funciona aqui — páginas bem formadas com <head> grande também
    teriam </body> "cedo" nessa medida. Em vez disso, mede-se quanto texto
    sobra depois da tag: numa página normal, só vem </html> e possivelmente
    espaço em branco; no bug, sobram dezenas de KB de conteúdo de verdade."""
    lower = html_text.lower()
    for tag in ("</body>", "</html>"):
        idx = lower.find(tag)
        if idx == -1:
            continue
        remainder = html_text[idx + len(tag):].strip()
        if len(remainder) > 200:
            return True
    return False


def fetch_url_source(url: str):
    """Baixa uma URL e devolve algo pronto para o DocumentConverter.

    Páginas HTML antigas às vezes têm uma tag </body> ou </html> fechada
    cedo demais no meio do documento — um erro de autoria que navegadores
    ignoram e continuam lendo, mas que faz o parser padrão do Docling
    truncar o conteúdo ali mesmo. Nesse caso (e só nesse caso — ver
    _html_needs_repair) o HTML é re-processado com o html5lib, que segue o
    algoritmo de recuperação de erros do HTML5 igual a um navegador de
    verdade, mas é bem mais lento que o parser padrão do Docling.
    """
    import requests
    from bs4 import BeautifulSoup
    from tomd import engine

    response = requests.get(url, headers=URL_FETCH_HEADERS, timeout=30)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")

    if "html" not in content_type.lower():
        # Não é HTML (PDF, imagem, docx etc. servido por link direto) —
        # entrega os bytes originais, sem qualquer reparo.
        name = os.path.basename(urlparse(url).path) or "arquivo"
        if not is_supported_file(name):
            guessed_ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
            if guessed_ext:
                name += guessed_ext
        return engine.DocumentStream(name=name, stream=BytesIO(response.content))

    encoding = _detect_html_encoding(response.content, content_type)
    html_text = response.content.decode(encoding, errors="replace")

    if _html_needs_repair(html_text):
        html_text = str(BeautifulSoup(html_text, "html5lib"))

    name = os.path.basename(urlparse(url).path) or "pagina"
    if not name.lower().endswith((".htm", ".html")):
        name += ".html"
    return engine.DocumentStream(name=name, stream=BytesIO(html_text.encode("utf-8")))
