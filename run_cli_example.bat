@echo off
cd /d %~dp0
python pdf2epub.py "u2.1 (1).pdf" -o "u2.1_ocr.epub" --ocr auto --ocr-lang spa+eng
pause
