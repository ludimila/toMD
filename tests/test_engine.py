import os

import pytest

from tomd.engine import precheck_local_file, suggest_markdown_path
from tomd.errors import UserFacingError


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


def test_precheck_aceita_pdf_de_verdade(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.7\n...conteudo...")
    precheck_local_file(str(pdf))  # não deve levantar


def test_precheck_aceita_pdf_com_lixo_antes_do_cabecalho(tmp_path):
    # A especificação tolera bytes antes de "%PDF-", desde que nos primeiros 1024.
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"\x00" * 100 + b"%PDF-1.4\n")
    precheck_local_file(str(pdf))


def test_precheck_rejeita_pdf_que_e_html(tmp_path):
    pdf = tmp_path / "peticao.pdf"
    pdf.write_bytes(b"<!DOCTYPE html><html><body>Sessao expirada</body></html>")
    with pytest.raises(UserFacingError, match="não é um PDF"):
        precheck_local_file(str(pdf))


def test_precheck_rejeita_arquivo_vazio(tmp_path):
    vazio = tmp_path / "doc.pdf"
    vazio.write_bytes(b"")
    with pytest.raises(UserFacingError, match="vazio"):
        precheck_local_file(str(vazio))


def test_precheck_ignora_formatos_sem_assinatura(tmp_path):
    txt = tmp_path / "notas.txt"
    txt.write_text("qualquer coisa")
    precheck_local_file(str(txt))  # só PDF tem checagem de conteúdo
