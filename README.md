# PDF → EPUB Converter v2 con OCR

Proyecto local para convertir PDF a EPUB con dos rutas de extracción:

- extracción normal para PDFs con texto real
- OCR opcional para páginas escaneadas o con texto corrupto

## Contenido

- `pdf2epub.py`: motor principal PDF → EPUB.
- `gui.py`: interfaz web local.
- `requirements.txt`: dependencias Python.
- `run_gui.bat`: arranca la GUI.
- `run_cli_example.bat`: ejemplo CLI.

## Requisitos

- Python 3.11 o superior recomendado.
- Windows, Linux o macOS.
- **Tesseract OCR** instalado si quieres usar OCR.

## Instalar dependencias Python

```bash
python -m venv .venv
```

### Windows

```bash
.venv\Scripts\activate
pip install -r requirements.txt
```

### Linux / macOS

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Instalar Tesseract OCR

### Windows

Instala Tesseract y asegúrate de que `tesseract.exe` quede en el `PATH` del sistema.
Si no queda en `PATH`, puedes pasar su ruta con `--tesseract-cmd`.

### Linux

```bash
sudo apt install tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng
```

### macOS

```bash
brew install tesseract
brew install tesseract-lang
```

## Uso por línea de comandos

### Sin OCR

```bash
python pdf2epub.py "Volumen 15.pdf" -o "Volumen 15.epub"
```

### OCR automático

```bash
python pdf2epub.py "u2.1 (1).pdf" -o "u2.1.epub" --ocr auto --ocr-lang spa+eng
```

### OCR forzado en todas las páginas

```bash
python pdf2epub.py "u2.1 (1).pdf" -o "u2.1_ocr.epub" --ocr force --ocr-lang spa+eng
```

### Si `tesseract.exe` no está en PATH

```bash
python pdf2epub.py "u2.1 (1).pdf" -o "u2.1_ocr.epub" --ocr auto --ocr-lang spa+eng --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

## Uso con interfaz web

```bash
python gui.py
```

Luego abre en tu navegador:

- `http://localhost:7474`

La GUI incluye:

- selector de modo OCR: desactivado, auto o forzado
- idiomas OCR
- recarga de `pdf2epub.py` desde disco al convertir

## Qué mejora esta v2

- mantiene el arreglo del orden de imágenes internas
- puede relanzar OCR solo en páginas problemáticas
- sirve mejor para PDFs escaneados o con capa de texto muy dañada

## Limitaciones

- tablas, fórmulas y diagramas pueden seguir quedando imperfectos
- el OCR mejora mucho texto corrido, pero no “entiende” la maquetación compleja como un humano
- para novelas y textos lineales suele dar mejores resultados que para libros técnicos
