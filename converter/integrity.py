# -*- coding: utf-8 -*-
"""E02: comprobaciones conservadoras contra pérdida silenciosa de contenido.

No es un sustituto de EPUBCheck: revisa XHTML/XML, referencias internas y
cobertura de párrafos narrativos desde la entrada hasta el libro generado.
"""

from collections import Counter
from pathlib import PurePosixPath
import re
import zipfile
import xml.etree.ElementTree as ET


class ConversionIntegrityError(RuntimeError):
    """La conversión no debe declararse exitosa ni reemplazar archivos."""


def _canonical(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()


def check_cleaned_pages(raw_pages: list[str], pages_paragraphs: list[list[str]]) -> None:
    """Detecta páginas con prosa extensa que se vaciaron durante la limpieza."""
    if len(raw_pages) != len(pages_paragraphs):
        raise ConversionIntegrityError('La cantidad de páginas cambió durante la limpieza')
    lost_pages = []
    for idx, (raw, paras) in enumerate(zip(raw_pages, pages_paragraphs), 1):
        original_words = [w for w in re.findall(r'\b\w{2,}\b', raw, flags=re.UNICODE)
                          if any(ch.isalpha() for ch in w)]
        cleaned_words = [w for w in re.findall(r'\b\w{2,}\b', ' '.join(paras), flags=re.UNICODE)
                         if any(ch.isalpha() for ch in w)]
        # Sólo marcar pérdidas evidentes; encabezados y pies pequeños no bastan.
        if len(original_words) >= 25 and len(cleaned_words) < max(8, len(original_words) * 0.35):
            lost_pages.append((idx, len(original_words), len(cleaned_words)))
    if lost_pages:
        samples = ', '.join(f'{page} ({before}->{after} palabras)' for page, before, after in lost_pages[:6])
        raise ConversionIntegrityError(
            'La limpieza eliminó la mayor parte del texto de páginas PDF: '
            + samples + '. Se detuvo la conversión para evitar un EPUB incompleto.'
        )


def check_chapter_coverage(pages_paragraphs: list[list[str]], chapters: list[dict],
                           excluded_pages: list[int] | None = None) -> None:
    """Cada párrafo largo fuera del índice debe sobrevivir a detectar capítulos."""
    excluded = set(excluded_pages or [])
    expected: Counter = Counter()
    for idx, page in enumerate(pages_paragraphs):
        if idx in excluded:
            continue
        for para in page:
            key = _canonical(para)
            # Los títulos y subtítulos pueden convertirse en elementos h1/h2.
            if len(key.split()) >= 12 and len(key) >= 85:
                expected[key] += 1
    retained = Counter(_canonical(p) for ch in chapters for p in ch.get('paragraphs', []) if _canonical(p))
    missing = expected - retained
    if missing:
        examples = ', '.join(repr(t[:65]) for t in list(missing)[:3])
        raise ConversionIntegrityError(
            f'Se perdieron {sum(missing.values())} párrafo(s) durante la detección de capítulos: {examples}'
        )


def _internal_target(base: str, href: str) -> str:
    # XML/EPUB no permite enlaces a recursos ajenos como reemplazo del contenido.
    if not href or href.startswith(('/', '#')) or '://' in href:
        raise ConversionIntegrityError(f'Referencia interna EPUB inválida: {href!r}')
    parts = []
    for part in (base + '/' + href.split('#', 1)[0]).split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            if not parts:
                raise ConversionIntegrityError(f'Ruta fuera del EPUB: {href!r}')
            parts.pop()
        else:
            parts.append(part)
    return '/'.join(parts)


def validate_epub_archive(path: str, expected_paragraphs: list[str] | None = None) -> dict:
    """Verifica paquete ZIP, XHTML parseable, manifest/spine, enlaces y texto emitido."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            listed = set(names)
            if len(listed) != len(names):
                raise ConversionIntegrityError('EPUB contiene rutas duplicadas')
            if not names or names[0] != 'mimetype' or archive.read('mimetype') != b'application/epub+zip':
                raise ConversionIntegrityError('EPUB inválido: mimetype ausente o en orden incorrecto')
            if archive.getinfo('mimetype').compress_type != zipfile.ZIP_STORED:
                raise ConversionIntegrityError('EPUB inválido: mimetype debe almacenarse sin compresión')
            mandatory = {'META-INF/container.xml', 'OEBPS/content.opf', 'OEBPS/toc.ncx'}
            if not mandatory <= listed:
                raise ConversionIntegrityError('EPUB incompleto: faltan archivos obligatorios')
            roots = {}
            for name in names:
                if name.endswith(('.xhtml', '.opf', '.ncx', '.xml')):
                    try:
                        roots[name] = ET.fromstring(archive.read(name))
                    except ET.ParseError as exc:
                        raise ConversionIntegrityError(f'XML/XHTML inválido en {name}: {exc}') from exc
            pkg = roots['OEBPS/content.opf']
            ns = {'opf': 'http://www.idpf.org/2007/opf', 'x': 'http://www.w3.org/1999/xhtml'}
            manifest = {}
            for item in pkg.findall('./opf:manifest/opf:item', ns):
                item_id = item.attrib.get('id')
                target = _internal_target('OEBPS', item.attrib.get('href', ''))
                if not item_id or item_id in manifest or target not in listed:
                    raise ConversionIntegrityError(f'Ítem de manifest inválido: {item_id} -> {target}')
                manifest[item_id] = target
            spine_items = pkg.findall('./opf:spine/opf:itemref', ns)
            if not spine_items:
                raise ConversionIntegrityError('EPUB vacío: no hay documentos en el orden de lectura')
            spine = []
            for item in spine_items:
                item_id = item.attrib.get('idref')
                if item_id not in manifest:
                    raise ConversionIntegrityError(f'Spine referencia un archivo inexistente: {item_id}')
                spine.append(manifest[item_id])
            if not any(n.endswith('.xhtml') and not n.endswith('/Portada.xhtml') for n in spine):
                raise ConversionIntegrityError('EPUB vacío: sólo se generó la portada, sin capítulos o ilustraciones')
            for name, root in roots.items():
                if not name.endswith('.xhtml'):
                    continue
                for elt in root.iter():
                    if elt.tag in (f'{{{ns["x"]}}}img', f'{{{ns["x"]}}}link'):
                        attr = 'src' if elt.tag.endswith('}img') else 'href'
                        target = _internal_target(str(PurePosixPath(name).parent), elt.attrib.get(attr, ''))
                        if target not in listed:
                            raise ConversionIntegrityError(f'Recurso no encontrado desde {name}: {target}')
            nav = roots['OEBPS/toc.ncx']
            for elt in nav.iter():
                if elt.tag.endswith('}content') and 'src' in elt.attrib:
                    target = _internal_target('OEBPS', elt.attrib['src'])
                    if target not in listed:
                        raise ConversionIntegrityError(f'Entrada del índice apunta a archivo inexistente: {target}')
            # Contra pérdida de párrafos por fragmentación de capítulos.
            expected = Counter(_canonical(p) for p in (expected_paragraphs or []) if _canonical(p))
            emitted = Counter()
            for name in spine:
                if not name.endswith('.xhtml'):
                    continue
                for para in roots[name].findall('.//x:p', ns):
                    emitted[_canonical(''.join(para.itertext()))] += 1
            missing = expected - emitted
            if missing:
                sample = ', '.join(repr(x[:55]) for x in list(missing)[:3])
                raise ConversionIntegrityError(
                    f'EPUB sin {sum(missing.values())} párrafo(s) de los capítulos: {sample}'
                )
            return {'spine_documents': len(spine), 'text_paragraphs': sum(expected.values()),
                    'xhtml_documents': sum(name.endswith('.xhtml') for name in names)}
    except (zipfile.BadZipFile, EOFError, OSError) as exc:
        raise ConversionIntegrityError(f'No se pudo validar el EPUB generado: {exc}') from exc
