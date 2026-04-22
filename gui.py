#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf2epub — Interfaz Web Local
Ejecutar: python3 gui.py
Luego abrir: http://localhost:7474
"""

import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request, send_file

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # 300 MB

APP_DATA_DIR = Path(__file__).parent / "gui_data"
JOBS_DIR = APP_DATA_DIR / "jobs"
EXPORTS_DIR = APP_DATA_DIR / "exports"
TEMP_DIR = APP_DATA_DIR / "temp"
for _dir in (APP_DATA_DIR, JOBS_DIR, EXPORTS_DIR, TEMP_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# Estado de trabajos activos {job_id: {status, log, output_path, ...}}
JOBS: dict[str, dict] = {}


def _sanitize_stem(value: str, default: str = "archivo") -> str:
    value = (value or "").strip()
    value = re.sub(r"[^\w\s\-áéíóúüñÁÉÍÓÚÜÑ]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or default


def _make_job_dir_name(filename: str | None) -> str:
    stem = _sanitize_stem(Path(filename or "libro.pdf").stem, default="libro")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    short_id = uuid.uuid4().hex[:6]
    return f"{timestamp}_{stem}_{short_id}"


def _unique_export_path(stem: str, suffix: str = ".epub") -> Path:
    safe_stem = _sanitize_stem(stem, default="libro")[:80]
    candidate = EXPORTS_DIR / f"{safe_stem}{suffix}"
    if not candidate.exists():
        return candidate
    idx = 2
    while True:
        candidate = EXPORTS_DIR / f"{safe_stem} ({idx}){suffix}"
        if not candidate.exists():
            return candidate
        idx += 1

# ─────────────────────────────────────────────
#  HTML / CSS / JS  — Una sola página
# ─────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>pdf2epub</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;1,400&family=DM+Mono:wght@300;400&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet"/>
<style>
  /* ── Variables ── */
  :root {
    --ink:     #0e0d0b;
    --paper:   #f5f0e8;
    --cream:   #ede7d9;
    --sepia:   #c8b89a;
    --accent:  #b5451b;
    --accent2: #2a5c45;
    --muted:   #7a6f62;
    --border:  #d4c9b8;
    --mono:    'DM Mono', monospace;
    --serif:   'Playfair Display', Georgia, serif;
    --sans:    'DM Sans', sans-serif;
  }

  /* ── Reset ── */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { font-size: 16px; scroll-behavior: smooth; }

  body {
    background: var(--paper);
    color: var(--ink);
    font-family: var(--sans);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  /* ── Grain overlay ── */
  body::before {
    content: '';
    position: fixed; inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E");
    pointer-events: none;
    z-index: 9999;
    opacity: .6;
  }

  /* ── Header ── */
  header {
    border-bottom: 2px solid var(--ink);
    padding: 1.4rem 2.5rem;
    display: flex;
    align-items: baseline;
    gap: 1.2rem;
    background: var(--ink);
    color: var(--paper);
  }
  header h1 {
    font-family: var(--serif);
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: -.01em;
  }
  header h1 em { color: var(--sepia); font-style: italic; }
  header span {
    font-family: var(--mono);
    font-size: .72rem;
    color: var(--sepia);
    letter-spacing: .1em;
    text-transform: uppercase;
    border: 1px solid var(--sepia);
    padding: .15rem .45rem;
    border-radius: 2px;
  }

  /* ── Layout ── */
  main {
    flex: 1;
    max-width: 860px;
    width: 100%;
    margin: 0 auto;
    padding: 2.5rem 2rem 4rem;
  }

  /* ── Sección ── */
  .section-label {
    font-family: var(--mono);
    font-size: .68rem;
    letter-spacing: .14em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: .6rem;
  }

  /* ── Drop zone PDF ── */
  #drop-pdf {
    border: 2px dashed var(--border);
    background: var(--cream);
    border-radius: 4px;
    padding: 3rem 2rem;
    text-align: center;
    cursor: pointer;
    transition: border-color .2s, background .2s;
    position: relative;
    margin-bottom: 2rem;
  }
  #drop-pdf:hover, #drop-pdf.dragover {
    border-color: var(--accent);
    background: #f9f3ea;
  }
  #drop-pdf.has-file {
    border-style: solid;
    border-color: var(--accent2);
    background: #edf4f0;
  }
  #drop-pdf input[type=file] {
    position: absolute; inset: 0;
    opacity: 0; cursor: pointer; width: 100%; height: 100%;
  }
  .drop-icon {
    font-size: 2.4rem;
    margin-bottom: .6rem;
    line-height: 1;
  }
  .drop-title {
    font-family: var(--serif);
    font-size: 1.2rem;
    color: var(--ink);
    margin-bottom: .3rem;
  }
  .drop-hint {
    font-size: .8rem;
    color: var(--muted);
    font-family: var(--mono);
  }
  #pdf-info {
    margin-top: .8rem;
    font-family: var(--mono);
    font-size: .78rem;
    color: var(--accent2);
    font-weight: 400;
  }
  #pdf-info .pages-badge {
    display: inline-block;
    background: var(--accent2);
    color: #fff;
    padding: .1rem .5rem;
    border-radius: 2px;
    margin-left: .5rem;
    font-size: .7rem;
  }

  /* ── Grid de campos ── */
  .fields-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.2rem 1.6rem;
    margin-bottom: 2rem;
  }
  @media (max-width: 600px) { .fields-grid { grid-template-columns: 1fr; } }

  .field { display: flex; flex-direction: column; gap: .3rem; }
  .field label {
    font-family: var(--mono);
    font-size: .7rem;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .field input[type=text], .field select {
    border: 1px solid var(--border);
    background: var(--cream);
    color: var(--ink);
    font-family: var(--sans);
    font-size: .9rem;
    padding: .55rem .75rem;
    border-radius: 3px;
    outline: none;
    transition: border-color .15s;
  }
  .field input[type=text]:focus, .field select:focus { border-color: var(--accent); }
  .field input[type=text]::placeholder { color: var(--sepia); font-size: .85rem; }

  /* ── Drop zone portada ── */
  #drop-cover {
    border: 1px dashed var(--border);
    background: var(--cream);
    border-radius: 3px;
    padding: .7rem;
    cursor: pointer;
    transition: border-color .2s;
    display: flex;
    align-items: center;
    gap: .7rem;
    position: relative;
    min-height: 52px;
  }
  #drop-cover:hover, #drop-cover.dragover { border-color: var(--accent); }
  #drop-cover.has-file { border-color: var(--accent2); border-style: solid; }
  #drop-cover input[type=file] {
    position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%;
  }
  #cover-thumb {
    width: 36px; height: 50px;
    object-fit: cover;
    border-radius: 2px;
    border: 1px solid var(--border);
    display: none;
    flex-shrink: 0;
  }
  #cover-thumb.visible { display: block; }
  .cover-placeholder {
    display: flex; flex-direction: column; gap: .15rem;
  }
  .cover-placeholder strong {
    font-size: .82rem; font-weight: 500;
  }
  .cover-placeholder small {
    font-family: var(--mono); font-size: .68rem; color: var(--muted);
  }

  /* ── Toggle verbose ── */
  .toggle-row {
    display: flex; align-items: center; gap: .7rem;
    margin-bottom: 2rem;
  }
  .toggle {
    position: relative; width: 40px; height: 22px; flex-shrink: 0;
  }
  .toggle input { opacity: 0; width: 0; height: 0; }
  .toggle-slider {
    position: absolute; inset: 0;
    background: var(--border);
    border-radius: 22px;
    cursor: pointer;
    transition: background .2s;
  }
  .toggle-slider::before {
    content: '';
    position: absolute;
    left: 3px; top: 3px;
    width: 16px; height: 16px;
    background: #fff;
    border-radius: 50%;
    transition: transform .2s;
    box-shadow: 0 1px 3px rgba(0,0,0,.2);
  }
  .toggle input:checked + .toggle-slider { background: var(--accent2); }
  .toggle input:checked + .toggle-slider::before { transform: translateX(18px); }
  .toggle-label { font-size: .85rem; color: var(--ink); }
  .toggle-label small { display: block; font-size: .75rem; color: var(--muted); font-family: var(--mono); }

  /* ── Separador ── */
  .divider {
    border: none; border-top: 1px solid var(--border);
    margin: 1.8rem 0;
  }

  /* ── Botón convertir ── */
  #btn-convert {
    width: 100%;
    padding: 1rem;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 3px;
    font-family: var(--serif);
    font-size: 1.1rem;
    font-style: italic;
    cursor: pointer;
    transition: background .2s, transform .1s;
    letter-spacing: .01em;
  }
  #btn-convert:hover:not(:disabled) { background: #9e3b17; }
  #btn-convert:active:not(:disabled) { transform: scale(.99); }
  #btn-convert:disabled { background: var(--border); color: var(--muted); cursor: not-allowed; }

  /* ── Panel de progreso ── */
  #progress-panel {
    margin-top: 2rem;
    display: none;
  }
  #progress-panel.visible { display: block; }

  .log-box {
    background: var(--ink);
    color: #c8d0b8;
    font-family: var(--mono);
    font-size: .75rem;
    line-height: 1.6;
    padding: 1rem 1.2rem;
    border-radius: 4px;
    min-height: 120px;
    max-height: 260px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-word;
    margin-bottom: 1rem;
  }
  .log-box .log-ok  { color: #7ec887; }
  .log-box .log-err { color: #e07070; }
  .log-box .log-dim { color: #6a7060; }

  /* ── Progress bar ── */
  .progress-bar-wrap {
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
    margin-bottom: 1rem;
  }
  .progress-bar-fill {
    height: 100%;
    background: var(--accent);
    border-radius: 2px;
    width: 0%;
    transition: width .4s ease;
  }
  .progress-bar-fill.indeterminate {
    animation: indeterminate 1.4s ease infinite;
    width: 40%;
  }
  @keyframes indeterminate {
    0%   { transform: translateX(-100%); }
    100% { transform: translateX(350%); }
  }

  /* ── Resultado ── */
  #result-panel {
    display: none;
    margin-top: 1.5rem;
    padding: 1.2rem 1.4rem;
    border-radius: 4px;
    border-left: 4px solid var(--accent2);
    background: #edf4f0;
  }
  #result-panel.visible { display: block; }
  #result-panel.error {
    border-color: var(--accent);
    background: #fdf0ed;
  }
  .result-title {
    font-family: var(--serif);
    font-size: 1.05rem;
    margin-bottom: .4rem;
  }
  .result-meta {
    font-family: var(--mono);
    font-size: .75rem;
    color: var(--muted);
    margin-bottom: .9rem;
  }
  #btn-download {
    display: inline-flex;
    align-items: center;
    gap: .45rem;
    padding: .55rem 1.1rem;
    background: var(--accent2);
    color: #fff;
    border: none;
    border-radius: 3px;
    font-size: .88rem;
    font-weight: 500;
    cursor: pointer;
    text-decoration: none;
    transition: background .2s;
  }
  #btn-download:hover { background: #1e4433; }

  /* ── Footer ── */
  footer {
    border-top: 1px solid var(--border);
    padding: .9rem 2.5rem;
    font-family: var(--mono);
    font-size: .68rem;
    color: var(--muted);
    display: flex;
    justify-content: space-between;
  }

  /* ── Animación de entrada ── */
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  main > * {
    animation: fadeUp .4s ease both;
  }
  main > *:nth-child(1) { animation-delay: .05s; }
  main > *:nth-child(2) { animation-delay: .12s; }
  main > *:nth-child(3) { animation-delay: .18s; }
  main > *:nth-child(4) { animation-delay: .24s; }
  main > *:nth-child(5) { animation-delay: .30s; }
</style>
</head>
<body>

<header>
  <h1>pdf<em>2</em>epub</h1>
  <span>v2 · Perfil Apotecaria</span>
</header>

<main>

  <!-- PDF Drop -->
  <div>
    <p class="section-label">Archivo PDF</p>
    <div id="drop-pdf">
      <input type="file" id="input-pdf" accept=".pdf"/>
      <div class="drop-icon">📄</div>
      <div class="drop-title">Arrastra el PDF aquí</div>
      <div class="drop-hint">o haz clic para seleccionar</div>
      <div id="pdf-info"></div>
    </div>
  </div>

  <!-- Campos -->
  <div>
    <p class="section-label">Metadatos</p>
    <div class="fields-grid">
      <div class="field">
        <label>Título</label>
        <input type="text" id="f-title" placeholder="Desde metadatos del PDF"/>
      </div>
      <div class="field">
        <label>Autor</label>
        <input type="text" id="f-author" placeholder="Desde metadatos del PDF"/>
      </div>
      <div class="field">
        <label>Portada (JPG / PNG)</label>
        <div id="drop-cover">
          <input type="file" id="input-cover" accept=".jpg,.jpeg,.png"/>
          <img id="cover-thumb" src="" alt="portada"/>
          <div class="cover-placeholder">
            <strong>Seleccionar imagen</strong>
            <small>Opcional — se genera una si no se especifica</small>
          </div>
        </div>
      </div>
      <div class="field">
        <label>Idioma</label>
        <input type="text" id="f-lang" value="es" placeholder="es, en, ja…"/>
      </div>
      <div class="field">
        <label>OCR</label>
        <select id="f-ocr-mode">
          <option value="off">Desactivado</option>
          <option value="auto" selected>Auto</option>
          <option value="force">Forzar en todas las páginas</option>
        </select>
      </div>
      <div class="field">
        <label>OCR idiomas (Tesseract)</label>
        <input type="text" id="f-ocr-lang" value="spa+eng" placeholder="spa+eng"/>
      </div>
    </div>
  </div>

  <!-- Verbose toggle -->
  <div class="toggle-row">
    <label class="toggle">
      <input type="checkbox" id="f-verbose"/>
      <span class="toggle-slider"></span>
    </label>
    <div class="toggle-label">
      Modo detallado
      <small>Muestra información extra durante la conversión</small>
    </div>
  </div>

  <hr class="divider"/>

  <!-- Botón -->
  <button id="btn-convert" disabled>Selecciona un PDF para comenzar</button>

  <!-- Progreso -->
  <div id="progress-panel">
    <div class="progress-bar-wrap">
      <div class="progress-bar-fill indeterminate" id="progress-bar"></div>
    </div>
    <div class="log-box" id="log-box"></div>
  </div>

  <!-- Resultado -->
  <div id="result-panel">
    <div class="result-title" id="result-title"></div>
    <div class="result-meta" id="result-meta"></div>
    <a id="btn-download" href="#" download>
      ⬇ Descargar EPUB
    </a>
  </div>

</main>

<footer>
  <span>pdf2epub · Perfil Apotecaria</span>
  <span id="ft-server">localhost:7474</span>
</footer>

<script>
// ── Estado ──
let pdfFile = null;
let coverFile = null;
let currentJobId = null;
let pollInterval = null;

// ── Elementos ──
const dropPdf    = document.getElementById('drop-pdf');
const inputPdf   = document.getElementById('input-pdf');
const pdfInfo    = document.getElementById('pdf-info');
const dropCover  = document.getElementById('drop-cover');
const inputCover = document.getElementById('input-cover');
const coverThumb = document.getElementById('cover-thumb');
const btnConvert = document.getElementById('btn-convert');
const progressPanel = document.getElementById('progress-panel');
const progressBar   = document.getElementById('progress-bar');
const logBox     = document.getElementById('log-box');
const resultPanel = document.getElementById('result-panel');
const resultTitle = document.getElementById('result-title');
const resultMeta  = document.getElementById('result-meta');
const btnDownload = document.getElementById('btn-download');

// ── Drag & drop PDF ──
['dragenter','dragover'].forEach(ev =>
  dropPdf.addEventListener(ev, e => { e.preventDefault(); dropPdf.classList.add('dragover'); }));
['dragleave','drop'].forEach(ev =>
  dropPdf.addEventListener(ev, e => { e.preventDefault(); dropPdf.classList.remove('dragover'); }));
dropPdf.addEventListener('drop', e => setPdf(e.dataTransfer.files[0]));
inputPdf.addEventListener('change', () => setPdf(inputPdf.files[0]));

function setPdf(file) {
  if (!file || !file.name.endsWith('.pdf')) return;
  pdfFile = file;
  dropPdf.classList.add('has-file');

  // Mostrar nombre + tamaño
  const mb = (file.size / 1024 / 1024).toFixed(1);
  pdfInfo.innerHTML = `📖 <strong>${file.name}</strong> — ${mb} MB<span class="pages-badge" id="pages-count">leyendo…</span>`;

  // Contar páginas y leer metadatos en el servidor
  const fd = new FormData();
  fd.append('pdf', file);
  fetch('/api/pagecount', { method: 'POST', body: fd })
    .then(r => r.json())
    .then(d => {
      const badge = document.getElementById('pages-count');
      if (badge) badge.textContent = d.pages ? `${d.pages} páginas` : '';

      // Pre-rellenar título y autor si los campos están vacíos
      const fTitle  = document.getElementById('f-title');
      const fAuthor = document.getElementById('f-author');
      if (d.title && !fTitle.value) {
        fTitle.value = d.title;
      } else if (!fTitle.value) {
        // fallback al nombre del archivo sin extensión
        fTitle.placeholder = file.name.replace(/\.pdf$/i, '');
      }
      if (d.author && !fAuthor.value) {
        fAuthor.value = d.author;
      }
    }).catch(() => {
      const badge = document.getElementById('pages-count');
      if (badge) badge.textContent = '';
      // fallback nombre de archivo
      const fTitle = document.getElementById('f-title');
      if (!fTitle.value) fTitle.placeholder = file.name.replace(/\.pdf$/i, '');
    });

  btnConvert.disabled = false;
  btnConvert.textContent = 'Convertir a EPUB';
  resetResult();
}

// ── Drag & drop portada ──
['dragenter','dragover'].forEach(ev =>
  dropCover.addEventListener(ev, e => { e.preventDefault(); dropCover.classList.add('dragover'); }));
['dragleave','drop'].forEach(ev =>
  dropCover.addEventListener(ev, e => { e.preventDefault(); dropCover.classList.remove('dragover'); }));
dropCover.addEventListener('drop', e => setCover(e.dataTransfer.files[0]));
inputCover.addEventListener('change', () => setCover(inputCover.files[0]));

function setCover(file) {
  if (!file) return;
  coverFile = file;
  dropCover.classList.add('has-file');
  const reader = new FileReader();
  reader.onload = e => {
    coverThumb.src = e.target.result;
    coverThumb.classList.add('visible');
  };
  reader.readAsDataURL(file);
}

// ── Convertir ──
btnConvert.addEventListener('click', startConversion);

async function startConversion() {
  if (!pdfFile) return;

  btnConvert.disabled = true;
  btnConvert.textContent = 'Convirtiendo…';
  progressPanel.classList.add('visible');
  progressBar.classList.add('indeterminate');
  logBox.innerHTML = '';
  resetResult();

  const fd = new FormData();
  fd.append('pdf', pdfFile);
  if (coverFile) fd.append('cover', coverFile);
  fd.append('title',   document.getElementById('f-title').value);
  fd.append('author',  document.getElementById('f-author').value);
  fd.append('lang',    document.getElementById('f-lang').value || 'es');
  fd.append('verbose', document.getElementById('f-verbose').checked ? '1' : '0');

  try {
    const resp = await fetch('/api/convert', { method: 'POST', body: fd });
    const data = await resp.json();
    if (!data.job_id) throw new Error(data.error || 'Error al iniciar conversión');
    currentJobId = data.job_id;
    pollInterval = setInterval(pollStatus, 800);
  } catch (err) {
    showError(err.message);
  }
}

async function pollStatus() {
  if (!currentJobId) return;
  try {
    const resp = await fetch(`/api/status/${currentJobId}`);
    const data = await resp.json();

    // Actualizar log
    if (data.log) renderLog(data.log);

    if (data.status === 'done') {
      clearInterval(pollInterval);
      progressBar.classList.remove('indeterminate');
      progressBar.style.width = '100%';
      showSuccess(data);
      btnConvert.disabled = false;
      btnConvert.textContent = 'Convertir otro PDF';
    } else if (data.status === 'error') {
      clearInterval(pollInterval);
      progressBar.classList.remove('indeterminate');
      showError(data.error || 'Error desconocido');
      btnConvert.disabled = false;
      btnConvert.textContent = 'Convertir a EPUB';
    }
  } catch (e) { /* ignorar errores de red transitorios */ }
}

function renderLog(text) {
  const lines = text.split('\n');
  logBox.innerHTML = lines.map(line => {
    if (line.includes('✅') || line.includes('Extraídas') || line.includes('Detectados'))
      return `<span class="log-ok">${escHtml(line)}</span>`;
    if (line.includes('⚠️') || line.includes('Error') || line.includes('falló'))
      return `<span class="log-err">${escHtml(line)}</span>`;
    if (line.startsWith('  '))
      return `<span class="log-dim">${escHtml(line)}</span>`;
    return escHtml(line);
  }).join('\n');
  logBox.scrollTop = logBox.scrollHeight;
}

function showSuccess(data) {
  resultPanel.className = 'visible';
  resultPanel.style.display = 'block';
  resultTitle.textContent = `✅ ${data.filename}`;
  const ocrInfo = data.ocr_pages ? ` · OCR ${data.ocr_pages} pág.` : '';
  resultMeta.textContent = `${data.size_kb} KB · ${data.chapters} capítulos · ${data.images} imágenes${ocrInfo}`;
  btnDownload.href = `/api/download/${currentJobId}`;
  btnDownload.download = data.filename;
}

function showError(msg) {
  resultPanel.className = 'error visible';
  resultPanel.style.display = 'block';
  resultTitle.textContent = '❌ Error en la conversión';
  resultMeta.textContent = msg;
  btnDownload.style.display = 'none';
}

function resetResult() {
  resultPanel.style.display = 'none';
  resultPanel.className = '';
  btnDownload.style.display = '';
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
</script>
</body>
</html>
"""

# ─────────────────────────────────────────────
#  RUTAS FLASK
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/pagecount", methods=["POST"])
def pagecount():
    """Cuenta páginas del PDF y lee metadatos básicos sin duplicar el archivo."""
    pdf = request.files.get("pdf")
    if not pdf:
        return jsonify({"pages": None})
    try:
        from pypdf import PdfReader
        pdf.stream.seek(0)
        reader = PdfReader(pdf.stream)
        info = reader.metadata or {}
        title  = (info.get("/Title")  or "").strip()
        author = (info.get("/Author") or "").strip()
        return jsonify({
            "pages":  len(reader.pages),
            "title":  title,
            "author": author,
        })
    except Exception as e:
        return jsonify({"pages": None, "error": str(e)})
    finally:
        try:
            pdf.stream.seek(0)
        except Exception:
            pass


@app.route("/api/convert", methods=["POST"])
def convert():
    """Inicia la conversión en un hilo secundario."""
    pdf = request.files.get("pdf")
    if not pdf:
        return jsonify({"error": "No se recibió ningún PDF"}), 400

    job_id = uuid.uuid4().hex
    job_dir = JOBS_DIR / _make_job_dir_name(pdf.filename)
    inputs_dir = job_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    # En una app web local el navegador no expone una ruta reutilizable al archivo original,
    # así que guardamos UNA sola copia de trabajo persistente para el hilo de conversión.
    safe_name = _sanitize_stem(Path(pdf.filename).stem if pdf.filename else "libro", default="libro")
    pdf_path = inputs_dir / f"{safe_name}.pdf"
    pdf.save(str(pdf_path))

    cover_path = None
    cover = request.files.get("cover")
    if cover and cover.filename:
        ext = Path(cover.filename).suffix or ".jpg"
        cover_path = inputs_dir / f"cover{ext}"
        cover.save(str(cover_path))

    config = {
        "title":     request.form.get("title", "").strip(),
        "author":    request.form.get("author", "").strip(),
        "lang":      request.form.get("lang", "es").strip() or "es",
        "verbose":   request.form.get("verbose", "0") == "1",
        "publisher": "",
        "date":      "2026",
        "ocr_mode":  request.form.get("ocr_mode", "auto").strip() or "auto",
        "ocr_lang":  request.form.get("ocr_lang", "spa+eng").strip() or "spa+eng",
        "ocr_dpi":   300,
        "ocr_min_text_chars": 90,
        "ocr_garbage_threshold": 0.22,
        "ocr_psm": 3,
        "ocr_oem": 3,
        "tesseract_cmd": request.form.get("tesseract_cmd", "").strip(),
    }

    JOBS[job_id] = {"status": "running", "log": "", "output_path": None,
                    "filename": "", "size_kb": 0, "chapters": 0, "images": 0, "ocr_pages": 0,
                    "job_dir": str(job_dir)}

    t = threading.Thread(target=_run_conversion,
                         args=(job_id, pdf_path, cover_path, config, job_dir),
                         daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


def _run_conversion(job_id, pdf_path, cover_path, config, job_dir):
    """Ejecuta la conversión y guarda el log en JOBS."""
    import io as _io
    import sys as _sys

    # Redirigir stdout al log del job
    log_lines = []

    class LogCapture:
        def write(self, s):
            log_lines.append(s)
            JOBS[job_id]["log"] = "".join(log_lines)
        def flush(self): pass

    old_stdout = _sys.stdout
    _sys.stdout = LogCapture()

    try:
        # Importar/recargar el módulo principal
        script_dir = Path(__file__).parent
        if str(script_dir) not in _sys.path:
            _sys.path.insert(0, str(script_dir))

        import importlib
        import pdf2epub as p2e
        p2e = importlib.reload(p2e)

        print(f"\n{'='*55}")
        print(f"  PDF → EPUB Converter  |  Perfil: Apotecaria")
        print(f"{'='*55}")

        # Metadatos — resolver título antes de definir output_path
        pdf_title, pdf_author = p2e.guess_title_author(str(pdf_path))
        meta = {
            "title":     config["title"]  or pdf_title  or pdf_path.stem,
            "author":    config["author"] or pdf_author or "Desconocido",
            "publisher": config.get("publisher", ""),
            "lang":      config["lang"],
            "date":      config.get("date", "2026"),
        }
        print(f"  Título : {meta['title']}")
        print(f"  Autor  : {meta['author']}")
        print()

        # Nombre del EPUB = título sanitizado
        import re as _re2
        epub_name = _re2.sub(r'[^\w\s\-áéíóúüñÁÉÍÓÚÜÑ]', '', meta["title"]).strip()
        epub_name = epub_name[:80] or pdf_path.stem  # máximo 80 chars
        output_path = _unique_export_path(epub_name)
        print(f"  Carpeta job : {job_dir}")
        print(f"  Export EPUB : {output_path}")

        print("▶ FASE 1 — Extrayendo texto e imágenes del PDF...")
        raw_pages, images = p2e.extract_pdf_content(str(pdf_path))

        print("\n▶ FASE 1.5 — Evaluando OCR...")
        raw_pages, ocr_stats = p2e.apply_ocr_to_pages(str(pdf_path), raw_pages, config)

        print("\n▶ FASE 2 — Limpiando texto...")
        pages_paragraphs = p2e.clean_text_per_page(raw_pages, config)
        clean = "\n\n".join(p for page in pages_paragraphs for p in page)

        print("\n▶ FASE 3 — Detectando capítulos...")
        chapters, page_to_chapter = p2e.detect_chapters(clean, config,
                                                         pages_paragraphs=pages_paragraphs)
        meta['excluded_pages'] = config.get('_excluded_pages', [])
        if not chapters:
            all_paras = [p for p in clean.split("\n\n") if p.strip()]
            chapters = [{"title": meta["title"], "subtitle": "", "paragraphs": all_paras,
                         "first_page_idx": 0}]
            page_to_chapter = [0] * len(raw_pages)

        p2e.detect_dialog_system(chapters)

        print("\n▶ FASE 4 — Generando EPUB...")
        cover = str(cover_path) if cover_path and cover_path.exists() else None
        if cover:
            print(f"  Portada     : manual ({cover_path.name})")
        else:
            print("  Portada     : automática (primera imagen útil del PDF)")
        p2e.create_epub(chapters, meta, str(output_path),
                        cover_image_path=cover,
                        images=images,
                        raw_pages=raw_pages,
                        pages_paragraphs=pages_paragraphs,
                        page_to_chapter=page_to_chapter)

        size_kb = round(output_path.stat().st_size / 1024, 1)
        JOBS[job_id].update({
            "status":      "done",
            "output_path": str(output_path),
            "filename":    output_path.name,
            "size_kb":     size_kb,
            "chapters":    len(chapters),
            "images":      len(images),
            "ocr_pages":   int(ocr_stats.get("pages_replaced", 0)),
        })

    except Exception:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"]  = traceback.format_exc().strip().split("\n")[-1]
        print(f"\n❌ Error:\n{traceback.format_exc()}")
    finally:
        _sys.stdout = old_stdout


@app.route("/api/status/<job_id>")
def status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"status": "not_found"}), 404
    return jsonify(job)


@app.route("/api/download/<job_id>")
def download(job_id):
    job = JOBS.get(job_id)
    if not job or job["status"] != "done":
        return "No disponible", 404
    return send_file(job["output_path"], as_attachment=True,
                     download_name=job["filename"],
                     mimetype="application/epub+zip")


# ─────────────────────────────────────────────
#  PUNTO DE ENTRADA
# ─────────────────────────────────────────────

if __name__ == "__main__":
    port = 7474
    url  = f"http://localhost:{port}"
    print(f"\n  📚 pdf2epub — Interfaz Web")
    print(f"  Abriendo {url} ...")
    print(f"  Presiona Ctrl+C para detener.\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="0.0.0.0", port=port, debug=False)
