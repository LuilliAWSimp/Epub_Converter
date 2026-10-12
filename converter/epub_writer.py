#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helpers de escritura XHTML/EPUB para PDF -> EPUB Converter.

Extraído de pdf2epub.py sin cambios de comportamiento.
"""

import io
import os
import re
import tempfile
import uuid
import zipfile

from converter.chapters import (
    _build_sequential_page_para_ranges,
    _normalize_spine_fragments,
    _validate_spine_fragments,
)
from converter.image_filters import _flatten_image_for_mobile_compat
from converter.integrity import ConversionIntegrityError, validate_epub_archive


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
            f'  <img alt="ilustración" src="../Images/{escape_xml_attr(img["name"])}"/>\n'
            f'</div>{caption_html}'
        )
    return XHTML_IMAGE_SEQUENCE_TEMPLATE.format(lang=escape_xml_attr(lang), title=escape_xml(title), body="\n".join(body_parts))


def escape_xml(text: str) -> str:
    """Escapa caracteres especiales para XML/HTML."""
    text = str(text).replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def escape_xml_attr(text: str) -> str:
    """Como escape_xml, incluyendo comillas dentro de atributos XML."""
    return escape_xml(text).replace('"', '&quot;').replace("'", '&apos;')


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
        f'  <img alt="ilustración" src="../Images/{escape_xml_attr(imgname)}"/>\n'
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
    seen_occurrences: set[str] = set()
    for img in inline_images:
        imgname = img.get("imgname", "")
        # E05: el mismo JPEG puede representarse en páginas diferentes;
        # evitar sólo la inserción repetida de la MISMA ocurrencia.
        occurrence = img.get('occurrence_id', imgname)
        if not imgname or occurrence in seen_occurrences or imgname in suppress_images:
            continue
        pos = img.get("after_para_idx", -1)
        if pos < start_idx - 1 or pos >= end_idx:
            continue
        rebased = pos - start_idx
        img_copy = dict(img)
        img_copy["after_para_idx"] = rebased
        img_by_pos.setdefault(rebased, []).append(img_copy)
        seen_occurrences.add(occurrence)

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
        lang=escape_xml_attr(lang),
        title=escape_xml(f"{title}{': ' + subtitle if subtitle else ''}"),
        body=body_html,
    )


def build_opf(meta: dict, manifest_items: list[dict], spine_idrefs: list[str], book_id: str) -> str:
    """Genera el content.opf."""

    manifest_xml = "\n    ".join(
        f'<item id="{escape_xml_attr(item["id"])}" href="{escape_xml_attr(item["href"])}" media-type="{escape_xml_attr(item["media_type"])}"/>'
        for item in manifest_items
    )

    spine_xml = "\n    ".join(
        f'<itemref idref="{escape_xml_attr(idref)}"/>' for idref in spine_idrefs
    )

    cover_item = next((i for i in manifest_items if i["id"] == "cover-image"), None)
    cover_meta = f'\n    <meta name="cover" content="cover-image"/>' if cover_item else ""
    first_content_href = next((i['href'] for i in manifest_items
                               if i['id'] in spine_idrefs and i['id'] != 'Portada'), 'Text/Portada.xhtml')

    return f"""<?xml version="1.0" encoding="utf-8"?>
<package version="2.0" unique-identifier="BookId"
         xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{escape_xml(meta.get('title', 'Sin título'))}</dc:title>
    <dc:creator>{escape_xml(meta.get('author', 'Desconocido'))}</dc:creator>
    <dc:language>{escape_xml(meta.get('lang', 'es'))}</dc:language>
    <dc:publisher>{escape_xml(meta.get('publisher', ''))}</dc:publisher>
    <dc:identifier id="BookId" opf:scheme="UUID">urn:uuid:{book_id}</dc:identifier>
    <dc:date>{escape_xml(meta.get('date', '2026'))}</dc:date>{cover_meta}
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
    <reference type="text" title="Inicio" href="{escape_xml_attr(first_content_href)}"/>
  </guide>
</package>
"""


def build_ncx(meta: dict, nav_points: list[dict], book_id: str) -> str:
    """Genera el toc.ncx."""
    nav_xml_parts = []
    for i, point in enumerate(nav_points, 1):
        nav_xml_parts.append(f"""    <navPoint id="navPoint-{i}" playOrder="{i}">
      <navLabel><text>{escape_xml(point['label'])}</text></navLabel>
      <content src="{escape_xml_attr(point['src'])}"/>
    </navPoint>""")

    nav_xml = "\n".join(nav_xml_parts)

    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
  "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="{escape_xml_attr(meta.get('lang','es'))}">
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
    return XHTML_COVER_TEMPLATE.format(lang=escape_xml_attr(lang))


def build_image_page_xhtml(img: dict, lang: str, title: str) -> str:
    """Genera el XHTML para una página completa de imagen."""
    caption_html = ""
    if img.get("caption"):
        caption_html = f'\n<p class="centrado"><i>{escape_xml(img["caption"])}</i></p>'
    return XHTML_IMAGE_PAGE_TEMPLATE.format(
        lang=escape_xml_attr(lang),
        title=escape_xml(title),
        alt="ilustración",
        imgname=escape_xml_attr(img["name"]),
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


def _create_epub_unchecked(chapters: list[dict], meta: dict, output_path: str,
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
    # E05: una misma ilustración puede aparecer en varias páginas. Conservar
    # todas las ocurrencias y leyendas, pero apuntar al mismo JPEG del EPUB.
    # Hacer copia superficial de los registros para no mutar el lote de entrada.
    images = [dict(img) for img in (images or [])]
    from hashlib import sha256
    seen_bitmap: dict[tuple[str, str], list[dict]] = {}
    repeated_assets = 0
    for img in images:
        img['_occurrence_name'] = img['name']
        signature = (img['media_type'], sha256(img['data']).hexdigest())
        candidates = seen_bitmap.setdefault(signature, [])
        original = next((candidate for candidate in candidates
                         if candidate['data'] == img['data']), None)
        if original is not None:
            img['name'] = original['name']
            repeated_assets += 1
        else:
            candidates.append(img)
    if repeated_assets:
        print(f'  [Imágenes E05] Recursos EPUB repetidos evitados: {repeated_assets}')
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
                "occurrence_id": iimg['_occurrence_name'],
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
                "occurrence_id": fimg['_occurrence_name'],
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
                lang=escape_xml_attr(lang), title="Portada",
                body=(f'<h1 class="titulo">{escape_xml(meta.get("title",""))}</h1>\n'
                      f'<h2 class="subtitulo">{escape_xml(meta.get("author",""))}</h2>'),
            ))

        written_images: set[str] = set()
        for img in images:
            if img['name'] not in written_images:
                zf.writestr(f"OEBPS/Images/{img['name']}", img['data'])
                written_images.add(img['name'])

        manifest_items: list[dict] = []
        spine_idrefs: list[str] = []

        manifest_items.append({"id": "Portada", "href": "Text/Portada.xhtml",
                               "media_type": "application/xhtml+xml"})
        spine_idrefs.append("Portada")

        if has_cover_img:
            manifest_items.append({"id": "cover-image", "href": "Images/cover.jpg",
                                   "media_type": "image/jpeg"})

        manifest_images: set[str] = set()
        for img in images:
            if img['name'] in manifest_images:
                continue
            manifest_images.add(img['name'])
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
                        lang=escape_xml_attr(lang),
                        title=escape_xml(title),
                        alt="ilustración",
                        imgname=escape_xml_attr(img["name"]),
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
                    build_image_sequence_xhtml(item["images"], lang=lang, title=title),
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



def create_epub(chapters: list[dict], meta: dict, output_path: str,
                cover_image_path: str | None = None,
                images: list[dict] | None = None,
                raw_pages: list[str] | None = None,
                pages_paragraphs: list[list[str]] | None = None,
                page_to_chapter: list | None = None) -> None:
    """Publica el EPUB únicamente tras validar el archivo temporal completo.

    Un fallo no sobreescribe una exportación anterior con un libro incompleto.
    """
    from xml.etree import ElementTree as ET

    output_path = os.path.abspath(output_path)
    destination = os.path.dirname(output_path)
    os.makedirs(destination, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.epub_e02_', suffix='.epub', dir=destination)
    os.close(fd)
    try:
        if not chapters and not images:
            raise ConversionIntegrityError('El PDF no contiene texto ni ilustraciones exportables')
        _create_epub_unchecked(chapters, meta, temporary, cover_image_path=cover_image_path,
                               images=images, raw_pages=raw_pages,
                               pages_paragraphs=pages_paragraphs,
                               page_to_chapter=page_to_chapter)
        # El motor convierte marcadores *cursiva* y **negrita** en nodos HTML.
        # Se compara el texto renderizado, no los asteriscos originales.
        expected_paragraphs = []
        for chapter in chapters:
            for paragraph in chapter.get('paragraphs', []):
                expected_paragraphs.append(''.join(ET.fromstring(para_to_html(paragraph)).itertext()))
        result = validate_epub_archive(temporary, expected_paragraphs)
        os.replace(temporary, output_path)
        print(f"  [Integridad E02] EPUB válido: {result['spine_documents']} documento(s) "
              f"en lectura, {result['text_paragraphs']} párrafo(s) verificados")
        print(f"\n  ✅ EPUB generado: {output_path}")
        print(f"     Tamaño: {os.path.getsize(output_path) / 1024:.1f} KB | "
              f"Capítulos: {len(chapters)} | Imágenes: {len(images or [])}")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

