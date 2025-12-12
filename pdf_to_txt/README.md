# PDF to TXT extractor

Small script to extract text from a PDF and save it to a .txt file using pdfminer.six.

Install:

```bash
python -m pip install -r requirements.txt
```

Usage:

```bash
python pdf_to_txt.py input.pdf output.txt
# or
python pdf_to_txt.py input.pdf
# (will create input.txt)
```

Notes:
- Works on macOS with zsh. Ensure Python 3.8+ is available.
- For large PDFs extraction may be slow and use significant memory.
