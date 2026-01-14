import re
import argparse
import os
from parsing_helpers import (
    extract_doi_ids,
    move_doi_to_end,
    normalize_line,
    attach_non_year_lines,
    merge_short_fragments,
    build_author_patterns,
    build_parenthesized_year_patterns,
    starts_with_prop_or_sou,
    build_nonparenthesized_year_pattern,
    get_full_text,
    split_urls_and_dois,
    fix_broken_doi_tokens,
    split_trailer_fragments,
    should_attach_comma_fragment,
    join_on_suffix_prefixes,
    ensure_space_after_canonical_doi,
    starts_with_initials_parenthesized_year,
    starts_with_initials_then_parenthesized_year_allowing_authors,
    line_ends_with_comma_or_initial,
    line_ends_with_conjunction,
    load_and_preprocess,
    fix_diaeresis_errors,
)
from debug_utils import write_debug, clear_debug_txt, reset_debug_sequence

# NOTE: The legacy Type-B fixed-point append workflow was intentionally
# removed from this script to simplify maintenance and make the mirror
# doiref-style merging the primary path for B/D references. A backup of
# the previous implementation is available at `backup/doiref_nonapa.py`
# in this repository if you need to revert or compare behaviors.

# lazy import placeholders for heavy external libs; actual imports happen
# inside the loader to avoid requiring pdfminer/requests at module import time
requests = None
extract_text = None
certifi = None

# NOTE: This script uses canonical functions directly from parsing_helpers
# without local wrappers. All DOI handling (move_doi_to_end, extract_doi_ids,
# etc.) uses the canonical implementations imported at the top of the file.


# --- CONFIGURATION ---
use_local_file = False  # Set to True to use a local PDF file, False to use URL
local_file_path = "sssf-vol-16-2025-p177-211-haklietal.pdf"
url = "https://mau.diva-portal.org/smash/get/diva2:1658049/FULLTEXT01.pdf"
headers = {"User-Agent": "Mozilla/5.0"}
use_txt_file = False  # Set to True to use a TXT file instead of PDF
txt_file_path = "References_extracted.txt"

# Parse optional command-line flag --strip-numbers while preserving existing positional args
parser = argparse.ArgumentParser(
    description='Extract references from PDF or TXT and save to a file (non-APA style).'
)
parser.add_argument(
    'url',
    nargs='?',
    default=None,
    help='PDF URL or path',
)
parser.add_argument(
    'output_filename',
    nargs='?',
    default=None,
    help='Output TXT filename',
)
parser.add_argument(
    '--max-append',
    type=int,
    default=25,
    dest='max_append',
    help='Maximum lines to append when searching for a year (safeguard)',
)
parser.add_argument(
    '--audit-log',
    type=str,
    default='audit_nonapa.txt',
    dest='audit_log',
    help='Path to audit log file (set empty string to disable)',
)
# Type A, example: 'Abbott, A. D. Chaos of Disciplines. Chicago: University of Chicago Press. 2001.'
# Type B, example: 'Abbott, A. D. 2001. Chaos of Disciplines. Chicago: University of Chicago Press.'
# Type C, example: 'Abbott, Andrew D. Chaos of Disciplines. Chicago: University of Chicago Press. 2001.'
# Type D, example: 'Abbott, Andrew D. 2001. Chaos of Disciplines. Chicago: University of Chicago Press.'
parser.add_argument(
    '--ref-type',
    choices=['A', 'B', 'C', 'D'],
    default='A',
    dest='ref_type',
    help=(
        'Reference layout type: A (year at end, default) or B (year after authors). '
        'C/D: same as A/B but enable full-firstname detection'
    ),
)
parser.add_argument(
    '--until-eof',
    action='store_true',
    dest='until_eof',
    help='Continue extracting references until end of file instead of stopping at next section',
)
parser.add_argument(
    '--min-page-number',
    type=int,
    default=50,
    dest='min_page_number',
    help='Minimum page number to consider as a page-number line (inclusive)',
)
parser.add_argument(
    '--max-page-number',
    type=int,
    default=400,
    dest='max_page_number',
    help='Maximum page number to consider as a page-number line (inclusive)',
)
parser.add_argument(
    '--extractor',
    choices=['pymupdf', 'pdfminer'],
    default='pdfminer',
    dest='extractor',
    help='PDF text extraction method: pymupdf or pdfminer (auto-selected by reference type if omitted)',
)

# Optional: mirror the simplified non-numbered joining behavior from `doiref.py`.
# When enabled, `doiref_nonapa.py` will run a doiref-style non-numbered pass
# (respecting non-parenthesized years via the existing `year_found` helper)
# instead of the default Type-B fixed-point appends. This lets you test the
# alternate merging strategy without modifying `doiref.py`.
# NOTE: mirror behavior is now controlled by `mirror_mode` (default for
# B/D references unless DOIREF_MIRROR_DISABLE=1). The old CLI flag was
# removed to simplify the interface.

args = parser.parse_args()

# Make the doiref-style mirrored merging the default for Type-B/D references.
# This preserves the previous explicit `--mirror-doiref` flag but enables the
# mirror behavior automatically when the user requests `--ref-type B` or `D`.
# Callers can still opt out by explicitly setting DOIREF_MIRROR_DISABLE=1 in
# the environment (useful for testing or reproducing legacy behavior).
try:
    _mirror_disable = int(os.environ.get('DOIREF_MIRROR_DISABLE', '0'))
except Exception:
    _mirror_disable = 0
mirror_mode = args.ref_type in ('B', 'D') and not _mirror_disable

if args.url and args.output_filename:
    url = args.url
    output_filename = args.output_filename
else:
    output_filename = args.output_filename if args.output_filename else "references_nonapa.txt"

# Honor environment override for using a TXT file when invoked by a caller
# (e.g., `doiref.py` which sets DOIREF_USE_TXT/DOIREF_TXT_PATH in the
# subprocess environment). We only honor the env override when there is no
# explicit positional URL provided on the command line (positional args
# take precedence).
env_txt = os.environ.get('DOIREF_USE_TXT')
if env_txt and not args.url:
    use_txt_file = True
    env_path = os.environ.get('DOIREF_TXT_PATH')
    if env_path:
        txt_file_path = env_path

# If the caller provided an input positional argument, respect it and allow
# it to override configuration flags. In particular, if the provided input
# looks like a .txt file (by extension or by existing path), switch to
# text-file processing regardless of the module-level `use_txt_file` default.
if args.url:
    provided = args.url
    # detect local path that exists and is a file
    try:
        is_file = os.path.isfile(provided)
    except Exception:
        is_file = False
    if provided.lower().endswith('.txt') or is_file and provided.lower().endswith('.txt'):
        use_txt_file = True
        txt_file_path = provided
    else:
        # treat as a PDF URL/path override
        url = provided

# Respect explicit output filename if provided
if args.output_filename:
    output_filename = args.output_filename

# Debug: write intermediate files to help trace parsing issues
DEBUG = False
# Audit log file (set to None to disable)
audit_fp = None
if args.audit_log:
    try:
        audit_fp = open(args.audit_log, 'w', encoding='utf-8')
        audit_fp.write('AUDIT LOG START\n')
    except Exception:
        audit_fp = None
if DEBUG:
    try:
        # Reset debug numbering and clear previous textual debug snapshots
        reset_debug_sequence(remove_prefixed_files=True)
        clear_debug_txt()
    except Exception:
        pass

# Ensure references_text is always defined even if loading fails earlier
# This prevents a NameError later when splitting into raw_lines. It will
# be overwritten by the loader below in normal operation.
references_text = ""

# --- PDF or TXT LOADING (centralized via parsing_helpers) ---
try:
    # Log intent to load full text
    if audit_fp:
        try:
            audit_fp.write(f"GET_FULL_TEXT: source={args.url or url} use_local_file={use_local_file} use_txt_file={use_txt_file} txt_file_path={txt_file_path} extractor={args.extractor}\n")
        except Exception:
            pass
    full_text = get_full_text(
        source=args.url or url,
        use_local_file=use_local_file,
        local_file_path=local_file_path,
        use_txt_file=use_txt_file,
        txt_file_path=txt_file_path,
        headers=headers,
        verify='combined_ca.pem',
        extractor=args.extractor,
    )
    if audit_fp:
        try:
            audit_fp.write(f"GET_FULL_TEXT: success len={len(full_text) if full_text is not None else 0}\n")
        except Exception:
            pass
except ValueError as e:
    if audit_fp:
        try:
            audit_fp.write(f"GET_FULL_TEXT: ERROR: {str(e)}\n")
        except Exception:
            pass
    print(str(e))
    raise

try:
    lp = load_and_preprocess(
        source=args.url or url,
        use_local_file=use_local_file,
        local_file_path=local_file_path,
        use_txt_file=use_txt_file,
        txt_file_path=txt_file_path,
        headers=headers,
        verify='combined_ca.pem',
        until_eof=args.until_eof,
        stop_at_allcaps=False,
        require_heading=not use_txt_file,
        audit_fp=audit_fp,
        # Provide the already-fetched full text to avoid fetch/extract
        # ordering differences and to mirror the behavior used by
        # `doiref.py` which passes a preloaded full-text blob.
        preloaded_full_text=full_text,
        extractor=args.extractor,
    )
except ValueError as e:
    if audit_fp:
        try:
            audit_fp.write(f"LOAD_AND_PREPROCESS: ERROR: {str(e)}\n")
        except Exception:
            pass
    print(str(e))
    raise

# Unpack canonical artifacts produced by the centralized loader. Use the
# provided `raw_lines` and `lines` to avoid duplicating extraction and
# normalization logic here — the centralized helper already performed
# inline CID removal, page-number filtering, normalization and hyphen-join.
full_text = lp.get('full_text')
references_text = lp.get('references_text')
raw_lines = lp.get('raw_lines', references_text.splitlines() if references_text else [])
# Prefer the pre-hyphen (uncollapsed) normalized lines for the non-APA
# pipeline because several downstream passes expect physical-line
# boundaries to be preserved. Fall back to the post-join `lines` if the
# loader does not provide a pre-join view.
lines = lp.get('pre_hyphen_lines') or lp.get('lines', [])

# Save the raw extracted reference section for inspection (mirror other pipelines)
try:
    with open('references_extracted.txt', 'w', encoding='utf-8') as f:
        f.write(references_text or '')
except Exception:
    pass
# and common trailing punctuation. Built from canonical helper for consistency.
year_pattern = build_nonparenthesized_year_pattern()

# Helper to detect a year while ignoring years immediately adjacent to
# hyphen-like characters (unless the match itself is an ISO-like date
# of the form YYYY-MM or YYYY-MM-DD). This enforces the requirement that
# years that immediately follow or are followed by a dash are not treated
# as terminating years for joining heuristics in the non-APA pipeline.
_HYphen_CHARS = set('-\u00AD\u2010\u2011\u2012\u2013\u2014\u2015\u2212')
_ISO_DATE_RE = re.compile(r'\b\d{4}-\d{2}(?:-\d{2})?\b')

def year_found(s: str) -> bool:
    """Return True if `s` contains a year match acceptable to the pipeline.

    Ignore matches that are immediately adjacent (before or after) a
    hyphen-like character, unless the matched text itself is an ISO-like
    date (YYYY-MM or YYYY-MM-DD), in which case we accept it.
    """
    if not s:
        return False
    for m in year_pattern.finditer(s):
        start, end = m.start(), m.end()
        before = s[start - 1] if start > 0 else ''
        after = s[end] if end < len(s) else ''
        # If either neighbour is a hyphen-like character, only accept when
        # the matched substring is an ISO date (YYYY-MM or YYYY-MM-DD).
        if (before in _HYphen_CHARS) or (after in _HYphen_CHARS):
            match_text = s[start:end]
            if _ISO_DATE_RE.search(match_text):
                return True
            # otherwise ignore this match and continue searching
            continue
        # otherwise accept this match
        return True
    return False

# Build author-related patterns: enable fullname detection for reference
# types C and D (C == A with fullname detection; D == B with fullname
# detection). Use the canonical builder from parsing_helpers which centralizes
# and hardens these regexes.
fullname_detection = args.ref_type in ('C', 'D')
_ap = build_author_patterns(fullname_detection=fullname_detection)
author_pattern = _ap['author_pattern_active']
author_start_like = _ap['author_start_like_active']
author_start_like_multi = _ap.get('author_start_like_multi')
author_start_like_fullname_space = _ap.get('author_start_like_fullname_space')
initial = _ap['initial']

# Detect reference style: always author for this script
ref_style = 'author'

# --- Collapse consecutive author lines (even with empty lines between) ---


def is_author_line(line, next_line=None):
    # An author-only line is one that matches the author pattern and does not contain a year
    # If the physical line begins with a leading comma, consult the
    # centralized comma-fragment heuristic which requires peeking at the
    # following physical line. If no `next_line` is supplied, be conservative
    # and return False (do not treat an orphan comma-led fragment as an
    # author-only line).
    if line and line.lstrip().startswith(','):
        if next_line:
            try:
                return should_attach_comma_fragment(line, next_line, fullname_detection, initial, author_start_like)
            except Exception:
                return False
        return False

    # Heuristic: if the current physical line ends with a comma (common when
    # the surname list continues on the next physical line with initials) and
    # the *next* physical line starts with an initial-like token, treat the
    # current line as an author-only line. This avoids requiring the initials
    # to be present on the same physical line while remaining conservative
    # (we also require the current line to look like an author-start and no
    # terminating year to be present).
    if line and line.rstrip().endswith(',') and next_line:
        try:
            if author_start_like.match(line):
                if re.match(r'^\s*' + initial, next_line):
                    if not year_found(line):
                        return True
        except Exception:
            # On any error, fall back to conservative behavior
            pass

    m = author_pattern.match(line)
    if not m:
        # If full author pattern doesn't match, check if the line starts like an author
        # but only accept it as an author line if it is a short single-line entry
        # (i.e., the start match reaches the end of the line) — otherwise reject.
        m2 = author_start_like.match(line)
        if not m2:
            return False
        # If the line is exactly the matched prefix (no continuation), allow it
        if m2 and m2.end() == len(line):
            # still ensure there is no year
            if re.search(r'\d', m2.group(0)):
                return False
            return not year_found(line)
        return False
    # Reject if the matched author prefix contains any digit (avoid false
    # positives where numeric tokens or page numbers appear in the text).
    matched_prefix = m.group(0)
    if re.search(r'\d', matched_prefix):
        return False

    # Additional safety: ensure the match either reaches the end of the line
    # or is followed by an initial-like token (single letter optionally followed
    # by a dot) or a connector. This prevents journal-title lines like
    # 'Astrophysical Journal, 739, L54' from matching as an author line when
    # they begin with a capitalized word and comma. If the author match is only
    # a bare surname or surname+comma and the line continues, reject it.
    after = line[len(matched_prefix):].lstrip()
    # Allow a trailing leftover that is only punctuation (e.g. '.' or ',') to
    # be treated as if there is no trailing text. This is a narrowly scoped
    # relaxation to accept author lines that end with a stray punctuation
    # character left outside the regex match (common in OCR or PDF line
    # fragments).
    if after and re.match(r'^[\s\.,:;\-\—\–&"\'\(\)\[\]]*$', after):
        after = ''
    # if the match consumed only a surname (no initials in matched_prefix)
    # and the line continues, we must reject (e.g., 'Astrophysics, 41, 57')
    # Detect by checking if the matched_prefix lacks an initial-like pattern
    if after:
        if not re.search(rf"{initial}", matched_prefix):
            return False
        # simple initial-like token (e.g., 'J.' or 'J') or connector allowed
        if not re.match(r'^[A-Za-z](?:\.|\b)', after) and not re.match(r'^(?:,|&|\band\b)', after):
            return False

    # Also reject if there's any obvious 4-digit year anywhere (looser check)
    if re.search(r'\b(17|18|19|20)\d{2}\b', line):
        return False

    return not year_found(line)


collapsed_lines = []
i = 0
n = len(lines)
while i < n:
    line = lines[i]
    if is_author_line(line):
        author_lines = [line]
        j = i + 1
        while j < n:
            next_line = lines[j]
            if next_line.strip() == "":
                j += 1
                continue
            # When deciding whether the following physical line is an
            # author-only line, pass the subsequent non-empty physical
            # line as `next_line` so the comma-led heuristic can consult
            # the continuation when needed.
            k = j + 1
            while k < n and not lines[k].strip():
                k += 1
            next_next = lines[k] if k < n else ''
            if is_author_line(next_line, next_next):
                author_lines.append(next_line)
                j += 1
            else:
                break
        collapsed_lines.append(" ".join(author_lines))
        i = j
    else:
        collapsed_lines.append(line)
        i += 1

lines = collapsed_lines


# If reference type B, perform pre-joining: iteratively append lines that do
# not contain a year to the previous line until fixed point. This ensures
# author-collapse happens first, then type-B merging attaches subsequent
# non-year continuation lines to their author lines.
mirror_result_lines = None
if args.ref_type in ('B', 'D'):
    try:
        max_iter = int(os.environ.get('DOIREF_MAX_ITER', '10'))
    except Exception:
        max_iter = 10

    # If requested, run a doiref-style non-numbered merging pass here.
    # This mirrors the simplified `one_pass_apply` logic used in `doiref.py`
    # but continues to use the non-parenthesized year detection available
    # in this module (`year_found`). The original Type-B flow remains
    # unchanged and will only be used when `--mirror-doiref` is not set.
    if mirror_mode:
        # Build local author patterns for merging decisions
        try:
            _ap_m = build_author_patterns(fullname_detection=fullname_detection)
            ap_author_pattern = _ap_m.get('author_pattern') or _ap_m.get('author_pattern_active')
            ap_author_start_like = _ap_m.get('author_start_like') or _ap_m.get('author_start_like_active')
        except Exception:
            ap_author_pattern = author_pattern
            ap_author_start_like = author_start_like

        # --- Mirror pre-append / pre-join passes from doiref.py ---
        # Build parenthesized-year helpers so we can run the same small
        # pre-append/pre-merge passes that doiref.py uses when mirroring.
        try:
            YR = build_parenthesized_year_patterns()
            YEAR_PAREN = YR.get('YEAR_PAREN')
            YEAR_PAREN_END = YR.get('YEAR_PAREN_END')
            YEAR_PAREN_START = YR.get('YEAR_PAREN_START')
        except Exception:
            YEAR_PAREN = YEAR_PAREN_END = YEAR_PAREN_START = re.compile(r'(?!x)x')

        # Helper: detect whether a physical line ends with a year token.
        # We must reuse the canonical year-detection rules (including the
        # hyphen-adjacency/ISO-date guard implemented in `year_found`) to
        # avoid false positives like 'abc-2016' being treated as a
        # terminating year. Find a year-like token at the end of the
        # line (parenthesized or bare) and then validate that specific
        # match using the same neighbor/ISO rules used by `year_found`.
        YEAR_END_RE = re.compile(r"(?:\(\s*((?:17|18|19|20)\d{2})\s*\)|\b((?:17|18|19|20)\d{2})\b)\.?\s*$")

        def line_ends_with_year(s: str) -> bool:
                if not s:
                    return False
                t = s.rstrip()
                m = YEAR_END_RE.search(t)
                if not m:
                    return False
                # Determine which capture matched (group 1 for parenthesized,
                # group 2 for bare year). Use the group's span within the
                # original string so we can apply the same hyphen/ISO guard as
                # `year_found` (which inspects neighbouring characters).
                if m.group(1) is not None:
                    start, end = m.start(1), m.end(1)
                else:
                    start, end = m.start(2), m.end(2)

                # Check adjacency to hyphen-like characters; if adjacent, only
                # accept when the matched substring itself is an ISO-like date.
                before = t[start - 1] if start > 0 else ''
                after = t[end] if end < len(t) else ''
                if (before in _HYphen_CHARS) or (after in _HYphen_CHARS):
                    match_text = t[start:end]
                    if _ISO_DATE_RE.search(match_text):
                        return True
                    return False
                return True

        # Helper: detect whether a physical line STARTS with a year token.
        # Mirrors `line_ends_with_year` but anchored to the start of the
        # line. Use the same hyphen-adjacency/ISO-date guard to avoid
        # treating hyphen-adjacent years as terminating/starting years.
        YEAR_START_RE = re.compile(r"^\s*(?:\(\s*((?:17|18|19|20)\d{2})\s*\)|((?:17|18|19|20)\d{2})\b)\.?\s*")

        def line_starts_with_year(s: str) -> bool:
                if not s:
                    return False
                m = YEAR_START_RE.match(s)
                if not m:
                    return False
                # Choose the matching group's span (group 1 parenthesized,
                # group 2 bare) so we can inspect adjacent characters.
                if m.group(1) is not None:
                    start, end = m.start(1), m.end(1)
                else:
                    start, end = m.start(2), m.end(2)
                before = s[start - 1] if start > 0 else ''
                after = s[end] if end < len(s) else ''
                if (before in _HYphen_CHARS) or (after in _HYphen_CHARS):
                    match_text = s[start:end]
                    if _ISO_DATE_RE.search(match_text):
                        return True
                    return False
                return True

        # Merge lines that start with a year (parenthesized or bare) into the previous
        # non-empty line. This handles lines like '(2016) Title...' or '2016 Title...'
        # which should attach to the prior reference.
        if lines:
            merged_start_year = []
            for ln in lines:
                # Use the hyphen/ISO-safe start-year detection which handles both
                # parenthesized and non-parenthesized years.
                if line_starts_with_year(ln):
                    if merged_start_year:
                        merged_start_year[-1] = merged_start_year[-1].rstrip() + ' ' + ln.lstrip()
                    else:
                        merged_start_year.append(ln)
                else:
                    merged_start_year.append(ln)
            lines = merged_start_year
            if DEBUG:
                try:
                    write_debug('debug_nonapa_mirror_after_year_start_merge.txt', lines)
                except Exception:
                    pass

        # Pre-append next non-empty line when a line ends with a year (parenthesized
        # or bare). This helps when the year is on its own physical line followed by
        # a continuation.
        if lines:
            new_lines = []
            i2 = 0
            while i2 < len(lines):
                ln2 = lines[i2]
                # line_ends_with_year handles both parenthesized and non-parenthesized years
                if line_ends_with_year(ln2):
                    j = i2 + 1
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    if j < len(lines):
                        # Do not append if the following line starts with Prop. or SOU
                        if starts_with_prop_or_sou(lines[j].lstrip()):
                            new_lines.append(ln2)
                            i2 += 1
                            continue
                        new_lines.append(ln2.rstrip() + ' ' + lines[j].lstrip())
                        i2 = j + 1
                        continue
                new_lines.append(ln2)
                i2 += 1
            lines = new_lines
            if DEBUG:
                try:
                    write_debug('debug_nonapa_mirror_post_year_end_pre_editor.txt', lines)
                except Exception:
                    pass

        # Editor-token merging passes (two-step iterative strategy from doiref.py).
        # Build a minimal set of author/editor patterns for conservative decisions.
        try:
            _ap_editor = build_author_patterns(fullname_detection)
            ap_author_pattern_active = _ap_editor.get('author_pattern_active')
            ap_author_start_like_active = _ap_editor.get('author_start_like_active')
            # Looser multi-surname start-like matcher (may be None)
            ap_author_start_like_multi = _ap_editor.get('author_start_like_multi')
            editor_token_re = _ap_editor.get('editor_token_re')
        except Exception:
            ap_author_pattern_active = None
            ap_author_start_like_active = None
            editor_token_re = re.compile(r'^(?:eds?|red)\.?$', flags=re.I)

        def _has_unresolved_editor_token(candidate_lines):
            for ln in candidate_lines:
                # Use the canonical year detection (hyphen/ISO-aware)
                # to decide whether this line should be skipped.
                if year_found(ln):
                    continue
                for p in re.findall(r'\(([^)]*)\)', ln):
                    if editor_token_re.match(p.strip()):
                        return True
            return False

        try:
            max_editor_iter = int(os.environ.get('DOIREF_EDITOR_MAX_ITER', '3'))
        except Exception:
            max_editor_iter = 3

        iter_e = 0
        while True:
            iter_e += 1
            merged_with_editors = []
            for idx, ref in enumerate(lines):
                # Skip merging when the line contains any acceptable year
                # (uses year_found which includes the hyphen/ISO guard).
                if idx > 0 and not year_found(ref):
                    m = re.search(r'\(([^)]*)\)', ref)
                    if m:
                        first_content = m.group(1).strip()
                        if editor_token_re.match(first_content):
                            # Do not merge if this line starts with Prop./SOU
                            if starts_with_prop_or_sou(ref.lstrip()):
                                merged_with_editors.append(ref)
                                continue
                            merged_with_editors[-1] = merged_with_editors[-1].rstrip() + ' ' + ref.lstrip()
                            continue
                merged_with_editors.append(ref)

            # second pass: if the previous line contains an editor token, append the current line
            out_after_prev_editor = []
            for i_idx, ref in enumerate(merged_with_editors):
                if i_idx == 0:
                    out_after_prev_editor.append(ref)
                    continue
                prev = out_after_prev_editor[-1]
                if not year_found(ref):
                    prev_paren_iters = list(re.finditer(r'\(([^)]*)\)', prev))
                    prev_has_editor = False
                    if prev_paren_iters:
                        last_paren = prev_paren_iters[-1]
                        paren_text = last_paren.group(1).strip()
                        if editor_token_re.match(paren_text):
                            after = prev[last_paren.end():].strip()
                            if not after or re.match(r'^[\s\.,:;\-\—\–\"\'\"\(\)\[\]]*$', after):
                                prev_has_editor = True

                    if prev_has_editor:
                        if starts_with_prop_or_sou(ref.lstrip()):
                            out_after_prev_editor.append(ref)
                            continue
                        if ap_author_pattern_active and ap_author_pattern_active.match(ref.lstrip()):
                            out_after_prev_editor.append(ref)
                            continue
                        if not ap_author_pattern_active and (
                            (ap_author_start_like_active and ap_author_start_like_active.match(ref.lstrip()))
                            or (ap_author_start_like_multi and ap_author_start_like_multi.match(ref.lstrip()))
                        ):
                            out_after_prev_editor.append(ref)
                            continue
                        out_after_prev_editor[-1] = prev.rstrip() + ' ' + ref.lstrip()
                        continue
                out_after_prev_editor.append(ref)

            lines = out_after_prev_editor
            if DEBUG:
                try:
                    write_debug(f'debug_nonapa_mirror_editor_iter{iter_e}.txt', lines)
                except Exception:
                    pass

            if not _has_unresolved_editor_token(lines) or iter_e >= max_editor_iter:
                break

        def one_pass_mirror(input_lines):
            out = []
            i = 0
            while i < len(input_lines):
                ln = input_lines[i].strip()
                if not ln:
                    i += 1
                    continue
                # If this line contains a non-parenthesized year (year_found), leave as-is.
                if year_found(ln):
                    out.append(ln)
                    i += 1
                    continue
                # If it starts with an author-like pattern and has at least two whitespace
                # tokens and no obvious digits, merge with the following non-empty line.
                if (
                    ((ap_author_pattern and ap_author_pattern.match(ln)) or (ap_author_start_like and ap_author_start_like.match(ln)))
                    and len(re.findall(r"\s", ln)) >= 2
                    and not re.search(r"\d", ln)
                ):
                    k = i + 1
                    while k < len(input_lines) and not input_lines[k].strip():
                        k += 1
                    if k < len(input_lines):
                        merged = ln + ' ' + input_lines[k].strip()
                        out.append(merged)
                        i = k + 1
                        continue
                out.append(ln)
                i += 1
            return out

        # Run iterative merging to fixed point
        try:
            MAX_ITER = int(os.environ.get('DOIREF_MAX_ITER', '10'))
        except Exception:
            MAX_ITER = 10
        prev_m = lines
        iter_m = 0
        while True:
            iter_m += 1
            new_m = one_pass_mirror(prev_m)
            if DEBUG:
                try:
                    write_debug(f'debug_nonapa_mirror_iter{iter_m}.txt', new_m)
                except Exception:
                    pass
            if new_m == prev_m or iter_m >= MAX_ITER:
                mirror_final = new_m
                break
            prev_m = new_m

        # After main merging, append non-year lines to previous (stop on year_found)
        def append_nonyear_mirror(input_lines):
            # Use the same conservative logic as the non-mirror `append_nonyear_fixed`
            # to avoid aggressive appends that join header-like fragments.
            out = []
            if not input_lines:
                return out
            out.append(input_lines[0])
            i = 1
            while i < len(input_lines):
                ln = input_lines[i]
                # attach to previous if this line does not contain a year
                if not year_found(ln):
                    # Safeguard: if the line looks like it starts with a surname/token
                    # (e.g., 'Astrophysics, 41, 57') but is NOT accepted as an author
                    # line by is_author_line, then do not append it here — keep it
                    # as its own fragment to avoid false joins. This mirrors the
                    # preappend safeguard.
                    ln_stripped = ln.strip()
                    # Peek the following physical line to provide context for
                    # comma-led fragments when deciding whether `ln_stripped`
                    # should be considered an author-only line.
                    next_ln = input_lines[i+1] if (i + 1) < len(input_lines) else ''
                    if author_start_like.match(ln_stripped) and not is_author_line(ln_stripped, next_ln):
                        # treat as separate fragment
                        out.append(ln_stripped)
                    else:
                        out[-1] = out[-1].rstrip() + ' ' + ln.lstrip()
                else:
                    out.append(ln)
                i += 1
            return out

        mirror_final2 = append_nonyear_mirror(mirror_final)
        # Use the mirror result as the assembled references for Type-B
        # Store the mirror result so we can replace the default Type-B
        # fixed-point appends later in the pipeline.
        mirror_result_lines = mirror_final2
        references = [ln.strip() for ln in mirror_final2]
        if DEBUG:
            try:
                write_debug('debug_nonapa_3_mirror_final.txt', references)
            except Exception:
                pass

        # Use the mirror result as the assembled fragments for Type-B.
        # The legacy non-mirror fixed-point Type-B workflow has been removed
        # to simplify the script; mirror_result_lines is expected to be set
        # (mirror is the default for ref-type B/D). If it's not set for some
        # reason, fall back conservatively to the current `lines` value.
        if mirror_result_lines:
            lines = mirror_result_lines
    # After finishing Type-B fixed-point appends, attach any physical line
    # that contains at least one digit but does not itself contain a year to
    # the previous physical line. Do this immediately after the Type-B
    # passes so numeric-containing continuations are attached before the
    # rest of the pipeline.
    if args.ref_type in ('B', 'D'):
        merged = []
        for ln in lines:
            if merged and re.search(r'\d', ln) and not year_found(ln):
                merged[-1] = merged[-1].rstrip() + ' ' + ln.lstrip()
            else:
                merged.append(ln)
        lines = merged
if DEBUG:
    try:
        # Before writing the collapsed-lines snapshot, run an initials+year
        # merge pass: join lines that START with 1-3 initials (with or
        # without trailing periods) followed by a parenthesized OR bare
        # year to the previous line when that previous line ends with a
        # comma or a single-letter initial. This is a conservative pass
        # similar to the one used in `doiref.py` but extended to accept
        # non-parenthesized years (common in non-APA references).
        # Only run the initials+year and conjunction-join passes for Type-B/D references
        if args.ref_type in ('B', 'D'):
            try:
                merged_initials = []
                for idx, ln in enumerate(lines):
                    if idx > 0:
                        starts_with_parenthesized = False
                        starts_with_bare_year = False
                        starts_with_relaxed = False
                        try:
                            starts_with_parenthesized = starts_with_initials_parenthesized_year(ln)
                        except Exception:
                            starts_with_parenthesized = False
                        try:
                            # conservative bare-year check: 1-3 initials then a 4-digit year
                            if re.match(r'^\s*(?:[A-Z]\.?? ?){1,3}\s*(?:17|18|19|20)\d{2}\b', ln):
                                starts_with_bare_year = True
                        except Exception:
                            starts_with_bare_year = False
                        try:
                            # relaxed check: allow intervening author fragments before a parenthesized year
                            starts_with_relaxed = starts_with_initials_then_parenthesized_year_allowing_authors(ln)
                        except Exception:
                            starts_with_relaxed = False

                        if (starts_with_parenthesized or starts_with_bare_year or starts_with_relaxed):
                            prev = merged_initials[-1] if merged_initials else None
                            if prev and line_ends_with_comma_or_initial(prev):
                                merged_initials[-1] = prev.rstrip() + ' ' + ln.lstrip()
                                continue
                    merged_initials.append(ln)
                lines = merged_initials
                write_debug('debug_nonapa_after_initials_year_merge.txt', lines)
            except Exception:
                try:
                    write_debug('debug_nonapa_after_initials_year_merge_error.txt', ['ERROR in initials-year merge'])
                except Exception:
                    pass

            # --- New pass: join author lines that end with '&', 'and', or 'och' to the next line
            # This mirrors doiref.py: conservatively skip joining when the following
            # non-empty line starts with Prop. or SOU markers which should start
            # a new reference.
            try:
                if lines:
                    merged_amp = []
                    i_amp = 0
                    while i_amp < len(lines):
                        ln_amp = lines[i_amp]
                        if line_ends_with_conjunction(ln_amp):
                            j_amp = i_amp + 1
                            while j_amp < len(lines) and not lines[j_amp].strip():
                                j_amp += 1
                            if j_amp < len(lines):
                                if starts_with_prop_or_sou(lines[j_amp].lstrip()):
                                    merged_amp.append(ln_amp)
                                    i_amp += 1
                                    continue
                                merged_amp.append(ln_amp.rstrip() + ' ' + lines[j_amp].lstrip())
                                i_amp = j_amp + 1
                                continue
                        merged_amp.append(ln_amp)
                        i_amp += 1
                    lines = merged_amp
                    write_debug('debug_nonapa_after_author_ampersand_merge.txt', lines)
            except Exception:
                try:
                    write_debug('debug_nonapa_after_author_ampersand_merge_error.txt', ['ERROR in ampersand/and/och merge'])
                except Exception:
                    pass
        else:
            # Record that we skipped the initials-year/conjunction merges for non-B/D types
            try:
                write_debug('debug_nonapa_initials_skipped.txt', [f'SKIPPED initials/conjunction merges for ref_type={args.ref_type}'])
            except Exception:
                pass

        write_debug('debug_nonapa_4_collapsed_lines.txt', lines)
    except Exception:
        with open('debug_nonapa_4_collapsed_lines.txt', 'w', encoding='utf-8') as df:
            for ln in lines:
                df.write(ln + '\n')

    # Post-process: append numeric-fragment-only lines to previous line.
    # These are lines that contain digits and allowed punctuation only
    # (periods, colons, parentheses, hyphens) and may include a single
    # one-letter abbreviation like 'p.' at the start. Examples:
    #   '20503121211034366.'
    #   '2022. 12(1): p. 31-46.'
    #   'p. 24-37.'
    # We conservatively match lines that consist entirely of [0-9().:;\-\s] and
    # optional single-letter+dot abbreviations (e.g. 'p.') and append them to
    # the previous non-empty line to preserve page/volume fragments.
    numeric_fragment_re = re.compile(r"^(?:[A-Za-z]\.|[0-9()\[\].:;\-\s])+$")
    merged = []
    for ln in lines:
        if merged and numeric_fragment_re.match(ln.strip()):
            # append to previous
            merged[-1] = merged[-1].rstrip() + ' ' + ln.lstrip()
        else:
            merged.append(ln)
    lines = merged
    if DEBUG:
        try:
            write_debug('debug_nonapa_5_numeric_appended.txt', lines)
        except Exception:
            with open('debug_nonapa_5_numeric_appended.txt', 'w', encoding='utf-8') as df:
                for ln in lines:
                    df.write(ln + '\n')

# (Hyphen continuation join was applied earlier to raw lines; no further pass needed here.)

# --- Main reference joining logic ---
# For Type B we've already done pre-append and numeric attachment on the
# physical `lines`; skip the iterative "append until year" joiner and treat
# each `lines` element as a starting reference fragment. For Type A, run the
# original joining loop.
if args.ref_type in ('B', 'D'):
    references = [ln.strip() for ln in lines]
    if DEBUG:
        try:
            write_debug('debug_nonapa_6_initial_joined.txt', references)
        except Exception:
            with open('debug_nonapa_6_initial_joined.txt', 'w', encoding='utf-8') as df:
                for r in references:
                    df.write(r + '\n')
else:
    references = []
    i = 0
    n = len(lines)
    # safeguard to avoid appending indefinitely on very messy input
    MAX_APPEND_STEPS = int(args.max_append)

    while i < n:
        # Start a new candidate reference at the current line
        current = lines[i]
        start_line = current
        i += 1

        # Iteratively append following lines until we detect a year or hit a safeguard
        steps = 0
        while not year_found(current) and i < n and steps < MAX_APPEND_STEPS:
            next_line = lines[i]
            # Append the next physical line (avoid creating duplicates by simple check)
            if next_line.strip() and next_line.strip() not in current:
                current = current.rstrip() + " " + next_line
            else:
                # still advance to avoid infinite loop; include the text to preserve content
                current = current.rstrip() + " " + next_line
            i += 1
            steps += 1

        # If we hit the safeguard, just finalize what we have to avoid eternal loops
        if steps >= MAX_APPEND_STEPS:
            if audit_fp:
                try:
                    msg = f"MAX_APPEND_HIT start='{start_line[:200]}' steps={steps}\n"
                    audit_fp.write(msg)
                except Exception:
                    pass

        references.append(current.strip())

# --- Splitting and DOI handling (same as original) ---
# Using canonical functions directly from parsing_helpers:
# - extract_doi_ids
# - move_doi_to_end
# - split_urls_and_dois

split_references = []


# Apply attach_non_year_lines to the assembled references (before splitting/DOI handling)
# The canonical function from parsing_helpers is now called directly with both arguments
attached_references = attach_non_year_lines(references, year_pattern)

if DEBUG:
    try:
        write_debug('debug_nonapa_8_attached_references.txt', attached_references)
    except Exception:
        with open('debug_nonapa_8_attached_references.txt', 'w', encoding='utf-8') as df:
            for r in attached_references:
                df.write(r + '\n')


# Final-pass: merge short trailing fragments into previous reference (fewer than 3 spaces)
# Use canonical merge_short_fragments implementation from parsing_helpers directly
merged_refs = merge_short_fragments(attached_references, max_spaces=2)

if DEBUG:
    try:
        write_debug('debug_nonapa_9_final_refs.txt', merged_refs)
    except Exception:
        with open('debug_nonapa_9_final_refs.txt', 'w', encoding='utf-8') as df:
            for r in merged_refs:
                df.write(r + '\n')

# Additional pre-join helper: attach first token of next fragment when previous
# fragment ends with common URL/DOI prefixes. We'll run this first (before the
# pass that joins fragments starting with 'https://'), so suffix-prefixes are
# resolved before any leading-URL joining occurs.


# Use the shared `join_on_suffix_prefixes` imported from parsing_helpers


# First, run the join-on-suffix-first-token pass on the merged refs so that
# any trailing URL/DOI prefixes are attached to the start of the following
# fragment before we perform the 'leading URL fragment' join below.
pre_joined = join_on_suffix_prefixes(merged_refs, author_predicate=is_author_line, audit_fp=audit_fp)

# Now run the pass that joins fragments that START with 'https://' (or
# similar leading DOI tokens) to the previous fragment. This now runs after
# the suffix-prefixes pass so that we avoid missing attachments caused by
# suffixes that should have consumed the first token of a following fragment.
pre_joined_final = []
for ref in pre_joined:
    s = ref.strip()
    if pre_joined_final and (
        s.lower().startswith('https://')
        or s.lower().startswith('doi:')
        or s.startswith('DOI:')
        or s.startswith('Doi:')
        or s.lower().startswith('doi.org')
        or s.lower().startswith('org/')
        or re.match(r'^10\.\d{3,8}/', s)
    ):
        # Join leading URL fragment to previous
        pre_joined_final[-1] = pre_joined_final[-1].rstrip() + ' ' + s
    else:
        pre_joined_final.append(ref)

pre_joined = pre_joined_final
if DEBUG:
    try:
        write_debug('debug_nonapa_pre_split_join_suffixes.txt', pre_joined)
    except Exception:
        try:
            with open('debug_nonapa_pre_split_join_suffixes.txt', 'w', encoding='utf-8') as df:
                for rr in pre_joined:
                    df.write(rr + '\n')
        except Exception:
            pass

# Split on access-date markers like '[Accessed on 2023-10-19]' (case-insensitive)
access_re = re.compile(r'\[\s*accessed\s+on\s*\d{4}-\d{2}-\d{2}\s*\]\.?', flags=re.I)
pre_split_refs = []
for ref in pre_joined:
    if not access_re.search(ref):
        pre_split_refs.append(ref)
        continue
    last = 0
    for m in access_re.finditer(ref):
        end = m.end()
        left = ref[last:end].strip()
        if left:
            pre_split_refs.append(left)
        last = end
    tail = ref[last:].strip()
    if tail:
        pre_split_refs.append(tail)

# NOTE: Conservative and aggressive pre-split DOI reattach passes have been
# intentionally removed here. The canonical `move_doi_to_end` implementation
# (imported as `move_doi_to_end`) performs normalization and reattachment
# of split DOI/URL fragments in a single, centralized place. Rely on that
# authoritative behavior to avoid duplicate/ordering-specific logic here.

# Simply use the pre-split fragments directly and let `move_doi_to_end` handle
# any DOI reattachment/normalization when we process each split fragment.
adjusted_pre_split_refs = pre_split_refs
if audit_fp:
    try:
        audit_fp.write('PH_CONSERVATIVE_DOI_REATTACH: SKIPPED — USING move_doi_to_end\n')
        audit_fp.flush()
    except Exception:
        pass

# Additional pre-split join pass: join fragments that end with specific
# DOI/URL prefixes with the following fragment without inserting a space.
# This helps when DOI/URL tokens are split across a line break such that
# the previous line ends in 'doi.org' or 'https://' etc.


# The join-on-suffix-prefixes behaviour is provided by the shared
# `join_on_suffix_prefixes` function imported from parsing_helpers.


# Avoid per-fragment pre-normalization here. The canonical
# `move_doi_to_end` implementation will perform normalization and
# reattachment as needed. Reuse the pre-split fragments directly.
normalized_pre_split_refs = adjusted_pre_split_refs

# Debug snapshot: post-normalization (before splitting on URLs/DOIs)
if DEBUG:
    try:
        write_debug('debug_nonapa_8_normalized_pre_split_refs.txt', normalized_pre_split_refs)
    except Exception:
        try:
            with open('debug_nonapa_8_normalized_pre_split_refs.txt', 'w', encoding='utf-8') as df:
                for rr in normalized_pre_split_refs:
                    df.write(rr + '\n')
        except Exception:
            pass

# Now perform splitting on URLs/DOIs and move DOIs to the end of each split fragment.
final_references = []
for ref in normalized_pre_split_refs:
    for part in split_urls_and_dois(ref):
        final_references.append(move_doi_to_end(part))

# Debug snapshot: immediately after splitting and moving DOIs, before further repairs
if DEBUG:
    try:
        write_debug('debug_nonapa_9_post_split_move_refs.txt', final_references)
    except Exception:
        try:
            with open('debug_nonapa_9_post_split_move_refs.txt', 'w', encoding='utf-8') as df:
                for fr in final_references:
                    df.write(fr + '\n')
        except Exception:
            pass


try:
    final_references = [fix_broken_doi_tokens(r) for r in final_references]
except Exception:
    def fix_broken_doi_tokens(ref):
        s = ref
        s = re.sub(r'(https?://doi\.org)10\.', r"\1/10.", s, flags=re.I)
        s = re.sub(r'(https?://doi\.org)\s+10\.', r"\1/10.", s, flags=re.I)
        s = re.sub(r'https?://doi\.\s*org', 'https://doi.org', s, flags=re.I)
        s = re.sub(r'(https?://doi\.org)10(?![\d/\.])', r"\1/10", s, flags=re.I)
        return s
    final_references = [fix_broken_doi_tokens(r) for r in final_references]
# Debug: after fix_broken_doi_tokens pass
if DEBUG:
    try:
        write_debug('debug_nonapa_9_after_fix_broken_tokens.txt', final_references)
    except Exception:
        try:
            with open('debug_nonapa_9_after_fix_broken_tokens.txt', 'w', encoding='utf-8') as df:
                for fr in final_references:
                    df.write(fr + '\n')
        except Exception:
            pass

# Post-split: split cases where a previous fragment ends with a bracketed
# qualification like '[Doktorsavhandling].' followed by an author start on the
# same fragment (e.g. "... universitet]. Freake, H., ..."). Conservatively
# split these into two separate references when the right-hand side looks
# like an author start. This mirrors the conservative split used in doiref.py
# and prevents accidental merges of two distinct references.
# Post-split: conservatively split trailing bracketed qualifications followed
# by an author-like start (e.g. '... universitet]. Freake, H., ...'). Use the
# centralized helper from parsing_helpers to avoid duplication.
try:
    # Non-APA pipeline: usually contains no parenthesized years at all,
    # so allow splitting even when zero parenthesized years are present to
    # preserve historical non-APA behaviour. Pass min_years=0 to the
    # centralized helper.
    final_references = split_trailer_fragments(final_references, author_start_like, min_years=0)
except Exception:
    # Non-fatal: keep original final_references on error
    pass

# New pass: join short trailing lines (fewer than 3 spaces) to the previous
# reference unless the fragment looks like an author line. This runs just
# before the parenthetical-attach pass so that very short continuations like
# 'suppl' or 'Erratum' are attached to the previous reference.
short_joined = []
for idx, frag in enumerate(final_references):
    s = frag
    space_count = s.count(' ') + s.count('\u00A0')
    # If this fragment is short and there is a previous fragment, consider
    # attaching it to the previous unless it looks like an author line.
    if short_joined and space_count < 3:
        attach = True
        if callable(globals().get('is_author_line')):
            try:
                # provide the next fragment as context so comma-led rules can
                # be applied when deciding whether `s` is an author line.
                next_frag = final_references[idx + 1] if (idx + 1) < len(final_references) else ''
                if is_author_line(s, next_frag):
                    attach = False
            except Exception:
                # on error, be conservative and do not attach
                attach = False
        if attach:
            short_joined[-1] = short_joined[-1].rstrip() + ' ' + s.lstrip()
            continue
    short_joined.append(frag)

if DEBUG:
    try:
        write_debug('debug_nonapa_9_after_short_join.txt', short_joined)
    except Exception:
        try:
            with open('debug_nonapa_9_after_short_join.txt', 'w', encoding='utf-8') as df:
                for fr in short_joined:
                    df.write(fr + '\n')
        except Exception:
            pass

final_references = short_joined

# Additional pass: attach fragments that start with '(' or '[' to the previous
# reference. This handles cases where a parenthetical or bracketed continuation
# (e.g., '(in press)', '[Supplement]') was split into its own fragment during
# DOI/URL splitting and should remain attached to the preceding reference.
attached_parenthetical = []
for frag in final_references:
    s = frag.lstrip()
    if attached_parenthetical and s.startswith(('(', '[')):
        # If the fragment contains a closing bracket/paren and then more text,
        # move only the bracketed portion to the previous reference and keep
        # the remainder as a separate fragment. Otherwise attach the whole
        # fragment as before.
        if s.startswith('('):
            close_idx = s.find(')')
        else:
            close_idx = s.find(']')

        if close_idx != -1:
            # include a directly-following period in the bracket part
            end_idx = close_idx + 1
            if end_idx < len(s) and s[end_idx] == '.':
                end_idx += 1
            bracket_part = s[:end_idx]
            remainder = s[end_idx:].lstrip()
            attached_parenthetical[-1] = attached_parenthetical[-1].rstrip() + ' ' + bracket_part
            if remainder:
                attached_parenthetical.append(remainder)
        else:
            # no closing bracket found; attach whole fragment
            attached_parenthetical[-1] = attached_parenthetical[-1].rstrip() + ' ' + s
    else:
        attached_parenthetical.append(frag)

final_references = attached_parenthetical


# Use the canonical `ensure_space_after_canonical_doi` from parsing_helpers


if DEBUG:
    try:
        write_debug('debug_nonapa_10_before_write_refs.txt', final_references)
    except Exception:
        try:
            with open('debug_nonapa_10_before_write_refs.txt', 'w', encoding='utf-8') as df:
                for fr in final_references:
                    df.write(fr + '\n')
        except Exception:
            pass


with open(output_filename, "w") as f:
    for ref in final_references:
        # Apply diaeresis error fixes as a final step
        ref = fix_diaeresis_errors(ref)
        f.write(ref + "\n")

if audit_fp:
    try:
        audit_fp.write('AUDIT LOG END\n')
        audit_fp.close()
    except Exception:
        pass
