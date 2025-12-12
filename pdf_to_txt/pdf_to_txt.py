#!/usr/bin/env python3
"""
Small CLI to extract text from a PDF and save it to a .txt file.
Tries multiple extraction methods in order: PyMuPDF (fitz), pdftotext, pdfminer.six

Usage:
    python pdf_to_txt.py input.pdf output.txt
If output.txt is omitted, the script will use input filename with .txt extension.

You can also set the input file directly in the script by modifying INPUT_FILE below.
"""
import sys
from pathlib import Path
from io import BytesIO

# Set your input file here (can be a local path or URL)
# Examples:
#   INPUT_FILE = "/Users/ah3264/Documents/Crossref_XML/myfile.pdf"
#   INPUT_FILE = "https://example.com/paper.pdf"
#   INPUT_FILE = None  # Use command-line arguments
INPUT_FILE = "https://mau.diva-portal.org/smash/get/diva2:1897522/FULLTEXT01.pdf"

# Lazy imports for optional dependencies
fitz = None
extract_text = None
requests = None
certifi = None

def _lazy_import_pymupdf():
    global fitz
    if fitz is None:
        try:
            import fitz as _fitz
        except Exception:
            return None
        fitz = _fitz
    return fitz

def _lazy_import_pdfminer():
    global extract_text
    if extract_text is None:
        try:
            from pdfminer.high_level import extract_text as _extract_text
        except Exception:
            return None
        extract_text = _extract_text
    return extract_text


def pdf_to_text(input_path: Path, output_path: Path) -> None:
    """Accept either a local PDF path or an http/https URL as input_path.

    If input_path is a URL the PDF is fetched via HTTP and the response is
    validated to be a PDF by checking the Content-Type header. Non-PDF
    responses are saved to 'downloaded_file.html' for inspection and an
    exception is raised.
    
    Extraction order: PyMuPDF (fitz) → pdftotext → pdfminer.six
    """
    # Determine if input_path is a URL
    s = str(input_path)
    is_url = s.startswith('http://') or s.startswith('https://')

    def _try_pymupdf(pdf_source) -> str | None:
        """Try PyMuPDF (fitz) extraction. Accepts Path or BytesIO."""
        fitz_module = _lazy_import_pymupdf()
        if fitz_module is None:
            return None
        try:
            if isinstance(pdf_source, BytesIO):
                doc = fitz_module.open(stream=pdf_source.getvalue(), filetype="pdf")
            else:
                doc = fitz_module.open(str(pdf_source))
            text = "\n".join([page.get_text() for page in doc])
            doc.close()
            return text if text.strip() else None
        except Exception:
            return None

    def _try_pdftotext(pdf_path: Path) -> str | None:
        """Try Poppler's pdftotext CLI tool."""
        try:
            import subprocess
            # use -layout to preserve a bit of layout; output to stdout
            proc = subprocess.run(['pdftotext', '-layout', str(pdf_path), '-'], check=True, capture_output=True)
            return proc.stdout.decode('utf-8', errors='replace')
        except FileNotFoundError:
            return None
        except subprocess.CalledProcessError:
            return None
    
    def _try_pdfminer(pdf_source) -> str | None:
        """Try pdfminer.six extraction. Accepts Path or BytesIO."""
        pdfminer = _lazy_import_pdfminer()
        if pdfminer is None:
            return None
        try:
            if isinstance(pdf_source, BytesIO):
                return pdfminer(pdf_source)
            else:
                return pdfminer(str(pdf_source))
        except Exception:
            return None

    if is_url:
        # Lazy import requests and certifi to avoid hard dependency unless needed
        try:
            import requests
        except Exception:
            raise RuntimeError('requests is required to fetch remote PDFs; install requests or pass a local file')
        # choose a CA bundle: prefer combined_ca.pem in repo if present
        verify = 'combined_ca.pem' if Path('combined_ca.pem').exists() else True
        try:
            from importlib import import_module
            certifi = import_module('certifi')
            if verify is True:
                verify = certifi.where()
        except Exception:
            # certifi optional; keep verify as-is
            pass

        resp = requests.get(s, headers={'User-Agent': 'Mozilla/5.0'}, allow_redirects=True, verify=verify)
        ctype = resp.headers.get('Content-Type', '')
        if 'application/pdf' not in ctype:
            # save for inspection
            with open('downloaded_file.html', 'wb') as f:
                f.write(resp.content)
            raise RuntimeError(f'URL did not return a PDF (Content-Type: {ctype}); saved response to downloaded_file.html')
        pdf_file = BytesIO(resp.content)
        
        # Try extraction methods in order: PyMuPDF → pdftotext → pdfminer
        text = _try_pymupdf(pdf_file)
        if text:
            print("Extracted using PyMuPDF")
        else:
            # Save to temp file for pdftotext
            try:
                from tempfile import NamedTemporaryFile
                with NamedTemporaryFile(suffix='.pdf', delete=False) as tf:
                    tf.write(resp.content)
                    temp_path = Path(tf.name)
                text = _try_pdftotext(temp_path)
                if text:
                    print("Extracted using pdftotext")
                else:
                    pdf_file.seek(0)
                    text = _try_pdfminer(pdf_file)
                    if text:
                        print("Extracted using pdfminer")
                temp_path.unlink()
            except Exception:
                pass
        
        if not text:
            raise RuntimeError("Failed to extract text using any available method")
        output_path.write_text(text, encoding='utf-8')
    else:
        p = Path(input_path)
        if not p.exists():
            raise FileNotFoundError(f"Input PDF not found: {p}")
        
        # Try extraction methods in order: PyMuPDF → pdftotext → pdfminer
        text = _try_pymupdf(p)
        if text:
            print("Extracted using PyMuPDF")
        else:
            text = _try_pdftotext(p)
            if text:
                print("Extracted using pdftotext")
            else:
                text = _try_pdfminer(p)
                if text:
                    print("Extracted using pdfminer")
        
        if not text:
            raise RuntimeError("Failed to extract text using any available method")
        output_path.write_text(text, encoding="utf-8")


def main(argv):
    # Use INPUT_FILE from the script if set, otherwise require command-line argument
    if INPUT_FILE is not None:
        raw_in = INPUT_FILE
        # If output is provided as command-line arg, use it
        output_override = argv[1] if len(argv) >= 2 else None
    elif len(argv) < 2:
        print("Usage: python pdf_to_txt.py input.pdf [output.txt]")
        print("  Or set INPUT_FILE in the script")
        return 2
    else:
        raw_in = argv[1]
        output_override = None
    # Detect URL before converting to Path because Path() can mangle URL
    # strings with schemes (e.g. it may collapse 'https://' to 'https:/').
    is_url = raw_in.startswith('http://') or raw_in.startswith('https://')
    if is_url:
        input_arg = raw_in
        if output_override:
            output_path = Path(output_override)
        elif len(argv) >= 3:
            output_path = Path(argv[2])
        else:
            # derive a sensible output filename from the URL path
            from urllib.parse import urlparse, unquote
            parsed = urlparse(raw_in)
            candidate = Path(unquote(parsed.path)).name or 'output'
            output_path = Path(candidate).with_suffix('.txt')
    else:
        input_arg = Path(raw_in)
        if output_override:
            output_path = Path(output_override)
        elif len(argv) >= 3:
            output_path = Path(argv[2])
        else:
            output_path = input_arg.with_suffix('.txt')
    try:
        pdf_to_text(input_arg, output_path)
        print(f"Saved text to: {output_path}")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
