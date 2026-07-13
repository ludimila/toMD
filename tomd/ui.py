import logging
import os
import time
import traceback

from PySide6.QtCore import QSettings, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tomd import engine
from tomd.engine import (
    ConversionWorker,
    estimate_initial_duration,
    suggest_markdown_path,
    unique_path,
)
from tomd.errors import friendly_error, friendly_save_error
from tomd.formats import build_file_dialog_filter, is_supported_file
from tomd.logs import log_file
from tomd.theme import (
    ACCENT_GREEN,
    BUTTON_QSS,
    CANVAS,
    FONT_FAMILY,
    HAIRLINE,
    INK,
    INK_FAINT,
    INK_MUTED,
    PRIMARY,
    PRIMARY_ACTIVE,
    SURFACE,
    apply_card_shadow,
    make_font,
    render_app_icon,
    render_doc_glyph,
)
from tomd.web import is_url, normalize_url

log = logging.getLogger(__name__)


def _settings() -> QSettings:
    # Escopo organização/app fixo: a mesma memória vale para abrir e salvar.
    return QSettings("toMD", "toMD")


def center_on_screen(widget: QWidget):
    screen = widget.screen() or QApplication.primaryScreen()
    if screen is None:
        return
    geo = screen.availableGeometry()
    frame = widget.frameGeometry()
    frame.moveCenter(geo.center())
    widget.move(frame.topLeft())


# ──────────────────────────────────────────────────────────────────────────────
# 3. COMPONENTE CUSTOMIZADO: ÁREA DE DRAG AND DROP ("feature-card")
# ──────────────────────────────────────────────────────────────────────────────
class DropZone(QWidget):
    files_dropped = Signal(list)
    url_dropped = Signal(str)

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

        self.text_label = QLabel("Arraste documentos ou um link aqui")
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
        settings = _settings()
        start_dir = settings.value("last_dir", "") or ""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar documento", start_dir, build_file_dialog_filter()
        )
        if file_path:
            settings.setValue("last_dir", os.path.dirname(file_path))
            self.files_dropped.emit([file_path])

    def _split_payload(self, mime_data):
        """Separa o que foi arrastado em arquivos locais suportados e links
        http(s). Navegadores fornecem a URL como QUrl remoto; alguns também
        só como texto — o fallback de texto cobre esse caso."""
        files, links = [], []
        for url in mime_data.urls():
            local = url.toLocalFile()
            if local:
                if is_supported_file(local):
                    files.append(local)
            elif url.scheme() in ("http", "https"):
                links.append(url.toString())
        if not links and not files and mime_data.hasText() and is_url(mime_data.text()):
            links.append(mime_data.text().strip())
        return files, links

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
        files, links = self._split_payload(event.mimeData())
        if files or links:
            event.acceptProposedAction()
            self.set_active_style()

    def dragLeaveEvent(self, event):
        self.reset_style()

    def dropEvent(self, event: QDropEvent):
        self.reset_style()
        event.acceptProposedAction()
        files, links = self._split_payload(event.mimeData())
        if files:
            self.files_dropped.emit(files)
        elif links:
            self.url_dropped.emit(links[0])
        else:
            QMessageBox.warning(
                self,
                "Formato não suportado",
                "Esse tipo de arquivo não é reconhecido pelo conversor.\n"
                "Veja a lista de formatos aceitos em \"Escolher arquivo\"."
            )


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
        self._batch_queue = None   # lista de arquivos do lote (None = conversão avulsa)
        self._batch_dir = None
        self._batch_index = 0
        self._batch_results = []   # tuplas (origem, sucesso: bool, info: str)
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
        self.drop_zone.files_dropped.connect(self.start_sources)
        self.drop_zone.url_dropped.connect(self.start_conversion)
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

    def start_sources(self, paths):
        """Um arquivo mantém o fluxo atual ("Salvar como"); dois ou mais
        entram na fila de lote, com uma única escolha de pasta de saída."""
        if len(paths) == 1:
            self.start_conversion(paths[0])
            return
        settings = _settings()
        start_dir = settings.value("last_dir", "") or ""
        out_dir = QFileDialog.getExistingDirectory(
            self, "Escolha a pasta onde salvar os arquivos .md", start_dir
        )
        if not out_dir:
            return
        settings.setValue("last_dir", out_dir)
        self._batch_queue = list(paths)
        self._batch_dir = out_dir
        self._batch_index = 0
        self._batch_results = []
        self._start_next_in_batch()

    def start_conversion(self, source):
        self._batch_queue = None
        self._start_worker(source)

    def _start_next_in_batch(self):
        if self._batch_index >= len(self._batch_queue):
            self._finish_batch()
            return
        self._start_worker(self._batch_queue[self._batch_index])

    def _start_worker(self, source):
        self.drop_zone.hide()
        self.url_widget.hide()
        label = source if is_url(source) else os.path.basename(source)
        if self._batch_queue is not None:
            label = f"arquivo {self._batch_index + 1} de {len(self._batch_queue)} — {label}"
        self.file_label.setText(label)
        self.progress_bar.setValue(0)
        if not engine.converter_ready():
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
        self.worker.finished_signal.connect(lambda md: self._on_worker_finished(source, md))
        self.worker.error_signal.connect(lambda exc: self._on_worker_error(source, exc))
        self.worker.start()

    def _on_worker_finished(self, source, md_content):
        if self._batch_queue is None:
            self.on_success(source, md_content)
            return
        name = os.path.splitext(os.path.basename(source))[0] + ".md"
        target = unique_path(os.path.join(self._batch_dir, name))
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(md_content)
            self._batch_results.append((source, True, os.path.basename(target)))
        except OSError as e:
            log.exception("Falha ao salvar %s", target)
            self._batch_results.append((source, False, friendly_save_error(e, self._batch_dir)))
        self._batch_index += 1
        self._start_next_in_batch()

    def _on_worker_error(self, source, exc):
        if self._batch_queue is None:
            self.on_error(exc)
            return
        self._batch_results.append((source, False, friendly_error(exc)))
        self._batch_index += 1
        self._start_next_in_batch()

    def _finish_batch(self):
        self.elapsed_ticker.stop()
        self._conversion_start = None
        self.progress_widget.hide()
        self.file_label.setText("")
        self.drop_zone.show()
        self.url_widget.show()

        results = self._batch_results
        out_dir = self._batch_dir
        self._batch_queue = None
        ok = [r for r in results if r[1]]
        failed = [r for r in results if not r[1]]
        lines = [f"Convertidos com sucesso: {len(ok)} de {len(results)}."]
        if failed:
            lines.append("")
            lines.append("Falharam:")
            for source, _, reason in failed:
                lines.append(f"• {os.path.basename(source)} — {reason}")
        lines.append("")
        lines.append(f"Os arquivos .md estão em:\n{out_dir}")
        QMessageBox.information(self, "Conversão em lote concluída", "\n".join(lines))

    def cancel_conversion(self):
        self._batch_queue = None  # cancelar interrompe a fila inteira, não só o arquivo atual
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
            # terminate() mata a thread à força, podendo interromper o
            # modelo de OCR/tabela no meio da inferência. Como o conversor é
            # reaproveitado entre conversões, um estado corrompido aqui
            # contaminaria todas as conversões seguintes — descarta o cache
            # para a próxima reconstruir do zero, limpa.
            engine.reset_converter()
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
        if self._batch_queue is not None:
            prefix = f"arquivo {self._batch_index + 1} de {len(self._batch_queue)} · "
            page_text = f"página {current} de {total}" if total > 1 else "processando documento"
            self.status_label.setText(f"{prefix}{page_text}…")
        elif total > 1:
            # Fluxo avulso: mesmas frases de antes do lote existir.
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
        settings = _settings()
        last_dir = settings.value("last_dir", "") or ""
        # Arquivo local sugere a própria pasta de origem (mais útil); para
        # URLs, que não têm pasta, a última pasta usada vence o padrão
        # Documentos.
        if is_url(original_path) and last_dir:
            suggested_path = os.path.join(last_dir, os.path.basename(suggested_path))

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar arquivo Markdown",
            suggested_path,
            "Arquivos Markdown (*.md)"
        )

        if save_path:
            settings.setValue("last_dir", os.path.dirname(save_path))
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
                    "Erro ao salvar",
                    friendly_save_error(e, os.path.dirname(save_path)),
                )

        self.progress_widget.hide()
        self.file_label.setText("")
        self.drop_zone.show()
        self.url_widget.show()

    def on_error(self, exc):
        self.elapsed_ticker.stop()
        self._conversion_start = None
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("Erro de conversão")
        box.setText(friendly_error(exc))
        box.setInformativeText(
            f"Se precisar de ajuda, o registro completo está em:\n{log_file()}"
        )
        # Detalhe técnico colapsado: o Qt só mostra ao clicar em "Show Details…".
        box.setDetailedText("".join(traceback.format_exception(exc)))
        box.exec()
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
