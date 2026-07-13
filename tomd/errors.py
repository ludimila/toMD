"""Tradução de erros técnicos para mensagens em português claro.

As regras casam por NOME de classe (não por isinstance) de propósito: as
exceções vêm de libs pesadas (requests, docling, pypdfium2) que este módulo
não pode importar — os testes rodam sem elas instaladas.
"""

GENERIC_MESSAGE = (
    "Não consegui converter este documento. Tente de novo; se o problema "
    "continuar, os detalhes técnicos abaixo ajudam a entender o motivo."
)


class UserFacingError(Exception):
    """Erro cuja mensagem já foi escrita para o usuário final (sem tradução)."""


def _iter_chain(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def _has_class(exc, *names):
    for e in _iter_chain(exc):
        for cls in type(e).__mro__:
            if cls.__name__ in names:
                return True
    return False


def _http_status(exc):
    for e in _iter_chain(exc):
        status = getattr(getattr(e, "response", None), "status_code", None)
        if isinstance(status, int):
            return status
    return None


def friendly_error(exc: BaseException) -> str:
    """Mensagem humana para o erro; casos desconhecidos caem na genérica."""
    if isinstance(exc, UserFacingError):
        return str(exc)

    full_text = " ".join(str(e) for e in _iter_chain(exc)).lower()

    if "password" in full_text or "encrypted" in full_text:
        return "Este PDF está protegido por senha. Remova a senha e tente de novo."

    status = _http_status(exc)
    if _has_class(exc, "HTTPError") and status:
        return f"O site não permitiu baixar esta página (erro {status})."

    if (
        _has_class(exc, "ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout")
        or "getaddrinfo" in full_text
        or "name or service not known" in full_text
        or "nodename nor servname" in full_text
    ):
        return "Sem conexão com a internet — verifique sua rede e tente de novo."

    if _has_class(exc, "ConversionError") or "corrupt" in full_text or "not valid" in full_text:
        return "Não consegui ler este arquivo — ele pode estar corrompido."

    return GENERIC_MESSAGE


def friendly_save_error(exc: BaseException, folder: str) -> str:
    """Erro de disco/permissão na hora de salvar o .md."""
    return f"Não consegui salvar em {folder} — escolha outra pasta."
