# ──────────────────────────────────────────────────────────────────────────────
# FORMATOS SUPORTADOS PELO DOCLING
# Espelha docling.datamodel.document.FormatToExtensions. Mantido como constante
# local (em vez de importado) para não precisar carregar o docling só para isso.
# Áudio/vídeo ficam de fora: o pipeline ASR do Docling não é configurado no
# app, então esses formatos nunca converteram de verdade.
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
