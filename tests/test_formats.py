from tomd.formats import (
    ALL_EXTENSIONS,
    FORMAT_GROUPS,
    build_file_dialog_filter,
    is_supported_file,
)


def test_extensao_simples():
    assert is_supported_file("peticao.pdf")
    assert is_supported_file("contrato.docx")


def test_extensao_composta_tar_gz():
    assert is_supported_file("dados.tar.gz")
    # "gz" sozinho não está na lista — só a composta "tar.gz".
    assert not is_supported_file("arquivo.gz")


def test_maiusculas():
    assert is_supported_file("CONTRATO.PDF")
    assert is_supported_file("Planilha.XLSX")


def test_rejeita_audio_e_video():
    for name in ("gravacao.mp3", "audiencia.mp4", "som.wav", "video.mov",
                 "audio.m4a", "faixa.flac", "clipe.avi", "voz.aac", "som.ogg"):
        assert not is_supported_file(name), name
    assert "Áudio / Vídeo" not in FORMAT_GROUPS


def test_legendas_e_outros_permanecem():
    assert is_supported_file("legenda.vtt")
    assert is_supported_file("dados.json")


def test_rejeita_desconhecidos():
    assert not is_supported_file("programa.exe")
    assert not is_supported_file("sem_extensao")


def test_extensoes_compostas_vem_antes_das_simples():
    # ALL_EXTENSIONS é ordenada da mais longa para a mais curta, para que
    # "tar.gz" seja testada antes de qualquer sufixo mais curto.
    assert ALL_EXTENSIONS.index("tar.gz") < ALL_EXTENSIONS.index("gz") if "gz" in ALL_EXTENSIONS else True
    assert ALL_EXTENSIONS == sorted(ALL_EXTENSIONS, key=len, reverse=True)


def test_filtro_do_dialogo_lista_grupos():
    filtro = build_file_dialog_filter()
    assert "Todos os documentos suportados" in filtro
    assert "*.pdf" in filtro
    assert "Todos os arquivos (*)" in filtro
    assert "Áudio" not in filtro
