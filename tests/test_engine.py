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


from tomd.engine import unique_path


def test_unique_path_devolve_o_original_se_livre(tmp_path):
    target = str(tmp_path / "doc.md")
    assert unique_path(target) == target


def test_unique_path_adiciona_sufixo_em_conflito(tmp_path):
    (tmp_path / "doc.md").write_text("x")
    assert unique_path(str(tmp_path / "doc.md")) == str(tmp_path / "doc (2).md")


def test_unique_path_pula_sufixos_ja_existentes(tmp_path):
    (tmp_path / "doc.md").write_text("x")
    (tmp_path / "doc (2).md").write_text("x")
    assert unique_path(str(tmp_path / "doc.md")) == str(tmp_path / "doc (3).md")
