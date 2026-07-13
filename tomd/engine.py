import os

# Precisa ser definido ANTES de importar torch/docling: os modelos de
# código/fórmula (Granite-Vision) tentam compilar código nativo com o
# torch.compile, o que exige um compilador C++ (MSVC) instalado — algo que a
# máquina do usuário não tem por padrão. Desativar o torch.compile faz esses
# modelos rodarem normalmente (só um pouco mais lento), sem exigir instalar
# as Build Tools do Visual Studio.
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
os.environ.setdefault("TORCH_COMPILE_DISABLE", "1")

import logging
import re
import sys
import threading
import time
from typing import Optional
from urllib.parse import urlparse

from PySide6.QtCore import QThread, Signal

from tomd.errors import UserFacingError
from tomd.web import fetch_url_source, is_url

log = logging.getLogger(__name__)

# O Docling/Torch só é importado em segundo plano (ver _load_docling), para que a
# janela de carregamento apareça instantaneamente ao abrir o programa em vez de
# ficar vários segundos sem nenhum feedback visual enquanto essas libs pesadas carregam.
DocumentConverter = None
PdfFormatOption = None
PdfPipelineOptions = None
DocumentStream = None

_progress_callback = None


def suggest_markdown_path(source: str) -> str:
    """Caminho sugerido para o .md de saída — deriva do arquivo local, ou de um
    slug do próprio link quando a origem é uma URL."""
    if is_url(source):
        parsed = urlparse(source)
        slug = (parsed.netloc + parsed.path).strip("/").replace("/", "-") or parsed.netloc or "pagina"
        slug = re.sub(r"[^\w\-.]", "_", slug)[:80] or "pagina"
        base_dir = os.path.join(os.path.expanduser("~"), "Documents")
        if not os.path.isdir(base_dir):
            base_dir = os.path.expanduser("~")
        return os.path.join(base_dir, slug + ".md")

    base_dir, file_name = os.path.split(source)
    suggested_name = os.path.splitext(file_name)[0] + ".md"
    return os.path.join(base_dir, suggested_name)


def unique_path(path: str) -> str:
    """Primeiro caminho livre entre nome.md, nome (2).md, nome (3).md…
    Usado no lote, onde salvar é automático e sobrescrever seria destrutivo."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def _load_docling():
    """Importa docling/torch (lento) e aplica o monkeypatch de progresso.
    Só é chamado uma vez, de dentro do LoaderThread, depois que a janela de
    carregamento já está visível na tela."""
    global DocumentConverter, DocumentStream
    global PdfFormatOption, ImageFormatOption
    global PdfPipelineOptions, TableFormerMode, AcceleratorOptions

    from docling.document_converter import (
        DocumentConverter as _DC,
        PdfFormatOption as _PdfFO,
        ImageFormatOption as _ImgFO,
    )
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions as _PPO,
        TableFormerMode as _TFM,
    )
    from docling.datamodel.accelerator_options import AcceleratorOptions as _AO
    from docling.pipeline.standard_pdf_pipeline import ProcessingResult
    from docling_core.types.io import DocumentStream as _DS

    DocumentConverter = _DC
    PdfFormatOption = _PdfFO
    ImageFormatOption = _ImgFO
    PdfPipelineOptions = _PPO
    TableFormerMode = _TFM
    AcceleratorOptions = _AO
    DocumentStream = _DS

    original_init = ProcessingResult.__init__

    def custom_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        class ProgressList(list):
            def __init__(self, name, proc_result):
                super().__init__()
                self.name = name
                self.proc_result = proc_result

            def append(self, item):
                super().append(item)
                total = self.proc_result.total_expected
                current = self.proc_result.success_count + self.proc_result.failure_count
                if _progress_callback:
                    _progress_callback(current, total)

            def extend(self, iterable):
                for item in iterable:
                    self.append(item)

        self.pages = ProgressList("pages", self)
        self.failed_pages = ProgressList("failed_pages", self)

    ProcessingResult.__init__ = custom_init


def _build_format_options():
    """Modo leve: mantém OCR (leve — só entra em ação em páginas sem texto
    extraível, como PDFs escaneados ou imagens) e tabelas no modo preciso,
    mas sem os modelos de IA pesados (código/fórmula, descrição de imagem,
    extração de gráficos), que exigem baixar vários GB de modelos e deixam
    a conversão bem mais lenta. Outros formatos (Word, Excel, PowerPoint,
    HTML, Markdown etc.) usam as opções padrão do Docling — parsing puro,
    sem IA nenhuma.
    """
    pdf_options = PdfPipelineOptions()
    pdf_options.do_ocr = True
    pdf_options.do_table_structure = True
    pdf_options.table_structure_options.mode = TableFormerMode.ACCURATE
    # Usa todos os núcleos da CPU em vez do padrão (4) — medido ~31% mais
    # rápido nos modelos de OCR/tabela, que rodam sobre o PyTorch.
    pdf_options.accelerator_options = AcceleratorOptions(num_threads=os.cpu_count() or 4)

    return {
        "pdf": PdfFormatOption(pipeline_options=pdf_options),
        "image": ImageFormatOption(pipeline_options=pdf_options),
    }


_converter = None
_converter_lock = threading.Lock()


def _get_converter():
    """Reaproveita o mesmo DocumentConverter entre conversões. Ele guarda os
    modelos de OCR/layout/tabela já carregados internamente — recriar um
    conversor novo a cada arquivo descartava esse cache e forçava recarregar
    tudo do zero (quase 3x mais lento: ~12s contra ~4,5s por conversão).

    O lock existe porque duas threads podem chamar isto ao mesmo tempo: o
    pré-aquecimento em segundo plano (ver WarmupThread) e uma conversão que
    o usuário inicia antes de o aquecimento terminar. Sem o lock, cada uma
    construiria seu próprio conversor — pagando o carregamento dos modelos
    duas vezes. Com ele, a conversão simplesmente espera o aquecimento
    acabar e reaproveita o resultado."""
    global _converter
    with _converter_lock:
        if _converter is None:
            _converter = DocumentConverter(format_options=_build_format_options())
        return _converter


def converter_ready() -> bool:
    """True se os modelos já foram carregados nesta sessão (ver _get_converter)."""
    return _converter is not None


def reset_converter():
    """Descarta o conversor em cache. Usado após um cancelamento forçado:
    terminate() pode interromper a inferência no meio e deixar estado
    corrompido, que contaminaria as conversões seguintes."""
    global _converter
    with _converter_lock:
        _converter = None


class WarmupThread(QThread):
    """Carrega os modelos de OCR/layout/tabela em segundo plano assim que a
    janela principal abre — em paralelo com o tempo que o usuário leva
    escolhendo o arquivo. Sem isso, esse carregamento (~15s) só começava
    quando o primeiro arquivo era solto.

    Construir o DocumentConverter não basta: os modelos carregam de forma
    preguiçosa, na primeira conversão. initialize_pipeline() é a API do
    Docling justamente para forçar esse carregamento adiantado."""

    def run(self):
        try:
            from docling.datamodel.base_models import InputFormat
            _get_converter().initialize_pipeline(InputFormat.PDF)
        except Exception:
            # Sem alarde: se algo falhar aqui, a primeira conversão de
            # verdade repete a inicialização e aí sim reporta o erro ao usuário.
            pass


def estimate_initial_duration(source: str) -> Optional[float]:
    """Estimativa inicial de duração, baseada no tamanho do arquivo — mostrada
    desde o primeiro instante da conversão. É refinada com dados reais de
    progresso por página quando o Docling reporta isso (ver update_progress).
    """
    size_mb = 0.2  # chute conservador para links (tamanho só é conhecido após o download)
    if not is_url(source):
        try:
            size_mb = max(os.path.getsize(source) / (1024 * 1024), 0.05)
        except OSError:
            size_mb = 0.2

    base_seconds = 4.0
    if _converter is None:
        # Modelos ainda não carregados nesta sessão: custo extra de inicialização.
        # No executável empacotado (PyInstaller) esse custo é bem maior do que
        # rodando direto do Python — o antivírus costuma escanear os arquivos
        # recém-extraídos na primeira execução, entre outras coisas.
        base_seconds += 60.0 if getattr(sys, "frozen", False) else 15.0

    seconds_per_mb = 3.5
    estimate = base_seconds + size_mb * seconds_per_mb

    # Teto de sanidade: para arquivos grandes essa conta linear vira um
    # exagero (chegava a mostrar "220 minutos" para um PDF grande) — a partir
    # de um certo tamanho é mais honesto não fingir precisão. Acima do teto,
    # a tela mostra só o tempo decorrido e "ainda processando…" (ver
    # _update_time_label) em vez de uma contagem regressiva enganosa.
    return min(estimate, 90.0)


class LoaderThread(QThread):
    """Carrega o Docling em segundo plano enquanto a janela de carregamento gira."""
    finished_ok = Signal()
    failed = Signal(str)

    def run(self):
        try:
            _load_docling()
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(str(e))


class ConversionWorker(QThread):
    progress_signal = Signal(int, int)  # current, total
    finished_signal = Signal(str)       # markdown text
    error_signal = Signal(object)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        global _progress_callback

        def progress_bridge(current, total):
            self.progress_signal.emit(current, total)

        _progress_callback = progress_bridge
        start = time.time()
        log.info("Conversão iniciada: %s", self.file_path)

        try:
            if not is_url(self.file_path) and not os.path.isfile(self.file_path):
                raise UserFacingError(
                    f"Não encontrei o arquivo em:\n{self.file_path}\n\n"
                    "Se ele estiver no OneDrive ou em outra nuvem, abra a pasta "
                    "no Explorador de Arquivos e espere baixar antes de arrastar."
                )

            conversor = _get_converter()

            if is_url(self.file_path):
                source = fetch_url_source(self.file_path)
            else:
                source = self.file_path
            resultado = conversor.convert(source)
            texto_markdown = resultado.document.export_to_markdown()
            log.info("Conversão concluída em %.1fs: %s", time.time() - start, self.file_path)
            self.finished_signal.emit(texto_markdown)
        except Exception as e:
            log.exception("Conversão falhou: %s", self.file_path)
            self.error_signal.emit(e)
        finally:
            _progress_callback = None
