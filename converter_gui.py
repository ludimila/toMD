import sys
import os

# Precisa ser definido ANTES de importar torch/docling: os modelos de
# código/fórmula (Granite-Vision) tentam compilar código nativo com o
# torch.compile, o que exige um compilador C++ (MSVC) instalado — algo que a
# máquina do usuário não tem por padrão. Desativar o torch.compile faz esses
# modelos rodarem normalmente (só um pouco mais lento), sem exigir instalar
# as Build Tools do Visual Studio.
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
os.environ.setdefault("TORCH_COMPILE_DISABLE", "1")

import re
import time
import mimetypes
import threading
from io import BytesIO
from typing import Optional
from urllib.parse import urlparse
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QFont, QIcon, QDragEnterEvent, QDropEvent, QPixmap, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QLineEdit,
    QFileDialog,
    QMessageBox,
    QGraphicsDropShadowEffect,
)

# O Docling/Torch só é importado em segundo plano (ver _load_docling), para que a
# janela de carregamento apareça instantaneamente ao abrir o programa em vez de
# ficar vários segundos sem nenhum feedback visual enquanto essas libs pesadas carregam.
DocumentConverter = None
PdfFormatOption = None
PdfPipelineOptions = None

# ──────────────────────────────────────────────────────────────────────────────
# FORMATOS SUPORTADOS PELO DOCLING
# Espelha docling.datamodel.document.FormatToExtensions. Mantido como constante
# local (em vez de importado) para não precisar carregar o docling só para isso.
# ──────────────────────────────────────────────────────────────────────────────
FORMAT_GROUPS = {
    "PDF": ["pdf"],
    "Word": ["docx", "dotx", "docm", "dotm"],
    "PowerPoint": ["pptx", "potx", "ppsx", "pptm", "potm", "ppsm"],
    "Excel": ["xlsx", "xlsm"],
    "OpenDocument": ["odt", "ott", "ods", "ots", "odp", "otp"],
    "Imagens": ["jpg", "jpeg", "png", "tif", "tiff", "bmp", "webp"],
    "Web / Markup": ["html", "htm", "xhtml", "xml", "nxml", "xbrl", "dclg"],
    "Texto / Markdown": ["md", "txt", "text", "qmd", "rmd", "Rmd", "asciidoc", "adoc", "asc", "csv", "tex", "latex"],
    "E-mail / E-book": ["eml", "epub"],
    "Legendas": ["vtt"],
    "Áudio / Vídeo": ["wav", "mp3", "m4a", "aac", "ogg", "flac", "mp4", "avi", "mov"],
    "Outros": ["json", "tar.gz"],
}

# Extensões "compostas" (com ponto no meio) precisam ser checadas antes das simples
# ao validar um nome de arquivo, senão "tar.gz" bateria como "gz" incorretamente.
ALL_EXTENSIONS = sorted(
    {ext.lower() for exts in FORMAT_GROUPS.values() for ext in exts},
    key=len,
    reverse=True,
)


def is_supported_file(file_path: str) -> bool:
    name = file_path.lower()
    return any(name.endswith("." + ext) for ext in ALL_EXTENSIONS)


def build_file_dialog_filter() -> str:
    all_patterns = " ".join(f"*.{ext}" for ext in ALL_EXTENSIONS)
    parts = [f"Todos os documentos suportados ({all_patterns})"]
    for label, exts in FORMAT_GROUPS.items():
        patterns = " ".join(f"*.{ext}" for ext in exts)
        parts.append(f"{label} ({patterns})")
    parts.append("Todos os arquivos (*)")
    return ";;".join(parts)


_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def is_url(text: str) -> bool:
    return bool(_URL_RE.match(text.strip()))


def normalize_url(text: str) -> str:
    text = text.strip()
    return text if is_url(text) else "https://" + text


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
        return DocumentStream(name=name, stream=BytesIO(response.content))

    encoding = _detect_html_encoding(response.content, content_type)
    html_text = response.content.decode(encoding, errors="replace")

    if _html_needs_repair(html_text):
        html_text = str(BeautifulSoup(html_text, "html5lib"))

    name = os.path.basename(urlparse(url).path) or "pagina"
    if not name.lower().endswith((".htm", ".html")):
        name += ".html"
    return DocumentStream(name=name, stream=BytesIO(html_text.encode("utf-8")))


def center_on_screen(widget: QWidget):
    screen = widget.screen() or QApplication.primaryScreen()
    if screen is None:
        return
    geo = screen.availableGeometry()
    frame = widget.frameGeometry()
    frame.moveCenter(geo.center())
    widget.move(frame.topLeft())


# ──────────────────────────────────────────────────────────────────────────────
# IDENTIDADE VISUAL — tokens extraídos de DESIGN-notion.md
# Canvas quente (não branco clínico), tinta quase-preta, um único azul
# estrutural, cantos em pílula para a ação primária, elevação por hairline +
# sombra quase invisível. Nada de cor decorativa virando estrutura.
# ──────────────────────────────────────────────────────────────────────────────
CANVAS = "#f6f5f4"          # canvas-soft — fundo da janela
SURFACE = "#ffffff"         # cards, campos
INK = "#1a1a19"             # texto principal (preto ~95%, não 100% cru)
INK_MUTED = "#615d59"
INK_FAINT = "#a39e98"
HAIRLINE = "#e6e6e6"
PRIMARY = "#0075de"         # único acento estrutural
PRIMARY_ACTIVE = "#005bab"
ACCENT_GREEN = "#1aae39"    # só decorativo: confirmação de sucesso

FONT_FAMILY = "Segoe UI"    # fallback documentado da própria Notion para Windows


def make_font(size: int, weight: QFont.Weight = QFont.Normal, tracking: float = 0.0) -> QFont:
    font = QFont(FONT_FAMILY, size, weight)
    if tracking:
        font.setLetterSpacing(QFont.AbsoluteSpacing, tracking)
    return font


_app_icon_cache = None


def render_app_icon() -> QPixmap:
    """Ícone no espírito dos 'app-icon stickers' da Notion: bloco de cor sólida,
    cantos arredondados, um glifo simples — mais um adesivo de personalidade
    (com um ponto de acento decorativo) do que um selo estrutural.

    Desenhado uma única vez e reaproveitado (é o mesmo ícone tanto na tela
    de carregamento quanto na janela principal)."""
    global _app_icon_cache
    if _app_icon_cache is not None:
        return _app_icon_cache

    size = 256
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    margin = 14
    p.setBrush(QColor(PRIMARY))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(margin, margin, size - margin * 2, size - margin * 2, 56, 56)

    p.setPen(QColor(SURFACE))
    p.setFont(make_font(78, QFont.Bold))
    p.drawText(pix.rect(), Qt.AlignCenter, "MD")

    # ponto decorativo (sticker), puramente de personalidade — não estrutural
    p.setBrush(QColor("#ff64c8"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(size - 62, size - 62, 34, 34)

    p.end()
    _app_icon_cache = pix
    return pix


def render_doc_glyph(color: str) -> QPixmap:
    """Glifo simples de 'documento' — só um lembrete visual de affordance."""
    w, h = 40, 48
    pix = QPixmap(w, h)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    fold = 11

    pen = QPen(QColor(color))
    pen.setWidthF(2.0)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    outline = [
        (4, 2), (w - fold - 2, 2), (w - 2, fold + 2),
        (w - 2, h - 2), (4, h - 2), (4, 2),
    ]
    for i in range(len(outline) - 1):
        p.drawLine(outline[i][0], outline[i][1], outline[i + 1][0], outline[i + 1][1])
    p.drawLine(w - fold - 2, 2, w - fold - 2, fold + 2)
    p.drawLine(w - fold - 2, fold + 2, w - 2, fold + 2)

    pen.setWidthF(1.4)
    p.setPen(pen)
    for i, y in enumerate((18, 26, 34)):
        width = 24 if i < 2 else 16
        p.drawLine(9, y, 9 + width, y)
    p.end()
    return pix


def apply_card_shadow(widget: QWidget):
    """Elevação Nível 1 da Notion: sombra em muitas camadas quase transparentes.
    O Qt só permite uma camada de QGraphicsDropShadowEffect; aproximamos com
    baixa opacidade e blur generoso para o efeito 'quase imperceptível'."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(28)
    shadow.setOffset(0, 6)
    shadow.setColor(QColor(0, 0, 0, 22))
    widget.setGraphicsEffect(shadow)


# ──────────────────────────────────────────────────────────────────────────────
# 1. IMPORTAÇÃO PREGUIÇOSA DO DOCLING + MONKEYPATCH DE PROGRESSO
# ──────────────────────────────────────────────────────────────────────────────
_progress_callback = None
DocumentStream = None


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


# ──────────────────────────────────────────────────────────────────────────────
# 2. WORKER THREAD PARA PROCESSAMENTO ASSÍNCRONO
# ──────────────────────────────────────────────────────────────────────────────
class ConversionWorker(QThread):
    progress_signal = Signal(int, int)  # current, total
    finished_signal = Signal(str)       # markdown text
    error_signal = Signal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        global _progress_callback

        def progress_bridge(current, total):
            self.progress_signal.emit(current, total)

        _progress_callback = progress_bridge

        try:
            if not is_url(self.file_path) and not os.path.isfile(self.file_path):
                raise FileNotFoundError(
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
            self.finished_signal.emit(texto_markdown)
        except Exception as e:
            self.error_signal.emit(str(e))
        finally:
            _progress_callback = None


# ──────────────────────────────────────────────────────────────────────────────
# 3. COMPONENTE CUSTOMIZADO: ÁREA DE DRAG AND DROP ("feature-card")
# ──────────────────────────────────────────────────────────────────────────────
class DropZone(QWidget):
    file_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("DropZone")
        self.setMinimumHeight(220)
        apply_card_shadow(self)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        self.icon_label = QLabel()
        self.icon_label.setPixmap(render_doc_glyph(INK_FAINT))
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self.icon_label, alignment=Qt.AlignHCenter)

        self.text_label = QLabel("Arraste um documento aqui")
        self.text_label.setFont(make_font(15, QFont.Normal))
        self.text_label.setStyleSheet(f"color: {INK}; border: none; background: transparent;")
        self.text_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.text_label)

        self.hint_label = QLabel("ou")
        self.hint_label.setFont(make_font(12))
        self.hint_label.setStyleSheet(f"color: {INK_FAINT}; border: none; background: transparent;")
        self.hint_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.hint_label)

        self.browse_button = QPushButton("Escolher arquivo")
        self.browse_button.setObjectName("primaryButton")
        self.browse_button.setFont(make_font(13, QFont.DemiBold))
        self.browse_button.setCursor(Qt.PointingHandCursor)
        self.browse_button.setFixedSize(180, 40)
        self.browse_button.clicked.connect(self.open_file_dialog)
        layout.addWidget(self.browse_button, alignment=Qt.AlignHCenter)

        self.reset_style()

    def open_file_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar documento", "", build_file_dialog_filter()
        )
        if file_path:
            self.file_dropped.emit(file_path)

    def reset_style(self):
        self.setStyleSheet(f"""
            #DropZone {{
                border: 1px solid {HAIRLINE};
                border-radius: 12px;
                background-color: {SURFACE};
            }}
        """)

    def set_active_style(self):
        self.setStyleSheet(f"""
            #DropZone {{
                border: 1.5px solid {PRIMARY};
                border-radius: 12px;
                background-color: {SURFACE};
            }}
        """)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(is_supported_file(url.toLocalFile()) for url in urls):
                event.acceptProposedAction()
                self.set_active_style()

    def dragLeaveEvent(self, event):
        self.reset_style()

    def dropEvent(self, event: QDropEvent):
        self.reset_style()
        event.acceptProposedAction()
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path and is_supported_file(file_path):
                self.file_dropped.emit(file_path)
                return
        QMessageBox.warning(
            self,
            "Formato não suportado",
            "Esse tipo de arquivo não é reconhecido pelo conversor.\n"
            "Veja a lista de formatos aceitos em \"Escolher arquivo\"."
        )


BUTTON_QSS = f"""
    QPushButton#primaryButton {{
        background-color: {PRIMARY};
        color: {SURFACE};
        border: none;
        border-radius: 20px;
    }}
    QPushButton#primaryButton:hover {{
        background-color: {PRIMARY_ACTIVE};
    }}
    QPushButton#primaryButton:pressed {{
        background-color: {PRIMARY_ACTIVE};
    }}
    QPushButton#primaryButton:focus {{
        outline: none;
        border: 2px solid {PRIMARY_ACTIVE};
    }}
    QPushButton#utilityButton {{
        background-color: {SURFACE};
        color: {INK};
        border: 1px solid {HAIRLINE};
        border-radius: 8px;
        padding: 4px 14px;
    }}
    QPushButton#utilityButton:hover {{
        background-color: {CANVAS};
        border-color: {INK_FAINT};
    }}
    QLineEdit#urlInput {{
        background-color: {SURFACE};
        color: {INK};
        border: 1px solid #dddddd;
        border-radius: 4px;
        padding: 9px 12px;
        font-family: '{FONT_FAMILY}';
        font-size: 13px;
    }}
    QLineEdit#urlInput:focus {{
        border: 1.5px solid {PRIMARY};
    }}
"""


# ──────────────────────────────────────────────────────────────────────────────
# 4. JANELA PRINCIPAL (MAIN WINDOW)
# ──────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("to.MD")
        self.setWindowIcon(QIcon(render_app_icon()))
        self.resize(540, 540)
        self.setMinimumSize(460, 480)
        self.worker = None
        self._conversion_start = None
        self._estimated_total = None
        self.elapsed_ticker = QTimer(self)
        self.elapsed_ticker.setInterval(250)
        self.elapsed_ticker.timeout.connect(self._update_time_label)
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {CANVAS};
            }}
            QLabel {{
                font-family: '{FONT_FAMILY}';
            }}
            QMessageBox {{
                background-color: {SURFACE};
            }}
            QMessageBox QLabel {{
                color: {INK};
                font-family: '{FONT_FAMILY}';
                font-size: 13px;
            }}
            QMessageBox QPushButton {{
                background-color: {PRIMARY};
                color: {SURFACE};
                border: none;
                border-radius: 16px;
                padding: 7px 20px;
                font-family: '{FONT_FAMILY}';
                font-size: 13px;
                font-weight: 500;
            }}
            QMessageBox QPushButton:hover {{
                background-color: {PRIMARY_ACTIVE};
            }}
            {BUTTON_QSS}
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(32, 32, 32, 28)
        main_layout.setSpacing(20)

        # Cabeçalho
        header_layout = QVBoxLayout()
        header_layout.setSpacing(6)

        self.title_label = QLabel("to.MD")
        self.title_label.setFont(make_font(26, QFont.Bold, tracking=-0.8))
        self.title_label.setStyleSheet(f"color: {INK};")
        self.title_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("PDF, Word, Excel, PowerPoint, imagens, links e mais → Markdown")
        self.subtitle_label.setFont(make_font(13))
        self.subtitle_label.setStyleSheet(f"color: {INK_MUTED};")
        self.subtitle_label.setAlignment(Qt.AlignCenter)
        self.subtitle_label.setWordWrap(True)
        header_layout.addWidget(self.subtitle_label)

        main_layout.addLayout(header_layout)

        # Área de Drop/Seleção
        self.drop_zone = DropZone()
        self.drop_zone.file_dropped.connect(self.start_conversion)
        main_layout.addWidget(self.drop_zone)

        # Opção de converter a partir de um link
        self.url_widget = QWidget()
        url_section = QVBoxLayout(self.url_widget)
        url_section.setContentsMargins(0, 0, 0, 0)
        url_section.setSpacing(8)

        url_divider = QLabel("ou converta a partir de um link")
        url_divider.setFont(make_font(11))
        url_divider.setStyleSheet(f"color: {INK_FAINT};")
        url_divider.setAlignment(Qt.AlignCenter)
        url_divider.setWordWrap(True)
        url_section.addWidget(url_divider)

        url_row = QHBoxLayout()
        url_row.setSpacing(8)

        self.url_input = QLineEdit()
        self.url_input.setObjectName("urlInput")
        self.url_input.setFont(make_font(13))
        self.url_input.setPlaceholderText("cole o link de um site aqui")
        self.url_input.returnPressed.connect(self.submit_url)
        url_row.addWidget(self.url_input, 1)

        self.url_button = QPushButton("Converter")
        self.url_button.setObjectName("primaryButton")
        self.url_button.setFont(make_font(13, QFont.DemiBold))
        self.url_button.setCursor(Qt.PointingHandCursor)
        self.url_button.setFixedSize(108, 38)
        self.url_button.clicked.connect(self.submit_url)
        url_row.addWidget(self.url_button)

        url_section.addLayout(url_row)
        main_layout.addWidget(self.url_widget)

        # Nome do arquivo selecionado
        self.file_label = QLabel("")
        self.file_label.setFont(make_font(12))
        self.file_label.setStyleSheet(f"color: {INK_MUTED};")
        self.file_label.setAlignment(Qt.AlignCenter)
        self.file_label.setWordWrap(True)
        main_layout.addWidget(self.file_label)

        # Painel de progresso (mesmo chrome de card — hairline + sombra suave)
        self.progress_widget = QWidget()
        self.progress_widget.setObjectName("ProgressCard")
        self.progress_widget.setStyleSheet(f"""
            #ProgressCard {{
                background-color: {SURFACE};
                border: 1px solid {HAIRLINE};
                border-radius: 12px;
            }}
        """)
        apply_card_shadow(self.progress_widget)
        progress_inner = QVBoxLayout(self.progress_widget)
        progress_inner.setContentsMargins(20, 18, 20, 18)
        progress_inner.setSpacing(12)

        self.status_label = QLabel("Preparando conversão…")
        self.status_label.setFont(make_font(13, QFont.DemiBold))
        self.status_label.setStyleSheet(f"color: {INK}; background: transparent; border: none;")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        progress_inner.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 4px;
                background-color: {CANVAS};
            }}
            QProgressBar::chunk {{
                background-color: {PRIMARY};
                border-radius: 4px;
            }}
        """)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_inner.addWidget(self.progress_bar)

        self.time_label = QLabel("")
        self.time_label.setFont(make_font(11))
        self.time_label.setStyleSheet(f"color: {INK_MUTED}; background: transparent; border: none;")
        self.time_label.setAlignment(Qt.AlignCenter)
        progress_inner.addWidget(self.time_label)

        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setObjectName("utilityButton")
        self.cancel_button.setFont(make_font(12))
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.clicked.connect(self.cancel_conversion)
        progress_inner.addWidget(self.cancel_button, alignment=Qt.AlignHCenter)

        main_layout.addWidget(self.progress_widget)
        self.progress_widget.hide()

        main_layout.addStretch()

        self.footer_label = QLabel("to.MD · processamento local, via Docling")
        self.footer_label.setFont(make_font(10))
        self.footer_label.setStyleSheet(f"color: {INK_FAINT};")
        self.footer_label.setAlignment(Qt.AlignCenter)
        self.footer_label.setWordWrap(True)
        main_layout.addWidget(self.footer_label)

    def submit_url(self):
        text = self.url_input.text().strip()
        if not text:
            return
        self.url_input.clear()
        self.start_conversion(normalize_url(text))

    def start_conversion(self, source):
        self.drop_zone.hide()
        self.url_widget.hide()
        self.file_label.setText(source if is_url(source) else os.path.basename(source))
        self.progress_bar.setValue(0)
        if _converter is None:
            self.status_label.setText("Carregando modelos (pode demorar mais na 1ª vez)…")
        else:
            self.status_label.setText("Preparando conversão…")
        self.progress_widget.show()

        self._conversion_start = time.time()
        self._estimated_total = estimate_initial_duration(source)
        self._update_time_label()
        self.elapsed_ticker.start()

        self.worker = ConversionWorker(source)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.finished_signal.connect(lambda md: self.on_success(source, md))
        self.worker.error_signal.connect(self.on_error)
        self.worker.start()

    def cancel_conversion(self):
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
            # terminate() mata a thread à força, podendo interromper o
            # modelo de OCR/tabela no meio da inferência. Como o conversor é
            # reaproveitado entre conversões (ver _get_converter), um estado
            # corrompido aqui contaminaria todas as conversões seguintes —
            # descarta o cache para a próxima reconstruir do zero, limpa.
            global _converter
            with _converter_lock:
                _converter = None
        self.elapsed_ticker.stop()
        self._conversion_start = None
        self.progress_widget.hide()
        self.file_label.setText("")
        self.drop_zone.show()
        self.url_widget.show()

    @staticmethod
    def _format_duration(seconds):
        seconds = max(0, int(round(seconds)))
        minutes, secs = divmod(seconds, 60)
        return f"{minutes}:{secs:02d}" if minutes else f"{secs}s"

    def _update_time_label(self):
        if self._conversion_start is None:
            return
        elapsed = time.time() - self._conversion_start
        text = f"decorrido {self._format_duration(elapsed)}"
        if self._estimated_total:
            if self._estimated_total > elapsed:
                restante = self._estimated_total - elapsed
                text += f" · restante: ~{self._format_duration(restante)}"
            else:
                # Passou da estimativa — melhor dizer que ainda está
                # trabalhando do que simplesmente parar de informar algo.
                text += " · ainda processando…"
        self.time_label.setText(text)

    @Slot(int, int)
    def update_progress(self, current, total):
        if total > 1:
            self.status_label.setText(f"Processando página {current} de {total}…")
        else:
            self.status_label.setText("Processando documento…")
        percent = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)

        if total > 1 and current > 0 and self._conversion_start:
            elapsed = time.time() - self._conversion_start
            self._estimated_total = elapsed * total / current

    def on_success(self, original_path, md_content):
        # Confirmação discreta: um toque de cor (sticker verde), não um efeito teatral.
        self.status_label.setText(f'<span style="color:{ACCENT_GREEN};">✓</span>&nbsp;&nbsp;Convertido')
        self.progress_bar.setValue(100)
        self.elapsed_ticker.stop()
        if self._conversion_start:
            self.time_label.setText(f"concluído em {self._format_duration(time.time() - self._conversion_start)}")
        self._conversion_start = None
        QTimer.singleShot(650, lambda: self._prompt_save(original_path, md_content))

    def _prompt_save(self, original_path, md_content):
        suggested_path = suggest_markdown_path(original_path)

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar arquivo Markdown",
            suggested_path,
            "Arquivos Markdown (*.md)"
        )

        if save_path:
            try:
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(md_content)
                QMessageBox.information(
                    self,
                    "Sucesso",
                    f"Arquivo salvo com sucesso em:\n{save_path}"
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Erro ao Salvar",
                    f"Não foi possível salvar o arquivo:\n{str(e)}"
                )

        self.progress_widget.hide()
        self.file_label.setText("")
        self.drop_zone.show()
        self.url_widget.show()

    def on_error(self, error_message):
        self.elapsed_ticker.stop()
        self._conversion_start = None
        QMessageBox.critical(
            self,
            "Erro de Conversão",
            f"Ocorreu um erro durante a conversão:\n{error_message}"
        )
        self.progress_widget.hide()
        self.file_label.setText("")
        self.drop_zone.show()
        self.url_widget.show()


# ──────────────────────────────────────────────────────────────────────────────
# 5. JANELA DE CARREGAMENTO (aparece na hora, antes do Docling/Torch importarem)
# ──────────────────────────────────────────────────────────────────────────────
class LoadingWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("to.MD")
        self.setWindowIcon(QIcon(render_app_icon()))
        self.setFixedSize(360, 170)
        self.setStyleSheet(f"background-color: {CANVAS};")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(14)

        title = QLabel("to.MD")
        title.setFont(make_font(17, QFont.Bold, tracking=-0.3))
        title.setStyleSheet(f"color: {INK};")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.status_label = QLabel("Iniciando…")
        self.status_label.setFont(make_font(12))
        self.status_label.setStyleSheet(f"color: {INK_MUTED};")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        bar = QProgressBar()
        bar.setRange(0, 0)  # indeterminado
        bar.setTextVisible(False)
        bar.setFixedWidth(240)
        bar.setFixedHeight(6)
        bar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 3px;
                background-color: {HAIRLINE};
            }}
            QProgressBar::chunk {{
                background-color: {PRIMARY};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(bar, alignment=Qt.AlignCenter)


# ──────────────────────────────────────────────────────────────────────────────
# 6. EXECUÇÃO
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)

    loading = LoadingWindow()
    loading.show()
    center_on_screen(loading)
    app.processEvents()  # força a janela a pintar antes de travar no import pesado

    main_window_holder = {}

    def on_docling_ready():
        window = MainWindow()
        main_window_holder["window"] = window
        window.show()
        center_on_screen(window)
        loading.close()
        # Começa a carregar os modelos agora, enquanto o usuário ainda está
        # escolhendo o arquivo — a 1ª conversão fica bem mais rápida.
        main_window_holder["warmup"] = WarmupThread()
        main_window_holder["warmup"].start()

    def on_docling_failed(message):
        QMessageBox.critical(
            loading,
            "Erro ao iniciar",
            f"Não foi possível carregar o Docling:\n{message}"
        )
        app.quit()

    loader = LoaderThread()
    loader.finished_ok.connect(on_docling_ready)
    loader.failed.connect(on_docling_failed)
    loader.start()

    sys.exit(app.exec())
