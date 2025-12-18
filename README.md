# Crossref DiVA Pipeline

Automated pipeline for extracting references from academic publications and registering DOIs with Crossref. Designed for DiVA (Digitala Vetenskapliga Arkivet) institutional repositories, with support for dissertations, reports, books, and journal articles.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Quick Start](#quick-start)
- [Core Pipeline Scripts](#core-pipeline-scripts)
- [Supporting Utilities](#supporting-utilities)
- [CSV-Based Batch Processing](#csv-based-batch-processing)
- [Preprocessing & Repair Tools](#preprocessing--repair-tools)
- [Troubleshooting](#troubleshooting)
- [File Structure](#file-structure)
- [Contributing](#contributing)
- [License](#license)

## Overview

This pipeline automates the process of:
1. **Extracting bibliographic metadata** from DiVA MODS XML exports
2. **Parsing references** from PDF publications using intelligent heuristics
3. **Generating Crossref-compliant XML** (schema 5.4.0)
4. **Registering DOIs** via Crossref deposit API

**Key capabilities:**
- APA and non-APA reference extraction with numbered-list detection
- Support for dissertations, reports, books (monographs and edited volumes)
- Batch CSV processing with HTML/PDF reference scraping
- Smart page-range detection and hyphen-joining for PDF artifacts
- Institutional metadata (ROR, ISNI, Wikidata) for Malmö University

## Features

- ✅ **Multi-format support**: Dissertations, reports, books, journal articles
- ✅ **Intelligent reference parsing**: APA-style with fallback heuristics
- ✅ **Batch processing**: CSV-based workflows for bulk deposits
- ✅ **Metadata enrichment**: Automatic institutional IDs (ROR/ISNI/Wikidata)
- ✅ **Debug capabilities**: Numbered debug files with canonical naming (controlled by DOIREF_DEBUG)
- ✅ **Secure credential management**: Environment variable support via `.env`
- ✅ **XSLT transformation**: MODS → Crossref XML with namespace handling
- ✅ **Multi-backend PDF extraction**: PyMuPDF, pdfminer, pdftotext fallback
- ✅ **Smart extractor selection**: Automatic PDF extractor choice based on reference type
- ✅ **Adaptive re-extraction**: Switches extractors when numbered references detected

## Prerequisites

### Required Software
- **Python 3.8+** (tested with 3.9-3.11)
- **Java 11+** (for Crossref upload tool)
- **Git** (for version control)

### System Dependencies (Optional)
- `pdftotext` (Poppler utils) - fallback PDF extractor
  ```bash
  # macOS
  brew install poppler
  
  # Ubuntu/Debian
  sudo apt-get install poppler-utils
  ```

### Crossref Account
- Active Crossref membership with deposit credentials
- Username and password from Crossref dashboard
- [crossref-upload-tool.jar](https://github.com/CrossRef/doiserver) downloaded

## Installation

### 1. Clone the Repository
```bash
git clone https://github.com/your-org/crossref-diva-pipeline.git
cd crossref-diva-pipeline
```

### 2. Install Python Dependencies
```bash
pip install -r requirements.txt
```

**Dependencies installed:**
- `lxml` - XML/XSLT processing
- `pandas` - CSV data handling
- `requests` - HTTP requests for PDF/HTML fetching
- `beautifulsoup4` - HTML reference extraction
- `python-dotenv` - Environment variable management
- `PyMuPDF` (fitz) - PDF text extraction
- `pdfminer.six` - Alternative PDF extraction

### 3. Configure Credentials
```bash
# Copy template to create your .env file
cp .env.example .env

# Edit .env with your credentials
nano .env  # or use your preferred editor
```

**Required values in `.env`:**
```
CROSSREF_USERNAME=your_username
CROSSREF_PASSWORD=your_password
CROSSREF_DEPOSITOR_NAME=your_org:your_org
CROSSREF_EMAIL=your.email@your-organization.org
CROSSREF_REGISTRANT=Your Organization Name
```

📖 **See [GITHUB_SECURITY.md](GITHUB_SECURITY.md)** for detailed security setup and best practices.

### 4. Download Crossref Upload Tool
```bash
# Download the JAR file
curl -L -o crossref-upload-tool.jar \
  https://github.com/CrossRef/doiserver/releases/download/v1.0/crossref-upload-tool.jar

# Or manually download from:
# https://github.com/CrossRef/doiserver/releases
```

Update JAR path in scripts if needed (default: `~/Documents/Crossref_XML/crossref-upload-tool.jar`).

## Configuration

### Environment Variables

All scripts auto-load `.env` via `python-dotenv`. Override any variable at runtime:

```bash
CROSSREF_USERNAME=test python csv_reg.py
```

**Core credentials:**
| Variable | Purpose | Default |
|----------|---------|---------|
| `CROSSREF_USERNAME` | Crossref login | **(required)** |
| `CROSSREF_PASSWORD` | Crossref password | **(required)** |
| `CROSSREF_DEPOSITOR_NAME` | Depositor ID | `malmo:malmo` |
| `CROSSREF_EMAIL` | Contact email | `depositor@example.com` |
| `CROSSREF_REGISTRANT` | Organization name | `Malmö University` |

**Reference extraction:**
| Variable | Purpose | Default |
|----------|---------|---------|
| `DOIREF_USE_TXT` | Force TXT mode instead of PDF | `False` |
| `DOIREF_TXT_PATH` | Path when TXT mode enabled | - |
| `DOIREF_MAX_ITER` | Max numbered-list join iterations | `10` |
| `DOIREF_DEBUG_DIR` | Custom debug output directory | `debug/` |
| `DOIREF_DEBUG` | Enable debug file creation (1/true/yes/on) | `False` |
| `DOIREF_EXTRACTOR` | Force specific PDF extractor (pymupdf/pdfminer) | auto-selected |
| `CSV_SAVE_REFS_TXT` | Save references in CSV pipeline | `True` |

## Quick Start

### Single Publication (DiVA MODS Export)
```bash
# 1. Export MODS metadata from DiVA to export.xml
# 2. Run the pipeline
python doireg.py

# Outputs:
# - doireg_<DOI_suffix>.xml: Crossref deposit XML
# - references_singleline.txt: Extracted references
# - Uploads to Crossref automatically
```

### Batch Processing (CSV)
```bash
# 1. Prepare DOI.csv with required columns (see CSV-BASED BATCH PROCESSING)
# 2. Run batch registration
python csv_reg.py

# Outputs:
# - crossref_output.xml: Batch Crossref XML
# - <DOI_suffix>.txt: Per-article references (if enabled)
# - Uploads to Crossref automatically
```

### Reference Extraction Only
```bash
# From PDF URL
python doiref.py https://example.com/paper.pdf output.txt

# From local PDF
python doiref.py /path/to/paper.pdf output.txt

# With options
python doiref.py paper.pdf refs.txt --ref-type F --strip-numbers --min-page-number 80
```

### Generate Crossref XML (No Upload)
```bash
# CSV to XML only (skip upload step)
python csv-crossref.py
# Output: crossref_output.xml
```

## Core Pipeline Scripts

### DiVA-CrossRef.xslt
------------------
XSLT 1.0 stylesheet transforming DiVA MODS metadata to Crossref 5.4.0 XML.

Purpose:
  Converts MODS (Metadata Object Description Schema) exports from DiVA into
  Crossref-compliant XML for DOI registration and metadata deposit.

Parameters:
  currentDateTime     Timestamp for deposit batch (YYYY-MM-DDTHH:MM:SS format)
                      Default: '1970-01-01T00:00:00'
                      Used for: doi_batch_id and timestamp elements
  
  genreOverride       Optional publication type override (empty string uses MODS genre)
                      Values: 'dissertation', 'report', 'book' (monograph), 'coll' (edited_book)
                      Default: '' (auto-detect from mods:genre)

Supported Publication Types:
  1. Dissertations (dissertation)
     - Detection: mods:genre[@authority='kev'] = 'dissertation' or genreOverride='dissertation'
     - Elements: approval_date, institution (with ROR/ISNI/Wikidata for Malmö), degree
     - Degrees: Doctoral thesis, Licentiate thesis (from publicationTypeCode)
  
  2. Reports (report-paper)
     - Detection: mods:genre[@type='publicationTypeCode'] = 'report' or genreOverride='report'
     - Variants: With series (report-paper_series_metadata) or standalone (report-paper_metadata)
     - Series detection: Presence of mods:relatedItem/mods:identifier[@type='issn']
  
  3. Books (book)
     - Detection: mods:genre[@authority='kev'] = 'book' or genreOverride='book'/'coll'
     - Types: Monograph (default) or edited_book (mods:genre[@authority='svep'] = 'sam' or genreOverride='coll')
     - Variants: With series (book_series_metadata) or standalone (book_metadata)

Named Templates:
  emit-language-attribute
    - Converts MODS @lang to CrossRef language attribute
    - Input: lang parameter (e.g., 'eng', 'swe')
    - Output: xml:lang attribute (e.g., 'en', 'sv')
  
  render-contributors
    - Generates <contributors> with <person_name> elements
    - Parameters: roleTerm ('aut'/'edt'), contributorRole ('author'/'editor')
    - Handles: given_name, surname, suffix, sequence (first/additional), ORCID
  
  render-titles
    - Generates <titles> with <title> and optional <subtitle>
    - Sources: mods:titleInfo/mods:title and mods:subTitle
    - Namespace: http://www.crossref.org/schema/5.4.0
  
  render-isbn
    - Generates <isbn> elements from mods:identifier[@type='isbn']
    - Namespace: http://www.crossref.org/schema/5.4.0
  
  render-publisher
    - Generates <publisher> with <publisher_name> and <publisher_place>
    - Sources: mods:originInfo/mods:publisher and mods:place/mods:placeTerm
    - Namespace: http://www.crossref.org/schema/5.4.0
  
  render-doi-data
    - Generates <doi_data> with DOI and resource URL
    - Sources: mods:identifier[@type='doi'] and mods:location/mods:url
    - Namespace: http://www.crossref.org/schema/5.4.0
  
  render-abstracts
    - Generates <jats:abstract> with JATS paragraph formatting
    - Language mapping: 13 languages (eng→en, swe→sv, nor→no, dan→da, etc.)
    - HTML processing: Converts <p> tags to <jats:p>, strips other HTML
    - Handles: Pre-formatted HTML or plain text (auto-wrapped in jats:p)
  
  process-paragraphs
    - Recursively processes <p>...</p> tags in abstract text
    - Normalizes whitespace and non-breaking spaces (&#160;)
  
  strip-html
    - Removes HTML tags from text (not currently used in active templates)

Special Features:
  - Institutional IDs: Auto-adds ROR, ISNI, Wikidata for Malmö University affiliations
  - Approval Date: Extracts defense date from mods:dateOther[@type='defence'] (dissertations)
  - Publication Date: Falls back to mods:dateIssued if defense date unavailable
  - Series Detection: ISSN-based series metadata for books/reports
  - Namespace Preservation: Explicit xmlns declarations prevent xmlns="" artifacts

Namespaces:
  - CrossRef: http://www.crossref.org/schema/5.4.0
  - MODS: http://www.loc.gov/mods/v3
  - JATS: http://www.ncbi.nlm.nih.gov/JATS1
  - XLink: http://www.w3.org/1999/xlink

Input: MODS XML (mods:modsCollection/mods:mods)
Output: Crossref doi_batch XML with head (depositor, timestamp) and body (publication metadata)

doireg.py
---------
End-to-end DOI registration orchestrator for DiVA exports.

Workflow:
  1. Loads export.xml (MODS metadata) and applies XSLT transformation
  2. Extracts fulltext URL and DOI from MODS
  3. Calls doiref.py to extract references from the PDF
  4. Generates Crossref-ready XML with timestamp
  5. Uploads to Crossref using crossref-upload-tool.jar

Features:
  - Auto-derives output filename from DOI suffix (sanitized)
  - Detects page count from MODS <extent> and sets smart page-range hints:
    * --max-page-number clamped to [30, 800]
    * --min-page-number set to extent - 50 (minimum 30)
  - Forwards extracted references to XSLT pipeline

No CLI arguments (configured via hardcoded paths and export.xml).

doiref.py
---------
APA-style reference extractor with numbered-list fallback and heuristic joining.

Usage:
  python doiref.py [URL_OR_PATH] [OUTPUT_FILE] [OPTIONS]

Arguments:
  url                 PDF URL or local path (optional if env DOIREF_USE_TXT set)
  output_filename     Output TXT filename (default: references_singleline.txt)

Options:
  --ref-type {N,F}    Reference detection mode:
                        N = initials-based (default, e.g., "Smith, J.")
                        F = fullname-aware (e.g., "Smith, John" or "Smith, John A.")
  
  --strip-numbers     Remove leading numbering from references (e.g., "1. " → "")
  
  --max-prefix-digits NUM
                      Max digits in numeric prefix to strip (default: 3)
  
  --until-eof         Extract references until EOF instead of stopping at next section
  
  --no-numbered-fallback
                      Disable numbered-list fallback path even if thresholds met
  
  --audit-log PATH    Path to audit log file (empty string disables; default: None)
  
  --min-page-number NUM
                      Minimum page number for page-line detection (default: 50)
  
  --max-page-number NUM
                      Maximum page number for page-line detection (default: 400)
  
  --extractor {pymupdf,pdfminer}
                      PDF text extraction method (default: pdfminer)

Environment Variables:
  DOIREF_USE_TXT      Force TXT mode instead of PDF
  DOIREF_TXT_PATH     TXT file path when TXT mode enabled
  DOIREF_MAX_ITER     Max iterations for numbered-list joining (default: 10)

Outputs:
  - references_extracted.txt: Raw extracted reference section
  - [output_filename]: Normalized, joined reference lines
  - debug/: Debug snapshots when DEBUG=True in source

Detection Heuristics:
  - Numbered lists: [3], (3), or 3. prefixes (threshold: 15+ for brackets/parens, 10-30 for bare)
  - Line joining: parenthesized years, author continuations, editor tokens
  - Conservative merging: respects Prop./SOU markers, avoids swallowing new refs

doiref_nonapa.py
----------------
Non-APA reference extractor with relaxed year/author patterns.

Usage:
  python doiref_nonapa.py [URL_OR_PATH] [OUTPUT_FILE] [OPTIONS]

Arguments:
  url                 PDF URL or local path
  output_filename     Output TXT filename

Options:
  --ref-type {A,B,C,D}
                      Reference layout type:
                        A = year at end, initials (default)
                        B = year after authors, initials
                        C = year at end, full first names
                        D = year after authors, full first names
  
  --max-append NUM    Max lines to append when searching for year (default: 25)
  
  --audit-log PATH    Path to audit log file (default: audit_nonapa.txt)
  
  --until-eof         Extract until EOF instead of stopping at next section
  
  --min-page-number NUM
                      Minimum page number for detection (default: 50)
  
  --max-page-number NUM
                      Maximum page number for detection (default: 400)
  
  --extractor {pymupdf,pdfminer}
                      PDF text extraction method (default: pymupdf)

Differences from doiref.py:
  - No numbered-list fallback (uses fixed-point year-appending)
  - Looser year detection (accepts non-parenthesized years)
  - Type-based layout modes (A/B/C/D) instead of N/F
  - Separate audit log by default


## Supporting Utilities

parsing_helpers.py
------------------
Shared library for pattern building and text preprocessing.

Key Functions:
  - build_parenthesized_year_patterns(): Year regex variants (YEAR_PAREN, YEAR_SINGLE, etc.)
  - build_author_patterns(fullname_detection): Author/initial patterns for N/F modes
  - build_nonparenthesized_year_pattern(): Bare year regex (e.g., "2020")
  - load_and_preprocess(): Centralized PDF/TXT loading, hyphen joining, heading detection
  - should_attach_comma_fragment(): Heuristic for comma-led author continuations
  - move_doi_to_end(): Relocate DOI fragments to reference end
  - split_trailer_fragments(): Separate trailing "In: ..." or "Retrieved from..."
  - starts_with_prop_or_sou(): Detect Swedish government refs (Prop./SOU)
  - get_full_text(): Unified PDF/TXT fetching with SSL verification

Shared by: doiref.py, doiref_nonapa.py, and downstream tools.

debug_utils.py
--------------
Debug file management with canonical numbering and persistence.

Features:
  - Allocates sequential numbered filenames (001_filename.txt, 002_filename.txt, ...)
  - Maintains .map.json (base → canonical mapping) and .counter (sequence number)
  - Thread-safe with in-memory cache
  - Honors DOIREF_DEBUG_DIR env for custom debug location

Functions:
  - write_debug(name, content, canonicalize=True): Write debug output to canonical file
  - debug_path(name): Get full path for a debug file
  - clear_debug_txt(): Remove all .txt files from debug/ (preserves state files)
  - reset_debug_sequence(remove_prefixed_files=False): Reset counter to 001

Non-fatal: All operations catch exceptions to prevent pipeline crashes.


## CSV-Based Batch Processing

csv_reg.py
----------
CSV-to-Crossref registration orchestrator.

Workflow:
  1. Calls csv-crossref.py to generate crossref_output.xml from DOI.csv
  2. Uploads XML to Crossref using crossref-upload-tool.jar

Usage:
  python csv_reg.py [OPTIONS]

Options:
  --save-references-txt
                      Enable saving per-DOI references txt (default: ON)
  
  --no-save-references-txt
                      Disable saving per-DOI references txt

Configuration:
  - Credentials loaded from .env file (auto-loaded via python-dotenv)
  - See GITHUB_SECURITY.md for credential setup
  - JAR path: ~/Documents/Crossref_XML/crossref-upload-tool.jar

csv-crossref.py
---------------
Generates Crossref 5.4.0 XML from DOI.csv with optional reference scraping.

Usage:
  python csv-crossref.py [OPTIONS]

Options:
  --save-references-txt
                      Enable saving per-DOI references txt (default: ON)
  
  --no-save-references-txt
                      Disable saving per-DOI references txt

Environment Variables:
  CSV_SAVE_REFS_TXT   Override flag (accepts 1/true/yes/on or 0/false/no/off)

Input: DOI.csv (semicolon-separated, required columns vary)
Output: crossref_output.xml (Crossref deposit XML)

Reference Saving (when enabled):
  - Scrapes HTML from LINK TO ARTICLE for <div class='references'>
  - Fallback: Calls doiref.py with LINK TO PDF if no HTML refs found
  - Saves to <DOI_suffix>.txt (DOI sanitized for filename safety)

CSV Columns (common):
  - JOURNAL, ISSN, YEAR, VOLUME (VOL), ISSUE
  - TITLE, ABSTRACT, ABSTRACT LANG
  - PUBLICATION DATE (YYYY-MM-DD format)
  - DOI, LINK TO ARTICLE, LINK TO PDF
  - AU1 FIRST NAME, AU1 LAST NAME, AU1 AFFILIATION, AU1 ORCID, ...
  - AU1 ORGANIZATION (for corporate authors)
  - FIRST PAGE, LAST PAGE

Special Handling:
  - Malmö University affiliations auto-tagged with ROR/ISNI/Wikidata IDs
  - JATS abstract formatting with <jats:p>
  - Issue-level and article-level publication dates


## Preprocessing & Repair Tools

pdf_to_txt.py
-------------
Standalone PDF-to-text converter with multi-backend support.

Usage:
  python pdf_to_txt.py [INPUT.pdf] [OUTPUT.txt]

Arguments:
  INPUT.pdf           PDF file path or URL (optional if INPUT_FILE set in script)
  OUTPUT.txt          Output text file (default: INPUT.txt)

Extraction Order:
  1. PyMuPDF (fitz) - fastest, good layout preservation
  2. pdftotext (Poppler CLI) - fallback if PyMuPDF unavailable
  3. pdfminer.six - slowest, best for complex PDFs

Features:
  - URL support with Content-Type validation (rejects non-PDFs)
  - Downloads saved to downloaded_file.html for inspection on error
  - Auto-derives output filename from URL path if not specified
  - Can be configured via INPUT_FILE constant in script

fix_dashed_refs.py
------------------
Repairs dash-based reference continuations from PDF extraction artifacts.

Usage:
  python fix_dashed_refs.py [INPUT_FILE] [OPTIONS]

Arguments:
  input_file          Input file with references

Options:
  --output PATH, -o PATH
                      Output file (default: input_file.fixed.txt)
  
  --placeholder STR, -p STR
                      Placeholder to replace (default: "---. ")
  
  --in-place, -i      Modify input file in-place

Behavior:
  - Replaces "---. " with the last author prefix from previous reference
  - Handles multi-line references by tracking author context
  - Useful for fixing PDF extraction artifacts like:
      Smith, J. (2020). Title.
      ---. (2021). Another title.  → Smith, J. (2021). Another title.

## Troubleshooting

### Common Issues

**"CROSSREF_USERNAME and CROSSREF_PASSWORD environment variables must be set"**
- Ensure `.env` file exists and contains credentials
- Verify `python-dotenv` is installed: `pip install python-dotenv`
- Check that scripts have `load_dotenv()` at the top

**"Java not found" or JAR execution fails**
- Install Java 11+: `brew install openjdk@11` (macOS) or `sudo apt install openjdk-11-jre` (Ubuntu)
- Verify: `java -version`
- Update JAR path in scripts if not using default location

**PDF extraction returns empty text**
- Try different extractors: `--extractor pymupdf` or `--extractor pdfminer`
- Check if PDF is image-based (requires OCR, not supported)
- Verify PDF URL is accessible: `curl -I <URL>`

**No references detected**
- Check PDF page range: adjust `--min-page-number` and `--max-page-number`
- Try `--until-eof` to extract until end of document
- Use `--ref-type F` for full-name authors instead of initials
- Enable debug mode in source to inspect detection steps

**XSLT transformation fails**
- Verify `export.xml` contains valid MODS structure
- Check for namespace issues: `xmlns` should be `http://www.loc.gov/mods/v3`
- Validate genre detection: ensure `mods:genre[@authority='kev']` is set

**Upload to Crossref fails**
- Verify credentials are correct (test login on Crossref website)
- Check XML validates against schema: use Crossref validator tools
- Review Crossref deposit logs for error messages
- Ensure DOI prefix matches your organization's allocation

**Debug files created when DEBUG=False**
- Verify you're using latest version of scripts (DEBUG guards added)
- Check if `DEBUG` variable exists in script: `grep "DEBUG = " doiref.py`

### Getting Help

- **Check logs**: Review terminal output for error messages
- **Enable debug mode**: Set `DEBUG = True` in `doiref.py` to generate debug files
- **Validate XML**: Use [Crossref Schema Validator](https://www.crossref.org/06members/51depositor.html)
- **Test credentials**: Try manual upload with `crossref-upload-tool.jar`
- **Review documentation**: See [GITHUB_SECURITY.md](GITHUB_SECURITY.md) for credential issues

## File Structure

```
.
├── README.md                    # Project documentation
├── GITHUB_SECURITY.md           # Credential management guide
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variable template (copy to .env locally)
├── .gitignore                   # Git exclusions
├── DiVA-CrossRef.xslt           # MODS → Crossref XML transformer
├── doireg.py                    # Single-publication pipeline (applies XSLT)
├── csv_reg.py                   # CSV batch pipeline orchestrator
├── csv-crossref.py              # CSV → Crossref XML generator
├── doiref.py                    # APA reference extractor
├── doiref_nonapa.py             # Non-APA reference extractor
├── parsing_helpers.py           # Shared parsing utilities
├── debug_utils.py               # Debug file management
├── fix_dashed_refs.py           # Reference repair tool
├── pdf_to_txt/                  # PDF extraction utility
│   ├── README.md
│   └── pdf_to_txt.py
└── (local only, untracked) .env # Your credentials, not in git
```

## Contributing

Contributions are welcome! Please:

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/your-feature-name`
3. **Make your changes** with clear commit messages
4. **Test thoroughly**: Verify scripts work with sample data
5. **Update documentation**: Reflect changes in README/comments
6. **Submit a pull request**: Describe changes and reasoning

### Development Guidelines

- Follow existing code style (PEP 8 for Python)
- Add comments for complex logic
- Update README if adding new features
- Test with both APA and non-APA references
- Verify XSLT changes with sample MODS files

### Reporting Issues

When reporting bugs, include:
- Script name and command used
- Error message (full traceback)
- Python version: `python --version`
- Operating system
- Sample data (if possible, anonymized)

## License

MIT License - See [LICENSE](LICENSE) file for details.

Copyright (c) 2025 Malmö University

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

---

**Maintained by**: Malmö University Library  
**Contact**: For questions or support, please open an issue on GitHub.  
**Crossref Documentation**: https://www.crossref.org/documentation/
