# -*- coding: utf-8 -*-
"""Extracción de texto/imágenes desde PDF y soporte OCR.

Este módulo centraliza la lectura con pypdf/pdfminer/PyMuPDF, las imágenes
editoriales y el OCR opcional mediante Tesseract. Se usa desde CLI y GUI.
"""

import io
import math
import os
import pickle
import tempfile
from collections import OrderedDict
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytesseract

from .image_filters import (
    _encode_image_for_epub,
    _filter_decorative_images,
    _image_position_bucket,
    _image_visual_hash_from_pil,
    _log_discarded_images,
    _looks_like_decorative_motif_image,
    _looks_like_image_artifact,
)
from .text_utils import (
    _clean_page_number_only,
    _estimate_garbage_score,
    _looks_like_visual_separator_text,
)


# OCR v2
DEFAULT_OCR_MODE = "off"        # off | auto | force
DEFAULT_OCR_LANG = "spa+eng"    # requiere paquetes de idioma instalados en Tesseract
DEFAULT_OCR_DPI = 300
DEFAULT_OCR_MIN_TEXT_CHARS = 90
DEFAULT_OCR_GARBAGE_THRESHOLD = 0.22

# Umbral: una página se considera "solo imagen" si tiene muy poco texto real
IMAGE_PAGE_TEXT_THRESHOLD = 20  # caracteres (excluyendo número de página)


def get_base_dir() -> Path:
    """Devuelve la carpeta base tanto en script normal como en PyInstaller."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def _tesseract_works(command: str) -> bool:
    """Detecta ejecutables rotos (por ejemplo, un .exe sin sus DLL)."""
    try:
        result = subprocess.run(
            [command, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def get_tesseract_cmd(user_path=None):
    """Busca Tesseract usable, sin elegir .exe de Windows en otros sistemas."""
    if user_path:
        command = str(user_path).strip().strip('"')
        if not _tesseract_works(command):
            raise RuntimeError(f"Tesseract no se puede ejecutar desde la ruta indicada: {command}")
        return command

    candidates = []
    base_dir = get_base_dir()
    if sys.platform == "win32":
        candidates.append(base_dir / "tesseract" / "tesseract.exe")
        for key in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(key):
                candidates.append(Path(os.environ[key]) / "Tesseract-OCR" / "tesseract.exe")

    installed = shutil.which("tesseract")
    if installed:
        candidates.append(installed)

    for candidate in candidates:
        if _tesseract_works(str(candidate)):
            return str(candidate)

    raise RuntimeError(
        "Tesseract OCR no está disponible o no puede ejecutarse. "
        "Instala Tesseract OCR con idiomas spa y eng; "
        "el tesseract.exe incluido necesita sus DLL en Windows."
    )


def configure_tesseract(config: dict | None = None) -> str:
    """Configura el motor y evita un TESSDATA_PREFIX heredado de otro ejecutable."""
    config = config or {}
    tesseract_cmd = get_tesseract_cmd(config.get("tesseract_cmd"))
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    # El paquete local puede aportar idiomas, pero el Tesseract instalado
    # conoce su propio tessdata: no hay que forzar las rutas equivocadas.
    bundled_dir = get_base_dir() / "tesseract"
    executable = Path(tesseract_cmd)
    if executable.parent.resolve() == bundled_dir.resolve():
        tessdata_dir = bundled_dir / "tessdata"
        if tessdata_dir.exists():
            os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
    return tesseract_cmd


def _is_image_only_page(text: str) -> bool:
    """Detecta páginas visuales con escaso texto real."""
    cleaned = _clean_page_number_only(text)
    compact = re.sub(r"\s+", " ", cleaned).strip()
    if len(compact) < IMAGE_PAGE_TEXT_THRESHOLD:
        return True
    if _looks_like_visual_separator_text(compact):
        return True
    return False


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

# E05: límite conservador para evitar que un solo pliego escaneado agote la RAM.
MAX_OCR_RENDER_PIXELS = 20_000_000


def _render_page_to_png_bytes(pdf_path: str, page_index: int,
                              dpi: int = DEFAULT_OCR_DPI, *, doc=None) -> bytes:
    """Rasteriza una página. Si se pasa `doc`, no reabre el PDF por página.

    Reduce proporcionalmente el DPI para pliegos excepcionalmente grandes y
    rechaza páginas que ni siquiera caben en el límite a 72 DPI.
    """
    import fitz  # PyMuPDF

    own_doc = doc is None
    if own_doc:
        doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_index)
        dpi = max(72, int(dpi))
        w, h = float(page.rect.width), float(page.rect.height)
        if w <= 0 or h <= 0:
            raise ValueError(f'Página {page_index + 1}: dimensiones inválidas para OCR')
        pixels = w * h * (dpi / 72.0) ** 2
        if pixels > MAX_OCR_RENDER_PIXELS:
            dpi = int(dpi * math.sqrt(MAX_OCR_RENDER_PIXELS / pixels))
            if dpi < 72:
                raise ValueError(
                    f'Página {page_index + 1}: imagen demasiado grande para OCR seguro'
                )
            print(f'    [OCR E05] Página {page_index + 1}: DPI ajustado a {dpi} por memoria')
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
        try:
            return pix.tobytes('png')
        finally:
            del pix
    finally:
        if own_doc:
            doc.close()

def _ocr_png_bytes(png_bytes: bytes, config: dict) -> str:
    from PIL import Image

    # La conversión por lotes configura Tesseract una sola vez antes del bucle.
    if not config.get('_ocr_engine_ready'):
        configure_tesseract(config)
    lang = (config.get('ocr_lang') or DEFAULT_OCR_LANG).strip()
    psm = str(config.get('ocr_psm', 3)).strip()
    oem = str(config.get('ocr_oem', 3)).strip()
    custom = f'--oem {oem} --psm {psm}'

    img = Image.open(io.BytesIO(png_bytes)).convert('L')
    return pytesseract.image_to_string(img, lang=lang, config=custom)

def apply_ocr_to_pages(pdf_path: str, raw_pages: list[str], config: dict) -> tuple[list[str], dict]:
    """Aplica OCR sin ocultar fallos; en 'force' los errores son fatales."""
    mode = (config.get('ocr_mode') or DEFAULT_OCR_MODE).lower()
    if mode not in {'off', 'auto', 'force'}:
        raise ValueError(f"Modo OCR no reconocido: {mode}")
    stats = {
        'mode': mode,
        'applied': False,
        'pages_attempted': 0,
        'pages_replaced': 0,
        'pages_failed': 0,
        'page_indexes': [],
        'reasons': {},
        'warnings': [],
    }
    if mode == 'off':
        print('  OCR: desactivado')
        return raw_pages, stats

    # Comprobar primero si existe alguna página que requiere OCR. En modo
    # automático no hace falta Tesseract para PDFs con texto correctamente extraído.
    pending = [
        (idx, reason) for idx, text in enumerate(raw_pages)
        for needed, reason, _ in [_should_ocr_page(text, config)] if needed
    ]
    if not pending:
        print('  OCR: no se detectaron páginas que requieran reconocimiento')
        return raw_pages, stats

    try:
        import fitz  # noqa: F401
        from PIL import Image  # noqa: F401
        resolved_cmd = configure_tesseract(config)
        requested_lang = (config.get('ocr_lang') or DEFAULT_OCR_LANG).strip()
        available_langs = set(pytesseract.get_languages(config=''))
        missing = [language for language in requested_lang.split('+') if language not in available_langs]
        if missing:
            raise RuntimeError(
                f"Faltan idiomas OCR: {', '.join(missing)}. "
                f"Disponibles: {', '.join(sorted(available_langs))}"
            )
    except Exception as exc:
        message = f'OCR no disponible: {exc}'
        if mode == 'force':
            raise RuntimeError(message) from exc
        stats['pages_failed'] = len(pending)
        stats['warnings'].append(message)
        print(f'  ⚠️  {message}. Se conserva el texto original.')
        return raw_pages, stats

    replaced = list(raw_pages)
    dpi = int(config.get('ocr_dpi', DEFAULT_OCR_DPI))
    print(f'  OCR: modo={mode} | lang={requested_lang} | dpi={dpi}')
    print(f'  OCR: tesseract={resolved_cmd}')
    ocr_config = dict(config, _ocr_engine_ready=True)

    # E05: un solo descriptor PyMuPDF para todas las páginas con OCR.
    import fitz
    try:
        ocr_doc = fitz.open(pdf_path)
    except Exception as exc:
        message = f'OCR no pudo abrir el PDF: {exc}'
        if mode == 'force':
            raise RuntimeError(message) from exc
        stats['pages_failed'] += len(pending)
        stats['warnings'].append(message)
        print(f'  ⚠️  {message}; se conserva la extracción normal')
        return raw_pages, stats
    try:
        for idx, reason in pending:
            stats['pages_attempted'] += 1
            try:
                png_bytes = _render_page_to_png_bytes(pdf_path, idx, dpi=dpi, doc=ocr_doc)
                ocr_text = _ocr_png_bytes(png_bytes, ocr_config).strip()
                if ocr_text:
                    replaced[idx] = ocr_text
                    stats['pages_replaced'] += 1
                    stats['page_indexes'].append(idx)
                    stats['reasons'][idx] = reason
                    stats['applied'] = True
                    print(f'    OCR página {idx+1}: {reason}')
                else:
                    print(f'    ⚠️  OCR página {idx+1}: sin texto reconocible; se conserva extracción normal')
                    stats['warnings'].append(f'Página {idx+1}: OCR no encontró texto')
            except Exception as exc:
                stats['pages_failed'] += 1
                message = f'OCR página {idx+1}: fallo ({exc})'
                if mode == 'force':
                    raise RuntimeError(message) from exc
                stats['warnings'].append(message)
                print(f'    ⚠️  {message}; se conserva extracción normal')
    finally:
        ocr_doc.close()

    if mode == 'force' and stats['pages_replaced'] == 0:
        raise RuntimeError('OCR forzado no reconoció texto en ninguna página. Verifica el PDF y los idiomas.')
    if stats['pages_replaced'] == 0:
        print('  OCR: ninguna página reemplazada')
    else:
        joined = ', '.join(str(i + 1) for i in stats['page_indexes'][:12])
        extra = '' if len(stats['page_indexes']) <= 12 else '…'
        print(f"  OCR: páginas reemplazadas = {stats['pages_replaced']} ({joined}{extra})")
    if stats['warnings']:
        print(f"  ⚠️  OCR finalizó con {len(stats['warnings'])} advertencia(s)")
    return replaced, stats


def _build_image_record(page_idx: int,
                        img_counter: int,
                        pil_img,
                        page_text: str,
                        is_full_page: bool,
                        caption: str,
                        bbox=None,
                        page_width: float | None = None,
                        page_height: float | None = None,
                        prepared: dict | None = None) -> tuple[dict | None, dict | None]:
    """Crea una ocurrencia visual con metadatos de su página concreta.

    `prepared` permite reutilizar JPEG, análisis visual y hash de un mismo
    xref entre páginas. El bbox, la leyenda y el filtro contextual NO se cachean.
    """
    if prepared is None:
        prepared = {}
    if 'data' not in prepared:
        if pil_img is None:
            raise ValueError('La imagen no está disponible para preparar el recurso')
        safe_img, img_data, ext, media_type = _encode_image_for_epub(pil_img)
        prepared.update({
            'data': img_data, 'ext': ext, 'media_type': media_type,
            'width': safe_img.width, 'height': safe_img.height,
            '_visual_hash': _image_visual_hash_from_pil(safe_img),
            '_artifact': _looks_like_image_artifact(safe_img),
        })
    else:
        safe_img = None

    name = f"img{img_counter:03d}.{prepared['ext']}"
    base = {
        "page_idx": page_idx,
        "name": name,
        "data": prepared['data'],
        "ext": prepared['ext'],
        "media_type": prepared['media_type'],
        "is_full_page": is_full_page,
        "caption": caption,
        "width": prepared['width'],
        "height": prepared['height'],
        "bbox": tuple(float(v) for v in bbox) if bbox else None,
        "page_width": float(page_width or 0),
        "page_height": float(page_height or 0),
        "_visual_hash": prepared['_visual_hash'],
    }

    if prepared['_artifact']:
        discard = dict(base)
        discard['discard_reason'] = 'artefacto_visual_pdf'
        discard['_position_bucket'] = _image_position_bucket(discard)
        return None, discard

    # Motivos sólo en páginas con prosa. El resultado visual se calcula una vez
    # por xref, pero la decisión de descartarlo depende siempre de esta página.
    page_has_text = len((page_text or '').strip()) >= 80
    if page_has_text and not is_full_page:
        if '_motif' not in prepared:
            if safe_img is not None:
                prepared['_motif'] = _looks_like_decorative_motif_image(safe_img)
            else:
                from PIL import Image
                with Image.open(io.BytesIO(prepared['data'])) as reopened:
                    prepared['_motif'] = _looks_like_decorative_motif_image(reopened)
        is_motif, motif_reason = prepared['_motif']
        if is_motif:
            discard = dict(base)
            discard['discard_reason'] = motif_reason or 'motivo_decorativo'
            discard['_position_bucket'] = _image_position_bucket(discard)
            return None, discard
    return base, None

def _extract_images_with_pymupdf(pdf_path: str, pages_text: list[str], total: int) -> tuple[list[dict], list[dict]]:
    """Extrae imágenes con coordenadas usando PyMuPDF. Si falla, el llamador usa fallback."""
    import fitz
    from PIL import Image

    images: list[dict] = []
    discarded: list[dict] = []
    img_counter = 0
    # Cache acotada por xref: las páginas suelen repetir sellos e ilustraciones.
    # Guardamos sólo JPEG compactado y análisis, no bitmaps PIL decodificados.
    cache: OrderedDict[int, dict] = OrderedDict()
    cache_bytes = 0
    cache_hits = 0
    cache_limit = 24 * 1024 * 1024
    cache_entries_limit = 128

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
                    prepared = None
                    pil_img = None
                    if xref > 0 and xref in cache:
                        prepared = cache[xref]
                        cache.move_to_end(xref)
                        cache_hits += 1
                    else:
                        if xref > 0:
                            extracted = doc.extract_image(xref)
                            img_bytes = extracted.get('image')
                            if not img_bytes:
                                continue
                            pil_img = Image.open(io.BytesIO(img_bytes))
                        else:
                            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=True)
                            pil_img = Image.open(io.BytesIO(pix.tobytes('png')))
                        prepared = {}
                    try:
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
                            prepared=prepared,
                        )
                    finally:
                        if pil_img is not None:
                            pil_img.close()
                    if xref > 0 and xref not in cache:
                        size = len(prepared.get('data', b''))
                        if 0 < size <= cache_limit:
                            while cache and (len(cache) >= cache_entries_limit or cache_bytes + size > cache_limit):
                                _, old = cache.popitem(last=False)
                                cache_bytes -= len(old['data'])
                            cache[xref] = prepared
                            cache_bytes += size
                    if discard:
                        discarded.append(discard)
                    elif record:
                        images.append(record)
                except Exception as ex:
                    print(f"  [Imágenes] ⚠️  No se pudo extraer imagen en pág {page_idx+1}: {ex}")
    finally:
        doc.close()
    if cache_hits:
        print(f'  [Imágenes E05] {cache_hits} reutilización(es) de recursos PDF sin recodificar')
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

        # E05: un único recorrido de pdfminer y bloques serializados a un
        # temporal con volcado a disco. No acumular LTPage ni todos los bloques
        # de cientos/miles de páginas simultáneamente en memoria.
        HEADER_ZONE = 0.90
        FOOTER_ZONE = 0.10
        from collections import Counter
        header_footer_counter: Counter = Counter()

        HF_VARIABLE_PATTERNS = [
            re.compile(r'P[áa]gina\s+N[°º]?\s*\d+', re.IGNORECASE),
            re.compile(r'\bpág(?:ina)?\s*\.?\s*\d+', re.IGNORECASE),
            re.compile(r'^\d{1,4}$'),
            re.compile(r'^[\-–—]\s*\d+\s*[\-–—]$'),
        ]

        # El temporal se cierra/elimina incluso si pdfminer genera una excepción.
        with tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024, mode='w+b') as spool:
            layout_count = 0
            for page_layout in extract_pages(pdf_path, laparams=laparams):
                h = page_layout.height or 842
                blocks = []
                for elem in page_layout:
                    if isinstance(elem, LTTextContainer):
                        txt = elem.get_text().strip()
                        if not txt:
                            continue
                        y_rel = elem.bbox[1] / h
                        is_border = y_rel > HEADER_ZONE or y_rel < FOOTER_ZONE
                        blocks.append((is_border, txt))
                        if is_border:
                            header_footer_counter[txt] += 1
                pickle.dump(blocks, spool, protocol=pickle.HIGHEST_PROTOCOL)
                layout_count += 1
                if layout_count % 100 == 0:
                    print(f'  [PDF E05] Páginas analizadas: {layout_count}/{total}', flush=True)

            confirmed_hf = {txt for txt, cnt in header_footer_counter.items() if cnt >= 4}
            spool.seek(0)
            for _ in range(layout_count):
                blocks = pickle.load(spool)
                page_lines = []
                for is_border, txt in blocks:
                    if txt in confirmed_hf:
                        continue
                    if is_border and any(p.search(txt) for p in HF_VARIABLE_PATTERNS):
                        continue
                    page_lines.append(txt)
                pages_text.append('\n'.join(page_lines))

        print(f"  [PDF] Extraídas {total} páginas con pdfminer.")
        if confirmed_hf:
            print(f"  [PDF] Encabezados/pies eliminados: {len(confirmed_hf)} "
                  f"({list(confirmed_hf)[:3]}...)" if len(confirmed_hf) > 3
                  else f"  [PDF] Encabezados/pies eliminados: {list(confirmed_hf)}")

    except Exception as e:
        print(f"  [PDF] pdfminer falló ({e}), usando pypdf para texto...")
        pages_text = []  # descartar extracción incompleta antes del fallback
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

