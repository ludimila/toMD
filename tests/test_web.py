from tomd.web import _detect_html_encoding, _html_needs_repair, is_url, normalize_url


def test_is_url():
    assert is_url("https://planalto.gov.br/lei")
    assert is_url("http://exemplo.com")
    assert is_url("  HTTPS://EXEMPLO.COM  ")
    assert not is_url("planalto.gov.br")
    assert not is_url("C:\\Users\\doc.pdf")


def test_normalize_url_adiciona_https():
    assert normalize_url("planalto.gov.br") == "https://planalto.gov.br"
    assert normalize_url("  exemplo.com ") == "https://exemplo.com"


def test_normalize_url_preserva_esquema_existente():
    assert normalize_url("http://exemplo.com") == "http://exemplo.com"
    assert normalize_url("https://exemplo.com") == "https://exemplo.com"


def test_encoding_do_header():
    assert _detect_html_encoding(b"<html></html>", "text/html; charset=ISO-8859-1") == "ISO-8859-1"


def test_encoding_da_meta_tag():
    raw = b'<html><head><meta charset="windows-1252"></head><body>x</body></html>'
    assert _detect_html_encoding(raw, "text/html") == "windows-1252"


def test_encoding_utf8_valido():
    raw = "acentuação em português".encode("utf-8")
    assert _detect_html_encoding(raw, "") == "utf-8"


def test_encoding_fallback_windows_1252():
    raw = "acentuação".encode("windows-1252")  # bytes inválidos em UTF-8
    assert _detect_html_encoding(raw, "") == "windows-1252"


def test_pagina_normal_nao_precisa_de_reparo():
    html = "<html><head></head><body>" + "conteúdo " * 100 + "</body></html>"
    assert not _html_needs_repair(html)


def test_body_fechado_cedo_demais_precisa_de_reparo():
    html = "<html><body>início</body>" + "x" * 500 + "</html>"
    assert _html_needs_repair(html)


def test_pagina_sem_body_de_fechamento_nao_precisa_de_reparo():
    html = "<html><body>" + "x" * 500
    assert not _html_needs_repair(html)
