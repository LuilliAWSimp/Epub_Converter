# -*- coding: utf-8 -*-
"""Regresiones E01: imágenes incrustadas y OCR desde la API pública del motor.

Ejecución desde la raíz: python -m unittest discover -s tests -v
"""
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import fitz
from PIL import Image, ImageDraw, ImageFont

import pdf2epub as engine
from converter import pdf_extract


class E01ExtractionOCRTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def _illustrated_pdf(self):
        # Imagen con colores y detalles: no se considera un adorno uniforme.
        image = Image.new('RGB', (420, 240), 'white')
        draw = ImageDraw.Draw(image)
        for y in range(240):
            draw.line((0, y, 420, y), fill=(y, 80, 255-y))
        draw.ellipse((100, 45, 300, 195), fill=(250, 220, 60), outline='black', width=4)
        buf = io.BytesIO()
        image.save(buf, format='PNG')
        pdf_path = self.folder / 'ilustrado.pdf'
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((65, 90), 'CAPITULO 1. Una ilustracion de prueba en el libro', fontsize=13)
        page.insert_text((65, 120), 'Habia una vez una escena llena de colores y detalles.', fontsize=11)
        page.insert_image(fitz.Rect(65, 180, 485, 420), stream=buf.getvalue())
        doc.save(str(pdf_path))
        doc.close()
        return pdf_path

    def _scanned_pdf(self):
        image = Image.new('RGB', (900, 250), 'white')
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype('DejaVuSans.ttf', 43)
        except OSError:
            font = ImageFont.load_default()
        draw.text((25, 70), 'SCANNED BOOK PAGE', font=font, fill='black')
        image = image.resize((1800, 500))
        buf = io.BytesIO()
        image.save(buf, format='PNG')
        pdf_path = self.folder / 'escaneado.pdf'
        doc = fitz.open()
        page = doc.new_page(width=612, height=340)
        page.insert_image(page.rect, stream=buf.getvalue())
        doc.save(str(pdf_path))
        doc.close()
        return pdf_path

    def test_cli_and_gui_reference_single_extractor(self):
        self.assertIs(engine.extract_pdf_content, pdf_extract.extract_pdf_content)
        self.assertIs(engine.apply_ocr_to_pages, pdf_extract.apply_ocr_to_pages)

    def test_illustration_is_included_in_epub(self):
        pdf_path = self._illustrated_pdf()
        raw_pages, images = engine.extract_pdf_content(str(pdf_path))
        self.assertEqual(len(raw_pages), 1)
        self.assertGreaterEqual(len(images), 1)
        self.assertTrue(images[0]['data'].startswith(b'\xff\xd8'))
        output_path = self.folder / 'ilustrado.epub'
        chapters = [{'title': 'Capitulo 1', 'subtitle': '',
                     'paragraphs': ['Esta es una prueba de ilustraciones.'], 'first_page_idx': 0}]
        engine.create_epub(chapters,
                           {'title':'Libro ilustrado', 'author':'Prueba', 'lang':'es', 'date':'2026'},
                           str(output_path), images=images, raw_pages=raw_pages,
                           pages_paragraphs=[['Esta es una prueba de ilustraciones.']],
                           page_to_chapter=[0])
        with zipfile.ZipFile(output_path) as epub:
            image_files = [n for n in epub.namelist() if n.startswith('OEBPS/Images/img')]
            self.assertTrue(image_files, 'EPUB debe conservar ilustraciones reales')
            xhtml = '\n'.join(epub.read(n).decode('utf-8') for n in epub.namelist()
                              if n.endswith('.xhtml'))
            self.assertIn(images[0]['name'], xhtml)

    def test_ocr_off_does_not_invoke_engine(self):
        with mock.patch.object(pdf_extract, 'configure_tesseract') as engine_mock:
            pages, stats = engine.apply_ocr_to_pages('unused.pdf', ['Hola'], {'ocr_mode':'off'})
        engine_mock.assert_not_called()
        self.assertEqual(pages, ['Hola'])
        self.assertEqual(stats['pages_replaced'], 0)

    def test_force_reports_tesseract_failure_instead_of_claiming_success(self):
        with mock.patch.object(pdf_extract, 'configure_tesseract', side_effect=RuntimeError('no está instalado')):
            with self.assertRaisesRegex(RuntimeError, 'OCR no disponible'):
                engine.apply_ocr_to_pages('unused.pdf', [''], {'ocr_mode':'force'})

    def test_auto_preserves_text_and_warns_when_ocr_is_unavailable(self):
        with mock.patch.object(pdf_extract, 'configure_tesseract', side_effect=RuntimeError('no está instalado')):
            pages, stats = engine.apply_ocr_to_pages('unused.pdf', ['poco texto'], {'ocr_mode':'auto'})
        self.assertEqual(pages, ['poco texto'])
        self.assertGreaterEqual(stats['pages_failed'], 1)
        self.assertTrue(stats['warnings'])

    def test_missing_language_in_force_mode_is_an_explicit_error(self):
        with mock.patch.object(pdf_extract.pytesseract, 'get_languages', return_value=['eng']):
            with mock.patch.object(pdf_extract, 'configure_tesseract', return_value='fake'):
                with self.assertRaisesRegex(RuntimeError, 'Faltan idiomas OCR'):
                    engine.apply_ocr_to_pages('unused.pdf', [''], {'ocr_mode':'force', 'ocr_lang':'spa+eng'})

    def test_live_tesseract_scanned_pdf_if_installed(self):
        try:
            pdf_extract.get_tesseract_cmd()
        except RuntimeError:
            self.skipTest('Requiere Tesseract real con paquete eng')
        path = self._scanned_pdf()
        raw_pages, _ = engine.extract_pdf_content(str(path))
        self.assertFalse('SCANNED' in ''.join(raw_pages).upper())
        try:
            output, stats = engine.apply_ocr_to_pages(str(path), raw_pages,
                                                      {'ocr_mode':'force', 'ocr_lang':'eng', 'ocr_dpi':150})
        except RuntimeError as exc:
            if 'Faltan idiomas OCR' in str(exc):
                self.skipTest(str(exc))
            raise
        self.assertEqual(stats['pages_replaced'], 1)
        self.assertIn('SCANNED', output[0].upper())


if __name__ == '__main__':
    unittest.main()
