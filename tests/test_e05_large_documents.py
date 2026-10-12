# -*- coding: utf-8 -*-
"""E05: regresiones del procesamiento escalable y recursos ilustrados compartidos."""
import io
import contextlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import fitz
from PIL import Image, ImageDraw

from converter import pdf_extract
from converter.epub_writer import create_epub
from converter.integrity import validate_epub_archive


class E05LargeDocumentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def make_pdf(self, pages=4, repeat_image=False):
        pdf = fitz.open()
        img_bytes = None
        if repeat_image:
            img = Image.new('RGB', (360, 220), 'white')
            draw = ImageDraw.Draw(img)
            for y in range(220):
                draw.line((0, y, 360, y), fill=(y, 40, 220 - y))
            draw.rectangle((75, 60, 285, 160), fill=(230, 194, 70), outline='black', width=5)
            data = io.BytesIO()
            img.save(data, format='PNG')
            img_bytes = data.getvalue()
        for idx in range(pages):
            page = pdf.new_page()
            page.insert_text((65, 65), f'Capitulo {idx + 1}: Un mundo distinto', fontsize=16)
            for line in range(7):
                page.insert_text((65, 90 + 18 * line),
                    f'La historia de las montanas contiene aventuras profundas pagina {idx+1} linea {line+1}.',
                    fontsize=10)
            if img_bytes:
                page.insert_image(fitz.Rect(105, 330, 465, 550), stream=img_bytes)
        path = self.folder / 'largo.pdf'
        pdf.save(str(path))
        pdf.close()
        return path

    def test_page_count_and_text_kept_with_spooled_pdfminer(self):
        pdf = self.make_pdf(pages=32)
        pages, images = pdf_extract.extract_pdf_content(str(pdf))
        self.assertEqual(len(pages), 32)
        self.assertEqual(images, [])
        self.assertTrue(all(f'pagina {i+1}' in p for i, p in enumerate(pages)))

    def test_large_text_extraction_reports_batch_progress(self):
        pdf = self.make_pdf(pages=102)
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            pages, images = pdf_extract.extract_pdf_content(str(pdf))
        self.assertEqual(len(pages), 102)
        self.assertEqual(images, [])
        self.assertIn('Páginas analizadas: 100/102', log.getvalue())

    def test_cached_xref_keeps_context_specific_flags(self):
        doc = fitz.open()
        img = Image.new('RGB', (340, 210), (225, 140, 80))
        draw = ImageDraw.Draw(img)
        for i in range(15):
            draw.line((i*20, 0, 340-i*12, 210), fill=(40+i*12, 70+i*7, 190))
        bytes_io = io.BytesIO()
        img.save(bytes_io, format='PNG')
        page = doc.new_page()
        page.insert_text((40, 50), 'Capitulo 1')
        for row in range(8):
            page.insert_text((40, 75+row*20), f'En un camino lejano la historia describe hechos de la vida {row}.')
        xref = page.insert_image(fitz.Rect(100, 320, 450, 540), stream=bytes_io.getvalue())
        page = doc.new_page()
        page.insert_image(fitz.Rect(100, 320, 450, 540), xref=xref)
        path = self.folder / 'diferente_contexto.pdf'
        doc.save(path)
        doc.close()
        pages, images = pdf_extract.extract_pdf_content(str(path))
        self.assertEqual(len(images), 2)
        self.assertFalse(images[0]['is_full_page'])
        self.assertTrue(images[1]['is_full_page'])
        self.assertEqual(images[0]['data'], images[1]['data'])
        self.assertNotEqual(images[0]['caption'], images[1]['caption'])

    def test_pdfminer_partial_exception_does_not_duplicate_fallback_pages(self):
        pdf = self.make_pdf(pages=3)
        from pdfminer import high_level
        real = high_level.extract_pages
        def fail_halfway(*args, **kwargs):
            yield next(iter(real(*args, **kwargs)))
            raise RuntimeError('Fallo simulado de página')
        with mock.patch.object(high_level, 'extract_pages', side_effect=fail_halfway):
            pages, _ = pdf_extract.extract_pdf_content(str(pdf))
        self.assertEqual(len(pages), 3)
        self.assertIn('pagina 3', pages[2])

    def test_repeated_images_reuse_encoding_and_keep_page_bboxes(self):
        pdf = self.make_pdf(pages=4, repeat_image=True)
        with mock.patch.object(pdf_extract, '_encode_image_for_epub', wraps=pdf_extract._encode_image_for_epub) as encode:
            pages, images = pdf_extract.extract_pdf_content(str(pdf))
        self.assertEqual(len(images), 4)
        self.assertEqual(encode.call_count, 1, 'el xref repetido sólo debe recodificarse una vez')
        self.assertEqual([i['page_idx'] for i in images], list(range(4)))
        self.assertTrue(all(i['bbox'] for i in images))
        self.assertEqual(len({id(i['data']) for i in images}), 1)

    def test_epub_deduplicates_binary_but_preserves_all_appearances(self):
        pdf = self.make_pdf(pages=3, repeat_image=True)
        pages, images = pdf_extract.extract_pdf_content(str(pdf))
        self.assertEqual(len(images), 3)
        chapters = [{'title': 'Capitulo 1', 'subtitle': '',
                     'paragraphs': ['Texto de la historia para ilustraciones duplicadas.'],
                     'first_page_idx': 0}]
        path = self.folder / 'largo.epub'
        create_epub(chapters, {'title':'Libro grande', 'author':'Prueba', 'lang':'es', 'date':'2026'},
                    str(path), images=images, raw_pages=pages,
                    pages_paragraphs=[['Texto de la historia para ilustraciones duplicadas.']]+[[]]*2,
                    page_to_chapter=[0, 0, 0])
        self.assertTrue(path.exists())
        validate_epub_archive(str(path), ['Texto de la historia para ilustraciones duplicadas.'])
        with zipfile.ZipFile(path) as epub:
            media = [n for n in epub.namelist() if n.startswith('OEBPS/Images/img')]
            self.assertEqual(len(media), 1, media)
            xhtml = ''.join(epub.read(n).decode('utf-8') for n in epub.namelist()
                            if n.startswith('OEBPS/Text/') and n.endswith('.xhtml'))
            self.assertGreaterEqual(xhtml.count('src="../Images/' + media[0].split('/')[-1]), 3)
            self.assertEqual(len(epub.namelist()), len(set(epub.namelist())))
        self.assertEqual(images[1]['name'], 'img002.jpg', 'no mutar los registros originales')

    def test_ocr_uses_one_document_handle_for_multiple_pages(self):
        pdf = self.make_pdf(pages=3)
        with mock.patch.object(pdf_extract, 'configure_tesseract', return_value='/usr/bin/tesseract'), \
             mock.patch.object(pdf_extract.pytesseract, 'get_languages', return_value=['eng']), \
             mock.patch.object(pdf_extract, '_ocr_png_bytes', return_value='Capitulo de prueba'), \
             mock.patch('fitz.open', wraps=fitz.open) as opened:
            output, stats = pdf_extract.apply_ocr_to_pages(str(pdf), ['', '', ''],
                                                           {'ocr_mode': 'force', 'ocr_lang': 'eng', 'ocr_dpi': 80})
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(stats['pages_replaced'], 3)
        self.assertEqual(len(output), 3)

    def test_large_ocr_page_lowers_dpi_without_exceeding_pixel_limit(self):
        pdf = self.make_pdf(pages=1)
        import fitz as f
        with f.open(pdf) as doc:
            # Simula un límite reducido para comprobar el ajuste sin generar
            # un bitmap de 20 millones de píxeles en las pruebas.
            with mock.patch.object(pdf_extract, 'MAX_OCR_RENDER_PIXELS', 650000):
                buf = pdf_extract._render_page_to_png_bytes(str(pdf), 0, dpi=300, doc=doc)
                self.assertTrue(buf.startswith(b'\x89PNG'))
                self.assertFalse(doc.is_closed)

    def test_auto_ocr_warns_if_pdf_cannot_be_opened(self):
        with mock.patch.object(pdf_extract, 'configure_tesseract', return_value='tesseract'), \
             mock.patch.object(pdf_extract.pytesseract, 'get_languages', return_value=['eng']), \
             mock.patch('fitz.open', side_effect=RuntimeError('PDF cifrado')):
            pages, stats = pdf_extract.apply_ocr_to_pages('missing.pdf', [''],
                                                        {'ocr_mode': 'auto', 'ocr_lang': 'eng'})
        self.assertEqual(pages, [''])
        self.assertEqual(stats['pages_failed'], 1)
        self.assertTrue(any('no pudo abrir' in warn for warn in stats['warnings']))

    def test_ocr_rejects_page_bigger_than_limit_at_72dpi(self):
        pdf = self.make_pdf(pages=1)
        with fitz.open(pdf) as doc:
            with mock.patch.object(pdf_extract, 'MAX_OCR_RENDER_PIXELS', 100_000):
                with self.assertRaisesRegex(ValueError, 'demasiado grande'):
                    pdf_extract._render_page_to_png_bytes(str(pdf), 0, dpi=300, doc=doc)

    def test_nonrepeated_image_keeps_visual_filter_and_image_data(self):
        pdf = self.make_pdf(pages=1, repeat_image=True)
        _, images = pdf_extract.extract_pdf_content(str(pdf))
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]['media_type'], 'image/jpeg')
        self.assertTrue(images[0]['data'].startswith(b'\xff\xd8'))


if __name__ == '__main__':
    unittest.main()
