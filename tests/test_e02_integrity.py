# -*- coding: utf-8 -*-
"""Regresiones E02: prosa preservada, XHTML/OPF y exportaciones atómicas."""
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from converter.text_utils import clean_text_per_page, detect_repeated_lines
from converter.chapters import detect_chapters
from converter.epub_writer import create_epub
from converter.integrity import (
    ConversionIntegrityError, check_cleaned_pages, check_chapter_coverage,
    validate_epub_archive,
)


class E02IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'salida.epub'
        self.meta = {'title': 'Texto & <imágenes>', 'author': 'Luz & Sol',
                     'publisher': 'La Editorial <Especial>', 'lang': 'es', 'date': '2026'}

    @staticmethod
    def _repeated_numbered_pages():
        return [
            ('Capitulo %d: Un misterio\n' % page)
            + '\n'.join(f'Este es el parrafo {n} de la pagina {page} y contiene un texto de ejemplo.'
                        for n in range(1, 9))
            for page in range(1, 6)
        ]

    def _simple_epub(self, paragraphs=None, title='Capítulo 1'):
        paras = paragraphs if paragraphs is not None else ['La noche empezó en calma.', 'Todo & todos estaban allí.']
        chapters = [{'title': title, 'subtitle': 'Amor & odio <3', 'paragraphs': paras,
                     'first_page_idx': 0}]
        raw = ['\n'.join(paras)]
        create_epub(chapters, self.meta, str(self.path), raw_pages=raw,
                    pages_paragraphs=[paras], page_to_chapter=[0])
        return self.path

    def test_repeated_numbers_do_not_become_headers(self):
        raw = self._repeated_numbered_pages()
        _, normalized = detect_repeated_lines(raw)
        self.assertNotIn('Este es el parrafo <PAGE_NUM> de la pagina <PAGE_NUM> y contiene un texto de ejemplo.', normalized)
        cleaned = clean_text_per_page(raw, {})
        self.assertEqual([len(pg) for pg in cleaned], [9] * 5)
        check_cleaned_pages(raw, cleaned)
        chapters, _ = detect_chapters('\n\n'.join(p for pg in cleaned for p in pg), {}, pages_paragraphs=cleaned)
        self.assertEqual(len(chapters), 5)
        self.assertEqual([len(ch['paragraphs']) for ch in chapters], [8] * 5)
        check_chapter_coverage(cleaned, chapters)

    def test_repeated_header_and_marginal_page_number_are_removed_only_on_edges(self):
        raw = []
        for n in range(1, 6):
            raw.append('EL GRAN VIAJE\n' + f'Página {n}\n'
                       + f'La casa número {n} tenía las ventanas abiertas durante aquella noche especial.\n'
                       + 'El pequeño viajero seguía la aventura.\n'
                       + f'Página {n}')
        cleaned = clean_text_per_page(raw, {})
        self.assertTrue(all('EL GRAN VIAJE' not in ' '.join(pg) for pg in cleaned))
        self.assertTrue(all('Página' not in ' '.join(pg) for pg in cleaned))
        self.assertTrue(all('número' in ' '.join(pg) for pg in cleaned))

    def test_repeated_sentence_in_middle_is_never_removed(self):
        raw = ['Capitulo 1\nTexto del encabezado %s\n' % i
               + 'Los viajeros observaban las luces de la ciudad aquella noche.\n'
               + 'Texto narrativo repetido.\n'
               + 'El tren llegó después del atardecer.'
               for i in range(1, 6)]
        cleaned = clean_text_per_page(raw, {})
        self.assertTrue(all('Texto narrativo repetido.' in ' '.join(x) for x in cleaned))

    def test_a_short_story_on_page_is_not_discarded(self):
        raw = ['Capitulo 1\nHola, mundo.\nFin.', 'Capitulo 2\nSí.\nHasta luego.']
        clean = clean_text_per_page(raw, {})
        chapters, _ = detect_chapters('\n\n'.join(p for pg in clean for p in pg), {}, pages_paragraphs=clean)
        self.assertEqual(len(chapters), 2)
        # El algoritmo actual puede interpretar la primera frase breve como subtítulo;
        # E03 abordará esa clasificación, E02 garantiza que NO se pierda.
        self.assertIn('Hola, mundo.', chapters[0]['subtitle'] + ' '.join(chapters[0]['paragraphs']))
        self.assertIn('Hasta luego.', chapters[1]['subtitle'] + ' '.join(chapters[1]['paragraphs']))

    def test_cleaning_massive_loss_is_explicit_error(self):
        raw = [' '.join(f'palabra{n}' for n in range(90))]
        with self.assertRaisesRegex(ConversionIntegrityError, 'limpieza eliminó'):
            check_cleaned_pages(raw, [[]])

    def test_chapter_detection_massive_loss_is_explicit_error(self):
        para = 'Esta frase permite comprobar si desaparece un párrafo significativo ' * 3
        with self.assertRaisesRegex(ConversionIntegrityError, 'detección de capítulos'):
            check_chapter_coverage([[para]], [{'title':'I', 'paragraphs':[]}])
        check_chapter_coverage([[para]], [], [0])  # TOC excluido de forma explícita

    def test_escaped_title_subtitle_metadata_and_paragraph(self):
        self._simple_epub(['Amor & odio < 3 y 5 > 2.', 'El barco cruzó el océano.'],
                          title='Capítulo 1: Amor & odio <prueba>')
        result = validate_epub_archive(str(self.path))
        self.assertEqual(result['spine_documents'], 2)
        with zipfile.ZipFile(self.path) as zf:
            chapter = zf.read('OEBPS/Text/001.xhtml').decode('utf-8')
            self.assertIn('Amor &amp; odio &lt;prueba&gt;', chapter)
            self.assertIn('Amor &amp; odio &lt;3', chapter)
            self.assertIn('La Editorial &lt;Especial&gt;', zf.read('OEBPS/content.opf').decode('utf-8'))

    def test_duplicate_paragraphs_are_not_silently_lost(self):
        para = 'Era una vez en una estación muy lejana.'
        self._simple_epub([para, para, para])
        with self.assertRaisesRegex(ConversionIntegrityError, 'párrafo'):
            validate_epub_archive(str(self.path), [para, para, para, para])
        result = validate_epub_archive(str(self.path), [para] * 3)
        self.assertEqual(result['text_paragraphs'], 3)

    def test_corrupt_xml_file_is_rejected(self):
        self._simple_epub()
        rewritten = self.path.parent / 'corrupto.epub'
        with zipfile.ZipFile(self.path) as source, zipfile.ZipFile(rewritten, 'w') as target:
            for name in source.namelist():
                payload = source.read(name)
                if name == 'OEBPS/Text/001.xhtml':
                    payload = payload.replace(b'</title>', b'</other>')
                target.writestr(name, payload, compress_type=source.getinfo(name).compress_type)
        with self.assertRaisesRegex(ConversionIntegrityError, 'XML/XHTML inválido'):
            validate_epub_archive(str(rewritten))

    def test_previous_export_stays_intact_if_new_one_invalid(self):
        self.path.write_bytes(b'PREVIOUS GOOD FILE')
        with self.assertRaisesRegex(ConversionIntegrityError, 'sólo se generó la portada'):
            create_epub([{'title':'Capítulo 1', 'paragraphs':[]}], self.meta, str(self.path),
                        raw_pages=['Capítulo 1'], pages_paragraphs=[['Capítulo 1']],
                        page_to_chapter=[0])
        self.assertEqual(self.path.read_bytes(), b'PREVIOUS GOOD FILE')
        self.assertEqual(list(self.path.parent.glob('.epub_e02_*')), [])

    def test_nonexistent_manifest_member_is_rejected(self):
        self._simple_epub()
        rewritten = self.path.parent / 'missing.epub'
        with zipfile.ZipFile(self.path) as source, zipfile.ZipFile(rewritten, 'w') as target:
            for name in source.namelist():
                if name == 'OEBPS/Styles/style.css':
                    continue
                target.writestr(name, source.read(name), compress_type=source.getinfo(name).compress_type)
        with self.assertRaisesRegex(ConversionIntegrityError, 'manifest inválido'):
            validate_epub_archive(str(rewritten))

    def test_full_conversion_with_pdf_reproducing_original_loss(self):
        import fitz
        from converter.pdf_extract import extract_pdf_content
        pdf = self.path.parent / 'repeticiones.pdf'
        document = fitz.open()
        for page_number in range(1, 6):
            page = document.new_page()
            page.insert_text((40, 40), f'Capitulo {page_number}: Un misterio', fontsize=11)
            for n in range(1, 9):
                page.insert_text((40, 60 + 25 * n),
                                 f'Este es el parrafo {n} de la pagina {page_number} y contiene un texto de ejemplo.',
                                 fontsize=9)
        document.save(str(pdf))
        document.close()
        raw_pages, images = extract_pdf_content(str(pdf))
        cleaned = clean_text_per_page(raw_pages, {})
        check_cleaned_pages(raw_pages, cleaned)
        chapters, mapping = detect_chapters('\n\n'.join(p for pg in cleaned for p in pg), {},
                                            pages_paragraphs=cleaned)
        check_chapter_coverage(cleaned, chapters)
        create_epub(chapters, self.meta, str(self.path), raw_pages=raw_pages,
                    pages_paragraphs=cleaned, page_to_chapter=mapping, images=images)
        expected = [p for ch in chapters for p in ch['paragraphs']]
        self.assertEqual(len(expected), 40)
        stats = validate_epub_archive(str(self.path), expected)
        self.assertEqual(stats['text_paragraphs'], 40)


if __name__ == '__main__':
    unittest.main()
