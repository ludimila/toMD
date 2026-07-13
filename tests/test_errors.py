from types import SimpleNamespace

from tomd.errors import (
    GENERIC_MESSAGE,
    UserFacingError,
    friendly_error,
    friendly_save_error,
)


def test_pdf_com_senha():
    exc = RuntimeError("Failed to open PDF: password required (pypdfium2)")
    assert friendly_error(exc) == (
        "Este PDF está protegido por senha. Remova a senha e tente de novo."
    )


def test_sem_conexao_por_classe():
    exc = ConnectionError("connection aborted")
    assert friendly_error(exc) == (
        "Sem conexão com a internet — verifique sua rede e tente de novo."
    )


def test_falha_de_dns_pela_mensagem():
    exc = Exception("HTTPSConnectionPool: Max retries exceeded (getaddrinfo failed)")
    assert friendly_error(exc) == (
        "Sem conexão com a internet — verifique sua rede e tente de novo."
    )


def test_http_4xx_5xx_mostra_o_codigo():
    HTTPError = type("HTTPError", (Exception,), {})
    exc = HTTPError("403 Client Error: Forbidden for url")
    exc.response = SimpleNamespace(status_code=403)
    assert friendly_error(exc) == "O site não permitiu baixar esta página (erro 403)."


def test_arquivo_corrompido():
    ConversionError = type("ConversionError", (Exception,), {})
    exc = ConversionError("File format not recognized")
    assert friendly_error(exc) == (
        "Não consegui ler este arquivo — ele pode estar corrompido."
    )


def test_causa_encadeada_e_inspecionada():
    outer = RuntimeError("conversion failed")
    outer.__cause__ = ConnectionError("network unreachable")
    assert friendly_error(outer) == (
        "Sem conexão com a internet — verifique sua rede e tente de novo."
    )


def test_user_facing_error_passa_direto():
    assert friendly_error(UserFacingError("mensagem já pronta")) == "mensagem já pronta"


def test_desconhecido_cai_na_generica():
    assert friendly_error(ValueError("boom")) == GENERIC_MESSAGE


def test_erro_ao_salvar_menciona_a_pasta():
    msg = friendly_save_error(PermissionError("denied"), "/uma/pasta")
    assert msg == "Não consegui salvar em /uma/pasta — escolha outra pasta."
