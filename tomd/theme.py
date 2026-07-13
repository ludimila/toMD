from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

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
