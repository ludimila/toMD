from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.pipeline.standard_pdf_pipeline import ProcessingResult
import logging

# Monkeypatch ProcessingResult to print progress page-by-page in standard terminal
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
            percent = (current / total) * 100 if total > 0 else 0.0
            
            bar_len = 20
            filled_len = int(round(bar_len * current / total)) if total > 0 else 0
            bar = '=' * filled_len + '-' * (bar_len - filled_len)
            
            print(f"\rProgresso: [{bar}] {current}/{total} páginas ({percent:.1f}%)", end="", flush=True)
            if current == total:
                print()
            
        def extend(self, iterable):
            for item in iterable:
                self.append(item)
            
    self.pages = ProgressList("pages", self)
    self.failed_pages = ProgressList("failed_pages", self)

ProcessingResult.__init__ = custom_init


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

caminho_pdf = "seu_documento.pdf"

print("--- INICIANDO PROCESSO ---")

# Configura o Docling para NÃO usar o RapidOCR teimoso
pipeline_options = PdfPipelineOptions()
pipeline_options.do_ocr = False  # Desativa temporariamente o OCR para testar o download dos outros modelos

conversor = DocumentConverter(
    format_options={
        "pdf": PdfFormatOption(pipeline_options=pipeline_options)
    }
)

print("Convertendo... Baixando modelos principais do Hugging Face.")
resultado = conversor.convert(caminho_pdf)

print("Exportando para Markdown...")
texto_markdown = resultado.document.export_to_markdown()

nome_saida = caminho_pdf.replace(".pdf", ".md")
with open(nome_saida, "w", encoding="utf-8") as f:
    f.write(texto_markdown)

print(f"--- FIM: Salvo como {nome_saida} ---")