#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════╗
║          PDF → EPUB Converter  (Perfil Apotecaria)       ║
║  Uso: python3 pdf2epub.py libro.pdf -o salida.epub       ║
╚══════════════════════════════════════════════════════════╝

Dependencias: pypdf pdfminer.six PyMuPDF pytesseract pillow
    pip install -r requirements.txt
"""

import argparse
import io
import math
import json
import hashlib
import os
import re
import shutil
import sys
import tempfile
import textwrap
import uuid
import zipfile
from collections import Counter
from pathlib import Path
import pytesseract

from converter.pdf_extract import get_base_dir, get_tesseract_cmd, _is_image_only_page
from converter.text_utils import (
    _clean_page_number_only,
    _estimate_garbage_score,
    _looks_like_visual_separator_text,
    _normalize_heading_text,
    clean_text,
    clean_text_per_page,
    is_structural_heading_line,
    looks_like_section_subtitle,
)
from converter.image_filters import (
    _encode_image_for_epub,
    _filter_decorative_images,
    _format_image_bbox_for_log,
    _image_position_bucket,
    _image_visual_hash_from_pil,
    _log_discarded_images,
    _looks_like_decorative_motif_image,
    _looks_like_image_artifact,
)

from converter.chapters import (
    CHAPTER_PATTERNS,
    SPECIAL_SECTION_PATTERNS,
    TOC_KEYWORDS,
    _ROMAN_VALUES,
    _add_toc_entry,
    _build_sequential_page_para_ranges,
    _build_toc_forced_headings,
    _chapter_label_key,
    _collect_auxiliary_pages,
    _consume_forced_toc_heading,
    _detect_page_heading,
    _find_first_body_page,
    _format_special_heading,
    _fragment_first_text,
    _fragment_image_names,
    _guess_toc_page_offset,
    _heading_identity_key,
    _is_probable_toc_page,
    _is_toc_entry_start_line,
    _line_has_trailing_page_number,
    _looks_like_short_heading,
    _normalize_spine_fragments,
    _parse_toc_entries_from_pages,
    _parse_toc_entry,
    _roman_to_int,
    _split_possible_toc_entries,
    _toc_entry_score,
    _validate_spine_fragments,
    detect_chapters,
)

# ─────────────────────────────────────────────
#  PERFIL DE FORMATO (basado en análisis EPUB)
# ─────────────────────────────────────────────

CSS_PROFILE = """\
/* === RESET === */
blockquote, div, h1, h2, h3, hr, p, img {
    font-size: 1em;
    font-style: inherit;
    font-weight: inherit;
    line-height: inherit;
    margin: 0;
    padding: 0;
    text-indent: 0;
}
a, b, i, ins, del, big, small, span, sub, sup {
    color: inherit;
    font-size: inherit;
    font-style: inherit;
    font-weight: inherit;
    text-decoration: none;
    vertical-align: baseline;
}

/* === BODY === */
body {
    border: 0;
    font-size: 1em;
    orphans: 2;
    padding: 0;
    widows: 2;
    font-style: normal;
    font-weight: normal;
}

/* === PÁRRAFOS === */
p {
    display: block;
    margin: 0;
    padding: 0;
    text-align: justify;
    text-indent: 1.6em;
    line-height: 1.6em;
    orphans: 1;
    widows: 2;
}
a { text-decoration: none; color: inherit; -webkit-text-fill-color: inherit; }

/* === SIN SANGRÍA (primer párrafo del capítulo) === */
.asangre, .asangre p { text-indent: 0; }

/* === ENCABEZADOS === */
h1, h2, h3, h4, h5, h6 {
    font-size: 1.2em;
    font-weight: bold;
    margin-top: 1em;
    margin-bottom: 1em;
    text-align: center;
    page-break-inside: avoid;
    break-inside: avoid;
    page-break-after: avoid;
    break-after: avoid;
}
h1 { font-size: 1.6em; margin-top: 0em; }
h1.titulo  { margin-top: 1.5em; margin-bottom: 0; }
h2.subtitulo { margin-top: 0.5em; margin-bottom: 0; }
h1.chapter-title { margin-top: 1.8em; margin-bottom: 0.4em; text-align: center; font-weight: bold; }
h2.chapter-subtitle { margin-top: 0.2em; margin-bottom: 1.4em; text-align: center; font-size: 1.15em; font-weight: bold; }
h3.part-title { margin-top: 1.4em; margin-bottom: 0.8em; text-align: center; font-size: 1.1em; font-weight: bold; }

/* === ESTILOS EN LÍNEA === */
i { font-style: italic; }
b { font-weight: bold; }
ins { text-decoration: underline; }
del { text-decoration: line-through; }
big { font-size: 1.2em; }
small { font-size: 0.8em; }

/* === NOTAS === */
.nota { padding-top: 10%; page-break-before: always; }
.nota p { text-indent: 0; }

/* === IMÁGENES === */
img {
    display: block;
    max-width: 100%;
    width: auto;
    height: auto;
    margin: 0 auto;
    page-break-inside: avoid;
    break-inside: avoid;
    border: 0;
}
div.dimg {
    width: auto;
    height: auto;
    max-width: 100%;
    margin: 1em auto;
    line-height: 0;
    text-align: center;
    page-break-inside: avoid;
    break-inside: avoid;
}
div.dimg.fullblock img {
    max-width: 100%;
    height: auto;
}
div.pagina  { width: 100%; height: auto; text-align: center; }
div.seguida { width: 100%; height: auto; }
div.galeria { width: 100%; height: auto; text-align: center; }
div.galeria .dimg { margin-top: 0.8em; margin-bottom: 0.8em; }

/* === ALINEACIÓN === */
.centrado,  .centrado p  { text-align: center; text-indent: 0; }
.izquierda, .izquierda p { text-align: left;   text-indent: 0; }
.derecha,   .derecha p   { text-align: right;  text-indent: 0; }

/* === SALTOS DE ESPACIO === */
.salto1 { margin-top: 1.5em; }
.salto2 { margin-top: 2em; }
.salto3 { margin-top: 2.5em; }

/* === CUBIERTA === */
.cubierta {
    margin: 0; padding: 0; border: 0;
    font-size: 0; text-align: center; text-indent: 0;
    page-break-before: always; page-break-after: always;
}
/* === OCULTO === */
.oculto { display: none; visibility: hidden; }
"""

XHTML_CHAPTER_TEMPLATE = """\
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">

<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}">
<head>
  <title>{title}</title>
  <link href="../Styles/style.css" rel="stylesheet" type="text/css"/>
</head>

<body>
{body}
</body>
</html>
"""

XHTML_COVER_TEMPLATE = """\
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">

<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}">
<head>
  <title>Portada</title>
  <link href="../Styles/style.css" rel="stylesheet" type="text/css"/>
</head>

<body>
<div class="cubierta">
  <img alt="portada" src="../Images/cover.jpg"/>
</div>
</body>
</html>
"""

XHTML_IMAGE_PAGE_TEMPLATE = """\
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">

<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}">
<head>
  <title>{title}</title>
  <link href="../Styles/style.css" rel="stylesheet" type="text/css"/>
</head>

<body>
<div class="pagina">
  <div class="dimg fullblock">
    <img alt="{alt}" src="../Images/{imgname}"/>
  </div>{caption_html}
</div>
</body>
</html>
"""

XHTML_IMAGE_SEQUENCE_TEMPLATE = """\
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">

<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}">
<head>
  <title>{title}</title>
  <link href="../Styles/style.css" rel="stylesheet" type="text/css"/>
</head>

<body>
<div class="galeria">
{body}
</div>
</body>
</html>
"""


# ─────────────────────────────────────────────
#  EXTRACCIÓN DE TEXTO E IMÁGENES DEL PDF
# ─────────────────────────────────────────────


# OCR v2
DEFAULT_OCR_MODE = "off"        # off | auto | force
DEFAULT_OCR_LANG = "spa+eng"    # requiere paquetes de idioma instalados en Tesseract
DEFAULT_OCR_DPI = 300
DEFAULT_OCR_MIN_TEXT_CHARS = 90
DEFAULT_OCR_GARBAGE_THRESHOLD = 0.22





def configure_tesseract(config: dict | None = None) -> str:
    """Configura pytesseract para usar Tesseract local o del sistema."""
    config = config or {}
    tesseract_cmd = get_tesseract_cmd(config.get("tesseract_cmd"))
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    tesseract_path = Path(tesseract_cmd)
    if tesseract_path.exists():
        tessdata_dir = tesseract_path.parent / "tessdata"
        if tessdata_dir.exists():
            os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)

    return pytesseract.pytesseract.tesseract_cmd









def _should_ocr_page(text: str, config: dict) -> tuple[bool, str, float]:
    mode = (config.get('ocr_mode') or DEFAULT_OCR_MODE).lower()
    if mode == 'off':
        return False, 'ocr desactivado', 0.0
    if mode == 'force':
        return True, 'modo force', 1.0

    cleaned = _clean_page_number_only(text)
    min_chars = int(config.get('ocr_min_text_chars', DEFAULT_OCR_MIN_TEXT_CHARS))
    garbage_threshold = float(config.get('ocr_garbage_threshold', DEFAULT_OCR_GARBAGE_THRESHOLD))

    if len(cleaned) < min_chars:
        return True, f'texto escaso (< {min_chars} chars)', 1.0

    garbage_score = _estimate_garbage_score(cleaned)
    if garbage_score >= garbage_threshold:
        return True, f'texto corrupto (score={garbage_score:.2f})', garbage_score

    return False, f'texto aceptable (score={garbage_score:.2f})', garbage_score


def _render_page_to_png_bytes(pdf_path: str, page_index: int, dpi: int = DEFAULT_OCR_DPI) -> bytes:
    import fitz  # PyMuPDF

    zoom = max(72, int(dpi)) / 72.0
    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_index)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes('png')
    finally:
        doc.close()


def _ocr_png_bytes(png_bytes: bytes, config: dict) -> str:
    from PIL import Image

    resolved_cmd = configure_tesseract(config)
    lang = (config.get('ocr_lang') or DEFAULT_OCR_LANG).strip()
    psm = str(config.get('ocr_psm', 3)).strip()
    oem = str(config.get('ocr_oem', 3)).strip()
    custom = f'--oem {oem} --psm {psm}'

    img = Image.open(io.BytesIO(png_bytes)).convert('L')
    return pytesseract.image_to_string(img, lang=lang, config=custom)


def apply_ocr_to_pages(pdf_path: str, raw_pages: list[str], config: dict) -> tuple[list[str], dict]:
    """Aplica OCR página por página cuando el modo/configuración lo requiere."""
    mode = (config.get('ocr_mode') or DEFAULT_OCR_MODE).lower()
    stats = {
        'mode': mode,
        'applied': False,
        'pages_replaced': 0,
        'page_indexes': [],
        'reasons': {},
    }

    if mode == 'off':
        print('  OCR: desactivado')
        return raw_pages, stats

    try:
        import pytesseract  # noqa: F401
        import fitz  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception as e:
        print(f'  ⚠️  OCR no disponible ({e}). Se usará extracción normal.')
        return raw_pages, stats

    replaced = list(raw_pages)
    dpi = int(config.get('ocr_dpi', DEFAULT_OCR_DPI))
    print(f'  OCR: modo={mode} | lang={config.get("ocr_lang", DEFAULT_OCR_LANG)} | dpi={dpi}')
    try:
        print(f'  OCR: tesseract={configure_tesseract(config)}')
    except Exception:
        pass

    for idx, original_text in enumerate(raw_pages):
        must_ocr, reason, score = _should_ocr_page(original_text, config)
        if not must_ocr:
            continue

        try:
            png_bytes = _render_page_to_png_bytes(pdf_path, idx, dpi=dpi)
            ocr_text = _ocr_png_bytes(png_bytes, config).strip()
            if ocr_text:
                replaced[idx] = ocr_text
                stats['pages_replaced'] += 1
                stats['page_indexes'].append(idx)
                stats['reasons'][idx] = reason
                stats['applied'] = True
                print(f'    OCR página {idx+1}: {reason}')
            else:
                print(f'    OCR página {idx+1}: sin texto reconocible, se conserva extracción normal')
        except Exception as e:
            print(f'    OCR página {idx+1}: fallo ({e}), se conserva extracción normal')

    if stats['pages_replaced'] == 0:
        print('  OCR: no fue necesario reemplazar páginas')
    else:
        joined = ', '.join(str(i + 1) for i in stats['page_indexes'][:12])
        extra = '' if len(stats['page_indexes']) <= 12 else '…'
        print(f"  OCR: páginas reemplazadas = {stats['pages_replaced']} ({joined}{extra})")

    return replaced, stats






























def _build_image_record(page_idx: int,
                        img_counter: int,
                        pil_img,
                        page_text: str,
                        is_full_page: bool,
                        caption: str,
                        bbox=None,
                        page_width: float | None = None,
                        page_height: float | None = None) -> tuple[dict | None, dict | None]:
    """Normaliza una imagen extraída y devuelve (imagen_valida, descarte)."""
    safe_img, img_data, ext, media_type = _encode_image_for_epub(pil_img)
    visual_hash = _image_visual_hash_from_pil(safe_img)
    name = f"img{img_counter:03d}.{ext}"
    base = {
        "page_idx": page_idx,
        "name": name,
        "data": img_data,
        "ext": ext,
        "media_type": media_type,
        "is_full_page": is_full_page,
        "caption": caption,
        "width": safe_img.width,
        "height": safe_img.height,
        "bbox": tuple(float(v) for v in bbox) if bbox else None,
        "page_width": float(page_width or 0),
        "page_height": float(page_height or 0),
        "_visual_hash": visual_hash,
    }

    if _looks_like_image_artifact(safe_img):
        discard = dict(base)
        discard["discard_reason"] = "artefacto_visual_pdf"
        discard["_position_bucket"] = _image_position_bucket(discard)
        return None, discard

    # Filtro específico para el caso de flores/marcos editoriales extraídos
    # como un rectángulo grande con fondo uniforme. No se aplica a páginas
    # completas ni a páginas casi sin texto para proteger ilustraciones reales.
    page_has_text = len((page_text or "").strip()) >= 80
    if page_has_text and not is_full_page:
        is_motif, motif_reason = _looks_like_decorative_motif_image(safe_img)
        if is_motif:
            discard = dict(base)
            discard["discard_reason"] = motif_reason or "motivo_decorativo"
            discard["_position_bucket"] = _image_position_bucket(discard)
            return None, discard

    return base, None


def _extract_images_with_pymupdf(pdf_path: str, pages_text: list[str], total: int) -> tuple[list[dict], list[dict]]:
    """Extrae imágenes con coordenadas usando PyMuPDF. Si falla, el llamador usa fallback."""
    import fitz
    from PIL import Image

    images: list[dict] = []
    discarded: list[dict] = []
    img_counter = 0

    doc = fitz.open(pdf_path)
    try:
        for page_idx in range(total):
            page = doc[page_idx]
            page_text = pages_text[page_idx] if page_idx < len(pages_text) else ""
            info_list = page.get_image_info(xrefs=True)
            if not info_list:
                continue

            is_full_page = _is_image_only_page(page_text)
            if not is_full_page and len(info_list) == 1 and _looks_like_visual_separator_text(page_text):
                is_full_page = True

            caption = ""
            if not is_full_page and page_text.strip():
                lines = [l.strip() for l in page_text.splitlines() if l.strip()]
                lines = [l for l in lines if not re.fullmatch(r'\d{1,4}', l)]
                if lines:
                    caption = " ".join(lines)

            for info in info_list:
                xref = int(info.get("xref") or 0)
                bbox = info.get("bbox")
                if not bbox:
                    continue
                rect = fitz.Rect(bbox)
                if rect.is_empty or rect.width <= 1 or rect.height <= 1:
                    continue

                img_counter += 1
                try:
                    if xref > 0:
                        extracted = doc.extract_image(xref)
                        img_bytes = extracted.get("image")
                        if not img_bytes:
                            continue
                        pil_img = Image.open(io.BytesIO(img_bytes))
                    else:
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=True)
                        pil_img = Image.open(io.BytesIO(pix.tobytes("png")))

                    record, discard = _build_image_record(
                        page_idx=page_idx,
                        img_counter=img_counter,
                        pil_img=pil_img,
                        page_text=page_text,
                        is_full_page=is_full_page,
                        caption=caption,
                        bbox=(rect.x0, rect.y0, rect.x1, rect.y1),
                        page_width=page.rect.width,
                        page_height=page.rect.height,
                    )
                    if discard:
                        discarded.append(discard)
                    elif record:
                        images.append(record)
                except Exception as ex:
                    print(f"  [Imágenes] ⚠️  No se pudo extraer imagen en pág {page_idx+1}: {ex}")
    finally:
        doc.close()

    return images, discarded


def _extract_images_with_pypdf(reader, pages_text: list[str], total: int) -> tuple[list[dict], list[dict]]:
    """Fallback sin coordenadas cuando PyMuPDF no puede extraer imágenes."""
    images: list[dict] = []
    discarded: list[dict] = []
    img_counter = 0

    for page_idx, page in enumerate(reader.pages):
        page_imgs = page.images
        if not page_imgs:
            continue

        page_text = pages_text[page_idx] if page_idx < len(pages_text) else ""
        is_full_page = _is_image_only_page(page_text)
        if not is_full_page and len(page_imgs) == 1 and _looks_like_visual_separator_text(page_text):
            is_full_page = True

        caption = ""
        if not is_full_page and page_text.strip():
            lines = [l.strip() for l in page_text.splitlines() if l.strip()]
            lines = [l for l in lines if not re.fullmatch(r'\d{1,4}', l)]
            if lines:
                caption = " ".join(lines)

        for img_obj in page_imgs:
            img_counter += 1
            try:
                record, discard = _build_image_record(
                    page_idx=page_idx,
                    img_counter=img_counter,
                    pil_img=img_obj.image,
                    page_text=page_text,
                    is_full_page=is_full_page,
                    caption=caption,
                    bbox=None,
                    page_width=None,
                    page_height=None,
                )
                if discard:
                    discarded.append(discard)
                elif record:
                    images.append(record)
            except Exception as ex:
                print(f"  [Imágenes] ⚠️  No se pudo extraer imagen en pág {page_idx+1}: {ex}")

    return images, discarded


def _find_neighbor_text_page(page_para_ranges: dict[tuple[int, int], tuple[int, int]],
                             ch_idx: int,
                             pg_idx: int,
                             direction: int,
                             limit: int = 3) -> tuple[int, tuple[int, int]] | None:
    step = 1 if direction > 0 else -1
    cur = pg_idx + step
    walked = 0
    while walked < limit and cur >= 0:
        key = (ch_idx, cur)
        if key in page_para_ranges:
            return cur, page_para_ranges[key]
        cur += step
        walked += 1
    return None


def build_image_sequence_xhtml(images: list[dict], lang: str, title: str) -> str:
    body_parts = []
    for img in images:
        caption_html = f'\n<p class="centrado"><i>{escape_xml(img.get("caption", ""))}</i></p>' if img.get("caption") else ""
        body_parts.append(
            f'<div class="dimg fullblock">\n'
            f'  <img alt="ilustración" src="../Images/{img["name"]}"/>\n'
            f'</div>{caption_html}'
        )
    return XHTML_IMAGE_SEQUENCE_TEMPLATE.format(lang=lang, title=title, body="\n".join(body_parts))



def extract_pdf_content(pdf_path: str) -> tuple[list[str], list[dict]]:
    """
    Extrae texto e imágenes del PDF página por página.
    Usa pdfminer con detección de encabezados/pies por posición Y.

    Devuelve:
      - pages: lista de strings con el texto por página (sin header/footer)
      - images: lista de dicts con info de cada imagen extraída
    """
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    total = len(reader.pages)

    # --- Texto con pdfminer con detección posicional de header/footer ---
    pages_text: list[str] = []
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LAParams, LTTextContainer
        laparams = LAParams(line_margin=0.5, word_margin=0.1)

        # Primera pasada: recopilar alturas de página y bloques con posición
        page_layouts = list(extract_pages(pdf_path, laparams=laparams))

        # Detectar zona de header/footer por posición Y relativa
        # Un bloque está en la zona de header si está en el 10% superior,
        # o en la zona de footer si está en el 10% inferior.
        HEADER_ZONE = 0.90  # y/altura > 0.90 → header
        FOOTER_ZONE = 0.10  # y/altura < 0.10 → footer

        # Recopilar textos de header/footer candidates para detección por repetición
        from collections import Counter
        header_footer_counter: Counter = Counter()

        raw_blocks: list[list[tuple]] = []  # por página: [(y_rel, text), ...]
        for page_layout in page_layouts:
            h = page_layout.height or 842
            blocks = []
            for elem in page_layout:
                if isinstance(elem, LTTextContainer):
                    txt = elem.get_text().strip()
                    if not txt:
                        continue
                    y_rel = elem.bbox[1] / h  # posición relativa desde abajo
                    is_border = y_rel > HEADER_ZONE or y_rel < FOOTER_ZONE
                    blocks.append((y_rel, txt, is_border))
                    if is_border:
                        header_footer_counter[txt] += 1
            raw_blocks.append(blocks)

        # Líneas que aparecen ≥4 veces en zona de borde = header/footer confirmado
        confirmed_hf = {txt for txt, cnt in header_footer_counter.items() if cnt >= 4}

        # Patrones de header/footer variables (número de página, nombre del libro…)
        # Detectamos la parte fija: si la línea sin número coincide ≥4 veces
        HF_VARIABLE_PATTERNS = [
            re.compile(r'P[áa]gina\s+N[°º]?\s*\d+', re.IGNORECASE),  # Página N° 12
            re.compile(r'\bpág(?:ina)?\s*\.?\s*\d+', re.IGNORECASE),  # Pág. 12
            re.compile(r'^\d{1,4}$'),                                   # solo número
            re.compile(r'^[\-–—]\s*\d+\s*[\-–—]$'),                    # — 12 —
        ]

        # Segunda pasada: construir texto limpio por página
        for blocks in raw_blocks:
            page_lines = []
            for y_rel, txt, is_border in blocks:
                # Saltar si es header/footer confirmado por repetición
                if txt in confirmed_hf:
                    continue
                # Saltar si está en zona de borde y coincide con patrón variable
                if is_border and any(p.search(txt) for p in HF_VARIABLE_PATTERNS):
                    continue
                page_lines.append(txt)
            pages_text.append("\n".join(page_lines))

        print(f"  [PDF] Extraídas {total} páginas con pdfminer.")
        if confirmed_hf:
            print(f"  [PDF] Encabezados/pies eliminados: {len(confirmed_hf)} "
                  f"({list(confirmed_hf)[:3]}...)" if len(confirmed_hf) > 3
                  else f"  [PDF] Encabezados/pies eliminados: {list(confirmed_hf)}")

    except Exception as e:
        print(f"  [PDF] pdfminer falló ({e}), usando pypdf para texto...")
        for page in reader.pages:
            pages_text.append(page.extract_text() or "")
        print(f"  [PDF] Extraídas {total} páginas con pypdf.")

    # --- Imágenes con PyMuPDF para obtener coordenadas reales ---
    # Las coordenadas permiten detectar flores/adornos de esquina, marcos y overlays
    # sin desactivar la conservación de ilustraciones reales.
    try:
        images, discarded_images = _extract_images_with_pymupdf(pdf_path, pages_text, total)
        print("  [Imágenes] Extracción con PyMuPDF: coordenadas disponibles para filtrado")
    except Exception as e:
        print(f"  [Imágenes] PyMuPDF falló ({e}), usando fallback pypdf sin coordenadas...")
        images, discarded_images = _extract_images_with_pypdf(reader, pages_text, total)

    filtered_images, decorative_images = _filter_decorative_images(images, total)
    all_discarded_images = discarded_images + decorative_images
    _log_discarded_images(all_discarded_images)

    print(f"  [Imágenes] Extraídas: {len(filtered_images)} "
          f"({sum(1 for i in filtered_images if i['is_full_page'])} pág. completa, "
          f"{sum(1 for i in filtered_images if not i['is_full_page'])} inline)")
    return pages_text, filtered_images


# Compatibilidad con código que llame a extract_pdf_text directamente
def extract_pdf_text(pdf_path: str) -> list[str]:
    pages, _ = extract_pdf_content(pdf_path)
    return pages


# ─────────────────────────────────────────────
#  LIMPIEZA DE TEXTO
# ─────────────────────────────────────────────









# ─────────────────────────────────────────────
#  DETECCIÓN Y ESTRUCTURA DE CAPÍTULOS
# ─────────────────────────────────────────────
# Implementación extraída a converter.chapters. Los nombres se importan arriba
# para mantener compatibilidad con llamadas externas a pdf2epub.*.



# ─────────────────────────────────────────────
#  CONVERSIÓN DE TEXTO A HTML
# ─────────────────────────────────────────────

# Sistema de diálogos detectado automáticamente
DIALOG_SYSTEMS = {
    "guion":   re.compile(r'^[—–]'),           # — Hola —dijo él
    "guion2":  re.compile(r'^─'),              # ─ Hola ─ (CoA style)
    "comillas": re.compile(r'^["«\u201c]'),    # "Hola", «Hola»
}

THOUGHT_PATTERN = re.compile(
    r'\*(.+?)\*'             # *pensamiento*
)

BOLD_PATTERN = re.compile(
    r'\*\*(.+?)\*\*'
)


def detect_dialog_system(chapters: list[dict]) -> str:
    """Detecta qué sistema de diálogos usa el texto."""
    counts = {"guion": 0, "guion2": 0, "comillas": 0, "none": 0}
    for ch in chapters:
        for para in ch["paragraphs"][:20]:
            for sys_name, pattern in DIALOG_SYSTEMS.items():
                if pattern.match(para):
                    counts[sys_name] += 1
                    break
            else:
                counts["none"] += 1
    dominant = max(counts, key=counts.get)
    print(f"  [Diálogos] Sistema detectado: {dominant} {dict(counts)}")
    return dominant


def escape_xml(text: str) -> str:
    """Escapa caracteres especiales para XML/HTML."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def apply_inline_styles(text: str) -> str:
    """
    Aplica estilos en línea:
    - **texto** → <b>texto</b>
    - *texto* → <i>texto</i>  (pensamientos y énfasis)
    - Cursiva directa (texto ya marcado con <i> queda)
    """
    # Primero negrita (para que ** se procese antes que *)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Luego cursiva
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    return text


def para_to_html(para: str, first_in_chapter: bool = False) -> str:
    """
    Convierte un párrafo de texto plano a HTML.
    - Maneja estilos en línea
    - Aplica class="asangre" al primer párrafo
    - Detecta pensamientos en cursiva (entre *asteriscos*)
    """
    para = escape_xml(para)
    para = apply_inline_styles(para)

    css_class = ' class="asangre"' if first_in_chapter else ""
    return f'<p{css_class}>{para}</p>'


def inline_image_html(imgname: str, caption: str = "", layout: str = "inline") -> str:
    """Genera el HTML para una imagen dentro del flujo de un capítulo."""
    cap_html = f'\n<p class="centrado"><i>{escape_xml(caption)}</i></p>' if caption else ""
    extra_class = " fullblock" if layout == "fullblock" else ""
    return (
        f'<div class="dimg{extra_class}">\n'
        f'  <img alt="ilustración" src="../Images/{imgname}"/>\n'
        f'</div>{cap_html}'
    )



def chapter_to_xhtml(chapter: dict, lang: str = "es") -> str:
    """Convierte un capítulo completo a XHTML."""
    return chapter_fragment_to_xhtml(
        chapter,
        start_idx=0,
        end_idx=len(chapter.get("paragraphs", [])),
        lang=lang,
        include_header=True,
        first_text_para_global=True,
    )


def chapter_fragment_to_xhtml(chapter: dict, start_idx: int, end_idx: int,
                              lang: str = "es", include_header: bool = True,
                              first_text_para_global: bool = True,
                              suppress_images: set[str] | None = None) -> str:
    """
    Convierte un fragmento de capítulo a XHTML para poder intercalar imágenes
    de página completa exactamente donde aparecen en el PDF.
    """
    title = chapter["title"]
    subtitle = chapter.get("subtitle", "").strip()
    paragraphs = chapter.get("paragraphs", [])[start_idx:end_idx]
    inline_images = chapter.get("inline_images", [])

    body_parts = []
    if include_header:
        section_kind = chapter.get("section_kind", "chapter")
        if section_kind == "part":
            body_parts.append(f'<h3 class="part-title">{escape_xml(title)}</h3>')
        else:
            body_parts.append(f'<h1 class="chapter-title">{escape_xml(title)}</h1>')
        if subtitle:
            body_parts.append(f'<h2 class="chapter-subtitle">{escape_xml(subtitle)}</h2>')

    suppress_images = suppress_images or set()
    img_by_pos: dict[int, list] = {}
    seen_img_names: set[str] = set()
    for img in inline_images:
        imgname = img.get("imgname", "")
        if not imgname or imgname in seen_img_names or imgname in suppress_images:
            continue
        pos = img.get("after_para_idx", -1)
        if pos < start_idx - 1 or pos >= end_idx:
            continue
        rebased = pos - start_idx
        img_copy = dict(img)
        img_copy["after_para_idx"] = rebased
        img_by_pos.setdefault(rebased, []).append(img_copy)
        seen_img_names.add(imgname)

    for img in img_by_pos.get(-1, []):
        body_parts.append(inline_image_html(img["imgname"], img.get("caption", ""), img.get("layout", "inline")))

    first_text_para = first_text_para_global
    for i, para in enumerate(paragraphs):
        if para.strip():
            body_parts.append(para_to_html(para, first_in_chapter=first_text_para))
            first_text_para = False
        for img in img_by_pos.get(i, []):
            body_parts.append(inline_image_html(img["imgname"], img.get("caption", ""), img.get("layout", "inline")))

    body_html = "\n".join(body_parts)

    return XHTML_CHAPTER_TEMPLATE.format(
        lang=lang,
        title=f"{title}{': ' + subtitle if subtitle else ''}",
        body=body_html,
    )


# ─────────────────────────────────────────────
#  GENERACIÓN DEL EPUB
# ─────────────────────────────────────────────

def build_opf(meta: dict, manifest_items: list[dict], spine_idrefs: list[str], book_id: str) -> str:
    """Genera el content.opf."""

    manifest_xml = "\n    ".join(
        f'<item id="{item["id"]}" href="{item["href"]}" media-type="{item["media_type"]}"/>'
        for item in manifest_items
    )

    spine_xml = "\n    ".join(
        f'<itemref idref="{idref}"/>' for idref in spine_idrefs
    )

    cover_item = next((i for i in manifest_items if i["id"] == "cover-image"), None)
    cover_meta = f'\n    <meta name="cover" content="cover-image"/>' if cover_item else ""

    return f"""<?xml version="1.0" encoding="utf-8"?>
<package version="2.0" unique-identifier="BookId"
         xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{escape_xml(meta.get('title', 'Sin título'))}</dc:title>
    <dc:creator>{escape_xml(meta.get('author', 'Desconocido'))}</dc:creator>
    <dc:language>{meta.get('lang', 'es')}</dc:language>
    <dc:publisher>{escape_xml(meta.get('publisher', ''))}</dc:publisher>
    <dc:identifier id="BookId" opf:scheme="UUID">urn:uuid:{book_id}</dc:identifier>
    <dc:date>{meta.get('date', '2026')}</dc:date>{cover_meta}
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="style" href="Styles/style.css" media-type="text/css"/>
    {manifest_xml}
  </manifest>
  <spine toc="ncx">
    {spine_xml}
  </spine>
  <guide>
    <reference type="cover" title="Portada" href="Text/Portada.xhtml"/>
    <reference type="text" title="Inicio" href="Text/001.xhtml"/>
  </guide>
</package>
"""


def build_ncx(meta: dict, nav_points: list[dict], book_id: str) -> str:
    """Genera el toc.ncx."""
    nav_xml_parts = []
    for i, point in enumerate(nav_points, 1):
        nav_xml_parts.append(f"""    <navPoint id="navPoint-{i}" playOrder="{i}">
      <navLabel><text>{escape_xml(point['label'])}</text></navLabel>
      <content src="{point['src']}"/>
    </navPoint>""")

    nav_xml = "\n".join(nav_xml_parts)

    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
  "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="{meta.get('lang','es')}">
  <head>
    <meta name="dtb:uid" content="urn:uuid:{book_id}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{escape_xml(meta.get('title',''))}</text></docTitle>
  <navMap>
{nav_xml}
  </navMap>
</ncx>
"""


def build_container_xml() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def build_cover_xhtml(lang: str = "es") -> str:
    return XHTML_COVER_TEMPLATE.format(lang=lang)


def build_image_page_xhtml(img: dict, lang: str, title: str) -> str:
    """Genera el XHTML para una página completa de imagen."""
    caption_html = ""
    if img.get("caption"):
        caption_html = f'\n<p class="centrado"><i>{escape_xml(img["caption"])}</i></p>'
    return XHTML_IMAGE_PAGE_TEMPLATE.format(
        lang=lang,
        title=title,
        alt="ilustración",
        imgname=img["name"],
        caption_html=caption_html,
    )


def _image_bytes_to_jpeg_bytes(image_bytes: bytes) -> bytes:
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    img = _flatten_image_for_mobile_compat(img)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92, progressive=False, optimize=False, subsampling=0)
    return buf.getvalue()


def _path_to_jpeg_bytes(image_path: str) -> bytes:
    with open(image_path, "rb") as f:
        return _image_bytes_to_jpeg_bytes(f.read())


def _pick_auto_cover_image(images: list[dict]) -> dict | None:
    if not images:
        return None

    useful: list[dict] = []
    for img in images:
        width = int(img.get("width") or 0)
        height = int(img.get("height") or 0)
        area = width * height
        if img.get("is_full_page") or area >= 160000 or len(img.get("data", b"")) >= 12000:
            useful.append(img)

    candidates = useful or images

    def sort_key(img: dict):
        page_idx = int(img.get("page_idx", 10**6))
        is_page_one = 0 if page_idx == 0 else 1
        full_page_priority = 0 if img.get("is_full_page") else 1
        later_page_penalty = page_idx
        size_penalty = -int((img.get("width") or 0) * (img.get("height") or 0))
        return (is_page_one, full_page_priority, later_page_penalty, size_penalty)

    candidates = sorted(candidates, key=sort_key)
    return candidates[0] if candidates else None


def resolve_cover_image(cover_image_path: str | None = None,
                        images: list[dict] | None = None) -> tuple[bytes | None, str, int | None]:
    if cover_image_path and os.path.exists(cover_image_path):
        return _path_to_jpeg_bytes(cover_image_path), "manual", None

    auto_cover = _pick_auto_cover_image(images or [])
    if auto_cover is not None:
        return (
            _image_bytes_to_jpeg_bytes(auto_cover["data"]),
            f"auto:página {int(auto_cover.get('page_idx', 0)) + 1}",
            int(auto_cover.get('page_idx', 0)),
        )

    return None, "none", None




# Helpers de fragmentos/spine extraídos a converter.chapters.

def create_epub(chapters: list[dict], meta: dict, output_path: str,
                cover_image_path: str | None = None,
                images: list[dict] | None = None,
                raw_pages: list[str] | None = None,
                pages_paragraphs: list[list[str]] | None = None,
                page_to_chapter: list | None = None) -> None:
    """
    Genera el archivo EPUB final siguiendo el orden real de las páginas del PDF,
    pero evitando desperdiciar espacio cuando hay ilustraciones o secuencias
    visuales. Las imágenes decorativas repetidas ya se filtran antes, y aquí:
      - las ilustraciones entre texto se integran dentro del flujo del capítulo
      - las imágenes de páginas consecutivas sin texto se agrupan en una galería
      - la portada automática no se duplica como página normal
    """
    lang = meta.get("lang", "es")
    images = images or []
    raw_pages = raw_pages or []
    pages_paragraphs = pages_paragraphs or []
    n_pages = len(raw_pages)

    excluded_pages = set(meta.get('excluded_pages', []) or [])
    full_page_img_map: dict[int, list] = {}
    inline_imgs_by_page: dict[int, list] = {}
    for img in images:
        if img["is_full_page"]:
            full_page_img_map.setdefault(img["page_idx"], []).append(img)
        else:
            inline_imgs_by_page.setdefault(img["page_idx"], []).append(img)

    if page_to_chapter is None or len(page_to_chapter) != n_pages:
        page_to_chapter = [0] * n_pages if chapters else []

    cover_bytes, cover_source, cover_page_idx = resolve_cover_image(cover_image_path=cover_image_path, images=images)
    has_cover_img = cover_bytes is not None

    mapped = sum(1 for c in page_to_chapter if c >= 0)
    print(f"  [EPUB] Mapa página→capítulo: {mapped}/{n_pages} páginas mapeadas")

    for ch in chapters:
        ch.setdefault("inline_images", [])

    page_para_ranges = _build_sequential_page_para_ranges(chapters, pages_paragraphs, page_to_chapter)

    # Imágenes inline normales: ancladas al final del rango textual de la página.
    for pg_idx, page_imgs in inline_imgs_by_page.items():
        ch_idx = page_to_chapter[pg_idx] if pg_idx < len(page_to_chapter) else -1
        if ch_idx < 0 or ch_idx >= len(chapters):
            continue
        start_end = page_para_ranges.get((ch_idx, pg_idx))
        if start_end:
            _, end_idx = start_end
            after_idx = end_idx - 1
        else:
            after_idx = -1
        for iimg in page_imgs:
            chapters[ch_idx]["inline_images"].append({
                "after_para_idx": after_idx,
                "imgname": iimg["name"],
                "caption": iimg.get("caption", ""),
                "layout": "inline",
            })

    # Imágenes de página completa dentro del cuerpo narrativo:
    # si están entre páginas del mismo capítulo, las integramos en el XHTML del
    # capítulo en vez de emitir una página EPUB aparte.
    consumed_full_pages: set[int] = set()
    for pg_idx, page_imgs in full_page_img_map.items():
        if pg_idx in excluded_pages:
            continue
        if cover_page_idx is not None and pg_idx == cover_page_idx:
            continue
        ch_idx = page_to_chapter[pg_idx] if pg_idx < len(page_to_chapter) else -1
        if ch_idx < 0 or ch_idx >= len(chapters):
            continue

        prev_info = _find_neighbor_text_page(page_para_ranges, ch_idx, pg_idx, -1, limit=2)
        next_info = _find_neighbor_text_page(page_para_ranges, ch_idx, pg_idx, +1, limit=2)
        if prev_info is None and next_info is None:
            continue

        if prev_info is not None:
            _, (_, prev_end_idx) = prev_info
            after_idx = prev_end_idx - 1
        else:
            after_idx = -1

        for fimg in page_imgs:
            chapters[ch_idx]["inline_images"].append({
                "after_para_idx": after_idx,
                "imgname": fimg["name"],
                "caption": fimg.get("caption", ""),
                "layout": "fullblock",
            })
        consumed_full_pages.add(pg_idx)

    for ch in chapters:
        ch["inline_images"].sort(key=lambda x: (x.get("after_para_idx", -1), x.get("imgname", "")))

    spine_items: list[dict] = []
    nav_points: list[dict] = [{"label": "Portada", "src": "Text/Portada.xhtml"}]
    chapter_nav_added: set[int] = set()
    current_segment: dict | None = None

    def flush_segment():
        nonlocal current_segment
        if current_segment and current_segment["start_idx"] < current_segment["end_idx"]:
            spine_items.append(dict(current_segment))
        current_segment = None

    pg_idx = 0
    while pg_idx < n_pages:
        if pg_idx in excluded_pages:
            pg_idx += 1
            continue
        if cover_page_idx is not None and pg_idx == cover_page_idx:
            pg_idx += 1
            continue
        if pg_idx in consumed_full_pages:
            pg_idx += 1
            continue

        ch_idx = page_to_chapter[pg_idx] if pg_idx < len(page_to_chapter) else -1
        page_range = page_para_ranges.get((ch_idx, pg_idx)) if ch_idx >= 0 else None

        if page_range:
            start_idx, end_idx = page_range
            if current_segment is None:
                current_segment = {
                    "type": "chapter_fragment",
                    "ch_idx": ch_idx,
                    "start_idx": start_idx,
                    "end_idx": end_idx,
                    "include_header": ch_idx not in chapter_nav_added,
                }
            elif current_segment["ch_idx"] == ch_idx and current_segment["end_idx"] == start_idx:
                current_segment["end_idx"] = end_idx
            else:
                flush_segment()
                current_segment = {
                    "type": "chapter_fragment",
                    "ch_idx": ch_idx,
                    "start_idx": start_idx,
                    "end_idx": end_idx,
                    "include_header": ch_idx not in chapter_nav_added,
                }
            if ch_idx >= 0:
                chapter_nav_added.add(ch_idx)
            pg_idx += 1
            continue

        if pg_idx in full_page_img_map:
            flush_segment()

            # Intento conservador de compactación: para front matter puramente visual
            # (sin mapeo a capítulo) permitimos agrupar COMO MÁXIMO dos páginas
            # visuales consecutivas en un solo XHTML simple. Esto recupera parte de
            # la compactación previa sin volver a las galerías largas que rompían la
            # compatibilidad en lectores móviles. Si hay cualquier duda, se mantiene
            # una imagen por XHTML.
            def _can_compact_front_visual(page_index: int) -> bool:
                if page_index in excluded_pages or page_index in consumed_full_pages:
                    return False
                if cover_page_idx is not None and page_index == cover_page_idx:
                    return False
                if page_index not in full_page_img_map:
                    return False
                mapped_ch = page_to_chapter[page_index] if page_index < len(page_to_chapter) else -1
                if mapped_ch >= 0:
                    return False
                imgs = full_page_img_map.get(page_index, [])
                if len(imgs) != 1:
                    return False
                img = imgs[0]
                width = int(img.get("width") or 0)
                height = int(img.get("height") or 0)
                if width <= 0 or height <= 0:
                    return False
                ratio = max(width, height) / max(1, min(width, height))
                # No compactar imágenes extremadamente altas/verticales ni muy grandes.
                if ratio > 1.9:
                    return False
                if width * height > 3_000_000:
                    return False
                return True

            if _can_compact_front_visual(pg_idx) and _can_compact_front_visual(pg_idx + 1):
                spine_items.append({
                    "type": "img_sequence",
                    "images": [full_page_img_map[pg_idx][0], full_page_img_map[pg_idx + 1][0]],
                })
                pg_idx += 2
                continue

            for fimg in full_page_img_map[pg_idx]:
                spine_items.append({"type": "img_page", "image": fimg})
            pg_idx += 1
            continue

        pg_idx += 1

    flush_segment()

    emitted_covering: dict[int, tuple[int, int]] = {}
    for item in spine_items:
        if item["type"] != "chapter_fragment":
            continue
        ch_idx = item["ch_idx"]
        start_idx = item["start_idx"]
        end_idx = item["end_idx"]
        prev = emitted_covering.get(ch_idx)
        if prev is None:
            emitted_covering[ch_idx] = (start_idx, end_idx)
        else:
            emitted_covering[ch_idx] = (min(prev[0], start_idx), max(prev[1], end_idx))

    chapter_ranges: dict[int, list[tuple[int, int]]] = {}
    for item in spine_items:
        if item["type"] != "chapter_fragment":
            continue
        chapter_ranges.setdefault(item["ch_idx"], []).append((item["start_idx"], item["end_idx"]))

    def _merged_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
        cleaned = sorted((s, e) for s, e in ranges if e >= s)
        if not cleaned:
            return []
        merged = [cleaned[0]]
        for start, end in cleaned[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        return merged

    for ch_idx, ch in enumerate(chapters):
        total = len(ch.get("paragraphs", []))
        ranges = _merged_ranges(chapter_ranges.get(ch_idx, []))

        if total == 0 and not ranges:
            spine_items.append({
                "type": "chapter_fragment",
                "ch_idx": ch_idx,
                "start_idx": 0,
                "end_idx": 0,
                "include_header": ch_idx not in chapter_nav_added,
            })
            continue

        if not ranges:
            spine_items.append({
                "type": "chapter_fragment",
                "ch_idx": ch_idx,
                "start_idx": 0,
                "end_idx": total,
                "include_header": ch_idx not in chapter_nav_added,
            })
            continue

        cursor = 0
        for start, end in ranges:
            if cursor < start:
                spine_items.append({
                    "type": "chapter_fragment",
                    "ch_idx": ch_idx,
                    "start_idx": cursor,
                    "end_idx": start,
                    "include_header": ch_idx not in chapter_nav_added and cursor == 0,
                })
                if cursor == 0:
                    chapter_nav_added.add(ch_idx)
            cursor = max(cursor, end)

        if cursor < total:
            spine_items.append({
                "type": "chapter_fragment",
                "ch_idx": ch_idx,
                "start_idx": cursor,
                "end_idx": total,
                "include_header": ch_idx not in chapter_nav_added and cursor == 0,
            })
            if cursor == 0:
                chapter_nav_added.add(ch_idx)

    spine_items, normalization_issues = _normalize_spine_fragments(spine_items, chapters)
    for issue in normalization_issues[:12]:
        print(f"  [EPUB] Ajuste fragmentos: {issue}")
    if len(normalization_issues) > 12:
        print(f"  [EPUB] Ajuste fragmentos: ... y {len(normalization_issues)-12} más")

    validation_issues = _validate_spine_fragments(spine_items, chapters)
    if validation_issues:
        print("  [EPUB] ⚠️ Validación de fragmentos detectó problemas residuales:")
        for issue in validation_issues[:12]:
            print(f"    - {issue}")
        if len(validation_issues) > 12:
            print(f"    ... y {len(validation_issues)-12} más")
    else:
        print("  [EPUB] Validación de fragmentos: sin solapamientos sospechosos")

    sequence_count = sum(1 for s in spine_items if s["type"] in {"img_page", "img_sequence"})
    inline_img_count = sum(len(ch.get("inline_images", [])) for ch in chapters)
    print(f"  [EPUB] Imágenes: {sequence_count} bloque(s) visual(es), {inline_img_count} integradas en texto")

    book_uuid = str(uuid.uuid4())

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", build_container_xml())
        zf.writestr("OEBPS/Styles/style.css", CSS_PROFILE)

        if has_cover_img:
            print(f"  [EPUB] Portada: {cover_source}")
            zf.writestr("OEBPS/Images/cover.jpg", cover_bytes)
            zf.writestr("OEBPS/Text/Portada.xhtml", build_cover_xhtml(lang))
        else:
            print("  [EPUB] Portada: sin imagen, se usará portada tipográfica")
            zf.writestr("OEBPS/Text/Portada.xhtml", XHTML_CHAPTER_TEMPLATE.format(
                lang=lang, title="Portada",
                body=(f'<h1 class="titulo">{escape_xml(meta.get("title",""))}</h1>\n'
                      f'<h2 class="subtitulo">{escape_xml(meta.get("author",""))}</h2>'),
            ))

        for img in images:
            zf.writestr(f"OEBPS/Images/{img['name']}", img["data"])

        manifest_items: list[dict] = []
        spine_idrefs: list[str] = []

        manifest_items.append({"id": "Portada", "href": "Text/Portada.xhtml",
                               "media_type": "application/xhtml+xml"})
        spine_idrefs.append("Portada")

        if has_cover_img:
            manifest_items.append({"id": "cover-image", "href": "Images/cover.jpg",
                                   "media_type": "image/jpeg"})

        for img in images:
            manifest_items.append({
                "id": f"img-{img['name'].replace('.', '-')}",
                "href": f"Images/{img['name']}",
                "media_type": img["media_type"],
            })

        visual_counter = 0
        text_counter = 0
        chapter_nav_written: set[int] = set()

        for item in spine_items:
            if item["type"] == "img_page":
                visual_counter += 1
                ip_filename = f"img_{visual_counter:03d}.xhtml"
                ip_id = f"imgpage{visual_counter:03d}"
                img = item["image"]
                title = img.get("caption") or f"Ilustración {visual_counter}"
                caption_html = f'\n<p class="centrado"><i>{escape_xml(img.get("caption", ""))}</i></p>' if img.get("caption") else ""
                zf.writestr(
                    f"OEBPS/Text/{ip_filename}",
                    XHTML_IMAGE_PAGE_TEMPLATE.format(
                        lang=lang,
                        title=escape_xml(title),
                        alt="ilustración",
                        imgname=img["name"],
                        caption_html=caption_html,
                    ),
                )
                manifest_items.append({"id": ip_id, "href": f"Text/{ip_filename}",
                                       "media_type": "application/xhtml+xml"})
                spine_idrefs.append(ip_id)
            elif item["type"] == "img_sequence":
                visual_counter += 1
                ip_filename = f"img_{visual_counter:03d}.xhtml"
                ip_id = f"imgpage{visual_counter:03d}"
                title = f"Ilustraciones {visual_counter}"
                zf.writestr(
                    f"OEBPS/Text/{ip_filename}",
                    build_image_sequence_xhtml(item["images"], lang=lang, title=escape_xml(title)),
                )
                manifest_items.append({"id": ip_id, "href": f"Text/{ip_filename}",
                                       "media_type": "application/xhtml+xml"})
                spine_idrefs.append(ip_id)
            else:
                text_counter += 1
                ch_idx = item["ch_idx"]
                chapter = chapters[ch_idx]
                filename = f"{text_counter:03d}.xhtml"
                item_id = f"cap{text_counter:03d}"
                first_global = item["start_idx"] == 0
                xhtml = chapter_fragment_to_xhtml(
                    chapter,
                    start_idx=item["start_idx"],
                    end_idx=item["end_idx"],
                    lang=lang,
                    include_header=item.get("include_header", False),
                    first_text_para_global=first_global,
                )
                zf.writestr(f"OEBPS/Text/{filename}", xhtml)
                manifest_items.append({"id": item_id, "href": f"Text/{filename}",
                                       "media_type": "application/xhtml+xml"})
                spine_idrefs.append(item_id)

                if ch_idx not in chapter_nav_written:
                    title = chapter["title"]
                    subtitle = chapter.get("subtitle", "")
                    nav_points.append({
                        "label": f"{title}: {subtitle}" if subtitle else title,
                        "src": f"Text/{filename}",
                    })
                    chapter_nav_written.add(ch_idx)

        zf.writestr("OEBPS/content.opf",
                    build_opf(meta, manifest_items, spine_idrefs, book_uuid))
        zf.writestr("OEBPS/toc.ncx",
                    build_ncx(meta, nav_points, book_uuid))

    print(f"\n  ✅ EPUB generado: {output_path}")
    size_kb = os.path.getsize(output_path) / 1024
    print(f"     Tamaño: {size_kb:.1f} KB | "
          f"Capítulos: {len(chapters)} | Imágenes: {len(images)}")


# ─────────────────────────────────────────────
#  INTERFAZ DE LÍNEA DE COMANDOS
# ─────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Convierte PDF → EPUB con soporte OCR opcional para PDFs escaneados o con texto corrupto.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Ejemplos:
              python3 pdf2epub.py libro.pdf
              python3 pdf2epub.py libro.pdf -o salida.epub
              python3 pdf2epub.py libro.pdf --title "Mi Novela" --author "Autor"
              python3 pdf2epub.py libro.pdf --cover portada.jpg -v
        """)
    )
    parser.add_argument("pdf", help="Archivo PDF de entrada")
    parser.add_argument("-o", "--output", help="Archivo EPUB de salida (por defecto: mismo nombre que el PDF)")
    parser.add_argument("--title",  default="", help="Título del libro")
    parser.add_argument("--author", default="", help="Autor del libro")
    parser.add_argument("--publisher", default="", help="Editorial")
    parser.add_argument("--lang", default="es", help="Idioma (por defecto: es)")
    parser.add_argument("--cover", default="", help="Ruta a imagen de portada (JPG/PNG)")
    parser.add_argument("--date", default="2026", help="Año de publicación")
    parser.add_argument("-v", "--verbose", action="store_true", help="Modo detallado")
    parser.add_argument("--config", default="", help="Archivo JSON con configuración adicional")
    parser.add_argument("--ocr", dest="ocr_mode", choices=["off", "auto", "force"],
                        default=DEFAULT_OCR_MODE,
                        help="OCR para páginas escaneadas o con texto corrupto")
    parser.add_argument("--ocr-lang", default=DEFAULT_OCR_LANG,
                        help="Idiomas Tesseract, por ejemplo spa o spa+eng")
    parser.add_argument("--ocr-dpi", type=int, default=DEFAULT_OCR_DPI,
                        help="Resolución de render para OCR (por defecto: 300)")
    parser.add_argument("--ocr-min-text-chars", type=int, default=DEFAULT_OCR_MIN_TEXT_CHARS,
                        help="En modo auto, activa OCR si la página tiene poco texto")
    parser.add_argument("--ocr-garbage-threshold", type=float, default=DEFAULT_OCR_GARBAGE_THRESHOLD,
                        help="En modo auto, activa OCR si el score de corrupción supera este valor")
    parser.add_argument("--tesseract-cmd", default="",
                        help="Ruta opcional al ejecutable tesseract.exe")
    return parser.parse_args()


def load_config(args) -> dict:
    """Combina defaults + archivo JSON opcional + CLI (la CLI tiene prioridad)."""
    config = {
        "title":     "",
        "author":    "",
        "publisher": "",
        "lang":      "es",
        "cover":     "",
        "date":      "2026",
        "verbose":   False,
        "ocr_mode":  DEFAULT_OCR_MODE,
        "ocr_lang":  DEFAULT_OCR_LANG,
        "ocr_dpi":   DEFAULT_OCR_DPI,
        "ocr_min_text_chars": DEFAULT_OCR_MIN_TEXT_CHARS,
        "ocr_garbage_threshold": DEFAULT_OCR_GARBAGE_THRESHOLD,
        "ocr_psm": 3,
        "ocr_oem": 3,
        "tesseract_cmd": "",
    }
    if args.config and os.path.exists(args.config):
        with open(args.config, encoding='utf-8') as f:
            extra = json.load(f)
        config.update(extra)

    cli_config = {
        "title":     args.title,
        "author":    args.author,
        "publisher": args.publisher,
        "lang":      args.lang,
        "cover":     args.cover,
        "date":      args.date,
        "verbose":   args.verbose,
        "ocr_mode":  args.ocr_mode,
        "ocr_lang":  args.ocr_lang,
        "ocr_dpi":   args.ocr_dpi,
        "ocr_min_text_chars": args.ocr_min_text_chars,
        "ocr_garbage_threshold": args.ocr_garbage_threshold,
        "tesseract_cmd": args.tesseract_cmd,
    }
    config.update(cli_config)
    return config


def guess_title_author(pdf_path: str) -> tuple[str, str]:
    """Intenta extraer título y autor de los metadatos del PDF."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        info = reader.metadata
        title  = (info.get("/Title")  or "").strip()
        author = (info.get("/Author") or "").strip()
        return title, author
    except Exception:
        return "", ""


# ─────────────────────────────────────────────
#  PUNTO DE ENTRADA PRINCIPAL
# ─────────────────────────────────────────────

def main():
    args = parse_args()
    config = load_config(args)

    pdf_path = args.pdf
    if not os.path.exists(pdf_path):
        print(f"❌ Error: No se encontró el archivo '{pdf_path}'")
        sys.exit(1)

    # Archivo de salida
    if args.output:
        output_path = args.output
    else:
        stem = Path(pdf_path).stem
        output_path = str(Path(pdf_path).parent / f"{stem}.epub")

    print(f"\n{'='*55}")
    print(f"  PDF → EPUB Converter  |  Perfil: Apotecaria")
    print(f"{'='*55}")
    print(f"  Entrada : {pdf_path}")
    print(f"  Salida  : {output_path}")

    # Metadatos
    pdf_title, pdf_author = guess_title_author(pdf_path)
    meta = {
        "title":     config["title"]     or pdf_title  or Path(pdf_path).stem,
        "author":    config["author"]    or pdf_author or "Desconocido",
        "publisher": config["publisher"] or "",
        "lang":      config["lang"],
        "date":      config["date"],
    }
    print(f"  Título  : {meta['title']}")
    print(f"  Autor   : {meta['author']}")
    print()

    # FASE 1: Extracción
    print("▶ FASE 1 — Extrayendo texto e imágenes del PDF...")
    raw_pages, images = extract_pdf_content(pdf_path)

    # FASE 1.5: OCR opcional
    print("\n▶ FASE 1.5 — Evaluando OCR...")
    raw_pages, ocr_stats = apply_ocr_to_pages(pdf_path, raw_pages, config)

    # FASE 2: Limpieza
    print("\n▶ FASE 2 — Limpiando texto...")
    pages_paragraphs = clean_text_per_page(raw_pages, config)   # ← por página
    clean = "\n\n".join(p for page in pages_paragraphs for p in page)

    if config["verbose"]:
        preview = clean[:500].replace("\n", "↵")
        print(f"\n  Vista previa (primeros 500 chars):\n  {preview}\n")

    # FASE 3: Detección de capítulos
    print("\n▶ FASE 3 — Detectando capítulos...")
    chapters, page_to_chapter = detect_chapters(clean, config,
                                                pages_paragraphs=pages_paragraphs)
    meta['excluded_pages'] = config.get('_excluded_pages', [])

    if not chapters:
        print("  ⚠️  No se detectaron capítulos. El PDF completo irá como un solo capítulo.")
        all_paras = [p for p in clean.split("\n\n") if p.strip()]
        chapters = [{"title": meta["title"], "subtitle": "", "paragraphs": all_paras,
                     "first_page_idx": 0}]
        page_to_chapter = [0] * len(raw_pages)

    # Detectar sistema de diálogos
    detect_dialog_system(chapters)

    # FASE 4: Generación
    print("\n▶ FASE 4 — Generando EPUB...")
    cover = config["cover"] if config["cover"] and os.path.exists(config["cover"]) else None
    create_epub(chapters, meta, output_path, cover_image_path=cover,
                images=images, raw_pages=raw_pages,
                pages_paragraphs=pages_paragraphs,
                page_to_chapter=page_to_chapter)

    print(f"\n{'='*55}")
    print(f"  ✅ Conversión completada exitosamente")
    print(f"  📖 {output_path}")
    if 'ocr_stats' in locals() and ocr_stats.get('pages_replaced'):
        print(f"  🔎 OCR páginas: {ocr_stats['pages_replaced']}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
