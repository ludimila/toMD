# to.MD

**Transforme quase qualquer documento em Markdown — com dois cliques.**

O **to.MD** é um aplicativo de desktop para Windows que converte PDFs, documentos do Office, imagens, páginas da web e muito mais para arquivos Markdown limpos e prontos para usar. Basta arrastar o arquivo para a janela (ou colar uma URL) e pronto!

Por baixo do capô, ele usa o [Docling](https://github.com/docling-project/docling), da IBM — uma biblioteca de ponta que entende a estrutura do documento (títulos, tabelas, listas) em vez de só extrair texto corrido.

---

## Para que serve?

Markdown é o formato favorito de ferramentas de IA, editores de notas (Obsidian, Notion) e documentação em geral. O to.MD é a ponte: pegue aquele PDF, contrato, planilha ou artigo da web e transforme em texto estruturado que qualquer ferramenta entende.

## Formatos suportados

| Grupo | Extensões |
|---|---|
| PDF | `pdf` |
| Word | `docx`, `dotx`, `docm`, `dotm` |
| PowerPoint | `pptx`, `potx`, `ppsx`, `pptm`, `potm`, `ppsm` |
| Excel | `xlsx`, `xlsm` |
| OpenDocument | `odt`, `ott`, `ods`, `ots`, `odp`, `otp` |
| Imagens | `jpg`, `jpeg`, `png`, `tif`, `tiff`, `bmp`, `webp` |
| Web / Markup | `html`, `htm`, `xhtml`, `xml`, `nxml`, `xbrl` — ou cole uma URL direto! |
| Texto / Markdown | `md`, `txt`, `csv`, `tex`, `latex`, `asciidoc`, `qmd`, `rmd`… |
| E-mail / E-book | `eml`, `epub` |
| Legendas | `vtt` |

## Como usar

### Opção 1 — Instalador (recomendado)

1. Baixe o `to.MD_Setup.exe` na [página de Releases](https://github.com/ludimila/toMD/releases/latest) e execute-o.

> O Windows pode mostrar um aviso do SmartScreen ("aplicativo não reconhecido") porque o instalador não tem assinatura digital paga. Clique em **Mais informações → Executar assim mesmo** — o app roda 100% na sua máquina e nenhum documento sai dela.

2. Siga o assistente (ele cria atalho na Área de Trabalho, se você quiser).
3. Abra o **to.MD**, arraste um arquivo ou cole uma URL, e salve o `.md` gerado.

> Na primeira conversão o app baixa os modelos de IA do Hugging Face — pode demorar um pouquinho. Depois disso, fica bem mais rápido.

### Opção 2 — Rodar do código-fonte

Você vai precisar de Python 3.10+ (um ambiente conda chamado `docling` funciona muito bem):

```bash
pip install -e .
python run.py
```

## Estrutura do projeto

```
toMD/
├── run.py            # Ponto de entrada (python run.py)
├── tomd/             # O aplicativo
│   ├── app.py        #   bootstrap (janela de carregamento + janela principal)
│   ├── ui.py         #   interface Qt (PySide6)
│   ├── engine.py     #   conversão via Docling (carregado em segundo plano)
│   ├── web.py        #   download e reparo de páginas da web
│   ├── formats.py    #   formatos aceitos
│   ├── errors.py     #   erros técnicos → mensagens em português claro
│   ├── logs.py       #   log em arquivo (%LOCALAPPDATA%\toMD\logs)
│   ├── updates.py    #   aviso de nova versão (GitHub Releases)
│   ├── theme.py      #   identidade visual
│   └── version.py    #   versão do app (fonte única)
├── tests/            # Testes (pytest)
├── to.MD.spec        # Receita do PyInstaller (gera o to.MD.exe)
├── installer.iss     # Receita do Inno Setup (gera o instalador)
├── LICENSE.md        # PolyForm Noncommercial 1.0.0
└── app_icon.ico      # Ícone do aplicativo
```

## Como gerar o executável e o instalador

Tudo é feito no Windows, em duas etapas:

```bash
# 1. Gerar a pasta dist/to.MD com o executável
pyinstaller to.MD.spec

# 2. Empacotar em um instalador único (requer Inno Setup instalado)
iscc installer.iss
# → o instalador sai em installer_output/to.MD_Setup.exe
```

As pastas `build/`, `dist/` e `installer_output/` são recriadas a cada build — por isso ficam fora do controle de versão.

## Licença

O to.MD é gratuito para uso pessoal e não comercial — use, adapte e compartilhe à vontade. O que **não** pode é usá-lo (ou código derivado dele) para ganhar dinheiro. Texto completo: [LICENSE.md](LICENSE.md) (PolyForm Noncommercial 1.0.0). Copyright © 2026 Mateus Freitas Gonçalves.

## Ideias para o futuro

- [ ] Opção de ligar/desligar OCR na interface
- [ ] Versão para macOS e Linux
