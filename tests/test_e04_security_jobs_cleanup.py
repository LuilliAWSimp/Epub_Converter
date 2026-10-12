# -*- coding: utf-8 -*-
"""E04: acceso local, procesos aislados, limpieza y compatibilidad E01-E03."""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import fitz
from converter.integrity import validate_epub_archive
from converter.local_security import is_allowed_request

ROOT = Path(__file__).resolve().parents[1]


class E04SecurityTests(unittest.TestCase):
    def good(self, **overrides):
        kw = {
            'host': '127.0.0.1:7474', 'remote_addr': '127.0.0.1',
            'method': 'POST', 'requested_with': 'XMLHttpRequest',
            'origin': 'http://127.0.0.1:7474',
        }
        kw.update(overrides)
        return is_allowed_request(**kw)

    def test_local_requests_ok(self):
        self.assertTrue(self.good())
        self.assertTrue(self.good(host='localhost:7474', origin='http://localhost:7474', remote_addr='::1'))
        self.assertTrue(is_allowed_request('localhost:7474', '127.0.0.1', method='GET'))

    def test_reject_network_and_dns_rebinding(self):
        self.assertFalse(self.good(remote_addr='192.168.1.2'))
        self.assertFalse(self.good(host='evil.example:7474', origin='http://evil.example:7474'))
        self.assertFalse(self.good(host='localhost.evil.com:7474'))
        self.assertFalse(self.good(host='localhost@evil.example:7474'))

    def test_reject_cross_site_post_and_simple_form(self):
        self.assertFalse(self.good(origin='https://attacker.example'))
        self.assertFalse(self.good(origin='null'))
        self.assertFalse(self.good(origin='http://127.0.0.1:9999'))
        self.assertFalse(self.good(requested_with=None))
        self.assertFalse(self.good(fetch_site='cross-site'))
        self.assertFalse(self.good(origin=None, referer='https://attacker.example/evil'))


class FlaskStub:
    def __init__(self):
        self.config = {}

    def route(self, *_args, **_kw):
        return lambda f: f


class DummyUpload:
    filename = 'historia.pdf'

    def __init__(self):
        self.saves = []

    def save(self, path):
        self.saves.append(path)
        Path(path).write_bytes(b'%PDF-1.4\nStub input')


class E04GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_flask = types.ModuleType('flask')
        fake_flask.Flask = lambda *_args, **_kwargs: FlaskStub()
        fake_flask.jsonify = lambda value: value
        fake_flask.render_template_string = lambda x: x
        fake_flask.send_file = lambda *args, **kwargs: (args, kwargs)
        fake_flask.request = types.SimpleNamespace(files={}, form={})
        spec = importlib.util.spec_from_file_location('epub_e04_gui_stubbed', ROOT / 'gui.py')
        gui = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {'flask': fake_flask}):
            spec.loader.exec_module(gui)
        cls.gui = gui

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        self.folder = folder
        self.gui.JOBS_DIR = folder / 'jobs'
        self.gui.EXPORTS_DIR = folder / 'exports'
        self.gui.TEMP_DIR = folder / 'temp'
        for name in ('JOBS_DIR', 'EXPORTS_DIR', 'TEMP_DIR'):
            getattr(self.gui, name).mkdir()
        self.gui.JOBS = {}
        self.gui._last_cleanup = 0
        self.gui.request.files = {}
        self.gui.request.form = {}

    def test_http_ignores_client_executable_path_and_returns_opaque_token(self):
        upload = DummyUpload()
        self.gui.request.files = {'pdf': upload}
        self.gui.request.form = {'tesseract_cmd': '/tmp/attacker', 'ocr_mode': 'off'}
        with mock.patch.object(self.gui.threading, 'Thread') as thread:
            response = self.gui.convert()
        self.assertEqual(len(response['job_id']), 32)
        config = thread.call_args.kwargs['args'][3]
        self.assertEqual(config['tesseract_cmd'], '')
        thread.return_value.start.assert_called_once()
        self.assertEqual(len(upload.saves), 1)

    def test_limit_concurrent_jobs_and_reject_unsafe_cover(self):
        self.gui.JOBS = {'a': {'status': 'running'}, 'b': {'status': 'running'}}
        self.gui.request.files = {'pdf': DummyUpload()}
        response = self.gui.convert()
        self.assertEqual(response[1], 429)
        self.gui.JOBS = {}
        self.gui.request.files['cover'] = types.SimpleNamespace(filename='evil.exe')
        response = self.gui.convert()
        self.assertEqual(response[1], 400)

    def test_status_never_exposes_server_paths(self):
        self.gui.JOBS['token'] = {'status': 'done', 'log': 'listo',
                                  'output_path': '/secreto/epub.epub', 'job_dir': '/secreto',
                                  'filename': 'libro.epub', 'size_kb': 10}
        res = self.gui.status('token')
        self.assertNotIn('output_path', res)
        self.assertNotIn('job_dir', res)
        self.assertEqual(res['filename'], 'libro.epub')

    def test_pruning_keeps_active_jobs_and_removes_stale_data(self):
        now = time.time()
        active = self.gui.JOBS_DIR / 'active'
        stale = self.gui.JOBS_DIR / 'stale'
        active.mkdir()
        stale.mkdir()
        recent = self.gui.EXPORTS_DIR / 'nuevo.epub'
        old = self.gui.EXPORTS_DIR / 'viejo.epub'
        recent.write_bytes(b'NEW')
        old.write_bytes(b'OLD')
        for path in (active, stale, old):
            os.utime(path, (now - 9 * 86400, now - 9 * 86400))
        self.gui.JOBS = {'active': {'status': 'running', 'job_dir': str(active), 'created_at': now},
                         'old': {'status': 'done', 'created_at': now - 9 * 86400}}
        self.gui.prune_storage(force=True, now=now)
        self.assertTrue(active.exists())
        self.assertFalse(stale.exists())
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertNotIn('old', self.gui.JOBS)

    def test_two_simultaneous_jobs_keep_independent_logs_and_epubs(self):
        """Dos subprocesos reales, sin recargar módulos ni modificar sys.stdout."""
        pdf_path = self.folder / 'entrada.pdf'
        pdf = fitz.open()
        for chapter in (1, 2):
            page = pdf.new_page()
            page.insert_text((45, 45), f'Capitulo {chapter}', fontsize=16)
            for n in range(1, 9):
                page.insert_text((45, 65 + 24*n),
                                 f'Esta pagina del relato incluye informacion especial sobre viaje {n}.', fontsize=10)
        pdf.save(str(pdf_path))
        pdf.close()

        config = {'title': 'Historia compartida', 'author': 'Prueba', 'lang': 'es',
                  'date': '2026', 'ocr_mode': 'off', 'ocr_lang': 'spa', 'verbose': False}
        before = sys.stdout
        threads = []
        for index in (1, 2):
            name = str(index)
            folder = self.gui.JOBS_DIR / name
            folder.mkdir()
            input_pdf = folder / 'entrada.pdf'
            input_pdf.write_bytes(pdf_path.read_bytes())
            self.gui.JOBS[name] = {'status': 'running', 'log': '', 'job_dir': str(folder)}
            unique_config = dict(config, title=f'Historia {index}')
            thread = threading.Thread(target=self.gui._run_conversion,
                                      args=(name, input_pdf, None, unique_config, folder))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join(timeout=45)
            self.assertFalse(thread.is_alive(), 'Un proceso hijo quedó bloqueado')
        self.assertIs(sys.stdout, before)
        for name in ('1', '2'):
            job = self.gui.JOBS[name]
            self.assertEqual(job['status'], 'done', job.get('error', job.get('log', '')[-500:]))
            self.assertIn(f'Historia {name}', job['log'])
            self.assertNotIn(f'Historia {3-int(name)}', job['log'])
            self.assertFalse((self.gui.JOBS_DIR / name).exists())
            with zipfile.ZipFile(job['output_path']) as epub:
                self.assertIn('OEBPS/content.opf', epub.namelist())
            validate_epub_archive(job['output_path'])
            with zipfile.ZipFile(job['output_path']) as book:
                chapter_files = [n for n in book.namelist() if n.startswith('OEBPS/Text/') and n.endswith('.xhtml') and not n.endswith('Portada.xhtml')]
                paragraphs = sum(len(ET.fromstring(book.read(n)).findall('.//{http://www.w3.org/1999/xhtml}p')) for n in chapter_files)
            self.assertGreaterEqual(paragraphs, 16)

    def test_frontend_posts_include_csrf_protection_header(self):
        self.assertIn("headers: { 'X-Requested-With': 'XMLHttpRequest' }", self.gui.HTML)
        self.assertIn('escHtml(file.name)', self.gui.HTML)


if __name__ == '__main__':
    unittest.main()
