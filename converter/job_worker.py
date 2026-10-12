# -*- coding: utf-8 -*-
"""E04: realiza UNA conversión dentro de un proceso separado del servidor web.

No escucha conexiones y no acepta rutas ni comandos proporcionados por el navegador.
El proceso padre crea el archivo de configuración y las rutas de trabajo.
"""
import json
import sys
import traceback
from pathlib import Path

import pdf2epub as p2e


def convert_document(pdf_path: Path, cover_path: Path | None, config: dict, output_path: Path) -> dict:
    print(f"\n{'=' * 55}")
    print("  PDF → EPUB Converter  |  Perfil: CoTE")
    print(f"{'=' * 55}")
    pdf_title, pdf_author = p2e.guess_title_author(str(pdf_path))
    meta = {
        'title': config['title'] or pdf_title or pdf_path.stem,
        'author': config['author'] or pdf_author or 'Desconocido',
        'publisher': config.get('publisher', ''),
        'lang': config['lang'],
        'date': config.get('date', '2026'),
    }
    print(f"  Título : {meta['title']}")
    print(f"  Autor  : {meta['author']}")
    print('▶ FASE 1 — Extrayendo texto e imágenes del PDF...')
    raw_pages, images = p2e.extract_pdf_content(str(pdf_path))
    print('\n▶ FASE 1.5 — Evaluando OCR...')
    raw_pages, ocr_stats = p2e.apply_ocr_to_pages(str(pdf_path), raw_pages, config)
    print('\n▶ FASE 2 — Limpiando texto...')
    pages_paragraphs = p2e.clean_text_per_page(raw_pages, config)
    p2e.check_cleaned_pages(raw_pages, pages_paragraphs)
    clean = '\n\n'.join(p for page in pages_paragraphs for p in page)
    print('\n▶ FASE 3 — Detectando capítulos...')
    chapters, page_to_chapter = p2e.detect_chapters(
        clean, config, pages_paragraphs=pages_paragraphs,
    )
    meta['excluded_pages'] = config.get('_excluded_pages', [])
    if not chapters:
        all_paras = [p for p in clean.split('\n\n') if p.strip()]
        chapters = [{'title': meta['title'], 'subtitle': '', 'paragraphs': all_paras,
                     'first_page_idx': 0}]
        page_to_chapter = [0] * len(raw_pages)
    p2e.check_chapter_coverage(pages_paragraphs, chapters, meta['excluded_pages'])
    p2e.detect_dialog_system(chapters)
    print('\n▶ FASE 4 — Generando EPUB...')
    cover = str(cover_path) if cover_path and cover_path.is_file() else None
    print(f"  Portada: {'manual' if cover else 'automática'}")
    p2e.create_epub(
        chapters, meta, str(output_path), cover_image_path=cover, images=images,
        raw_pages=raw_pages, pages_paragraphs=pages_paragraphs,
        page_to_chapter=page_to_chapter,
    )
    print('\n✅ Conversión validada correctamente')
    return {
        'title': meta['title'],
        'chapters': len(chapters),
        'images': len(images),
        'ocr_pages': int(ocr_stats.get('pages_replaced', 0)),
    }


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 5:
        print('Uso interno: job_worker PDF COVER CONFIG OUTPUT RESULT', file=sys.stderr)
        return 2
    pdf, cover, settings, output, result = (Path(arg) for arg in argv)
    try:
        config = json.loads(settings.read_text(encoding='utf-8'))
        # Nunca se interpreta una ruta a ejecutables proporcionada por la web.
        config['tesseract_cmd'] = ''
        stats = convert_document(pdf, cover if str(cover) != '-' else None, config, output)
        result.write_text(json.dumps({'ok': True, **stats}, ensure_ascii=False), encoding='utf-8')
        return 0
    except Exception as exc:
        message = f'{type(exc).__name__}: {exc}'
        print(f'\n❌ Error: {message}', flush=True)
        result.write_text(json.dumps({'ok': False, 'error': message}, ensure_ascii=False), encoding='utf-8')
        return 1


if __name__ == '__main__':
    sys.exit(main())
