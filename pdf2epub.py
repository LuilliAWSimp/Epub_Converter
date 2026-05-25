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

from converter.epub_writer import (
    CSS_PROFILE,
    XHTML_CHAPTER_TEMPLATE,
    XHTML_COVER_TEMPLATE,
    XHTML_IMAGE_PAGE_TEMPLATE,
    XHTML_IMAGE_SEQUENCE_TEMPLATE,
    _find_neighbor_text_page,
    _image_bytes_to_jpeg_bytes,
    _path_to_jpeg_bytes,
    _pick_auto_cover_image,
    apply_inline_styles,
    build_container_xml,
    build_cover_xhtml,
    build_image_page_xhtml,
    build_image_sequence_xhtml,
    build_ncx,
    build_opf,
    chapter_fragment_to_xhtml,
    chapter_to_xhtml,
    create_epub,
    escape_xml,
    inline_image_html,
    para_to_html,
    resolve_cover_image,
)

# ─────────────────────────────────────────────
#  PERFIL DE FORMATO (basado en análisis EPUB)
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















# ─────────────────────────────────────────────
#  GENERACIÓN DEL EPUB
# ─────────────────────────────────────────────





















# Helpers de fragmentos/spine extraídos a converter.chapters.



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
