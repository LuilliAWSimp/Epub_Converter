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
from pathlib import Path
import pytesseract


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

# Umbral: una página se considera "solo imagen" si tiene muy poco texto real
IMAGE_PAGE_TEXT_THRESHOLD = 20  # caracteres (excluyendo número de página)

# OCR v2
DEFAULT_OCR_MODE = "off"        # off | auto | force
DEFAULT_OCR_LANG = "spa+eng"    # requiere paquetes de idioma instalados en Tesseract
DEFAULT_OCR_DPI = 300
DEFAULT_OCR_MIN_TEXT_CHARS = 90
DEFAULT_OCR_GARBAGE_THRESHOLD = 0.22

def get_base_dir() -> Path:
    """Devuelve la carpeta base tanto en script normal como en PyInstaller."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def get_tesseract_cmd(user_path=None):
    """
    Prioridad:
    1) ruta pasada por usuario
    2) tesseract embebido junto al proyecto / ejecutable
    3) comando global del sistema
    """
    if user_path:
        user_path = str(user_path).strip().strip('"')
        if user_path and Path(user_path).exists():
            return user_path

    base_dir = get_base_dir()
    local = base_dir / "tesseract" / "tesseract.exe"
    if local.exists():
        return str(local)

    return "tesseract"


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

def _is_image_only_page(text: str) -> bool:
    """Devuelve True si la página es prácticamente solo una imagen (sin texto real)."""
    cleaned = _clean_page_number_only(text)
    compact = re.sub(r"\s+", " ", cleaned).strip()
    if len(compact) < IMAGE_PAGE_TEXT_THRESHOLD:
        return True
    if _looks_like_visual_separator_text(compact):
        return True
    return False


def _looks_like_visual_separator_text(text: str) -> bool:
    """Heurística para páginas visuales con muy poco texto útil."""
    cleaned = _clean_page_number_only(text)
    compact = re.sub(r"\s+", " ", cleaned).strip()
    if not compact:
        return True
    if len(compact) <= 70:
        return True

    line_count = len([ln for ln in cleaned.splitlines() if ln.strip()])
    alpha_words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ']+", compact)
    if line_count <= 4 and len(alpha_words) <= 14:
        narrative_punct = sum(compact.count(ch) for ch in '.!?¿¡;:')
        if narrative_punct <= 1:
            return True
    return False


def _clean_page_number_only(text: str) -> str:
    return re.sub(r'^\s*\d{1,4}\s*$', '', (text or '').strip())


def _estimate_garbage_score(text: str) -> float:
    """Heurística simple para detectar texto corrupto/mojibake extraído del PDF."""
    cleaned = _clean_page_number_only(text)
    if not cleaned:
        return 1.0

    nonspace = ''.join(ch for ch in cleaned if not ch.isspace())
    if not nonspace:
        return 1.0

    allowed_re = r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9\s\.,;:!\?¡¿()\[\]\{\}\-—–_\"'/%&@#=+*…ºª€$]"
    weird_chars = sum(1 for ch in cleaned if not re.match(allowed_re, ch))
    weird_ratio = weird_chars / max(1, len(nonspace))

    # Tokens con demasiados símbolos internos suelen indicar extracción mala.
    suspicious_tokens = re.findall(r"\b\S*[\*\[\]\{\}\|\\`~^<>_]\S*\b", cleaned)
    tokens = re.findall(r"\b\S+\b", cleaned)
    suspicious_ratio = len(suspicious_tokens) / max(1, len(tokens))

    # Si casi no hay letras, probablemente es una imagen, tabla o basura.
    alpha_chars = sum(ch.isalpha() for ch in cleaned)
    alpha_ratio = alpha_chars / max(1, len(nonspace))
    alpha_penalty = 0.25 if alpha_ratio < 0.55 else 0.0

    score = weird_ratio + suspicious_ratio + alpha_penalty
    return min(1.0, score)


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


def _decorative_image_hash(img: dict) -> str:
    return hashlib.sha1(img.get("data", b"")).hexdigest()


def _flatten_image_for_mobile_compat(pil_img, background=(255, 255, 255)):
    """Aplana cualquier alpha/transparencia y normaliza a RGB.

    Varios lectores EPUB móviles renderizan mal PNGs con alpha o imágenes
    extraídas desde streams PDF con composición compleja, produciendo bloques
    negros o zonas vacías. Para máxima compatibilidad, aquí se rasteriza todo a
    un bitmap RGB simple sobre fondo sólido.
    """
    from PIL import Image

    if pil_img.mode not in ("RGB", "RGBA", "LA", "L"):
        pil_img = pil_img.convert("RGBA") if 'A' in pil_img.mode else pil_img.convert("RGB")

    if pil_img.mode in ("RGBA", "LA"):
        rgba = pil_img.convert("RGBA")
        base = Image.new("RGB", rgba.size, background)
        base.paste(rgba, mask=rgba.getchannel("A"))
        return base

    if pil_img.mode == "L":
        return pil_img.convert("RGB")

    return pil_img.convert("RGB")


def _encode_image_for_epub(pil_img):
    """Convierte cualquier imagen extraída del PDF a un formato muy compatible.

    Para evitar diferencias entre lectores de laptop y móvil, todas las imágenes
    terminan como JPEG RGB baseline estándar, sin alpha ni formatos internos del
    PDF (JPX/JPEG2000, máscaras, etc.).
    """
    out = _flatten_image_for_mobile_compat(pil_img)
    fmt = "JPEG"
    ext = "jpg"
    media_type = "image/jpeg"

    buf = io.BytesIO()
    out.save(
        buf,
        format=fmt,
        quality=92,
        progressive=False,
        optimize=False,
        subsampling=0,
    )
    return out, buf.getvalue(), ext, media_type


def _looks_like_image_artifact(pil_img) -> bool:
    """Descarta máscaras/artefactos del PDF que no son ilustraciones reales.

    Heurística conservadora y sin dependencias extra.
    Busca especialmente:
    - bloques grises/negros casi uniformes
    - máscaras parciales con esquinas transparentes
    - recursos pequeños o medianos con muy poco detalle real
    """
    from PIL import ImageStat

    def _entropy_from_hist(hist):
        total = float(sum(hist) or 1.0)
        ent = 0.0
        for c in hist:
            if c:
                p = c / total
                ent -= p * math.log2(p)
        return ent

    try:
        rgba = pil_img.convert("RGBA")
        width, height = rgba.size
        area = width * height
        if area <= 0:
            return True

        rgb = rgba.convert("RGB")
        gray = rgb.convert("L")
        hsv = rgb.convert("HSV")

        rgb_stat = ImageStat.Stat(rgb)
        gray_stat = ImageStat.Stat(gray)
        hsv_stat = ImageStat.Stat(hsv)

        avg_std = sum(rgb_stat.stddev[:3]) / 3.0
        avg_mean = sum(rgb_stat.mean[:3]) / 3.0
        sat_mean = float(hsv_stat.mean[1])
        sat_std = float(hsv_stat.stddev[1])
        gray_entropy = _entropy_from_hist(gray.histogram())

        # Detección explícita de recursos "basura" del PDF:
        # máscaras negras/grises, overlays mínimos o imágenes casi monocromas
        # de muy pocos bytes. El caso problemático real del PDF de prueba cae aquí.
        try:
            color_probe = rgba.getcolors(maxcolors=8)
        except Exception:
            color_probe = None
        color_count = None if color_probe is None else len(color_probe)
        raw_bbox = rgba.getbbox()
        if raw_bbox is None:
            return True

        # Conteo de colores más fino para recursos pequeños/medianos.
        rich_color_count = None
        dominant_ratio = 0.0
        if area <= 50000:
            try:
                rich_probe = rgba.getcolors(maxcolors=min(262144, area + 1))
            except Exception:
                rich_probe = None
            if rich_probe:
                rich_color_count = len(rich_probe)
                dominant_ratio = max(count for count, _ in rich_probe) / float(area)

        if color_count is not None and color_count <= 2:
            # Recurso casi monocromático: si además es relativamente pequeño
            # o de muy pocos bytes visuales, es casi seguro un artefacto.
            if area <= 120000:
                return True
            if avg_std < 3.0 and gray_entropy < 1.2:
                return True

        if avg_std < 2.0 and gray_entropy < 0.8 and area <= 180000:
            return True

        # Caso muy específico del bloque gris: recurso pequeño, en escala de grises,
        # con muy pocos colores reales y un tono dominante enorme.
        if (
            area <= 50000
            and max(width, height) <= 240
            and sat_mean < 1.5
            and sat_std < 1.5
            and rich_color_count is not None
            and rich_color_count <= 160
            and dominant_ratio >= 0.70
        ):
            return True

        # Caso muy específico y común en estos PDFs:
        # rectángulos negros/grises pequeños-medianos con un solo color útil.
        if color_count == 1 and area <= 250000:
            return True

        # Casos muy pequeños y casi uniformes.
        if area <= 50000 and avg_std < 6.0:
            return True
        if max(width, height) <= 220 and avg_std < 8.0:
            return True

        # Bloques casi vacíos, extremadamente oscuros o claros.
        if area <= 180000 and avg_std < 5.0 and (avg_mean < 15 or avg_mean > 245):
            return True

        alpha = rgba.getchannel("A")
        alpha_bbox = alpha.getbbox()
        if alpha_bbox is None:
            return True

        visible_ratio = float((alpha_bbox[2] - alpha_bbox[0]) * (alpha_bbox[3] - alpha_bbox[1])) / float(area or 1)
        alpha_crop = alpha.crop(alpha_bbox)
        alpha_stat = ImageStat.Stat(alpha_crop)
        alpha_mean = float(alpha_stat.mean[0])
        alpha_std = float(alpha_stat.stddev[0])

        rgb_crop = rgb.crop(alpha_bbox)
        gray_crop = gray.crop(alpha_bbox)
        hsv_crop = hsv.crop(alpha_bbox)

        crop_stat = ImageStat.Stat(rgb_crop)
        vis_mean = sum(crop_stat.mean[:3]) / 3.0
        vis_std = sum(crop_stat.stddev[:3]) / 3.0
        sat_crop_mean = float(ImageStat.Stat(hsv_crop).mean[1])
        sat_crop_std = float(ImageStat.Stat(hsv_crop).stddev[1])
        crop_entropy = _entropy_from_hist(gray_crop.histogram())

        extrema = rgb_crop.getextrema()
        channel_ranges = [mx - mn for (mn, mx) in extrema[:3]]

        # M áscaras/stencils típicos del PDF: bloques negros o grises casi uniformes,
        # con saturación bajísima y muy poco detalle.
        if vis_std < 6.0 and sat_crop_mean < 8.0 and crop_entropy < 2.2 and area <= 250000:
            return True

        # Variante ligeramente más grande pero aún con muy poca información visual.
        if vis_std < 10.0 and sat_crop_mean < 10.0 and crop_entropy < 2.6 and area <= 320000 and max(channel_ranges) <= 40:
            return True

        # Rectángulos redondeados / overlays con transparencia parcial.
        # Esquinas muy transparentes + centro semitransparente + poca variación tonal.
        corner_pts = [
            (0, 0),
            (max(0, width - 1), 0),
            (0, max(0, height - 1)),
            (max(0, width - 1), max(0, height - 1)),
        ]
        corner_alpha = [alpha.getpixel(pt) for pt in corner_pts]
        center_alpha = alpha.getpixel((width // 2, height // 2))
        if (
            max(corner_alpha) < 25
            and 25 < center_alpha < 245
            and sat_mean < 10.0
            and avg_std < 12.0
            and gray_entropy < 2.8
            and area <= 350000
        ):
            return True

        # Imágenes casi uniformes con muy poca variación tonal y ocupación alta.
        if max(channel_ranges) <= 6 and visible_ratio > 0.9 and crop_entropy < 2.0:
            return True

        # Recursos medianos de fondo gris/negro sin textura real.
        if (
            area <= 400000
            and sat_mean < 8.0
            and sat_std < 6.0
            and gray_stat.stddev[0] < 12.0
            and gray_entropy < 3.0
            and avg_mean < 200
        ):
            return True

        return False
    except Exception:
        return False

def _filter_decorative_images(images: list[dict], total_pages: int) -> tuple[list[dict], list[dict]]:
    """
    Omite imágenes repetidas y pequeñas que suelen ser adornos de pie de página,
    logos o elementos decorativos incrustados en casi todas las páginas.
    """
    from collections import Counter

    if not images:
        return images, []

    hash_counts = Counter(_decorative_image_hash(img) for img in images)
    decorative: list[dict] = []
    kept: list[dict] = []

    repeat_threshold = max(5, int(total_pages * 0.10))
    very_repeat_threshold = max(8, int(total_pages * 0.30))

    for img in images:
        h = _decorative_image_hash(img)
        repeats = hash_counts[h]
        width = int(img.get("width") or 0)
        height = int(img.get("height") or 0)
        area = width * height
        smallish = area <= 120000 or max(width, height) <= 600
        highly_repeated = repeats >= repeat_threshold
        overwhelmingly_repeated = repeats >= very_repeat_threshold

        # Repetido en gran parte del documento y además pequeño → casi seguro adorno.
        if smallish and (highly_repeated or overwhelmingly_repeated):
            decorative.append(img)
            continue

        kept.append(img)

    return kept, decorative


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

    # --- Imágenes con pypdf ---
    images: list[dict] = []
    img_counter = 0

    for page_idx, page in enumerate(reader.pages):
        page_imgs = page.images
        if not page_imgs:
            continue

        page_text = pages_text[page_idx] if page_idx < len(pages_text) else ""
        is_full_page = _is_image_only_page(page_text)
        if not is_full_page and len(page_imgs) == 1 and _looks_like_visual_separator_text(page_text):
            is_full_page = True

        # Pie de foto: texto real en páginas con imagen pero con algo de texto
        caption = ""
        if not is_full_page and page_text.strip():
            lines = [l.strip() for l in page_text.splitlines() if l.strip()]
            lines = [l for l in lines if not re.fullmatch(r'\d{1,4}', l)]
            if lines:
                caption = " ".join(lines)

        for img_obj in page_imgs:
            img_counter += 1
            try:
                pil_img = img_obj.image
                safe_img, img_data, ext, media_type = _encode_image_for_epub(pil_img)

                if _looks_like_image_artifact(safe_img):
                    continue

                images.append({
                    "page_idx":     page_idx,
                    "name":         f"img{img_counter:03d}.{ext}",
                    "data":         img_data,
                    "ext":          ext,
                    "media_type":   media_type,
                    "is_full_page": is_full_page,
                    "caption":      caption,
                    "width":        safe_img.width,
                    "height":       safe_img.height,
                })
            except Exception as ex:
                print(f"  [Imágenes] ⚠️  No se pudo extraer imagen en pág {page_idx+1}: {ex}")

    filtered_images, decorative_images = _filter_decorative_images(images, total)
    if decorative_images:
        decorative_pages = sorted({img["page_idx"] + 1 for img in decorative_images})
        preview = ", ".join(map(str, decorative_pages[:8]))
        extra = "" if len(decorative_pages) <= 8 else "…"
        print(f"  [Imágenes] Decorativas omitidas: {len(decorative_images)} (págs {preview}{extra})")

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

# Patrones de encabezados/pies repetidos (se detectan dinámicamente)
HEADER_FOOTER_MIN_REPEAT = 4  # aparece en al menos N páginas = candidato a header/footer
VARIABLE_PAGE_LINE_RE = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .:'’_\-]{3,80}\s*\|\s*\d{1,4}$")
STRUCTURAL_HEADING_RE = re.compile(
    r'^[\-—–―|\s]*'
    r'(?:cap[ií]tulo(?:\s+(?:\d+|extra|especial))?|chapter(?:\s+(?:\d+|extra|special))?|'
    r'parte(?:\s+\d+)?|pr[oó]logo|prologue|ep[ií]logo|afterword|short\s+story|'
    r'palabras del autor|agradecimientos?|acknowledgements?)\b',
    re.IGNORECASE,
)


def is_structural_heading_line(line: str) -> bool:
    s = _normalize_heading_text(line)
    return bool(s and STRUCTURAL_HEADING_RE.match(s))


def looks_like_section_subtitle(line: str) -> bool:
    s = _normalize_heading_text(line)
    if not s or is_structural_heading_line(s):
        return False
    if len(s) > 120 or len(s.split()) > 14:
        return False
    if re.search(r'\.{2,}\s*\d{1,4}$', s):
        return False
    if '|' in s and re.search(r'\d{1,4}$', s):
        return False
    if re.fullmatch(r'\d{1,4}', s):
        return False
    if re.match(r'^(?:cap[ií]tulo|chapter|parte|pr[oó]logo|ep[ií]logo|afterword|short\s+story)\b', s, re.IGNORECASE):
        return False
    words = [w for w in re.split(r'\s+', s) if w]
    titled = sum(1 for w in words if re.match(r'^[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+', w))
    return titled >= max(1, len(words) // 2)


def normalize_header_footer_candidate(line: str) -> str:
    """Normaliza líneas candidatas a header/footer con número de página variable."""
    s = re.sub(r'\s+', ' ', (line or '').strip())
    if not s:
        return ''
    if is_structural_heading_line(s):
        return ''

    if re.fullmatch(r'[\-–—\s]*\d{1,4}[\-–—\s]*', s):
        return '<PAGE_NUM>'

    s = re.sub(r'\b(P[áa]g(?:ina)?\.?\s*)\d{1,4}\b', r'\1<PAGE_NUM>', s, flags=re.IGNORECASE)

    if VARIABLE_PAGE_LINE_RE.fullmatch(s):
        s = re.sub(r'\d{1,4}\s*$', '<PAGE_NUM>', s)

    if re.fullmatch(r'[\-–—\s]*<PAGE_NUM>[\-–—\s]*', s):
        return '<PAGE_NUM>'

    s = re.sub(r'(?<!\w)\d{1,4}(?!\w)', '<PAGE_NUM>', s)
    s = re.sub(r'\s+', ' ', s).strip()

    if is_structural_heading_line(s):
        return ''
    return s
def detect_repeated_lines(pages: list[str]) -> tuple[set[str], set[str]]:
    """Detecta líneas repetidas exactas y líneas repetidas tras normalización."""
    from collections import Counter

    exact_count: Counter = Counter()
    normalized_count: Counter = Counter()

    for page_text in pages:
        lines = page_text.strip().splitlines()
        candidates = lines[:3] + lines[-3:] if len(lines) >= 6 else lines
        seen_exact: set[str] = set()
        seen_normalized: set[str] = set()
        for line in candidates:
            stripped = re.sub(r'\s+', ' ', line.strip())
            if not stripped or len(stripped) <= 2:
                continue
            if is_structural_heading_line(stripped):
                continue
            if stripped not in seen_exact:
                exact_count[stripped] += 1
                seen_exact.add(stripped)
            normalized = normalize_header_footer_candidate(stripped)
            if normalized and normalized not in seen_normalized:
                normalized_count[normalized] += 1
                seen_normalized.add(normalized)

    repeated_exact = {line for line, count in exact_count.items() if count >= HEADER_FOOTER_MIN_REPEAT}
    repeated_normalized = {line for line, count in normalized_count.items() if count >= HEADER_FOOTER_MIN_REPEAT}
    return repeated_exact, repeated_normalized


def clean_text(raw_pages: list[str], config: dict) -> str:
    """
    Limpieza del texto ya extraído. Devuelve un único string con párrafos
    separados por doble newline.
    NOTA: Para preservar info de página usa clean_text_per_page().
    """
    cleaned_pages = clean_text_per_page(raw_pages, config)
    # Unir todas las páginas en un único string para detect_chapters
    all_paragraphs: list[str] = []
    for page_paras in cleaned_pages:
        all_paragraphs.extend(page_paras)
    return "\n\n".join(all_paragraphs)


def clean_text_per_page(raw_pages: list[str], config: dict) -> list[list[str]]:
    """
    Igual que clean_text pero devuelve una lista de listas:
      result[page_idx] = [párrafo1, párrafo2, ...]

    Esto preserva a qué página pertenece cada párrafo, lo que permite
    construir un mapa página→capítulo exacto en create_epub.
    """
    repeated_lines, repeated_normalized = detect_repeated_lines(raw_pages)
    if config.get("verbose"):
        if repeated_lines:
            print(f"  [Limpieza] Líneas repetidas residuales exactas ({len(repeated_lines)}):")
            for l in list(sorted(repeated_lines))[:5]:
                print(f"    - {repr(l)}")
        if repeated_normalized:
            print(f"  [Limpieza] Patrones repetidos normalizados ({len(repeated_normalized)}):")
            for l in list(sorted(repeated_normalized))[:5]:
                print(f"    - {repr(l)}")

    HF_EXTRA_PATTERNS = [
        re.compile(r'P[áa]gina\s+N[°º]?\s*\d+', re.IGNORECASE),
        re.compile(r'\bpág(?:ina)?\s*\.?\s*\d+', re.IGNORECASE),
        re.compile(r'^[\-–—]\s*\d+\s*[\-–—]$'),
        VARIABLE_PAGE_LINE_RE,
    ]

    verbose_removed = 0
    result: list[list[str]] = []
    for page_idx, page_text in enumerate(raw_pages):
        page_lines: list[str] = []
        for line in page_text.splitlines():
            stripped = re.sub(r'\s+', ' ', line.strip())
            if not stripped:
                page_lines.append("")
                continue

            normalized = normalize_header_footer_candidate(stripped)
            should_remove = False
            if stripped in repeated_lines:
                should_remove = True
            elif normalized and normalized in repeated_normalized:
                should_remove = True
            elif re.fullmatch(r'\d{1,4}', stripped):
                should_remove = True
            elif any(p.search(stripped) for p in HF_EXTRA_PATTERNS):
                should_remove = True

            # No eliminar headings narrativos legítimos.
            if should_remove and is_structural_heading_line(stripped):
                should_remove = False

            if should_remove:
                if config.get("verbose") and verbose_removed < 10:
                    print(f"  [Limpieza] Header/footer residual eliminado p.{page_idx + 1}: {repr(stripped)}")
                    verbose_removed += 1
                continue
            page_lines.append(stripped)
        paragraphs = reconstruct_paragraphs(page_lines, config)
        result.append(paragraphs)

    return result

def reconstruct_paragraphs(lines: list[str], config: dict) -> list[str]:
    """
    Reconstruye párrafos a partir de líneas sueltas.
    Heurísticas:
    - Línea vacía → salto de párrafo definitivo
    - Línea estructural (Prólogo / Capítulo / Parte / etc.) → párrafo propio
    - Línea de subtítulo tras heading estructural → párrafo propio
    - Línea que termina con guión de silabeo → unir con la siguiente
    - Línea que termina en punto/interrogación/exclamación → párrafo completo
    """
    paragraphs: list[str] = []
    current: list[str] = []

    END_PUNCTUATION = re.compile(r"[.!?»\"'—\u201d\u2019]$")
    DIALOG_START = re.compile(r'^[—–\-"«\u201c\u2018]')
    SENTENCE_START = re.compile(r'^[A-ZÁÉÍÓÚÜÑ"«\u201c\u2018—–]')
    HYPHEN_END = re.compile(r'-$')

    prev_nonempty = ""
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line == "":
            if current:
                paragraphs.append(" ".join(current))
                current = []
            i += 1
            continue

        if is_structural_heading_line(line):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            paragraphs.append(_normalize_heading_text(line))
            prev_nonempty = _normalize_heading_text(line)
            i += 1
            continue

        if prev_nonempty and is_structural_heading_line(prev_nonempty) and looks_like_section_subtitle(line):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            paragraphs.append(_normalize_heading_text(line))
            prev_nonempty = _normalize_heading_text(line)
            i += 1
            continue

        if HYPHEN_END.search(line) and i + 1 < len(lines) and lines[i + 1].strip():
            next_line = lines[i + 1].strip()
            if next_line and next_line[0].islower():
                current.append(line[:-1] + next_line)
                prev_nonempty = next_line
                i += 2
                continue

        current.append(line)
        prev_nonempty = line

        close_paragraph = False
        if END_PUNCTUATION.search(line):
            close_paragraph = True
        elif i + 1 < len(lines) and lines[i + 1].strip():
            next_line = lines[i + 1].strip()
            if is_structural_heading_line(next_line):
                close_paragraph = True
            elif SENTENCE_START.match(next_line) or DIALOG_START.match(next_line):
                close_paragraph = True

        if close_paragraph:
            paragraphs.append(" ".join(current))
            current = []

        i += 1

    if current:
        paragraphs.append(" ".join(current))

    result = []
    for p in paragraphs:
        p = p.strip()
        if p and len(p) > 1:
            result.append(p)
    return result

# ─────────────────────────────────────────────
#  DETECCIÓN DE CAPÍTULOS
# ─────────────────────────────────────────────

CHAPTER_PATTERNS = [
    re.compile(
        r'^[\-—–―|\s]*'
        r'(?:CAPÍTULO|CAPITULO|Capítulo|Capitulo|CHAPTER|Chapter|CAP\.|Cap\.)\s*'
        r'(\d+|[IVXLCDM]+|EXTRA|ESPECIAL)'
        r'(?:\s*[:.\-–—|]\s*(.+))?'
        r'[\-—–―|\s]*$',
        re.IGNORECASE
    ),
    re.compile(
        r'^[\-—–―|\s]*(?:PARTE|Parte|PART)\s*(\d+|[IVXLCDM]+)'
        r'(?:\s*[:.\-–—|]\s*(.+))?[\-—–―|\s]*$',
        re.IGNORECASE
    ),
    re.compile(r'^[\-—–―|\s]*(?:SHORT\s+STORY|Short\s+Story)[\-—–―|\s]*$', re.IGNORECASE),
    re.compile(r'^(\d{1,3})[.\-–]\s+([A-ZÁÉÍÓÚ].{3,})$'),
    re.compile(
        r'^[\-—–―|\s]*(Prólogo|Prolog|Epílogo|Epilogo|Interludio|Interlúdio|Interludio|'
        r'Prefacio|Presentación|Presentacion|Introducción|Introduccion|'
        r'Palabras del autor|Afterword|Foreword|Omake|Extra|Agradecimiento|Agradecimientos|Acknowledgement|Acknowledgements)\b',
        re.IGNORECASE
    ),
]

SPECIAL_SECTION_PATTERNS = [
    ("prologue", re.compile(r'^(?:prólogo|prologo|prefacio|foreword|introducción|introduccion)\b', re.IGNORECASE)),
    ("epilogue", re.compile(r'^(?:epílogo|epilogo)\b', re.IGNORECASE)),
    ("afterword", re.compile(r'^(?:afterword|palabras del autor)\b', re.IGNORECASE)),
    ("acknowledgements", re.compile(r'^(?:agradecimiento|agradecimientos|acknowledgement|acknowledgements)\b', re.IGNORECASE)),
    ("short_story", re.compile(r'^(?:short\s+story)\b', re.IGNORECASE)),
    ("part", re.compile(r'^(?:parte)\s+(?:\d+|[ivxlcdm]+)\b', re.IGNORECASE)),
    ("extra", re.compile(r'^(?:omake|extra)\b', re.IGNORECASE)),
]

TOC_KEYWORDS = (
    "tabla de contenido", "tabla de contenidos", "contenido", "contenidos",
    "table of contents", "contents", "índice", "indice", "toc"
)


def _normalize_heading_text(text: str) -> str:
    text = (text or "").replace(" ", " ")
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^[\-—–―|\s]+', '', text)
    text = re.sub(r'[\-—–―|\s]+$', '', text)
    return text.strip()


def _toc_entry_score(text: str) -> int:
    text = _normalize_heading_text(text)
    lower = text.lower()
    if not text:
        return 0

    score = 0
    shortish = len(text) <= 140 and len(text.split()) <= 18
    has_section_name = bool(re.search(r'(cap[ií]tulo|chapter|prólogo|prologo|ep[ií]logo|epilogo|afterword|palabras del autor|agradecimiento)', lower))
    has_leaders = bool(re.search(r'\.{2,}\s*\d{1,4}$', text))
    has_pipe = '|' in text
    trailing_page = bool(re.search(r'\b\d{1,4}$', text))

    if any(k in lower for k in TOC_KEYWORDS):
        score += 4
    if shortish and has_section_name:
        score += 2
    if shortish and has_leaders:
        score += 3
    if shortish and has_pipe and has_section_name:
        score += 2
    if shortish and trailing_page and (has_section_name or has_leaders or has_pipe):
        score += 1
    return score


def _is_probable_toc_page(page_paragraphs: list[str]) -> bool:
    if not page_paragraphs:
        return False
    joined = _normalize_heading_text(" ".join(page_paragraphs))
    lower = joined.lower()
    if any(k in lower for k in TOC_KEYWORDS):
        return True
    scores = [_toc_entry_score(p) for p in page_paragraphs]
    strong = sum(1 for s in scores if s >= 3)
    medium = sum(1 for s in scores if s >= 2)
    chapter_mentions = len(re.findall(r'(cap[ií]tulo|chapter|pr[óo]logo|ep[ií]logo|afterword)', lower))
    page_numbers = len(re.findall(r'\b\d{1,4}\b', lower))
    leader_count = len(re.findall(r'\.{2,}', joined))
    return (
        strong >= 2
        or (medium >= 3 and page_numbers >= 3)
        or (chapter_mentions >= 3 and page_numbers >= 3)
        or (chapter_mentions >= 3 and leader_count >= 2)
    )


def _find_first_body_page(pages_paragraphs: list[list[str]], toc_pages: set[int]) -> int:
    terminal_allowed = max(toc_pages) + 1 if toc_pages else 0
    for pg_idx, page_paras in enumerate(pages_paragraphs):
        if pg_idx in toc_pages:
            continue
        visible = [p.strip() for p in page_paras if p and p.strip()]
        if not visible:
            continue
        heading = _detect_page_heading(visible, allow_terminal=pg_idx >= terminal_allowed)
        if heading and heading['kind'] in {'prologue', 'chapter'}:
            return pg_idx
    for pg_idx, page_paras in enumerate(pages_paragraphs):
        if pg_idx in toc_pages:
            continue
        visible = [p.strip() for p in page_paras if p and p.strip()]
        if not visible:
            continue
        heading = _detect_page_heading(visible, allow_terminal=True)
        if heading:
            return pg_idx
    return -1


def _collect_auxiliary_pages(pages_paragraphs: list[list[str]], toc_pages: set[int], first_body_page: int) -> set[int]:
    aux_pages: set[int] = set(toc_pages)
    if first_body_page < 0:
        return aux_pages
    for pg_idx in range(first_body_page):
        visible = [p.strip() for p in pages_paragraphs[pg_idx] if p and p.strip()]
        if visible:
            continue
        if any(abs(pg_idx - toc_pg) <= 1 for toc_pg in toc_pages):
            aux_pages.add(pg_idx)
    return aux_pages

def _looks_like_short_heading(text: str) -> bool:
    text = _normalize_heading_text(text)
    if not text or len(text) > 120:
        return False
    if text.count('.') >= 3:
        return False
    return True


def _format_special_heading(kind: str, text: str) -> str:
    text = _normalize_heading_text(text)
    if kind == 'prologue':
        return 'Prólogo'
    if kind == 'epilogue':
        return 'Epílogo'
    if kind == 'afterword':
        return 'Afterword' if text.lower().startswith('afterword') else 'Palabras del autor'
    if kind == 'acknowledgements':
        return 'Agradecimiento' if text.lower().startswith('agradecimiento') else 'Agradecimientos'
    if kind == 'short_story':
        return 'Short Story'
    if kind == 'part':
        m = re.search(r'(\d+|[IVXLCDM]+)', text, re.IGNORECASE)
        return f"Parte {m.group(1)}" if m else 'Parte'
    return text or 'Extra'
def _detect_page_heading(page_paragraphs: list[str], allow_terminal: bool = True) -> dict | None:
    candidates = [_normalize_heading_text(p) for p in page_paragraphs[:5] if _normalize_heading_text(p)]
    if not candidates:
        return None

    if _toc_entry_score(candidates[0]) >= 3 and _is_probable_toc_page(candidates):
        return None

    heading_idx = 0
    for idx, cand in enumerate(candidates[:4]):
        if any(pat.match(cand) for _, pat in SPECIAL_SECTION_PATTERNS) or CHAPTER_PATTERNS[0].match(cand) or CHAPTER_PATTERNS[1].match(cand) or CHAPTER_PATTERNS[2].match(cand):
            heading_idx = idx
            break
    first = candidates[heading_idx]
    rest = candidates[heading_idx + 1:]

    for kind, pattern in SPECIAL_SECTION_PATTERNS:
        if kind in {'epilogue', 'afterword', 'acknowledgements'} and not allow_terminal:
            continue
        if pattern.match(first) and _looks_like_short_heading(first):
            consume = heading_idx + 1
            subtitle = ''
            if rest and looks_like_section_subtitle(rest[0]) and _toc_entry_score(rest[0]) < 2:
                second_is_same_special = any(pat.match(rest[0]) for _, pat in SPECIAL_SECTION_PATTERNS)
                if kind == 'afterword' and re.match(r'^(?:palabras del autor)$', rest[0], re.IGNORECASE):
                    subtitle = rest[0]
                    consume += 1
                elif not second_is_same_special and not CHAPTER_PATTERNS[0].match(rest[0]):
                    subtitle = rest[0]
                    consume += 1
            return {'kind': kind, 'title': _format_special_heading(kind, first), 'subtitle': subtitle, 'consume': consume}

    m = CHAPTER_PATTERNS[0].match(first)
    if m and _looks_like_short_heading(first):
        label = m.group(1)
        subtitle = (m.group(2) or '').strip()
        consume = heading_idx + 1
        if not subtitle and rest and looks_like_section_subtitle(rest[0]) and _toc_entry_score(rest[0]) < 2:
            if not any(pat.match(rest[0]) for _, pat in SPECIAL_SECTION_PATTERNS) and not CHAPTER_PATTERNS[0].match(rest[0]):
                subtitle = rest[0]
                consume += 1
        title = f'Capítulo {label.title() if str(label).isalpha() else label}'
        return {'kind': 'chapter', 'title': title, 'subtitle': subtitle, 'consume': consume}

    m = CHAPTER_PATTERNS[1].match(first)
    if m and _looks_like_short_heading(first):
        label = m.group(1)
        subtitle = (m.group(2) or '').strip()
        consume = heading_idx + 1
        if not subtitle and rest and looks_like_section_subtitle(rest[0]) and _toc_entry_score(rest[0]) < 2:
            subtitle = rest[0]
            consume += 1
        return {'kind': 'part', 'title': f'Parte {label}', 'subtitle': subtitle, 'consume': consume}

    if CHAPTER_PATTERNS[2].match(first):
        subtitle = ''
        consume = heading_idx + 1
        if rest and looks_like_section_subtitle(rest[0]) and _toc_entry_score(rest[0]) < 2:
            subtitle = rest[0]
            consume += 1
        return {'kind': 'short_story', 'title': 'Short Story', 'subtitle': subtitle, 'consume': consume}

    m = CHAPTER_PATTERNS[3].match(first)
    if m and _looks_like_short_heading(first):
        return {'kind': 'chapter', 'title': f'Capítulo {m.group(1)}', 'subtitle': (m.group(2) or '').strip(), 'consume': heading_idx + 1}

    return None
def detect_chapters(full_text: str, config: dict,
                    pages_paragraphs: list | None = None) -> tuple:
    """
    Divide el texto en secciones lógicas preservando el orden real del PDF.
    Prioriza el análisis por página para evitar que la tabla de contenido o
    encabezados auxiliares se mezclen con capítulos reales.
    """
    paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]

    if not pages_paragraphs:
        chapters: list = []
        current_chapter: dict | None = None
        intro_paragraphs: list = []
        for para in paragraphs:
            heading = _detect_page_heading([para])
            if heading:
                if current_chapter is not None:
                    chapters.append(current_chapter)
                elif intro_paragraphs:
                    chapters.append({
                        'title': 'Introducción', 'subtitle': '', 'paragraphs': intro_paragraphs,
                        'is_intro': True, 'first_page_idx': -1, 'section_kind': 'intro',
                    })
                    intro_paragraphs = []
                current_chapter = {
                    'title': heading['title'], 'subtitle': heading.get('subtitle', ''),
                    'paragraphs': [], 'is_intro': heading['kind'] != 'chapter',
                    'first_page_idx': -1, 'section_kind': heading['kind'],
                }
                continue
            if current_chapter is None:
                intro_paragraphs.append(para)
            else:
                current_chapter['paragraphs'].append(para)

        if current_chapter is not None:
            chapters.append(current_chapter)
        elif intro_paragraphs:
            chapters.append({
                'title': 'Introducción', 'subtitle': '', 'paragraphs': intro_paragraphs,
                'is_intro': True, 'first_page_idx': -1, 'section_kind': 'intro',
            })
        config['_excluded_pages'] = []
        config['_frontmatter_pages'] = []
        return chapters, []

    n_pages = len(pages_paragraphs)
    preliminary_body_page = -1
    for pg_idx, page_paras in enumerate(pages_paragraphs):
        visible = [p.strip() for p in page_paras if p and p.strip()]
        if not visible:
            continue
        heading = _detect_page_heading(visible, allow_terminal=False)
        if heading and heading['kind'] in {'prologue', 'chapter'}:
            preliminary_body_page = pg_idx
            break

    toc_pages: set[int] = set()
    toc_mode = False
    toc_scan_limit = preliminary_body_page if preliminary_body_page > 0 else min(n_pages, 40)
    for pg_idx, page_paras in enumerate(pages_paragraphs[:toc_scan_limit]):
        visible = [p.strip() for p in page_paras if p and p.strip()]
        is_toc = _is_probable_toc_page(visible)
        if is_toc:
            toc_pages.add(pg_idx)
            toc_mode = True
        elif toc_mode and visible and sum(_toc_entry_score(p) for p in visible[:6]) >= 5:
            toc_pages.add(pg_idx)
        else:
            toc_mode = False

    first_body_page = preliminary_body_page if preliminary_body_page >= 0 else _find_first_body_page(pages_paragraphs, toc_pages)
    auxiliary_pages = _collect_auxiliary_pages(pages_paragraphs, toc_pages, first_body_page)
    frontmatter_pages = sorted(pg for pg in range(first_body_page) if pg not in auxiliary_pages) if first_body_page > 0 else []

    chapters: list[dict] = []
    current_section: dict | None = None
    intro_paragraphs: list[str] = []
    intro_first_page = -1
    page_to_chapter: list[int] = [-1] * n_pages
    body_started = False

    def flush_current() -> None:
        nonlocal current_section, intro_paragraphs, intro_first_page
        if current_section is not None:
            chapters.append(current_section)
            current_section = None
        elif intro_paragraphs:
            chapters.append({
                'title': 'Introducción', 'subtitle': '', 'paragraphs': intro_paragraphs,
                'is_intro': True, 'first_page_idx': intro_first_page, 'section_kind': 'intro',
            })
            intro_paragraphs = []
            intro_first_page = -1

    for pg_idx, page_paras in enumerate(pages_paragraphs):
        if pg_idx in auxiliary_pages:
            continue

        visible_paras = [p.strip() for p in page_paras if p and p.strip()]
        if not visible_paras:
            continue

        allow_terminal = body_started or pg_idx >= first_body_page
        heading = _detect_page_heading(visible_paras, allow_terminal=allow_terminal)
        consume = 0
        if heading:
            if heading['kind'] in {'prologue', 'chapter'}:
                body_started = True
            elif not body_started and heading['kind'] in {'epilogue', 'afterword', 'acknowledgements'}:
                heading = None
            if heading:
                flush_current()
                current_section = {
                    'title': heading['title'],
                    'subtitle': heading.get('subtitle', ''),
                    'paragraphs': [],
                    'is_intro': heading['kind'] != 'chapter',
                    'first_page_idx': pg_idx,
                    'section_kind': heading['kind'],
                }
                consume = int(heading.get('consume', 1))

        content_paras = visible_paras[consume:]
        if len(content_paras) <= 2 and _looks_like_visual_separator_text(' '.join(content_paras)):
            content_paras = []

        if current_section is None:
            if content_paras:
                intro_paragraphs.extend(content_paras)
                if intro_first_page == -1:
                    intro_first_page = pg_idx
        else:
            current_section['paragraphs'].extend(content_paras)

    flush_current()

    if chapters:
        ch_starts = sorted(
            [(ch.get('first_page_idx', -1), i) for i, ch in enumerate(chapters) if ch.get('first_page_idx', -1) >= 0],
            key=lambda x: x[0]
        )
        cur_ch = -1
        ci = 0
        for pg in range(n_pages):
            if pg in auxiliary_pages:
                page_to_chapter[pg] = -1
                continue
            while ci < len(ch_starts) and ch_starts[ci][0] <= pg:
                cur_ch = ch_starts[ci][1]
                ci += 1
            page_to_chapter[pg] = cur_ch

    config['_excluded_pages'] = sorted(auxiliary_pages)
    config['_frontmatter_pages'] = frontmatter_pages

    print(f"  [Capítulos] Detectados: {len(chapters)}")
    if toc_pages:
        printable = ', '.join(str(p + 1) for p in sorted(toc_pages)[:6])
        extra = '' if len(toc_pages) <= 6 else '…'
        print(f"  [Estructura] TOC excluido en páginas: {printable}{extra}")
    if frontmatter_pages:
        printable = ', '.join(str(p + 1) for p in frontmatter_pages[:8])
        extra = '' if len(frontmatter_pages) <= 8 else '…'
        print(f"  [Estructura] Front matter visual antes del cuerpo: {printable}{extra}")
    for ch in chapters[:8]:
        pg = ch.get('first_page_idx', -1)
        pg_str = f" (pág PDF {pg+1})" if pg >= 0 else ''
        sk = ch.get('section_kind', 'chapter')
        print(f"    - [{sk}] {ch['title']}" + (f": {ch['subtitle'][:40]}" if ch.get('subtitle') else '') + pg_str)
    if len(chapters) > 8:
        print(f"    ... y {len(chapters)-8} más")

    return chapters, page_to_chapter



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




def _build_sequential_page_para_ranges(chapters: list[dict], pages_paragraphs: list[list[str]], page_to_chapter: list[int]) -> dict[tuple[int, int], tuple[int, int]]:
    """Mapea páginas a rangos de párrafos secuenciales dentro de cada capítulo.
    Evita que párrafos repetidos se asignen siempre a su primera aparición."""
    n_pages = len(pages_paragraphs)
    chapter_pages: dict[int, list[int]] = {}
    for pg_idx in range(n_pages):
        ch_idx = page_to_chapter[pg_idx] if pg_idx < len(page_to_chapter) else -1
        if ch_idx >= 0:
            chapter_pages.setdefault(ch_idx, []).append(pg_idx)

    ranges: dict[tuple[int, int], tuple[int, int]] = {}
    for ch_idx, page_indices in chapter_pages.items():
        chapter_paras = [p.strip() for p in chapters[ch_idx].get("paragraphs", []) if p and p.strip()]
        if not chapter_paras:
            continue

        positions_by_key: dict[str, list[int]] = {}
        for pos, para in enumerate(chapter_paras):
            positions_by_key.setdefault(para, []).append(pos)

        cursor = 0
        for pg_idx in page_indices:
            visible = [p.strip() for p in pages_paragraphs[pg_idx] if p and p.strip()]
            if not visible:
                continue

            matched_positions: list[int] = []
            local_cursor = cursor
            for para in visible:
                candidates = positions_by_key.get(para)
                if not candidates:
                    continue
                chosen = next((pos for pos in candidates if pos >= local_cursor), None)
                if chosen is None:
                    continue
                matched_positions.append(chosen)
                local_cursor = chosen + 1

            if matched_positions:
                start = matched_positions[0]
                end = matched_positions[-1] + 1
                ranges[(ch_idx, pg_idx)] = (start, end)
                cursor = max(cursor, end)

    return ranges


def _fragment_first_text(chapters: list[dict], item: dict) -> str:
    if item.get("type") != "chapter_fragment":
        return ""
    ch_idx = item.get("ch_idx", -1)
    if ch_idx < 0 or ch_idx >= len(chapters):
        return ""
    paras = chapters[ch_idx].get("paragraphs", [])
    start = max(0, int(item.get("start_idx", 0)))
    end = min(len(paras), int(item.get("end_idx", 0)))
    for para in paras[start:end]:
        key = (para or "").strip()
        if key:
            return key
    return ""


def _fragment_image_names(chapters: list[dict], item: dict) -> set[str]:
    if item.get("type") != "chapter_fragment":
        return set()
    ch_idx = item.get("ch_idx", -1)
    if ch_idx < 0 or ch_idx >= len(chapters):
        return set()
    start_idx = int(item.get("start_idx", 0))
    end_idx = int(item.get("end_idx", 0))
    names: set[str] = set()
    for img in chapters[ch_idx].get("inline_images", []):
        name = img.get("imgname", "")
        if not name:
            continue
        pos = int(img.get("after_para_idx", -1))
        if start_idx - 1 <= pos < end_idx:
            names.add(name)
    return names


def _normalize_spine_fragments(spine_items: list[dict], chapters: list[dict]) -> tuple[list[dict], list[str]]:
    normalized: list[dict] = []
    issues: list[str] = []
    last_end_by_chapter: dict[int, int] = {}
    prev_fragment: dict | None = None

    for item in spine_items:
        if item.get("type") != "chapter_fragment":
            normalized.append(item)
            prev_fragment = None
            continue

        cur = dict(item)
        ch_idx = int(cur.get("ch_idx", -1))
        start = int(cur.get("start_idx", 0))
        end = int(cur.get("end_idx", 0))

        last_end = last_end_by_chapter.get(ch_idx)
        if last_end is not None and start < last_end:
            issues.append(f"overlap_trim ch={ch_idx} {start}->{end} trimmed_to {last_end}->{end}")
            start = last_end
            cur["start_idx"] = start
        if end <= start:
            issues.append(f"empty_drop ch={ch_idx} {start}->{end}")
            continue

        if prev_fragment and prev_fragment.get("type") == "chapter_fragment" and prev_fragment.get("ch_idx") == ch_idx:
            prev_first = _fragment_first_text(chapters, prev_fragment)
            cur_first = _fragment_first_text(chapters, cur)
            if prev_first and cur_first and prev_first == cur_first:
                prev_end = int(prev_fragment.get("end_idx", 0))
                if start < prev_end:
                    start = prev_end
                    cur["start_idx"] = start
                    issues.append(f"same_start_trim ch={ch_idx} -> {start}->{end}")
            shared_images = _fragment_image_names(chapters, prev_fragment) & _fragment_image_names(chapters, cur)
            if shared_images:
                suppress = set(cur.get("suppress_images", []))
                suppress.update(shared_images)
                cur["suppress_images"] = sorted(suppress)
                issues.append(f"shared_images_suppressed ch={ch_idx} imgs={','.join(sorted(shared_images))}")
            if int(cur.get("end_idx", 0)) <= int(cur.get("start_idx", 0)):
                issues.append(f"post_check_drop ch={ch_idx} {cur.get('start_idx')}->{cur.get('end_idx')}")
                continue

        normalized.append(cur)
        last_end_by_chapter[ch_idx] = int(cur.get("end_idx", 0))
        prev_fragment = cur

    return normalized, issues


def _validate_spine_fragments(spine_items: list[dict], chapters: list[dict]) -> list[str]:
    issues: list[str] = []
    prev_fragment: dict | None = None
    for item in spine_items:
        if item.get("type") != "chapter_fragment":
            prev_fragment = None
            continue
        if prev_fragment and prev_fragment.get("type") == "chapter_fragment" and prev_fragment.get("ch_idx") == item.get("ch_idx"):
            if int(item.get("start_idx", 0)) < int(prev_fragment.get("end_idx", 0)):
                issues.append(f"overlap ch={item.get('ch_idx')} {prev_fragment.get('start_idx')}->{prev_fragment.get('end_idx')} with {item.get('start_idx')}->{item.get('end_idx')}")
            prev_first = _fragment_first_text(chapters, prev_fragment)
            cur_first = _fragment_first_text(chapters, item)
            if prev_first and cur_first and prev_first == cur_first:
                issues.append(f"same_start_text ch={item.get('ch_idx')} text={prev_first[:80]}")
            shared_images = _fragment_image_names(chapters, prev_fragment) & _fragment_image_names(chapters, item)
            shared_images -= set(item.get("suppress_images", []))
            if shared_images:
                issues.append(f"shared_images ch={item.get('ch_idx')} imgs={','.join(sorted(shared_images))}")
        prev_fragment = item
    return issues

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
