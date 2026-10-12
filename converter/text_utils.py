# -*- coding: utf-8 -*-
"""Utilidades de limpieza y normalización de texto para pdf2epub.py.

Este módulo contiene solo helpers sin dependencia directa del flujo principal.
"""

import re
from collections import Counter

# Patrones de encabezados/pies repetidos (se detectan dinámicamente)
HEADER_FOOTER_MIN_REPEAT = 4  # aparece en al menos N páginas = candidato a header/footer
VARIABLE_PAGE_LINE_RE = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .:'’_\-]{3,80}\s*\|\s*\d{1,4}$")
STRUCTURAL_HEADING_RE = re.compile(
    r'^[\-—–―|\s]*'
    r'(?:cap[ií]tulo(?:\s+(?:\d+|extra|especial))?|chapter(?:\s+(?:\d+|extra|special))?|'
    r'parte(?:\s+\d+)?|pr[oó]logo|prologue|ep[ií]logo|afterword|short\s+story|'
    r'palabras del autor|agradecimientos?|acknowledgements?)\b',
    re.IGNORECASE,
)


def _normalize_heading_text(text: str) -> str:
    text = (text or "").replace(" ", " ")
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^[\-—–―|\s]+', '', text)
    text = re.sub(r'[\-—–―|\s]+$', '', text)
    return text.strip()


def is_structural_heading_line(line: str) -> bool:
    s = _normalize_heading_text(line)
    return bool(s and STRUCTURAL_HEADING_RE.match(s))


def looks_like_section_subtitle(line: str) -> bool:
    s = _normalize_heading_text(line)
    if not s or is_structural_heading_line(s):
        return False
    if len(s) > 120 or len(s.split()) > 14:
        return False
    if re.search(r'\.{2,}\s*\d{1,4}$', s):
        return False
    if '|' in s and re.search(r'\d{1,4}$', s):
        return False
    if re.fullmatch(r'\d{1,4}', s):
        return False
    if re.match(r'^(?:cap[ií]tulo|chapter|parte|pr[oó]logo|ep[ií]logo|afterword|short\s+story)\b', s, re.IGNORECASE):
        return False
    words = [w for w in re.split(r'\s+', s) if w]
    titled = sum(1 for w in words if re.match(r'^[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+', w))
    return titled >= max(1, len(words) // 2)


def normalize_header_footer_candidate(line: str) -> str:
    """Normaliza SOLO numeración de margen conocida, nunca cifras de la prosa.

    E02: sustituir todas las cifras producía colisiones entre frases legítimas
    ("párrafo 1" / "párrafo 2"), que después se borraban por completo.
    """
    s = re.sub(r'\s+', ' ', (line or '').strip())
    if not s:
        return ''
    if is_structural_heading_line(s):
        return ''

    if re.fullmatch(r'[\-–—\s]*\d{1,4}[\-–—\s]*', s):
        return '<PAGE_NUM>'

    if re.fullmatch(r'(?:p[áa]g(?:ina)?\.?\s*|p\.?\s*)\d{1,4}', s, flags=re.IGNORECASE):
        return '<PAGE_NUM>'

    if VARIABLE_PAGE_LINE_RE.fullmatch(s):
        s = re.sub(r'\d{1,4}\s*$', '<PAGE_NUM>', s)

    if re.fullmatch(r'[\-–—\s]*<PAGE_NUM>[\-–—\s]*', s):
        return '<PAGE_NUM>'

    if is_structural_heading_line(s):
        return ''
    return s


def _margin_positions(lines: list[str]) -> set[int]:
    """Posiciones de encabezado/pie de página; no incluir la prosa interior."""
    nonempty = [i for i, line in enumerate(lines) if line.strip()]
    return set(nonempty[:2] + nonempty[-2:])


def _plausible_running_header(line: str) -> bool:
    """No eliminar una oración narrativa aunque se repita entre páginas."""
    stripped = line.strip()
    if len(stripped) > 100 or len(stripped.split()) > 12:
        return False
    if re.search(r'[.!?…]["”’]?$', stripped) and not re.match(
        r'^(?:p[áa]g(?:ina)?\.?\s*|p\.?\s*)\d+$', stripped, flags=re.IGNORECASE
    ):
        return False
    return True


def detect_repeated_lines(pages: list[str]) -> tuple[set[str], set[str]]:
    """Detecta líneas repetidas exactas y líneas repetidas tras normalización."""
    from collections import Counter

    exact_count: Counter = Counter()
    normalized_count: Counter = Counter()

    for page_text in pages:
        lines = page_text.splitlines()
        candidates = (lines[i] for i in sorted(_margin_positions(lines)))
        seen_exact: set[str] = set()
        seen_normalized: set[str] = set()
        for line in candidates:
            stripped = re.sub(r'\s+', ' ', line.strip())
            if not stripped or len(stripped) <= 2 or not _plausible_running_header(stripped):
                continue
            if is_structural_heading_line(stripped):
                continue
            if stripped not in seen_exact:
                exact_count[stripped] += 1
                seen_exact.add(stripped)
            normalized = normalize_header_footer_candidate(stripped)
            if normalized and normalized not in seen_normalized:
                normalized_count[normalized] += 1
                seen_normalized.add(normalized)

    # Repetición en un porcentaje alto de páginas, con mínimo de cuatro.
    min_repeat = max(HEADER_FOOTER_MIN_REPEAT, int(len(pages) * .45))
    repeated_exact = {line for line, count in exact_count.items() if count >= min_repeat}
    repeated_normalized = {line for line, count in normalized_count.items() if count >= min_repeat}
    return repeated_exact, repeated_normalized


def clean_text(raw_pages: list[str], config: dict) -> str:
    """
    Limpieza del texto ya extraído. Devuelve un único string con párrafos
    separados por doble newline.
    NOTA: Para preservar info de página usa clean_text_per_page().
    """
    cleaned_pages = clean_text_per_page(raw_pages, config)
    # Unir todas las páginas en un único string para detect_chapters
    all_paragraphs: list[str] = []
    for page_paras in cleaned_pages:
        all_paragraphs.extend(page_paras)
    return "\n\n".join(all_paragraphs)


def clean_text_per_page(raw_pages: list[str], config: dict) -> list[list[str]]:
    """
    Igual que clean_text pero devuelve una lista de listas:
      result[page_idx] = [párrafo1, párrafo2, ...]

    Esto preserva a qué página pertenece cada párrafo, lo que permite
    construir un mapa página→capítulo exacto en create_epub.
    """
    repeated_lines, repeated_normalized = detect_repeated_lines(raw_pages)
    if config.get("verbose"):
        if repeated_lines:
            print(f"  [Limpieza] Líneas repetidas residuales exactas ({len(repeated_lines)}):")
            for l in list(sorted(repeated_lines))[:5]:
                print(f"    - {repr(l)}")
        if repeated_normalized:
            print(f"  [Limpieza] Patrones repetidos normalizados ({len(repeated_normalized)}):")
            for l in list(sorted(repeated_normalized))[:5]:
                print(f"    - {repr(l)}")

    HF_EXTRA_PATTERNS = [
        re.compile(r'^P[áa]gina\s+N[°º]?\s*\d+$', re.IGNORECASE),
        re.compile(r'^\s*pág(?:ina)?\s*\.?\s*\d+\s*$', re.IGNORECASE),
        re.compile(r'^[\-–—]\s*\d+\s*[\-–—]$'),
        VARIABLE_PAGE_LINE_RE,
    ]

    verbose_removed = 0
    result: list[list[str]] = []
    for page_idx, page_text in enumerate(raw_pages):
        page_lines: list[str] = []
        source_lines = page_text.splitlines()
        margin = _margin_positions(source_lines)
        for line_idx, line in enumerate(source_lines):
            stripped = re.sub(r'\s+', ' ', line.strip())
            if not stripped:
                page_lines.append("")
                continue

            normalized = normalize_header_footer_candidate(stripped)
            should_remove = False
            if line_idx in margin and stripped in repeated_lines and _plausible_running_header(stripped):
                should_remove = True
            elif line_idx in margin and normalized and normalized in repeated_normalized and _plausible_running_header(stripped):
                should_remove = True
            elif line_idx in margin and re.fullmatch(r'\d{1,4}', stripped):
                should_remove = True
            elif line_idx in margin and any(p.fullmatch(stripped) for p in HF_EXTRA_PATTERNS):
                should_remove = True

            # No eliminar headings narrativos legítimos.
            if should_remove and is_structural_heading_line(stripped):
                should_remove = False

            if should_remove:
                if config.get("verbose") and verbose_removed < 10:
                    print(f"  [Limpieza] Header/footer residual eliminado p.{page_idx + 1}: {repr(stripped)}")
                    verbose_removed += 1
                continue
            page_lines.append(stripped)
        paragraphs = reconstruct_paragraphs(page_lines, config)
        result.append(paragraphs)

    return result


def reconstruct_paragraphs(lines: list[str], config: dict) -> list[str]:
    """
    Reconstruye párrafos a partir de líneas sueltas.
    Heurísticas:
    - Línea vacía → salto de párrafo definitivo
    - Línea estructural (Prólogo / Capítulo / Parte / etc.) → párrafo propio
    - Línea de subtítulo tras heading estructural → párrafo propio
    - Línea que termina con guión de silabeo → unir con la siguiente
    - Línea que termina en punto/interrogación/exclamación → párrafo completo
    """
    paragraphs: list[str] = []
    current: list[str] = []

    END_PUNCTUATION = re.compile(r"[.!?»\"'—\u201d\u2019]$")
    DIALOG_START = re.compile(r'^[—–\-"«\u201c\u2018]')
    SENTENCE_START = re.compile(r'^[A-ZÁÉÍÓÚÜÑ"«\u201c\u2018—–]')
    HYPHEN_END = re.compile(r'-$')

    prev_nonempty = ""
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line == "":
            if current:
                paragraphs.append(" ".join(current))
                current = []
            i += 1
            continue

        if is_structural_heading_line(line):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            paragraphs.append(_normalize_heading_text(line))
            prev_nonempty = _normalize_heading_text(line)
            i += 1
            continue

        if prev_nonempty and is_structural_heading_line(prev_nonempty) and looks_like_section_subtitle(line):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            paragraphs.append(_normalize_heading_text(line))
            prev_nonempty = _normalize_heading_text(line)
            i += 1
            continue

        if HYPHEN_END.search(line) and i + 1 < len(lines) and lines[i + 1].strip():
            next_line = lines[i + 1].strip()
            if next_line and next_line[0].islower():
                current.append(line[:-1] + next_line)
                prev_nonempty = next_line
                i += 2
                continue

        current.append(line)
        prev_nonempty = line

        close_paragraph = False
        if END_PUNCTUATION.search(line):
            close_paragraph = True
        elif i + 1 < len(lines) and lines[i + 1].strip():
            next_line = lines[i + 1].strip()
            if is_structural_heading_line(next_line):
                close_paragraph = True
            elif SENTENCE_START.match(next_line) or DIALOG_START.match(next_line):
                close_paragraph = True

        if close_paragraph:
            paragraphs.append(" ".join(current))
            current = []

        i += 1

    if current:
        paragraphs.append(" ".join(current))

    result = []
    for p in paragraphs:
        p = p.strip()
        if p and len(p) > 1:
            result.append(p)
    return result


def _looks_like_visual_separator_text(text: str) -> bool:
    """Heurística para páginas visuales con muy poco texto útil."""
    cleaned = _clean_page_number_only(text)
    compact = re.sub(r"\s+", " ", cleaned).strip()
    if not compact:
        return True
    if len(compact) <= 70:
        return True

    line_count = len([ln for ln in cleaned.splitlines() if ln.strip()])
    alpha_words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ']+", compact)
    if line_count <= 4 and len(alpha_words) <= 14:
        narrative_punct = sum(compact.count(ch) for ch in '.!?¿¡;:')
        if narrative_punct <= 1:
            return True
    return False


def _clean_page_number_only(text: str) -> str:
    return re.sub(r'^\s*\d{1,4}\s*$', '', (text or '').strip())


def _estimate_garbage_score(text: str) -> float:
    """Heurística simple para detectar texto corrupto/mojibake extraído del PDF."""
    cleaned = _clean_page_number_only(text)
    if not cleaned:
        return 1.0

    nonspace = ''.join(ch for ch in cleaned if not ch.isspace())
    if not nonspace:
        return 1.0

    allowed_re = r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9\s\.,;:!\?¡¿()\[\]\{\}\-—–_\"'/%&@#=+*…ºª€$]"
    weird_chars = sum(1 for ch in cleaned if not re.match(allowed_re, ch))
    weird_ratio = weird_chars / max(1, len(nonspace))

    # Tokens con demasiados símbolos internos suelen indicar extracción mala.
    suspicious_tokens = re.findall(r"\b\S*[\*\[\]\{\}\|\\`~^<>_]\S*\b", cleaned)
    tokens = re.findall(r"\b\S+\b", cleaned)
    suspicious_ratio = len(suspicious_tokens) / max(1, len(tokens))

    # Si casi no hay letras, probablemente es una imagen, tabla o basura.
    alpha_chars = sum(ch.isalpha() for ch in cleaned)
    alpha_ratio = alpha_chars / max(1, len(nonspace))
    alpha_penalty = 0.25 if alpha_ratio < 0.55 else 0.0

    score = weird_ratio + suspicious_ratio + alpha_penalty
    return min(1.0, score)


