# -*- coding: utf-8 -*-
"""Helpers pequeños relacionados con rutas y clasificación de páginas PDF."""

import re
import sys
from pathlib import Path

from .text_utils import _clean_page_number_only, _looks_like_visual_separator_text


# Umbral: una página se considera "solo imagen" si tiene muy poco texto real
IMAGE_PAGE_TEXT_THRESHOLD = 20  # caracteres (excluyendo número de página)


def get_base_dir() -> Path:
    """Devuelve la carpeta base tanto en script normal como en PyInstaller."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def get_tesseract_cmd(user_path=None):
    """
    Prioridad:
    1) ruta pasada por usuario
    2) tesseract embebido junto al proyecto / ejecutable
    3) comando global del sistema
    """
    if user_path:
        user_path = str(user_path).strip().strip('"')
        if user_path and Path(user_path).exists():
            return user_path

    base_dir = get_base_dir()
    local = base_dir / "tesseract" / "tesseract.exe"
    if local.exists():
        return str(local)

    return "tesseract"


def _is_image_only_page(text: str) -> bool:
    """Devuelve True si la página es prácticamente solo una imagen (sin texto real)."""
    cleaned = _clean_page_number_only(text)
    compact = re.sub(r"\s+", " ", cleaned).strip()
    if len(compact) < IMAGE_PAGE_TEXT_THRESHOLD:
        return True
    if _looks_like_visual_separator_text(compact):
        return True
    return False


