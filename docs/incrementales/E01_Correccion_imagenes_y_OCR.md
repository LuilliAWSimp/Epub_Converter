# E01 — Corrección de extracción de imágenes y OCR

**Base:** `Epub_Converter-main.zip` original entregado para auditoría.

## Objetivo

Corregir la extracción de ilustraciones y el OCR de documentos PDF, tanto con la interfaz Flask como por línea de comandos, sin alterar el diseño visual ni el algoritmo de detección de capítulos.

## Cambios

- `pdf2epub.py`: retirada la segunda implementación de las funciones de lectura del PDF, extracción de imágenes y OCR, que ocultaba (`shadowing`) las funciones importadas de `converter/pdf_extract.py`. Esa copia carecía de imports como `io` y `pytesseract`. Ambas formas de ejecución usan las mismas funciones del módulo centralizado.
- `converter/pdf_extract.py`: selección de Tesseract **ejecutable** y compatible con el sistema operativo. En Windows se prueba el ejecutable incluido, luego las ubicaciones de instalación habituales y el disponible en PATH. Si el ejecutable incluido no arranca por DLL faltantes, se intenta otro que sí funcione.
- En sistemas distintos de Windows ya no se intenta ejecutar `tesseract.exe` de Windows.
- Detección explícita de paquetes de idiomas antes del procesamiento OCR; se informa cuáles faltan.
- En modo `force`, los errores reales del OCR interrumpen la conversión y ya no se ocultan detrás de un supuesto éxito. Si no se reconoce texto en ninguna página, también se muestra error.
- En modo `auto`, si el motor OCR falla, se preserva la extracción original y se muestra una **advertencia**, incluyendo conteos de páginas fallidas. No se miente sobre el número de páginas OCR reconocidas.
- OCR por lotes evita comprobar una y otra vez la instalación de Tesseract durante cada página.
- `tests/test_e01_extraction_ocr.py`: siete pruebas de regresión que generan PDFs temporales; verifican integración con el EPUB, reconocimiento de PDF escaneado, desactivación OCR, idioma faltante y errores del motor.

## Instalación incremental

1. Conservar una copia de seguridad del proyecto original.
2. Extraer `Incremental_E01_Epub_Converter.zip` directamente sobre la raíz del proyecto que contiene `pdf2epub.py` y `converter/`, respetando rutas y sustituyendo los archivos del mismo nombre.
3. No es necesario volver a instalar dependencias Python si las originales ya estaban instaladas (`requirements.txt` no cambió).
4. Arrancar normalmente con `run_gui_autoinstall.bat` en Windows o con `python gui.py` en un entorno con Flask instalado.

## Requisito del OCR en Windows

El archivo `tesseract/tesseract.exe` del ZIP base **no incluye todas las DLL necesarias**. E01 detecta si no logra ejecutarse y busca otra instalación válida. Si no existe ninguna, instalar Tesseract OCR para Windows, incluyendo idiomas `spa` y `eng`; el OCR se podrá usar después de reiniciar la aplicación. **E01 no incluye un instalador de Tesseract ni reemplaza el ejecutable distribuido**.

## Prueba rápida

Desde la carpeta que contiene `pdf2epub.py`:

```sh
python -m unittest discover -s tests -v
python pdf2epub.py "ejemplo.pdf" -o "ejemplo.epub" --ocr off
python pdf2epub.py "escaneado.pdf" -o "escaneado.epub" --ocr force --ocr-lang spa+eng
```

Para `force` debe estar instalado y operativo Tesseract con los idiomas solicitados.

### Resultados verificados (Linux)

- 7/7 pruebas automáticas correctas (incluida extracción de imágenes, EPUB final y OCR con Tesseract real).
- PDF de prueba ilustrado: EPUB incluye `img001.jpg` y su referencia XHTML.
- PDF narrativo de cinco páginas, OCR `force`: reemplazó cinco páginas con texto reconocido.

### Límites de esta entrega

- **E02:** permanece pendiente la integridad de textos, posibles capítulos vacíos y el escape/validación XHTML.
- **E03:** permanece pendiente conectar los controles OCR visibles en la interfaz a sus parámetros `ocr_mode`/`ocr_lang`. Actualmente la interfaz solicita los valores por defecto (`auto`, `spa+eng`); la CLI sí permite seleccionar modos e idiomas.
- **E04:** seguridad del servidor web, aislamiento de trabajos concurrentes y limpieza de temporales no se modifican.
- No se pudo ejecutar ni validar el OCR en Windows en este entorno de pruebas; sí se ejecutó en Linux con un Tesseract instalado.

## Archivos incluidos

- `pdf2epub.py`
- `converter/pdf_extract.py`
- `tests/test_e01_extraction_ocr.py`
- `docs/incrementales/E01_Correccion_imagenes_y_OCR.md`

## Commit sugerido (GitHub Desktop)

`E01: corregir extracción de imágenes y OCR con pruebas de regresión`
