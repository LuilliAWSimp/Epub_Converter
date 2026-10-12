# E03 — Controles OCR y detección de capítulos

**Base:** `Epub_Converter-main.zip` con E01 y E02 aplicados, en ese orden.

## Objetivo

Conectar las opciones de OCR que ya muestra la interfaz web al motor real y mejorar la clasificación de índices, encabezados y subtítulos evitando perder narración. Conservar la interfaz existente, los parámetros de la CLI y la validación de EPUB de E02.

## Correcciones incluidas

### Interfaz web y OCR (`gui.py`)

- `startConversion()` agrega a `FormData` el valor del selector `f-ocr-mode` y el idioma del campo `f-ocr-lang` (recortando espacios externos).
- `/api/convert` recibe y valida `off`, `auto` y `force`, además de listas de idiomas como `spa`, `eng` o `spa+eng`, **antes de guardar archivos**.
- Los parámetros verificados se entregan al hilo de conversión en `config`, que utiliza la implementación OCR de E01.
- Si OCR está desactivado, el idioma no se usa: un texto erróneo en ese campo no impide continuar y se sustituye por el valor por defecto.
- Si OCR está en `auto`/`force` y se envían opciones inválidas, el servidor devuelve `400` con un mensaje de error claro.
- **No** se modificó el HTML visual, su CSS, ni los requisitos de instalación.

### Detección de capítulos (`converter/chapters.py`, `pdf2epub.py`)

- Se eliminó de `pdf2epub.py` un bloque de **funciones duplicadas de capítulos** que sobrescribía las importaciones desde `converter/chapters.py` (situación similar a la de extracción corregida en E01). CLI y Flask ahora comparten el mismo motor de capítulos.
- Una aparición de las palabras «contenido», «índice» o «contents» dentro de un párrafo narrativo ya no se considera automáticamente una página de índice. Se requieren encabezados de índice identificables o entradas de índice coherentes.
- Los subtítulos reconocidos deben parecer títulos breves; oraciones narrativas con puntuación final se mantienen en el cuerpo del libro, no se consumen como subtítulos.
- Siguen admitiéndose subtítulos explícitos tras `Capítulo II: ...`, incluso con punto final, y capítulos romanos conservan números en mayúsculas: `Capítulo II`, no `Capítulo Ii`.
- Cuando la página tiene texto antes del encabezado de un capítulo nuevo, el texto previo se incorpora a la sección anterior en lugar de perderse.
- Mejor clasificación de encabezados breves numerados, evitando confundir frases numeradas terminadas en punto con títulos.
- Se conserva la detección de TOC, los capítulos y la integración de ilustraciones en la generación EPUB existente. La validación de integridad E02 sigue activa.

## Archivos incluidos en este ZIP

```text
gui.py
pdf2epub.py
converter/chapters.py
tests/test_e03_ocr_chapters.py
docs/incrementales/E03_Controles_OCR_y_capitulos.md
```

## Aplicación

1. Respaldar el proyecto.
2. Aplicar E01 y E02, en ese orden, **antes de E03**.
3. Descomprimir este ZIP en la raíz donde está `pdf2epub.py`, sustituyendo los archivos y respetando las carpetas `converter/`, `tests/` y `docs/incrementales/`.
4. Continuar iniciando la aplicación como antes.

Para verificar:

```sh
python -m unittest discover -s tests -v
python pdf2epub.py "libro.pdf" -o "libro.epub" --ocr off
```

**Prueba dirigida en Windows (GUI):** abrir `http://localhost:7474`, seleccionar un PDF y probar por separado (1) `OCR desactivado`, (2) `OCR auto` y (3) `Forzar`, seleccionando `spa+eng` o `eng`; verificar registros y EPUB final. Para `force` debe estar instalado Tesseract con los idiomas elegidos. Si el paquete de Tesseract de Windows carece de DLL, seguirá necesitando una instalación funcional (no forma parte de E03).

## Validación ejecutada

- **33/33 tests automatizados aprobados** (7 E01, 12 E02 y 14 E03).
- Prueba real de la función JavaScript `startConversion()` con Node.js y DOM simulado: envía correctamente `force` y `spa+eng`.
- Pruebas de la ruta POST con sustitutos controlados de Flask: comprueban el paso de `ocr_mode` y `ocr_lang` a `config`, así como respuestas 400 sin guardar PDF en entradas inválidas.
- Casos de capítulos: tabla de contenido real, texto con «contenido», subtítulos, numeración romana y prosa anterior a un encabezado.
- Conversión real por consola de PDF narrativo de 5 páginas (`--ocr off`): EPUB generado con **5 capítulos y 40 párrafos**, validación E02 exitosa.
- Se ejecutaron nuevamente las pruebas E01 de imágenes y OCR con Tesseract disponible en Linux.
- El entorno de trabajo **no dispone de Flask** ni acceso al índice de paquetes para instalarlo: **no se inició el servidor ni se probó en un navegador real**. La ruta de POST se probó con objetos simulados; queda prueba dirigida en Windows.

## Fuera de alcance

- E04: seguridad de red de Flask, configuración remota de Tesseract, aislamiento de trabajos y limpieza de temporales.
- E05: optimización para PDF grandes y ubicación precisa de imágenes en páginas con cambios de capítulo.
- E06: EPUBCheck y pruebas exhaustivas en lectores EPUB.

## Commit sugerido (GitHub Desktop)

`E03: conectar controles OCR y mejorar detección de capítulos`
