# -*- coding: utf-8 -*-
"""E03: controles OCR enviados desde interfaz y capítulos sin pérdida narrativa."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import pdf2epub as engine
from converter import chapters
from converter.integrity import check_chapter_coverage

ROOT = Path(__file__).resolve().parents[1]


class E03ChapterTests(unittest.TestCase):
    def make_chapters(self, pages):
        config = {}
        output, mapping = engine.detect_chapters(
            '\n\n'.join(paragraph for page in pages for paragraph in page),
            config, pages_paragraphs=pages,
        )
        check_chapter_coverage(pages, output, config['_excluded_pages'])
        return output, mapping, config

    def test_engine_uses_single_module_not_duplicate_chapter_logic(self):
        self.assertIs(engine.detect_chapters, chapters.detect_chapters)
        self.assertIs(engine._detect_page_heading, chapters._detect_page_heading)

    def test_narrative_mentioning_contenido_is_not_omitted_as_toc(self):
        pages = [
            ['Capítulo 1', 'El contenido de la carta era completamente falso.',
             'El contenido no coincidía con lo prometido.'],
            ['El contenido del sobre parecía una broma cruel.',
             'La mujer se volvió hacia la puerta.'],
        ]
        items, mapping, config = self.make_chapters(pages)
        self.assertEqual(config['_excluded_pages'], [])
        self.assertEqual(len(items), 1)
        self.assertEqual(mapping, [0, 0])
        self.assertEqual(len(items[0]['paragraphs']), 4)

    def test_explicit_index_excluded_and_chapters_kept(self):
        pages = [
            ['Índice', 'Capítulo 1 .... 2', 'Capítulo 2 .... 3'],
            ['Capítulo 1', 'La historia comienza aquí.'],
            ['Capítulo 2', 'La historia termina aquí.'],
        ]
        items, mapping, config = self.make_chapters(pages)
        self.assertEqual(config['_excluded_pages'], [0])
        self.assertEqual(mapping, [-1, 0, 1])
        self.assertEqual([i['title'] for i in items], ['Capítulo 1', 'Capítulo 2'])

    def test_real_subtitle_and_roman_numerals(self):
        pages = [
            ['Capítulo II', 'La Casa de la Niebla', 'El viento golpeaba las ventanas.'],
            ['Capítulo III: El desenlace.', 'Nadie esperaba aquella respuesta.'],
        ]
        items, _, _ = self.make_chapters(pages)
        self.assertEqual([item['title'] for item in items], ['Capítulo II', 'Capítulo III'])
        self.assertEqual(items[0]['subtitle'], 'La Casa de la Niebla')
        self.assertEqual(items[1]['subtitle'], 'El desenlace.')
        self.assertEqual(items[0]['paragraphs'], ['El viento golpeaba las ventanas.'])

    def test_narrative_sentence_is_not_eaten_as_subtitle(self):
        pages = [
            ['Capítulo 1', 'El Bosque se despertó de pronto.', 'Nadie quiso mirar atrás.'],
            ['Capítulo 2', 'Una Noche Diferente', 'El río se desbordó.'],
        ]
        items, _, _ = self.make_chapters(pages)
        self.assertEqual(items[0]['subtitle'], '')
        self.assertEqual(items[0]['paragraphs'][0], 'El Bosque se despertó de pronto.')
        self.assertEqual(items[1]['subtitle'], 'Una Noche Diferente')

    def test_leading_paragraphs_before_heading_stay_in_previous_chapter(self):
        pages = [
            ['Capítulo 1', 'Una Historia Extraña'],
            ['El viajero llegó muy tarde.', 'El cielo estaba oscuro.',
             'Capítulo 2', 'Dos Caminos', 'La mañana comenzó con lluvia.'],
        ]
        items, _, _ = self.make_chapters(pages)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['paragraphs'], ['El viajero llegó muy tarde.', 'El cielo estaba oscuro.'])
        self.assertEqual(items[1]['paragraphs'], ['La mañana comenzó con lluvia.'])

    def test_numbered_heading_with_title_and_not_a_sentence(self):
        self.assertEqual(chapters._detect_page_heading(['2. La Casa Perdida'])['title'], 'Capítulo 2')
        self.assertIsNone(chapters._detect_page_heading(['2. La Casa se desmoronó.']))


class FakeFlaskApp:
    def __init__(self):
        self.config = {}

    def route(self, *_args, **_kwargs):
        return lambda func: func


class FakePDF:
    filename = 'prueba.pdf'

    def __init__(self):
        self.saved = False

    def save(self, path):
        self.saved = True
        Path(path).write_bytes(b'%PDF-1.4\nFake test input')


class E03GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Flask no es obligatorio para el motor. Este stub comprueba la ruta
        # POST sin levantar el servidor; las pruebas reales de Flask se harán
        # en Windows con requirements.txt instalado.
        fake_flask = types.ModuleType('flask')
        fake_flask.Flask = lambda *_args, **_kwargs: FakeFlaskApp()
        fake_flask.jsonify = lambda payload: payload
        fake_flask.render_template_string = lambda payload: payload
        fake_flask.send_file = lambda *_args, **_kwargs: None
        fake_flask.request = types.SimpleNamespace(files={}, form={})
        spec = importlib.util.spec_from_file_location('epub_e03_gui_isolated', ROOT / 'gui.py')
        gui = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {'flask': fake_flask}):
            spec.loader.exec_module(gui)
        cls.gui = gui

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gui.JOBS_DIR = Path(self.tmp.name)
        self.gui.JOBS = {}

    def call_convert(self, mode, lang):
        fake_pdf = FakePDF()
        self.gui.request.files = {'pdf': fake_pdf}
        self.gui.request.form = {'ocr_mode': mode, 'ocr_lang': lang}
        with mock.patch.object(self.gui.threading, 'Thread') as thread_mock:
            response = self.gui.convert()
        return response, fake_pdf, thread_mock

    def test_post_forwards_mode_off_and_eng_into_job_config(self):
        response, pdf, thread = self.call_convert('off', 'eng')
        self.assertTrue(pdf.saved)
        self.assertIn('job_id', response)
        config = thread.call_args.kwargs['args'][3]
        self.assertEqual(config['ocr_mode'], 'off')
        self.assertEqual(config['ocr_lang'], 'eng')
        thread.return_value.start.assert_called_once()

    def test_post_forwards_force_and_spa_eng_into_job_config(self):
        response, pdf, thread = self.call_convert('force', 'spa+eng')
        self.assertIn('job_id', response)
        self.assertEqual(thread.call_args.kwargs['args'][3]['ocr_mode'], 'force')
        self.assertEqual(thread.call_args.kwargs['args'][3]['ocr_lang'], 'spa+eng')

    def test_ocr_bad_mode_returns_400_before_saving(self):
        response, pdf, thread = self.call_convert('unknown', 'spa')
        self.assertEqual(response[1], 400)
        self.assertFalse(pdf.saved)
        thread.assert_not_called()

    def test_off_does_not_fail_for_unused_language_selection(self):
        response, pdf, thread = self.call_convert('off', 'no válido;')
        self.assertIn('job_id', response)
        self.assertEqual(thread.call_args.kwargs['args'][3]['ocr_lang'], 'spa+eng')

    def test_ocr_bad_languages_returns_400_before_saving(self):
        response, pdf, thread = self.call_convert('auto', 'spa;bad')
        self.assertEqual(response[1], 400)
        self.assertFalse(pdf.saved)
        thread.assert_not_called()

    def test_js_contains_connected_form_fields(self):
        self.assertIn("fd.append('ocr_mode', document.getElementById('f-ocr-mode').value)", self.gui.HTML)
        self.assertIn("fd.append('ocr_lang', document.getElementById('f-ocr-lang').value.trim())", self.gui.HTML)

    @unittest.skipUnless(shutil.which('node'), 'Node.js no disponible para ejecutar JavaScript')
    def test_real_frontend_js_submits_selected_modes(self):
        """Ejecuta startConversion con DOM simulado y captura el FormData real."""
        script = self.gui.HTML.split('<script>', 1)[1].split('</script>', 1)[0]
        start = script.index('async function startConversion() {')
        end = script.index('async function pollStatus()', start)
        function_code = script[start:end]
        node_script = r'''
const vm=require('node:vm');
const fn=JSON.parse(process.argv[1]);
const captured={};
const values={
 'f-title':{value:'El libro'},'f-author':{value:'Autor'},'f-lang':{value:'es'},
 'f-ocr-mode':{value:'force'},'f-ocr-lang':{value:'  spa+eng  '},
 'f-verbose':{checked:false}
};
const sandbox={
 pdfFile:{name:'prueba.pdf'}, coverFile:null,
 btnConvert:{disabled:false,textContent:''},
 progressPanel:{classList:{add(){}}}, progressBar:{classList:{add(){}}},
 logBox:{innerHTML:''},resetResult(){},showError(e){throw e;},
 document:{getElementById:(id)=>values[id]},
 FormData:class {append(k,v){captured[k]=v;}},
 fetch:async (url,payload)=>{Object.assign(captured,payload.body); return {json:async()=>({job_id:'test-id'})}},
 setInterval:()=>1,pollStatus:()=>{},
};
vm.runInNewContext(fn+';startConversion()',sandbox);
setImmediate(()=>{process.stdout.write(JSON.stringify(captured))});
'''
        outcome = subprocess.run(
            ['node', '-e', node_script, json.dumps(function_code)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(outcome.returncode, 0, outcome.stderr)
        sent = json.loads(outcome.stdout)
        self.assertEqual(sent['ocr_mode'], 'force')
        self.assertEqual(sent['ocr_lang'], 'spa+eng')
        self.assertEqual(sent['title'], 'El libro')


if __name__ == '__main__':
    unittest.main()
