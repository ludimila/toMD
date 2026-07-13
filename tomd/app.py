import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from tomd.engine import LoaderThread, WarmupThread
from tomd.ui import LoadingWindow, MainWindow, center_on_screen


def main():
    app = QApplication(sys.argv)

    loading = LoadingWindow()
    loading.show()
    center_on_screen(loading)
    app.processEvents()  # força a janela a pintar antes de travar no import pesado

    holder = {}

    def on_docling_ready():
        window = MainWindow()
        holder["window"] = window
        window.show()
        center_on_screen(window)
        loading.close()
        # Começa a carregar os modelos agora, enquanto o usuário ainda está
        # escolhendo o arquivo — a 1ª conversão fica bem mais rápida.
        holder["warmup"] = WarmupThread()
        holder["warmup"].start()

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
