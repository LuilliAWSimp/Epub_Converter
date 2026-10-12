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
import json
import os
import re
import sys
import textwrap
import uuid
import zipfile
from collections import Counter
from pathlib import Path

from converter.pdf_extract import (
    DEFAULT_OCR_DPI,
    DEFAULT_OCR_GARBAGE_THRESHOLD,
    DEFAULT_OCR_LANG,
    DEFAULT_OCR_MIN_TEXT_CHARS,
    DEFAULT_OCR_MODE,
    _build_image_record,
    _extract_images_with_pymupdf,
    _extract_images_with_pypdf,
    _is_image_only_page,
    _ocr_png_bytes,
    _render_page_to_png_bytes,
    _should_ocr_page,
    apply_ocr_to_pages,
    configure_tesseract,
    extract_pdf_content,
    extract_pdf_text,
    get_base_dir,
    get_tesseract_cmd,
)
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
from converter.integrity import check_cleaned_pages, check_chapter_coverage
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

# E01: OCR y extracción de imágenes dependen únicamente de converter.pdf_extract.
# No redefinir estas funciones: sus versiones anteriores ocultaban los imports
# correctos (io/pytesseract) y provocaban pérdidas silenciosas de imágenes/OCR.






















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


def _decorative_image_hash(img: dict) -> str:
    return hashlib.sha1(img.get("data", b"")).hexdigest()


def _image_visual_hash_from_pil(pil_img, size: int = 8) -> str:
    """Hash perceptual muy simple para detectar adornos repetidos aunque cambie el nombre del recurso."""
    try:
        small = pil_img.convert("L").resize((size, size))
        pixels = list(small.getdata())
        avg = sum(pixels) / float(len(pixels) or 1)
        bits = ''.join('1' if px >= avg else '0' for px in pixels)
        return f"{int(bits, 2):0{(size * size) // 4}x}"
    except Exception:
        return ""


def _looks_like_decorative_motif_image(pil_img) -> tuple[bool, str]:
    """Detecta adornos extraídos como imágenes grandes con fondo uniforme.

    Algunos PDFs guardan las flores/marcos como un recurso rectangular grande:
    el bitmap contiene mucho fondo negro/blanco/transparente y apenas hojas en
    las esquinas o bordes. Si se inserta tal cual, el EPUB muestra un bloque
    fantasma entre párrafos. Esta prueba busca justamente ese patrón, pero evita
    eliminar ilustraciones reales comprobando que la zona central casi no tenga
    contenido visual.
    """
    try:
        from PIL import ImageStat
        import math

        rgb = pil_img.convert("RGB")
        w, h = rgb.size
        area = w * h
        if area <= 0:
            return True, "imagen_sin_area"

        # Miniaturas e iconos ya los manejan otras reglas. Esta heurística se
        # enfoca en recursos medianos/grandes que parecen fondos o marcos.
        if area < 30000:
            return False, ""

        # Trabajar en una versión pequeña mantiene la conversión rápida.
        max_side = 360
        scale = min(1.0, max_side / float(max(w, h)))
        if scale < 1.0:
            small = rgb.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        else:
            small = rgb

        sw, sh = small.size
        pix = small.load()
        total = sw * sh

        # Color de fondo estimado desde los bordes, que es donde los adornos
        # suelen dejar grandes zonas vacías. Se cuantiza para tolerar compresión.
        border = []
        for x in range(sw):
            border.append(pix[x, 0])
            border.append(pix[x, sh - 1])
        for y in range(sh):
            border.append(pix[0, y])
            border.append(pix[sw - 1, y])
        if not border:
            return False, ""

        def q(c):
            return tuple(int(round(v / 16.0) * 16) for v in c)

        from collections import Counter
        bg_q, bg_count = Counter(q(c) for c in border).most_common(1)[0]
        bg_ratio_border = bg_count / float(len(border))

        # Si los bordes no tienen un fondo dominante, no parece marco/adornos.
        if bg_ratio_border < 0.45:
            return False, ""

        def dist(c, b):
            return math.sqrt(sum((int(c[i]) - int(b[i])) ** 2 for i in range(3)))

        tolerance = 34.0
        bg_pixels = 0
        fg_pixels = 0
        center_fg = 0
        border_fg = 0
        minx = sw
        miny = sh
        maxx = -1
        maxy = -1

        cx0 = int(sw * 0.22)
        cx1 = int(sw * 0.78)
        cy0 = int(sh * 0.22)
        cy1 = int(sh * 0.78)
        bx0 = int(sw * 0.16)
        bx1 = int(sw * 0.84)
        by0 = int(sh * 0.16)
        by1 = int(sh * 0.84)

        for y in range(sh):
            for x in range(sw):
                c = pix[x, y]
                if dist(c, bg_q) <= tolerance:
                    bg_pixels += 1
                else:
                    fg_pixels += 1
                    minx = min(minx, x)
                    miny = min(miny, y)
                    maxx = max(maxx, x)
                    maxy = max(maxy, y)
                    if cx0 <= x <= cx1 and cy0 <= y <= cy1:
                        center_fg += 1
                    if x <= bx0 or x >= bx1 or y <= by0 or y >= by1:
                        border_fg += 1

        bg_ratio = bg_pixels / float(total)
        fg_ratio = fg_pixels / float(total)
        center_fg_ratio = center_fg / float(max(1, fg_pixels))
        border_fg_ratio = border_fg / float(max(1, fg_pixels))

        # Fondos casi negros o casi blancos son muy comunes en recursos decorativos.
        bg_luma = sum(bg_q) / 3.0
        is_blank_like_bg = bg_luma <= 35 or bg_luma >= 220 or bg_ratio >= 0.72

        if fg_pixels == 0:
            return True, "fondo_uniforme_sin_contenido"

        fg_bbox_area = ((maxx - minx + 1) * (maxy - miny + 1)) / float(total)

        # Patrón típico del fallo: bloque grande, fondo dominante, contenido visual
        # concentrado en esquinas/bordes, centro casi vacío.
        if (
            is_blank_like_bg
            and bg_ratio >= 0.58
            and fg_ratio <= 0.34
            and center_fg_ratio <= 0.18
            and border_fg_ratio >= 0.58
        ):
            return True, (
                "motivo_decorativo_fondo_uniforme:"
                f"bg={bg_ratio:.2f}:fg={fg_ratio:.2f}:center_fg={center_fg_ratio:.2f}:border_fg={border_fg_ratio:.2f}"
            )

        # Variante más estricta para marcos/florales de esquina: el foreground puede
        # tener bbox grande por ocupar esquinas opuestas, pero casi no toca el centro.
        if (
            is_blank_like_bg
            and bg_ratio >= 0.50
            and center_fg_ratio <= 0.08
            and border_fg_ratio >= 0.70
            and fg_bbox_area >= 0.20
        ):
            return True, (
                "marco_o_flores_en_bordes:"
                f"bg={bg_ratio:.2f}:center_fg={center_fg_ratio:.2f}:border_fg={border_fg_ratio:.2f}"
            )

        return False, ""
    except Exception:
        return False, ""


def _bbox_tuple(value) -> tuple[float, float, float, float] | None:
    if not value:
        return None
    try:
        x0, y0, x1, y1 = value
        return float(x0), float(y0), float(x1), float(y1)
    except Exception:
        return None


def _image_bbox_metrics(img: dict) -> dict:
    """Devuelve métricas normalizadas de la posición visual de la imagen en la página."""
    bbox = _bbox_tuple(img.get("bbox"))
    page_w = float(img.get("page_width") or 0)
    page_h = float(img.get("page_height") or 0)
    px_w = int(img.get("width") or 0)
    px_h = int(img.get("height") or 0)

    if bbox and page_w > 0 and page_h > 0:
        x0, y0, x1, y1 = bbox
        disp_w = max(0.0, x1 - x0)
        disp_h = max(0.0, y1 - y0)
        page_area = max(1.0, page_w * page_h)
        coverage = (disp_w * disp_h) / page_area
        rel = (x0 / page_w, y0 / page_h, x1 / page_w, y1 / page_h)
    else:
        disp_w = float(px_w)
        disp_h = float(px_h)
        coverage = 0.0
        rel = None

    return {
        "bbox": bbox,
        "page_w": page_w,
        "page_h": page_h,
        "pixel_w": px_w,
        "pixel_h": px_h,
        "display_w": disp_w,
        "display_h": disp_h,
        "coverage": coverage,
        "rel": rel,
    }


def _image_position_bucket(img: dict) -> str:
    metrics = _image_bbox_metrics(img)
    rel = metrics.get("rel")
    if not rel:
        return "unknown"

    x0, y0, x1, y1 = rel
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0

    near_left = x0 <= 0.12
    near_right = x1 >= 0.88
    near_top = y0 <= 0.12
    near_bottom = y1 >= 0.88

    if near_top and near_left:
        return "corner-top-left"
    if near_top and near_right:
        return "corner-top-right"
    if near_bottom and near_left:
        return "corner-bottom-left"
    if near_bottom and near_right:
        return "corner-bottom-right"
    if near_top:
        return "edge-top"
    if near_bottom:
        return "edge-bottom"
    if near_left:
        return "edge-left"
    if near_right:
        return "edge-right"
    if 0.25 <= cx <= 0.75 and 0.20 <= cy <= 0.80:
        return "center"
    return "body"


def _is_relevant_visual_candidate(img: dict) -> bool:
    """Protege ilustraciones reales: páginas completas, imágenes centrales grandes y mapas/figuras amplias."""
    metrics = _image_bbox_metrics(img)
    coverage = float(metrics.get("coverage") or 0.0)
    bucket = _image_position_bucket(img)
    px_w = int(metrics.get("pixel_w") or 0)
    px_h = int(metrics.get("pixel_h") or 0)

    if img.get("is_full_page"):
        return True
    if coverage >= 0.30:
        return True
    if bucket in {"center", "body"} and coverage >= 0.14:
        return True
    if bucket == "center" and min(px_w, px_h) >= 420 and coverage >= 0.08:
        return True
    return False


def _decorative_filter_reason(img: dict,
                              hash_counts,
                              visual_hash_counts,
                              position_hash_counts,
                              total_pages: int) -> str | None:
    """Heurística conservadora para descartar decoración sin eliminar ilustraciones reales."""
    if _is_relevant_visual_candidate(img):
        return None

    metrics = _image_bbox_metrics(img)
    bucket = _image_position_bucket(img)
    coverage = float(metrics.get("coverage") or 0.0)
    disp_w = float(metrics.get("display_w") or 0.0)
    disp_h = float(metrics.get("display_h") or 0.0)
    page_w = float(metrics.get("page_w") or 0.0)
    page_h = float(metrics.get("page_h") or 0.0)
    px_w = int(metrics.get("pixel_w") or 0)
    px_h = int(metrics.get("pixel_h") or 0)
    pixel_area = px_w * px_h

    h = img.get("_exact_hash") or _decorative_image_hash(img)
    vh = img.get("_visual_hash") or ""
    exact_repeats = hash_counts.get(h, 0)
    visual_repeats = visual_hash_counts.get(vh, 0) if vh else 0
    pos_repeats = position_hash_counts.get((vh, bucket), 0) if vh else 0

    # Umbrales de repetición: no hace falta que aparezca en todo el libro; adornos de
    # esquina suelen repetirse por secciones o muchas páginas consecutivas.
    repeat_threshold = max(3, min(8, int(max(total_pages, 1) * 0.06)))
    strong_repeat_threshold = max(5, min(12, int(max(total_pages, 1) * 0.12)))

    rel_w = disp_w / page_w if page_w else 0.0
    rel_h = disp_h / page_h if page_h else 0.0
    small_display = coverage > 0 and coverage <= 0.075
    medium_display = coverage > 0 and coverage <= 0.18
    thin_display = (rel_w > 0 and rel_w <= 0.075) or (rel_h > 0 and rel_h <= 0.075)
    border_bucket = bucket.startswith("edge-") or bucket.startswith("corner-")
    corner_bucket = bucket.startswith("corner-")

    # 1) Decoración repetida en la misma zona de la página.
    if border_bucket and medium_display and pos_repeats >= repeat_threshold:
        return f"repetida_en_borde:{bucket}:veces={pos_repeats}"

    # 2) Misma imagen repetida muchas veces y no central/grande.
    if (exact_repeats >= strong_repeat_threshold or visual_repeats >= strong_repeat_threshold) and coverage <= 0.22:
        return f"imagen_repetida_pequena:exact={exact_repeats}:visual={visual_repeats}"

    # 3) Adornos de esquina, aunque aparezcan una sola vez: flores, hojas, marcos parciales.
    if corner_bucket and medium_display:
        return f"adorno_de_esquina:{bucket}:coverage={coverage:.3f}"

    # 4) Separadores o filetes delgados en márgenes superiores/inferiores/laterales.
    if border_bucket and thin_display and coverage <= 0.16:
        return f"adorno_delgado_en_margen:{bucket}:rel={rel_w:.3f}x{rel_h:.3f}"

    # 5) Iconos/miniadornos muy pequeños, salvo que estén en zona central protegida.
    if border_bucket and (small_display or pixel_area <= 45000 or max(px_w, px_h) <= 260):
        return f"imagen_pequena_en_margen:{bucket}:px={px_w}x{px_h}:coverage={coverage:.3f}"

    # 6) Fondos/overlays decorativos repetidos sobre páginas con texto.
    # Si fuera una ilustración real, normalmente sería página completa sin texto y ya estaría protegida por is_full_page.
    if coverage >= 0.60 and not img.get("is_full_page") and (exact_repeats >= 2 or visual_repeats >= 2):
        return f"overlay_fondo_repetido:coverage={coverage:.3f}:veces={max(exact_repeats, visual_repeats)}"

    return None


def _filter_decorative_images(images: list[dict], total_pages: int) -> tuple[list[dict], list[dict]]:
    """
    Omite imágenes decorativas del diseño editorial sin eliminar ilustraciones reales.

    Criterios combinados:
    - repetición exacta/perceptual
    - posición en esquinas/márgenes
    - tamaño visual dentro de la página
    - protección de imágenes centrales, mapas e ilustraciones de página completa
    """
    from collections import Counter

    if not images:
        return images, []

    for img in images:
        img["_exact_hash"] = _decorative_image_hash(img)
        img.setdefault("_visual_hash", "")
        img["_position_bucket"] = _image_position_bucket(img)

    hash_counts = Counter(img.get("_exact_hash", "") for img in images)
    visual_hash_counts = Counter(img.get("_visual_hash", "") for img in images if img.get("_visual_hash"))
    position_hash_counts = Counter((img.get("_visual_hash", ""), img.get("_position_bucket", "unknown"))
                                   for img in images if img.get("_visual_hash"))

    decorative: list[dict] = []
    kept: list[dict] = []

    for img in images:
        reason = _decorative_filter_reason(img, hash_counts, visual_hash_counts, position_hash_counts, total_pages)
        if reason:
            img = dict(img)
            img["discard_reason"] = reason
            decorative.append(img)
        else:
            kept.append(img)

    return kept, decorative


def _format_image_bbox_for_log(img: dict) -> str:
    metrics = _image_bbox_metrics(img)
    bbox = metrics.get("bbox")
    if bbox:
        x0, y0, x1, y1 = bbox
        return f"bbox=({x0:.1f},{y0:.1f},{x1:.1f},{y1:.1f}) coverage={metrics.get('coverage', 0):.3f}"
    return "bbox=n/d coverage=n/d"


def _log_discarded_images(discarded_images: list[dict], max_lines: int = 120) -> None:
    if not discarded_images:
        return
    print(f"  [Imágenes] Decorativas/artefactos omitidos: {len(discarded_images)}")
    for img in discarded_images[:max_lines]:
        page = int(img.get("page_idx", -1)) + 1
        reason = img.get("discard_reason", "sin_motivo")
        bucket = img.get("_position_bucket") or _image_position_bucket(img)
        print(
            "    - "
            f"pág {page}: {img.get('name', 'sin_nombre')} "
            f"{img.get('width', '?')}x{img.get('height', '?')} "
            f"{_format_image_bbox_for_log(img)} pos={bucket} motivo={reason}"
        )
    if len(discarded_images) > max_lines:
        print(f"    ... y {len(discarded_images) - max_lines} descartes más")








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





# Compatibilidad con código que llame a extract_pdf_text directamente


# ─────────────────────────────────────────────
#  LIMPIEZA DE TEXTO
# ─────────────────────────────────────────────









# E03: detección de capítulos, TOC y auxiliares se importan exclusivamente
# de converter.chapters. Mantener una sola implementación para CLI y Flask.


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
    check_cleaned_pages(raw_pages, pages_paragraphs)
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

    check_chapter_coverage(pages_paragraphs, chapters, meta['excluded_pages'])

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
