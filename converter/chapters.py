#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helpers de detección y estructura de capítulos para pdf2epub.

Módulo extraído sin cambios lógicos desde pdf2epub.py.
"""

import re
from collections import Counter

from converter.text_utils import (
    _looks_like_visual_separator_text,
    _normalize_heading_text,
    looks_like_section_subtitle,
)



CHAPTER_PATTERNS = [
    re.compile(
        r'^[\-—–―|\s]*'
        r'(?:CAPÍTULO|CAPITULO|Capítulo|Capitulo|CHAPTER|Chapter|CAP\.|Cap\.)\s*'
        r'(\d+|[IVXLCDM]+|EXTRA|ESPECIAL)'
        r'(?:\s*[:.\-–—|]\s*(.+))?'
        r'[\-—–―|\s]*$',
        re.IGNORECASE
    ),
    re.compile(
        r'^[\-—–―|\s]*(?:PARTE|Parte|PART)\s*(\d+|[IVXLCDM]+)'
        r'(?:\s*[:.\-–—|]\s*(.+))?[\-—–―|\s]*$',
        re.IGNORECASE
    ),
    re.compile(r'^[\-—–―|\s]*(?:SHORT\s+STORY|Short\s+Story)[\-—–―|\s]*$', re.IGNORECASE),
    re.compile(r'^(\d{1,3})[.\-–]\s+([A-ZÁÉÍÓÚ].{3,})$'),
    re.compile(
        r'^[\-—–―|\s]*(Prólogo|Prolog|Epílogo|Epilogo|Interludio|Interlúdio|Interludio|'
        r'Prefacio|Presentación|Presentacion|Introducción|Introduccion|'
        r'Palabras del autor|Afterword|Foreword|Omake|Extra|Agradecimiento|Agradecimientos|Acknowledgement|Acknowledgements)\b',
        re.IGNORECASE
    ),
]

SPECIAL_SECTION_PATTERNS = [
    ("prologue", re.compile(r'^(?:prólogo|prologo|prefacio|foreword|introducción|introduccion)\b', re.IGNORECASE)),
    ("epilogue", re.compile(r'^(?:epílogo|epilogo)\b', re.IGNORECASE)),
    ("afterword", re.compile(r'^(?:afterword|palabras del autor)\b', re.IGNORECASE)),
    ("acknowledgements", re.compile(r'^(?:agradecimiento|agradecimientos|acknowledgement|acknowledgements)\b', re.IGNORECASE)),
    ("short_story", re.compile(r'^(?:short\s+story)\b', re.IGNORECASE)),
    ("part", re.compile(r'^(?:parte)\s+(?:\d+|[ivxlcdm]+)\b', re.IGNORECASE)),
    ("extra", re.compile(r'^(?:omake|extra)\b', re.IGNORECASE)),
]

TOC_KEYWORDS = (
    "tabla de contenido", "tabla de contenidos", "contenido", "contenidos",
    "table of contents", "contents", "índice", "indice", "toc"
)




def _toc_entry_score(text: str) -> int:
    text = _normalize_heading_text(text)
    lower = text.lower()
    if not text:
        return 0

    score = 0
    shortish = len(text) <= 140 and len(text.split()) <= 18
    has_section_name = bool(re.search(r'(cap[ií]tulo|chapter|prólogo|prologo|ep[ií]logo|epilogo|afterword|palabras del autor|agradecimiento)', lower))
    has_leaders = bool(re.search(r'\.{2,}\s*\d{1,4}$', text))
    has_pipe = '|' in text
    trailing_page = bool(re.search(r'\b\d{1,4}$', text))

    if any(k in lower for k in TOC_KEYWORDS):
        score += 4
    if shortish and has_section_name:
        score += 2
    if shortish and has_leaders:
        score += 3
    if shortish and has_pipe and has_section_name:
        score += 2
    if shortish and trailing_page and (has_section_name or has_leaders or has_pipe):
        score += 1
    return score


def _is_probable_toc_page(page_paragraphs: list[str]) -> bool:
    if not page_paragraphs:
        return False
    joined = _normalize_heading_text(" ".join(page_paragraphs))
    lower = joined.lower()
    if any(k in lower for k in TOC_KEYWORDS):
        return True
    scores = [_toc_entry_score(p) for p in page_paragraphs]
    strong = sum(1 for s in scores if s >= 3)
    medium = sum(1 for s in scores if s >= 2)
    chapter_mentions = len(re.findall(r'(cap[ií]tulo|chapter|pr[óo]logo|ep[ií]logo|afterword)', lower))
    page_numbers = len(re.findall(r'\b\d{1,4}\b', lower))
    leader_count = len(re.findall(r'\.{2,}', joined))
    return (
        strong >= 2
        or (medium >= 3 and page_numbers >= 3)
        or (chapter_mentions >= 3 and page_numbers >= 3)
        or (chapter_mentions >= 3 and leader_count >= 2)
    )


_ROMAN_VALUES = {
    'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000,
}


def _roman_to_int(value: str) -> int | None:
    value = (value or '').upper().strip()
    if not value or not re.fullmatch(r'[IVXLCDM]+', value):
        return None
    total = 0
    previous = 0
    for ch in reversed(value):
        cur = _ROMAN_VALUES.get(ch, 0)
        if cur < previous:
            total -= cur
        else:
            total += cur
            previous = cur
    return total if total > 0 else None


def _chapter_label_key(label: str | int | None) -> str:
    if label is None:
        return ''
    label_s = str(label).strip()
    if not label_s:
        return ''
    if label_s.isdigit():
        return str(int(label_s))
    roman = _roman_to_int(label_s)
    if roman is not None:
        return str(roman)
    return re.sub(r'\s+', ' ', label_s.lower())


def _heading_identity_key(heading: dict | None) -> tuple[str, str]:
    if not heading:
        return ('', '')
    kind = heading.get('kind') or heading.get('section_kind') or 'chapter'
    title = _normalize_heading_text(heading.get('title', ''))
    m = re.search(r'cap[ií]tulo\s+([0-9]+|[IVXLCDM]+)', title, re.IGNORECASE)
    if kind == 'chapter' or m:
        return ('chapter', _chapter_label_key(m.group(1) if m else title))
    return (kind, re.sub(r'\s+', ' ', title.lower()))


def _split_possible_toc_entries(text: str) -> list[str]:
    """Divide un párrafo de índice que pudo quedar unido en varias entradas."""
    text = _normalize_heading_text(text)
    if not text:
        return []
    # Mantener la entrada completa si parece una sola línea normal.
    if len(re.findall(r'(?i)\bcap[ií]tulo\s+\d+', text)) <= 1:
        return [text]
    starts = [m.start() for m in re.finditer(r'(?i)\bcap[ií]tulo\s+\d+', text)]
    parts = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        part = text[start:end].strip(' -–—|')
        if part:
            parts.append(part)
    return parts or [text]


def _parse_toc_entry(text: str) -> dict | None:
    """
    Extrae una entrada del índice con número de página destino.

    Ejemplos soportados:
      Capítulo 24: Hōkō .... 288
      Capitulo 24 - Hoko 288
      Prólogo 19
      Epílogo .... 305
    """
    original = _normalize_heading_text(text)
    if not original:
        return None
    # Quitar líderes de índice, pipes decorativos y espacios raros.
    clean = re.sub(r'\.{2,}', ' ', original)
    clean = re.sub(r'[|·•]{2,}', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()

    page_m = re.search(r'\b(\d{1,4})\s*$', clean)
    if not page_m:
        return None
    target_page = int(page_m.group(1))
    body = clean[:page_m.start()].strip(' -–—:|')
    if not body or target_page <= 0:
        return None

    chap_m = re.match(
        r'(?i)^(?:cap[ií]tulo|chapter|cap\.)\s*([0-9]+|[IVXLCDM]+|extra|especial)\s*(?:[:.\-–—|]\s*)?(.*)$',
        body,
    )
    if chap_m:
        label = chap_m.group(1)
        subtitle = _normalize_heading_text(chap_m.group(2) or '')
        title_label = label.title() if str(label).isalpha() and not str(label).isdigit() else label
        return {
            'kind': 'chapter',
            'title': f'Capítulo {title_label}',
            'subtitle': subtitle,
            'consume': 0,
            'toc_target_page': target_page,
            'toc_source': original,
        }

    special_patterns = [
        ('prologue', r'pr[óo]logo|prolog|prefacio|foreword|introducci[óo]n'),
        ('epilogue', r'ep[íi]logo|epilogo'),
        ('afterword', r'afterword|palabras del autor'),
        ('acknowledgements', r'agradecimientos?|acknowledgements?'),
    ]
    for kind, pat in special_patterns:
        if re.match(rf'(?i)^({pat})\b', body):
            return {
                'kind': kind,
                'title': _format_special_heading(kind, body),
                'subtitle': '',
                'consume': 0,
                'toc_target_page': target_page,
                'toc_source': original,
            }
    return None


def _is_toc_entry_start_line(text: str) -> bool:
    text = _normalize_heading_text(text)
    if not text:
        return False
    return bool(re.search(
        r'(?i)\b(?:cap[ií]tulo|chapter|cap\.|pr[óo]logo|prolog|ep[íi]logo|epilogo|afterword|palabras del autor|introducci[óo]n|prefacio|foreword)\b',
        text,
    ))


def _line_has_trailing_page_number(text: str) -> bool:
    text = _normalize_heading_text(text)
    return bool(re.search(r'\b\d{1,4}\s*$', text))


def _add_toc_entry(entries: list[dict], seen: set[tuple[str, str, int]], candidate: str) -> None:
    for part in _split_possible_toc_entries(candidate):
        entry = _parse_toc_entry(part)
        if not entry:
            continue
        key = (*_heading_identity_key(entry), int(entry['toc_target_page']))
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)


def _parse_toc_entries_from_pages(pages_paragraphs: list[list[str]], toc_pages: set[int]) -> list[dict]:
    """
    Extrae entradas desde páginas de índice.

    Soporta dos casos habituales:
      1) Entrada completa en una sola línea:
         "Capítulo 24: Hōkō .... 288"
      2) Entrada partida por la extracción PDF:
         "Capítulo 24" / "Hōkō" / "288"

    El segundo caso era el que dejaba sin marcadores a muchos PDFs con
    páginas de capítulo decorativas, porque el título real no aparece como
    texto extraíble en la página del capítulo.
    """
    entries: list[dict] = []
    seen: set[tuple[str, str, int]] = set()

    for pg_idx in sorted(toc_pages):
        if pg_idx < 0 or pg_idx >= len(pages_paragraphs):
            continue

        lines = [_normalize_heading_text(p) for p in pages_paragraphs[pg_idx] if _normalize_heading_text(p)]

        # 1) Entradas completas o varias entradas pegadas en un párrafo.
        for para in lines:
            _add_toc_entry(entries, seen, para)

        # 2) Entradas partidas en 2-5 líneas consecutivas.
        #    Ej.: ["Capítulo 24", "Hōkō", "288"]
        for i, line in enumerate(lines):
            if not _is_toc_entry_start_line(line):
                continue
            window_parts: list[str] = []
            for j in range(i, min(len(lines), i + 5)):
                part = lines[j]
                if j > i and _is_toc_entry_start_line(part):
                    break
                window_parts.append(part)
                candidate = ' '.join(window_parts)
                # No intentar parsear "Capítulo 24" como si 24 fuera página;
                # esperamos otra línea con número de página o una entrada completa.
                if j == i and re.fullmatch(r'(?i)cap[ií]tulo\s+\d{1,4}', candidate):
                    continue
                if _line_has_trailing_page_number(candidate):
                    _add_toc_entry(entries, seen, candidate)

    entries.sort(key=lambda e: (int(e.get('toc_target_page', 10**9)), _heading_identity_key(e)))
    return entries


def _guess_toc_page_offset(pages_paragraphs: list[list[str]], toc_pages: set[int], toc_entries: list[dict]) -> int:
    """
    Algunas tablas de contenido usan paginación impresa y otras el índice real del PDF.
    Si podemos empatar headings detectados naturalmente contra el índice, calculamos offset.
    """
    if not toc_entries:
        return 0
    natural: dict[tuple[str, str], int] = {}
    for pg_idx, page_paras in enumerate(pages_paragraphs):
        if pg_idx in toc_pages:
            continue
        visible = [p.strip() for p in page_paras if p and p.strip()]
        if not visible:
            continue
        heading = _detect_page_heading(visible, allow_terminal=True)
        key = _heading_identity_key(heading)
        if key != ('', '') and key not in natural:
            natural[key] = pg_idx + 1
    offsets: list[int] = []
    for entry in toc_entries:
        key = _heading_identity_key(entry)
        if key in natural:
            offsets.append(natural[key] - int(entry['toc_target_page']))
    if not offsets:
        return 0
    return Counter(offsets).most_common(1)[0][0]


def _consume_forced_toc_heading(visible_paras: list[str], heading: dict) -> int:
    """Evita duplicar el título si la página también lo trae como texto extraíble."""
    if not visible_paras:
        return 0
    title = _normalize_heading_text(heading.get('title', ''))
    subtitle = _normalize_heading_text(heading.get('subtitle', ''))
    title_key = _heading_identity_key(heading)
    consume = 0
    first = _normalize_heading_text(visible_paras[0])
    if first:
        first_key = _heading_identity_key({'kind': heading.get('kind', 'chapter'), 'title': first})
        if first_key == title_key or first.lower() == title.lower() or title.lower() in first.lower():
            consume = 1
    if subtitle and len(visible_paras) > consume:
        nxt = _normalize_heading_text(visible_paras[consume])
        if nxt.lower() == subtitle.lower() or subtitle.lower() in nxt.lower():
            consume += 1
    return consume


def _build_toc_forced_headings(pages_paragraphs: list[list[str]], toc_pages: set[int]) -> dict[int, dict]:
    toc_entries = _parse_toc_entries_from_pages(pages_paragraphs, toc_pages)
    if not toc_entries:
        return {}
    offset = _guess_toc_page_offset(pages_paragraphs, toc_pages, toc_entries)
    forced: dict[int, dict] = {}
    for entry in toc_entries:
        target_idx = int(entry['toc_target_page']) + offset - 1
        if target_idx < 0 or target_idx >= len(pages_paragraphs):
            continue
        if target_idx in toc_pages:
            continue
        # No reemplazar una marca ya existente por otra menos informativa.
        existing = forced.get(target_idx)
        if existing and existing.get('kind') == 'chapter' and entry.get('kind') != 'chapter':
            continue
        forced[target_idx] = {
            'kind': entry.get('kind', 'chapter'),
            'title': entry.get('title', 'Capítulo'),
            'subtitle': entry.get('subtitle', ''),
            'consume': 0,
            'source': 'toc',
            'toc_source': entry.get('toc_source', ''),
        }
    if forced:
        print(f"  [Estructura] Marcadores de capítulos desde TOC: {len(forced)}" + (f" (offset {offset:+d})" if offset else ""))
    return forced


def _find_first_body_page(pages_paragraphs: list[list[str]], toc_pages: set[int]) -> int:
    terminal_allowed = max(toc_pages) + 1 if toc_pages else 0
    for pg_idx, page_paras in enumerate(pages_paragraphs):
        if pg_idx in toc_pages:
            continue
        visible = [p.strip() for p in page_paras if p and p.strip()]
        if not visible:
            continue
        heading = _detect_page_heading(visible, allow_terminal=pg_idx >= terminal_allowed)
        if heading and heading['kind'] in {'prologue', 'chapter'}:
            return pg_idx
    for pg_idx, page_paras in enumerate(pages_paragraphs):
        if pg_idx in toc_pages:
            continue
        visible = [p.strip() for p in page_paras if p and p.strip()]
        if not visible:
            continue
        heading = _detect_page_heading(visible, allow_terminal=True)
        if heading:
            return pg_idx
    return -1


def _collect_auxiliary_pages(pages_paragraphs: list[list[str]], toc_pages: set[int], first_body_page: int) -> set[int]:
    aux_pages: set[int] = set(toc_pages)
    if first_body_page < 0:
        return aux_pages
    for pg_idx in range(first_body_page):
        visible = [p.strip() for p in pages_paragraphs[pg_idx] if p and p.strip()]
        if visible:
            continue
        if any(abs(pg_idx - toc_pg) <= 1 for toc_pg in toc_pages):
            aux_pages.add(pg_idx)
    return aux_pages

def _looks_like_short_heading(text: str) -> bool:
    text = _normalize_heading_text(text)
    if not text or len(text) > 120:
        return False
    if text.count('.') >= 3:
        return False
    return True


def _format_special_heading(kind: str, text: str) -> str:
    text = _normalize_heading_text(text)
    if kind == 'prologue':
        return 'Prólogo'
    if kind == 'epilogue':
        return 'Epílogo'
    if kind == 'afterword':
        return 'Afterword' if text.lower().startswith('afterword') else 'Palabras del autor'
    if kind == 'acknowledgements':
        return 'Agradecimiento' if text.lower().startswith('agradecimiento') else 'Agradecimientos'
    if kind == 'short_story':
        return 'Short Story'
    if kind == 'part':
        m = re.search(r'(\d+|[IVXLCDM]+)', text, re.IGNORECASE)
        return f"Parte {m.group(1)}" if m else 'Parte'
    return text or 'Extra'
def _detect_page_heading(page_paragraphs: list[str], allow_terminal: bool = True) -> dict | None:
    candidates = [_normalize_heading_text(p) for p in page_paragraphs[:5] if _normalize_heading_text(p)]
    if not candidates:
        return None

    if _toc_entry_score(candidates[0]) >= 3 and _is_probable_toc_page(candidates):
        return None

    heading_idx = 0
    for idx, cand in enumerate(candidates[:4]):
        if any(pat.match(cand) for _, pat in SPECIAL_SECTION_PATTERNS) or CHAPTER_PATTERNS[0].match(cand) or CHAPTER_PATTERNS[1].match(cand) or CHAPTER_PATTERNS[2].match(cand):
            heading_idx = idx
            break
    first = candidates[heading_idx]
    rest = candidates[heading_idx + 1:]

    for kind, pattern in SPECIAL_SECTION_PATTERNS:
        if kind in {'epilogue', 'afterword', 'acknowledgements'} and not allow_terminal:
            continue
        if pattern.match(first) and _looks_like_short_heading(first):
            consume = heading_idx + 1
            subtitle = ''
            if rest and looks_like_section_subtitle(rest[0]) and _toc_entry_score(rest[0]) < 2:
                second_is_same_special = any(pat.match(rest[0]) for _, pat in SPECIAL_SECTION_PATTERNS)
                if kind == 'afterword' and re.match(r'^(?:palabras del autor)$', rest[0], re.IGNORECASE):
                    subtitle = rest[0]
                    consume += 1
                elif not second_is_same_special and not CHAPTER_PATTERNS[0].match(rest[0]):
                    subtitle = rest[0]
                    consume += 1
            return {'kind': kind, 'title': _format_special_heading(kind, first), 'subtitle': subtitle, 'consume': consume}

    m = CHAPTER_PATTERNS[0].match(first)
    if m:
        label = m.group(1)
        subtitle = (m.group(2) or '').strip()
        short_heading = _looks_like_short_heading(first)
        # Si el extractor pegó el título con el primer párrafo, no consumimos
        # esa línea para no perder texto. Esto crea un corte de capítulo fiable
        # aunque el subtítulo no pueda recuperarse perfecto.
        consume = heading_idx + 1 if short_heading else heading_idx
        if short_heading and not subtitle and rest and looks_like_section_subtitle(rest[0]) and _toc_entry_score(rest[0]) < 2:
            if not any(pat.match(rest[0]) for _, pat in SPECIAL_SECTION_PATTERNS) and not CHAPTER_PATTERNS[0].match(rest[0]):
                subtitle = rest[0]
                consume += 1
        if not short_heading:
            subtitle = ''
        title = f'Capítulo {label.title() if str(label).isalpha() else label}'
        return {'kind': 'chapter', 'title': title, 'subtitle': subtitle, 'consume': consume}

    m = CHAPTER_PATTERNS[1].match(first)
    if m and _looks_like_short_heading(first):
        label = m.group(1)
        subtitle = (m.group(2) or '').strip()
        consume = heading_idx + 1
        if not subtitle and rest and looks_like_section_subtitle(rest[0]) and _toc_entry_score(rest[0]) < 2:
            subtitle = rest[0]
            consume += 1
        return {'kind': 'part', 'title': f'Parte {label}', 'subtitle': subtitle, 'consume': consume}

    if CHAPTER_PATTERNS[2].match(first):
        subtitle = ''
        consume = heading_idx + 1
        if rest and looks_like_section_subtitle(rest[0]) and _toc_entry_score(rest[0]) < 2:
            subtitle = rest[0]
            consume += 1
        return {'kind': 'short_story', 'title': 'Short Story', 'subtitle': subtitle, 'consume': consume}

    m = CHAPTER_PATTERNS[3].match(first)
    if m and _looks_like_short_heading(first):
        return {'kind': 'chapter', 'title': f'Capítulo {m.group(1)}', 'subtitle': (m.group(2) or '').strip(), 'consume': heading_idx + 1}

    return None
def detect_chapters(full_text: str, config: dict,
                    pages_paragraphs: list | None = None) -> tuple:
    """
    Divide el texto en secciones lógicas preservando el orden real del PDF.
    Prioriza el análisis por página para evitar que la tabla de contenido o
    encabezados auxiliares se mezclen con capítulos reales.
    """
    paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]

    if not pages_paragraphs:
        chapters: list = []
        current_chapter: dict | None = None
        intro_paragraphs: list = []
        for para in paragraphs:
            heading = _detect_page_heading([para])
            if heading:
                if current_chapter is not None:
                    chapters.append(current_chapter)
                elif intro_paragraphs:
                    chapters.append({
                        'title': 'Introducción', 'subtitle': '', 'paragraphs': intro_paragraphs,
                        'is_intro': True, 'first_page_idx': -1, 'section_kind': 'intro',
                    })
                    intro_paragraphs = []
                current_chapter = {
                    'title': heading['title'], 'subtitle': heading.get('subtitle', ''),
                    'paragraphs': [], 'is_intro': heading['kind'] != 'chapter',
                    'first_page_idx': -1, 'section_kind': heading['kind'],
                }
                continue
            if current_chapter is None:
                intro_paragraphs.append(para)
            else:
                current_chapter['paragraphs'].append(para)

        if current_chapter is not None:
            chapters.append(current_chapter)
        elif intro_paragraphs:
            chapters.append({
                'title': 'Introducción', 'subtitle': '', 'paragraphs': intro_paragraphs,
                'is_intro': True, 'first_page_idx': -1, 'section_kind': 'intro',
            })
        config['_excluded_pages'] = []
        config['_frontmatter_pages'] = []
        return chapters, []

    n_pages = len(pages_paragraphs)
    preliminary_body_page = -1
    for pg_idx, page_paras in enumerate(pages_paragraphs):
        visible = [p.strip() for p in page_paras if p and p.strip()]
        if not visible:
            continue
        heading = _detect_page_heading(visible, allow_terminal=False)
        if heading and heading['kind'] in {'prologue', 'chapter'}:
            preliminary_body_page = pg_idx
            break

    toc_pages: set[int] = set()
    toc_mode = False
    toc_scan_limit = min(n_pages, 60)
    for pg_idx, page_paras in enumerate(pages_paragraphs[:toc_scan_limit]):
        visible = [p.strip() for p in page_paras if p and p.strip()]
        is_toc = _is_probable_toc_page(visible)
        if is_toc:
            toc_pages.add(pg_idx)
            toc_mode = True
        elif toc_mode and visible and sum(_toc_entry_score(p) for p in visible[:6]) >= 5:
            toc_pages.add(pg_idx)
        else:
            toc_mode = False

    first_body_page = preliminary_body_page if preliminary_body_page >= 0 else _find_first_body_page(pages_paragraphs, toc_pages)
    auxiliary_pages = _collect_auxiliary_pages(pages_paragraphs, toc_pages, first_body_page)
    frontmatter_pages = sorted(pg for pg in range(first_body_page) if pg not in auxiliary_pages) if first_body_page > 0 else []
    toc_forced_headings = _build_toc_forced_headings(pages_paragraphs, toc_pages)


    chapters: list[dict] = []
    current_section: dict | None = None
    intro_paragraphs: list[str] = []
    intro_first_page = -1
    page_to_chapter: list[int] = [-1] * n_pages
    body_started = False

    def flush_current() -> None:
        nonlocal current_section, intro_paragraphs, intro_first_page
        if current_section is not None:
            chapters.append(current_section)
            current_section = None
        elif intro_paragraphs:
            chapters.append({
                'title': 'Introducción', 'subtitle': '', 'paragraphs': intro_paragraphs,
                'is_intro': True, 'first_page_idx': intro_first_page, 'section_kind': 'intro',
            })
            intro_paragraphs = []
            intro_first_page = -1

    for pg_idx, page_paras in enumerate(pages_paragraphs):
        if pg_idx in auxiliary_pages:
            continue

        forced_heading = toc_forced_headings.get(pg_idx)
        visible_paras = [p.strip() for p in page_paras if p and p.strip()]
        if not visible_paras and not forced_heading:
            continue

        allow_terminal = body_started or pg_idx >= first_body_page
        heading = dict(forced_heading) if forced_heading else _detect_page_heading(visible_paras, allow_terminal=allow_terminal)
        consume = 0
        if heading:
            if heading.get('source') == 'toc':
                consume = _consume_forced_toc_heading(visible_paras, heading)
                heading['consume'] = consume
            if heading['kind'] in {'prologue', 'chapter'}:
                body_started = True
            elif not body_started and heading['kind'] in {'epilogue', 'afterword', 'acknowledgements'}:
                heading = None
            if heading:
                flush_current()
                current_section = {
                    'title': heading['title'],
                    'subtitle': heading.get('subtitle', ''),
                    'paragraphs': [],
                    'is_intro': heading['kind'] != 'chapter',
                    'first_page_idx': pg_idx,
                    'section_kind': heading['kind'],
                }
                consume = int(heading.get('consume', 1))

        content_paras = visible_paras[consume:]
        # E02: no descartar párrafos narrativos solo por ser breves. La antigua
        # heurística los confundía con páginas visuales (<70 caracteres).
        # Las páginas efectivamente vacías ya se gestionan por separado.

        if current_section is None:
            if content_paras:
                intro_paragraphs.extend(content_paras)
                if intro_first_page == -1:
                    intro_first_page = pg_idx
        else:
            current_section['paragraphs'].extend(content_paras)

    flush_current()

    if chapters:
        ch_starts = sorted(
            [(ch.get('first_page_idx', -1), i) for i, ch in enumerate(chapters) if ch.get('first_page_idx', -1) >= 0],
            key=lambda x: x[0]
        )
        cur_ch = -1
        ci = 0
        for pg in range(n_pages):
            if pg in auxiliary_pages:
                page_to_chapter[pg] = -1
                continue
            while ci < len(ch_starts) and ch_starts[ci][0] <= pg:
                cur_ch = ch_starts[ci][1]
                ci += 1
            page_to_chapter[pg] = cur_ch

    config['_excluded_pages'] = sorted(auxiliary_pages)
    config['_frontmatter_pages'] = frontmatter_pages

    print(f"  [Capítulos] Detectados: {len(chapters)}")
    if toc_pages:
        printable = ', '.join(str(p + 1) for p in sorted(toc_pages)[:6])
        extra = '' if len(toc_pages) <= 6 else '…'
        print(f"  [Estructura] TOC excluido en páginas: {printable}{extra}")
    if frontmatter_pages:
        printable = ', '.join(str(p + 1) for p in frontmatter_pages[:8])
        extra = '' if len(frontmatter_pages) <= 8 else '…'
        print(f"  [Estructura] Front matter visual antes del cuerpo: {printable}{extra}")
    for ch in chapters[:8]:
        pg = ch.get('first_page_idx', -1)
        pg_str = f" (pág PDF {pg+1})" if pg >= 0 else ''
        sk = ch.get('section_kind', 'chapter')
        print(f"    - [{sk}] {ch['title']}" + (f": {ch['subtitle'][:40]}" if ch.get('subtitle') else '') + pg_str)
    if len(chapters) > 8:
        print(f"    ... y {len(chapters)-8} más")

    return chapters, page_to_chapter


def _build_sequential_page_para_ranges(chapters: list[dict], pages_paragraphs: list[list[str]], page_to_chapter: list[int]) -> dict[tuple[int, int], tuple[int, int]]:
    """Mapea páginas a rangos de párrafos secuenciales dentro de cada capítulo.
    Evita que párrafos repetidos se asignen siempre a su primera aparición."""
    n_pages = len(pages_paragraphs)
    chapter_pages: dict[int, list[int]] = {}
    for pg_idx in range(n_pages):
        ch_idx = page_to_chapter[pg_idx] if pg_idx < len(page_to_chapter) else -1
        if ch_idx >= 0:
            chapter_pages.setdefault(ch_idx, []).append(pg_idx)

    ranges: dict[tuple[int, int], tuple[int, int]] = {}
    for ch_idx, page_indices in chapter_pages.items():
        chapter_paras = [p.strip() for p in chapters[ch_idx].get("paragraphs", []) if p and p.strip()]
        if not chapter_paras:
            continue

        positions_by_key: dict[str, list[int]] = {}
        for pos, para in enumerate(chapter_paras):
            positions_by_key.setdefault(para, []).append(pos)

        cursor = 0
        for pg_idx in page_indices:
            visible = [p.strip() for p in pages_paragraphs[pg_idx] if p and p.strip()]
            if not visible:
                continue

            matched_positions: list[int] = []
            local_cursor = cursor
            for para in visible:
                candidates = positions_by_key.get(para)
                if not candidates:
                    continue
                chosen = next((pos for pos in candidates if pos >= local_cursor), None)
                if chosen is None:
                    continue
                matched_positions.append(chosen)
                local_cursor = chosen + 1

            if matched_positions:
                start = matched_positions[0]
                end = matched_positions[-1] + 1
                ranges[(ch_idx, pg_idx)] = (start, end)
                cursor = max(cursor, end)

    return ranges


def _fragment_first_text(chapters: list[dict], item: dict) -> str:
    if item.get("type") != "chapter_fragment":
        return ""
    ch_idx = item.get("ch_idx", -1)
    if ch_idx < 0 or ch_idx >= len(chapters):
        return ""
    paras = chapters[ch_idx].get("paragraphs", [])
    start = max(0, int(item.get("start_idx", 0)))
    end = min(len(paras), int(item.get("end_idx", 0)))
    for para in paras[start:end]:
        key = (para or "").strip()
        if key:
            return key
    return ""


def _fragment_image_names(chapters: list[dict], item: dict) -> set[str]:
    if item.get("type") != "chapter_fragment":
        return set()
    ch_idx = item.get("ch_idx", -1)
    if ch_idx < 0 or ch_idx >= len(chapters):
        return set()
    start_idx = int(item.get("start_idx", 0))
    end_idx = int(item.get("end_idx", 0))
    names: set[str] = set()
    for img in chapters[ch_idx].get("inline_images", []):
        name = img.get("imgname", "")
        if not name:
            continue
        pos = int(img.get("after_para_idx", -1))
        if start_idx - 1 <= pos < end_idx:
            names.add(name)
    return names


def _normalize_spine_fragments(spine_items: list[dict], chapters: list[dict]) -> tuple[list[dict], list[str]]:
    normalized: list[dict] = []
    issues: list[str] = []
    last_end_by_chapter: dict[int, int] = {}
    prev_fragment: dict | None = None

    for item in spine_items:
        if item.get("type") != "chapter_fragment":
            normalized.append(item)
            prev_fragment = None
            continue

        cur = dict(item)
        ch_idx = int(cur.get("ch_idx", -1))
        start = int(cur.get("start_idx", 0))
        end = int(cur.get("end_idx", 0))

        last_end = last_end_by_chapter.get(ch_idx)
        if last_end is not None and start < last_end:
            issues.append(f"overlap_trim ch={ch_idx} {start}->{end} trimmed_to {last_end}->{end}")
            start = last_end
            cur["start_idx"] = start
        if end <= start:
            issues.append(f"empty_drop ch={ch_idx} {start}->{end}")
            continue

        if prev_fragment and prev_fragment.get("type") == "chapter_fragment" and prev_fragment.get("ch_idx") == ch_idx:
            prev_first = _fragment_first_text(chapters, prev_fragment)
            cur_first = _fragment_first_text(chapters, cur)
            if prev_first and cur_first and prev_first == cur_first:
                prev_end = int(prev_fragment.get("end_idx", 0))
                if start < prev_end:
                    start = prev_end
                    cur["start_idx"] = start
                    issues.append(f"same_start_trim ch={ch_idx} -> {start}->{end}")
            shared_images = _fragment_image_names(chapters, prev_fragment) & _fragment_image_names(chapters, cur)
            if shared_images:
                suppress = set(cur.get("suppress_images", []))
                suppress.update(shared_images)
                cur["suppress_images"] = sorted(suppress)
                issues.append(f"shared_images_suppressed ch={ch_idx} imgs={','.join(sorted(shared_images))}")
            if int(cur.get("end_idx", 0)) <= int(cur.get("start_idx", 0)):
                issues.append(f"post_check_drop ch={ch_idx} {cur.get('start_idx')}->{cur.get('end_idx')}")
                continue

        normalized.append(cur)
        last_end_by_chapter[ch_idx] = int(cur.get("end_idx", 0))
        prev_fragment = cur

    return normalized, issues


def _validate_spine_fragments(spine_items: list[dict], chapters: list[dict]) -> list[str]:
    issues: list[str] = []
    prev_fragment: dict | None = None
    for item in spine_items:
        if item.get("type") != "chapter_fragment":
            prev_fragment = None
            continue
        if prev_fragment and prev_fragment.get("type") == "chapter_fragment" and prev_fragment.get("ch_idx") == item.get("ch_idx"):
            if int(item.get("start_idx", 0)) < int(prev_fragment.get("end_idx", 0)):
                issues.append(f"overlap ch={item.get('ch_idx')} {prev_fragment.get('start_idx')}->{prev_fragment.get('end_idx')} with {item.get('start_idx')}->{item.get('end_idx')}")
            prev_first = _fragment_first_text(chapters, prev_fragment)
            cur_first = _fragment_first_text(chapters, item)
            if prev_first and cur_first and prev_first == cur_first:
                issues.append(f"same_start_text ch={item.get('ch_idx')} text={prev_first[:80]}")
            shared_images = _fragment_image_names(chapters, prev_fragment) & _fragment_image_names(chapters, item)
            shared_images -= set(item.get("suppress_images", []))
            if shared_images:
                issues.append(f"shared_images ch={item.get('ch_idx')} imgs={','.join(sorted(shared_images))}")
        prev_fragment = item
    return issues
