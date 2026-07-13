import os

from tomd.engine import suggest_markdown_path


def test_arquivo_local_vira_md_na_mesma_pasta():
    source = os.path.join("pasta", "peticao.pdf")
    assert suggest_markdown_path(source) == os.path.join("pasta", "peticao.md")


def test_url_com_caminho_gera_slug():
    path = suggest_markdown_path("https://example.com/artigos/lei-teste")
    assert os.path.basename(path) == "example.com-artigos-lei-teste.md"
    assert os.path.isabs(path)


def test_url_raiz_usa_o_dominio():
    path = suggest_markdown_path("https://example.com/")
    assert os.path.basename(path) == "example.com.md"
