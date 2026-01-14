import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import argparse  # noqa: E402
import os  # noqa: E402
from debug_utils import write_debug, debug_path, clear_debug_txt, reset_debug_sequence  # noqa: E402
from parsing_helpers import (  # noqa: E402
    build_parenthesized_year_patterns,
    starts_with_prop_or_sou,
    build_author_patterns,
    move_doi_to_end,
    split_trailer_fragments,
    get_full_text,
    load_and_preprocess,
    should_attach_comma_fragment,
    starts_with_initials_parenthesized_year,
    # relaxed variant allowing intervening author fragments before the year
    starts_with_initials_then_parenthesized_year_allowing_authors,
    line_ends_with_comma_or_initial,
    line_ends_with_conjunction,
    fix_diaeresis_errors,
)
# Precompiled whitespace strip pattern (used when --strip-numbers is requested)
# Keep conservative: only remove the first occurrence per-line when used.
import re as _re  # local alias to avoid shadowing
strip_pattern = _re.compile(r'^\s+|\s+$')
use_local_file = False  # Set to True to use a local PDF file, False to use URL
local_file_path = "PDF.pdf"
url = "https://mau.diva-portal.org/smash/get/diva2:1641892/FULLTEXT01.pdf"
headers = {"User-Agent": "Mozilla/5.0"}

# TXT-mode defaults. The script prefers URL/PDF mode by default; callers and
# test harnesses can force TXT mode by setting the DOIREF_USE_TXT environment
# variable. If DOIREF_USE_TXT is set, DOIREF_TXT_PATH (if present) will be
# used as the TXT input path.
use_txt_file = False
txt_file_path = "references_extracted.txt"

# Parse optional command-line flag --strip-numbers while preserving existing positional args
parser = argparse.ArgumentParser(
    description=(
        'Extract references from PDF or TXT and save to a file.'
    )
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
    '--ref-type',
    choices=['N', 'F'],
    default='N',
    dest='ref_type',
    help=(
        'Reference name type: N (initials-based, default) or '
        'F (full-firstname-aware)'
    ),
)

parser.add_argument(
    '--strip-numbers',
    action='store_true',
    dest='strip_numbers',
    help='Remove leading numbering from references',
)

parser.add_argument(
    '--max-prefix-digits',
    type=int,
    default=3,
    dest='max_prefix_digits',
    help=(
        'Maximum number of digits to consider as a leading list '
        'prefix to strip'
    ),
)

parser.add_argument(
    '--until-eof',
    action='store_true',
    dest='until_eof',
    help=(
        'Continue extracting references until end of file instead of '
        'stopping at next section or single "I"'
    ),
)

parser.add_argument(
    '--no-numbered-fallback',
    action='store_true',
    dest='no_numbered_fallback',
    help=(
        'Do not take the numbered-list fallback path even if '
        'numbered-pattern thresholds are met'
    ),
)
parser.add_argument(
    '--audit-log',
    type=str,
    default=None,
    dest='audit_log',
    help='Path to audit log file (set empty string to disable)',
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
    help='PDF text extraction method: pymupdf or pdfminer (default)',
)
args = parser.parse_args()

# Smart extractor selection based on reference type (APA-style -> pymupdf)
# If the user explicitly provided --extractor on the CLI, respect that choice.
# Otherwise, default to pymupdf for APA-style references which handle
# formatted author/year patterns better. Allow override via DOIREF_EXTRACTOR env var.
if not sys.argv or '--extractor' not in sys.argv:
    # CLI did not explicitly set --extractor, so use smart default
    smart_extractor = os.environ.get('DOIREF_EXTRACTOR', 'pdfminer')  # APA default
    args.extractor = smart_extractor
    if args.url:
        # Log choice for debugging (only when a URL is provided)
        print(f"[Auto-selected extractor: {smart_extractor} for APA-style references]", file=sys.stderr)

if args.url and args.output_filename:
    url = args.url
    output_filename = args.output_filename
else:
    output_filename = args.output_filename if args.output_filename else "references_singleline.txt"

# Flag to control whether to strip numbering when writing output
STRIP_NUMBERS = bool(args.strip_numbers)
# Reference name detection type: default 'N' for initials-based detection.
# If set to 'F' the parser will enable fullname-aware author detection
# (accepts 'Smith, John' or 'Smith, John A.').
REF_TYPE = args.ref_type if hasattr(args, 'ref_type') else 'N'
FULLNAME_DETECTION = (REF_TYPE == 'F')
# Debug: write intermediate files to help trace parsing issues
DEBUG = False
if DEBUG:
    try:
        # Reset the debug canonicalization sequence and remove previous
        # textual snapshots so numbering starts at 001 for this run.
        # We remove existing numerically-prefixed debug files to ensure a
        # truly clean debug/ directory for each run.
        reset_debug_sequence(remove_prefixed_files=True)
        clear_debug_txt()
    except Exception:
        # Non-fatal: continue even if cleanup fails
        pass

# Audit log file (set to None to disable)
audit_fp = None
if getattr(args, 'audit_log', None):
    try:
        audit_fp = open(args.audit_log, 'w', encoding='utf-8')
        audit_fp.write('AUDIT LOG START\n')
    except Exception:
        audit_fp = None

# Honor environment override for using a TXT file, but only when the caller
# explicitly sets DOIREF_USE_TXT. Command-line URL takes precedence (see
# callers like doireg.py that pass a URL). If DOIREF_USE_TXT is set, use the
# provided DOIREF_TXT_PATH if available.
env_txt = os.environ.get('DOIREF_USE_TXT')
if env_txt:
    # Only honor the environment override if there is no explicit URL provided
    # on the command line. If a URL was supplied as an argument, prefer that.
    if not args.url:
        use_txt_file = True
        env_path = os.environ.get('DOIREF_TXT_PATH')
        if env_path:
            txt_file_path = env_path

# If a URL was provided explicitly on the command line, always prefer
# URL/PDF mode regardless of the default above. This ensures callers like
# `doireg.py` that pass a URL will never accidentally run in TXT-mode.
if args.url:
    use_txt_file = False

YR = build_parenthesized_year_patterns()

# Expose the same names used previously in this file for compatibility
YEAR_SINGLE = YR['YEAR_SINGLE']
YEAR_PAREN_INNER = YR['YEAR_PAREN_INNER']
YEAR_PAREN = YR['YEAR_PAREN']
YEAR_PAREN_END = YR['YEAR_PAREN_END']
YEAR_PAREN_START = YR['YEAR_PAREN_START']
YEAR_OPTIONAL_PAREN = YR['YEAR_OPTIONAL_PAREN']
YEAR_BOUNDED_PRE = YR['YEAR_BOUNDED_PRE']

# Build bare year pattern for merging lines that start with a year
try:
    from parsing_helpers import build_nonparenthesized_year_pattern
    YEAR_BARE_START = build_nonparenthesized_year_pattern()
except Exception:
    YEAR_BARE_START = None

# --- PDF or TXT LOADING + basic preprocessing (centralized) ---
# Use the shared helper to load, extract, normalize and hyphen-join the
# reference-bearing text. This centralizes behavior and preserves the
# TXT-mode conservative `require_heading` default by passing
# `require_heading=not use_txt_file` when omitted.
# To mirror the non-APA pipeline behaviour we fetch the full text first
# and then pass it into the centralized preprocessor to avoid subtle
# differences introduced by separate fetch/extract flows.
try:
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
        preloaded_full_text=full_text,
        extractor=args.extractor,
    )
except ValueError as e:
    print(str(e))
    raise

# Unpack canonical artifacts expected by the rest of the pipeline. We keep
# `raw_lines` as the literal split of `references_text` to preserve older
# semantics where callers peek at original physical lines; `lines` contains
# the normalized, hyphen-joined sequence produced by the helper.
full_text = lp.get('full_text')
references_text = lp.get('references_text')
raw_lines = lp.get('raw_lines', references_text.splitlines() if references_text else [])
lines = lp.get('lines', [])

# Save the raw extracted reference section for inspection (mirror non-APA behavior)
try:
    with open('references_extracted.txt', 'w', encoding='utf-8') as f:
        f.write(references_text or '')
except Exception:
    # non-fatal: continue even if writing fails
    pass

# Early debug snapshots: dump full-text info and the raw/normalized lines
if DEBUG:
    try:
        write_debug('doiref_pre_hyphen_fulltext_info.txt', [f'full_text_len: {len(full_text) if full_text is not None else 0}'])
    except Exception:
        pass
    try:
        write_debug('doiref_pre_hyphen_raw_lines.txt', raw_lines)
    except Exception:
        pass
    try:
        write_debug('doiref_pre_hyphen_normalized_lines.txt', lines)
    except Exception:
        pass

# Prepare a view of the lines for numbered-list detection. We avoid
# mutating the canonical `lines` list here unless the user explicitly
# requested `--strip-numbers`. `count_lines` is used for pattern counting
# and detection heuristics. It must be a non-destructive copy of `lines`
# so that numeric prefixes remain available for detection (previously
# we accidentally stripped them which prevented the numbered-path from
# triggering).
# NOTE: keep the numeric prefixes in `count_lines` (don't strip them)
# because the numbered-list heuristics rely on seeing leading numbers.
# Removing those prefixes hides numbered items from detection and can
# silently break the numbered-path (this comment prevents that regression).
try:
    count_lines = list(lines)
except Exception:
    count_lines = lines[:]

if DEBUG:
    try:
        write_debug('doiref_count_lines_snapshot.txt', count_lines)
    except Exception:
        pass

# If the caller requested number stripping, apply it to `lines` now. Keep
# `count_lines` available for detection even when stripping is enabled.
if STRIP_NUMBERS:
    try:
        lines = [strip_pattern.sub('', ln, count=1) for ln in lines]
    except Exception:
        # conservative fallback: leave lines unchanged on error
        pass

    if DEBUG:
        write_debug('doiref_1_raw_lines.txt', lines)

# Detect if the references use a numbered list format. We prefer styles in
# this order: bracketed '[3]' (or '[3.]'), parenthesized '(3)' (or '(3.)'),
# then bare '3.'; we also limit numeric tokens to at most 3 digits to avoid
# matching page numbers or years. Detection uses `count_lines` (the
# non-destructive view) to avoid being influenced by stripping.
re_bracket = re.compile(r'^\[\s*\d{1,3}\.??\s*\]')
re_paren = re.compile(r'^\(\s*\d{1,3}\.??\s*\)')
re_bare = re.compile(r'^\d{1,3}\.\s*')

# Count occurrences per style
bracket_count = sum(1 for ln in count_lines if re_bracket.match(ln))
paren_count = sum(1 for ln in count_lines if re_paren.match(ln))
bare_count = sum(1 for ln in count_lines if re_bare.match(ln))

numbered_style = None
numbered_pattern = None
if bracket_count >= 15:
    numbered_style = 'bracket'
    numbered_pattern = re.compile(r'^\[\s*\d{1,3}\.??\s*\]\s*')
    num_count = bracket_count
elif paren_count >= 15:
    numbered_style = 'paren'
    numbered_pattern = re.compile(r'^\(\s*\d{1,3}\.??\s*\)\s*')
    num_count = paren_count
else:
    bare_threshold = 30 if args.until_eof else 10
    if bare_count >= bare_threshold:
        numbered_style = 'bare'
        numbered_pattern = re.compile(r'^\d{1,3}\.\s*')
        num_count = bare_count
    else:
        numbered_style = None
        numbered_pattern = None
        num_count = 0

# Heuristic: trigger the numbered-path when enough numbered lines are found.
if not getattr(args, 'no_numbered_fallback', False):
    trigger_threshold = 10
    if numbered_style == 'bare' and args.until_eof:
        trigger_threshold = 30
    if num_count >= trigger_threshold:
        # Numbered references detected! Re-extract with pymupdf if we used pdfminer.
        # pymupdf works better for numbered/structured reference lists.
        if args.extractor == 'pdfminer' and not use_txt_file:
            print(f"[Numbered references detected ({num_count} items, style={numbered_style})]", file=sys.stderr)
            print(f"[Re-extracting with pymupdf for better numbered-list handling...]", file=sys.stderr)
            try:
                # Re-fetch full text with pymupdf
                full_text = get_full_text(
                    source=args.url or url,
                    use_local_file=use_local_file,
                    local_file_path=local_file_path,
                    use_txt_file=False,  # Never use TXT for re-extraction
                    txt_file_path=txt_file_path,
                    headers=headers,
                    verify='combined_ca.pem',
                    extractor='pymupdf',
                )
                # Re-run preprocessing with pymupdf extraction
                lp = load_and_preprocess(
                    source=args.url or url,
                    use_local_file=use_local_file,
                    local_file_path=local_file_path,
                    use_txt_file=False,
                    txt_file_path=txt_file_path,
                    headers=headers,
                    verify='combined_ca.pem',
                    until_eof=args.until_eof,
                    stop_at_allcaps=False,
                    require_heading=not use_txt_file,
                    audit_fp=audit_fp,
                    preloaded_full_text=full_text,
                    extractor='pymupdf',
                )
                # Update lines and references_text with pymupdf extraction
                full_text = lp.get('full_text')
                references_text = lp.get('references_text')
                raw_lines = lp.get('raw_lines', references_text.splitlines() if references_text else [])
                lines = lp.get('lines', [])
                
                # Re-save the extracted reference section
                try:
                    with open('references_extracted.txt', 'w', encoding='utf-8') as f:
                        f.write(references_text or '')
                except Exception:
                    pass
                
                # Rebuild count_lines for the new extraction
                try:
                    count_lines = list(lines)
                except Exception:
                    count_lines = lines[:]
                
                # Re-detect numbered patterns with new extraction
                bracket_count = sum(1 for ln in count_lines if re_bracket.match(ln))
                paren_count = sum(1 for ln in count_lines if re_paren.match(ln))
                bare_count = sum(1 for ln in count_lines if re_bare.match(ln))
                
                if bracket_count >= 15:
                    numbered_style = 'bracket'
                    numbered_pattern = re.compile(r'^\[\s*\d{1,3}\.??\s*\]\s*')
                    num_count = bracket_count
                elif paren_count >= 15:
                    numbered_style = 'paren'
                    numbered_pattern = re.compile(r'^\(\s*\d{1,3}\.??\s*\)\s*')
                    num_count = paren_count
                else:
                    bare_threshold = 30 if args.until_eof else 10
                    if bare_count >= bare_threshold:
                        numbered_style = 'bare'
                        numbered_pattern = re.compile(r'^\d{1,3}\.\s*')
                        num_count = bare_count
                
                print(f"[Re-extraction complete: {num_count} numbered items detected with pymupdf]", file=sys.stderr)
            except Exception as e:
                print(f"[Warning: Re-extraction with pymupdf failed: {e}]", file=sys.stderr)
                print(f"[Continuing with original pdfminer extraction...]", file=sys.stderr)
        
        try:
            local_max_iter = int(os.environ.get('DOIREF_MAX_ITER', '10'))
        except Exception:
            local_max_iter = 10

        def one_numbered_pass(input_lines):
            out = []
            curr = None
            curr_number = None
            for ln in input_lines:
                if numbered_pattern.match(ln):
                    mnum = re.search(r'\d{1,3}', ln)
                    this_num = int(mnum.group(0)) if mnum else None
                    rest = numbered_pattern.sub('', ln, count=1)
                    if curr is not None and not rest.strip() and curr_number is not None:
                        if this_num is not None and this_num == curr_number + 1:
                            out.append(curr)
                            curr = ln
                            curr_number = this_num
                            continue
                        else:
                            curr = curr.rstrip() + ' ' + ln.lstrip()
                            continue
                    if curr is not None:
                        out.append(curr)
                    curr = ln
                    curr_number = this_num
                else:
                    if curr is None:
                        curr = ln
                        curr_number = None
                    else:
                        if starts_with_prop_or_sou(ln.lstrip()):
                            out.append(curr)
                            curr = ln
                            curr_number = None
                        else:
                            curr = curr.rstrip() + ' ' + ln.lstrip()
            if curr is not None:
                out.append(curr)
            return out

        prev_num = lines
        iter_num = 0
        while True:
            iter_num += 1
            new_num = one_numbered_pass(prev_num)
            if DEBUG:
                write_debug(f'doiref_numbered_iter{iter_num}.txt', new_num)
            if new_num == prev_num:
                final_numbered = new_num
                break
            if iter_num >= local_max_iter:
                if DEBUG:
                    hdr = [
                        f'MAX_ITER reached in numbered pass: {local_max_iter} iterations',
                        f'ITERATIONS_PERFORMED: {iter_num}',
                        'CURRENT_OUTPUT:',
                    ]
                    write_debug('doiref_numbered_maxiter.txt', hdr + new_num)
                final_numbered = new_num
                break
            prev_num = new_num

    # Only proceed with final-numbered output/debug if the numbered pass actually ran
    if num_count >= trigger_threshold:
        if DEBUG:
            write_debug('doiref_numbered_after_join.txt', [f'ITERATIONS_PERFORMED: {iter_num}'] + final_numbered)

        if numbered_style == 'bracket':
            number_prefix_re = re.compile(r'^\s*\[\s*\d{1,3}\.??\s*\]\s*')
        elif numbered_style == 'paren':
            number_prefix_re = re.compile(r'^\s*\(\s*\d{1,3}\.??\s*\)\s*')
        else:
            number_prefix_re = re.compile(r'^\s*\d{1,3}\.\s*')

        with open(output_filename, 'w', encoding='utf-8') as f:
            for ref in final_numbered:
                if STRIP_NUMBERS:
                    cleaned = number_prefix_re.sub('', ref, count=1)
                    f.write(cleaned + '\n')
                else:
                    f.write(ref + '\n')

        standalone_count = 0
        total_lines = 0
        if os.path.exists(output_filename):
            with open(output_filename, 'r', encoding='utf-8', errors='replace') as of:
                for ref in of:
                    total_lines += 1
                    ref = ref.rstrip('\n')
                    rest = number_prefix_re.sub('', ref, count=1).strip()
                    if not rest:
                        standalone_count += 1
        else:
            for ref in final_numbered:
                total_lines += 1
                rest = number_prefix_re.sub('', ref, count=1).strip()
                if not rest:
                    standalone_count += 1

        ratio = 0.0 if total_lines == 0 else (standalone_count / float(total_lines))

        if DEBUG:
            debug_items = [
                f'numbered_style: {numbered_style}',
                f'total_lines: {total_lines}',
                f'standalone_count: {standalone_count}',
                f'ratio: {ratio}',
            ]
            write_debug('doiref_numbered_standalone_check.txt', debug_items)

        if total_lines > 0 and ratio > 0.5:
            stripped_path = 'references_raw_no_numbers.txt'
            out_lines = []
            prefix_re = number_prefix_re
            debug1_path = debug_path('doiref_1_raw_lines.txt')
            if os.path.exists(debug1_path):
                with open(debug1_path, 'r', encoding='utf-8', errors='replace') as srcf:
                    for ln in srcf:
                        out_lines.append(prefix_re.sub('', ln.rstrip('\n'), count=1))
            elif os.path.exists(output_filename):
                with open(output_filename, 'r', encoding='utf-8', errors='replace') as of:
                    for ln in of:
                        out_lines.append(prefix_re.sub('', ln.rstrip('\n'), count=1))
            elif os.path.exists('references_raw.txt'):
                with open('references_raw.txt', 'r', encoding='utf-8', errors='replace') as rf:
                    for ln in rf:
                        out_lines.append(prefix_re.sub('', ln.rstrip('\n'), count=1))
            else:
                for ln in lines:
                    out_lines.append(prefix_re.sub('', ln, count=1))
            with open(stripped_path, 'w', encoding='utf-8') as sf:
                sf.write('\n'.join(out_lines))

            if DEBUG:
                write_debug('doiref_numbered_fallback_stripped.txt', out_lines)

            env = os.environ.copy()
            env['DOIREF_USE_TXT'] = '1'
            env['DOIREF_TXT_PATH'] = os.path.abspath(stripped_path)
            try:
                subprocess.run(
                    [
                        sys.executable,
                        os.path.join(os.path.dirname(__file__), 'doiref_nonapa.py'),
                    ],
                    check=True,
                    env=env,
                )
            except Exception as e:
                if DEBUG:
                    write_debug('doiref_numbered_fallback_error.txt', str(e))
            sys.exit(0)

        sys.exit(0)

# Before pre-appending the following non-empty line when a line ends with a
# parenthesized bounded year, first merge any lines that START with a
# parenthesis or a year into the previous non-empty line. This handles
# cases where the parenthesized year appears on the beginning of a physical
# line (e.g. "(2016) Title...") which should be treated as a continuation
# of the previous reference rather than a new reference.
if DEBUG:
    # write a pre-merge snapshot for easier debugging
    write_debug('doiref_pre_year_start_merge.txt', lines)

# Merge lines that start with '(' or a bare year to the previous line.
if lines:
    merged_start_paren = []
    for ln in lines:
        stripped = ln.lstrip()
        starts_with_paren = stripped.startswith('(')
        starts_with_year = False
        
        # Check if line starts with a bare year
        if YEAR_BARE_START and not starts_with_paren:
            try:
                match = YEAR_BARE_START.match(stripped)
                if match:
                    starts_with_year = True
            except Exception:
                pass
        
        if starts_with_paren or starts_with_year:
            if merged_start_paren:
                # append this line starting with '(' or year to the last merged entry
                merged_start_paren[-1] = merged_start_paren[-1].rstrip() + ' ' + stripped
            else:
                # no previous line to attach to; keep as-is
                merged_start_paren.append(ln)
        else:
            merged_start_paren.append(ln)
    lines = merged_start_paren
    if DEBUG:
        write_debug('doiref_after_paren_start_merge.txt', lines)

# Pre-append next non-empty line when a line ends with a parenthesized bounded
# year. This helps when the year is on its own line followed by
# a continuation (e.g., title or publisher) on the next physical line.
year_end_paren = YEAR_PAREN_END
if lines:
    # General exception: do not join lines that START with a Prop. marker
    # or with a SOU entry of the form 'SOU YYYY:NNN' (1900-2030, 1-3 digits).
    # This applies across all join rules below: if the candidate next line
    # begins with either marker, we will NOT append it to the previous line.
    # The centralized helper `starts_with_prop_or_sou` was imported earlier
    # to make it available for the numbered-pass and other early logic.

    new_lines = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if year_end_paren.search(ln):
            # If a line ends with a parenthesized year we previously intended to
            # append the following non-empty line; keep the pre-append behavior
            # here and then fall through to the simplified pipeline below.
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                # Do not append if the following line starts with Prop. or SOU
                if starts_with_prop_or_sou(lines[j].lstrip()):
                    new_lines.append(ln)
                    # do not consume the following line here; let normal flow handle it
                    i += 1
                    continue
                new_lines.append(ln.rstrip() + ' ' + lines[j].lstrip())
                i = j + 1
                continue
        new_lines.append(ln)
        i += 1

    lines = new_lines

    # Debug snapshot: state immediately after the "year ends with parenthesized"
    # pre-append pass and before we begin editor-token merging. This helps
    # trace regressions where pre-append combined or skipped an intended
    # continuation. Use the existing DEBUG guard and the canonical
    # write_debug helper so snapshots follow the same naming/numbering.
    # --- New iterative pass: join short single-token lines that contain
    # at least one digit or one of the characters ()[]/: to the previous
    # non-empty line. Run iteratively until fixed-point or max iterations
    # (default 10) to handle cascaded fragments (e.g. DOI parts split over
    # several single-token lines). A 'single-token' here means the line
    # contains no whitespace.
    try:
        try:
            max_single_token_iter = int(os.environ.get('DOIREF_JOIN_SHORT_MAX_ITER', '10'))
        except Exception:
            max_single_token_iter = 10

        iter_j = 0
        prev_join = list(lines)
        while True:
            iter_j += 1
            new_join = []
            changed = False
            for idx, ln in enumerate(prev_join):
                # allow trailing/leading whitespace — operate on the stripped token
                stripped_ln = ln.strip() if ln is not None else ''
                # join any single-token physical line (no internal whitespace)
                # including letters-only tokens
                if idx > 0 and stripped_ln and not re.search(r'\s', stripped_ln):
                    # attach this short token (use stripped form) to previous
                    new_join[-1] = new_join[-1].rstrip() + ' ' + stripped_ln
                    changed = True
                    continue
                new_join.append(ln)

            prev_join = new_join
            if DEBUG:
                try:
                    write_debug(f'doiref_post_year_end_pre_editor_join_iter{iter_j}.txt', prev_join)
                except Exception:
                    pass
            if not changed or iter_j >= max_single_token_iter:
                break

        lines = prev_join
    except Exception:
        # conservative: leave original lines on error
        if DEBUG:
            try:
                write_debug('doiref_post_year_end_pre_editor_join_error.txt', ['ERROR in single-token join pass'])
            except Exception:
                pass

    if DEBUG:
        try:
            write_debug('doiref_post_year_end_pre_editor.txt', lines)
        except Exception:
            pass

    # --- New small pass: merge lines that start with 1-3 initials + (year)
    # into the previous line when the previous line ends with a comma or an initial.
    # This sits before the editor-token pass to avoid swallowing editor tokens.
    try:
        if lines:
            merged_initials = []
            for idx, ln in enumerate(lines):
                if idx > 0 and (
                    starts_with_initials_parenthesized_year(ln)
                    or starts_with_initials_then_parenthesized_year_allowing_authors(ln)
                ):
                    prev = merged_initials[-1] if merged_initials else None
                    if prev and line_ends_with_comma_or_initial(prev):
                        # attach to previous
                        merged_initials[-1] = prev.rstrip() + ' ' + ln.lstrip()
                        continue
                merged_initials.append(ln)
            lines = merged_initials
            if DEBUG:
                write_debug('doiref_after_initials_year_merge.txt', lines)
    except Exception:
        # conservative: on error, keep original lines
        if DEBUG:
            try:
                write_debug('doiref_after_initials_year_merge_error.txt', ['ERROR in initials-year merge'])
            except Exception:
                pass

    # --- New pass: join author lines that end with '&', 'and', or 'och' to the next line
    # This helps when author lists are split across physical lines with a trailing
    # conjunction (for example 'Smith, J., &' followed by 'Doe, A. (2020) ...').
    # We conservatively skip joining when the following non-empty line starts
    # with a Prop. or SOU marker which should start a new reference.
    try:
        if lines:
            merged_amp = []
            i = 0
            while i < len(lines):
                ln = lines[i]
                if line_ends_with_conjunction(ln):
                    # find next non-empty line
                    j = i + 1
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    if j < len(lines):
                        # Do not join if the following line begins with Prop. or SOU
                        if starts_with_prop_or_sou(lines[j].lstrip()):
                            merged_amp.append(ln)
                            i += 1
                            continue
                        # Attach the following non-empty line
                        merged_amp.append(ln.rstrip() + ' ' + lines[j].lstrip())
                        i = j + 1
                        continue
                merged_amp.append(ln)
                i += 1
            lines = merged_amp
            if DEBUG:
                write_debug('doiref_after_author_ampersand_merge.txt', lines)
    except Exception:
        if DEBUG:
            try:
                write_debug('doiref_after_author_ampersand_merge_error.txt', ['ERROR in ampersand/and/och merge'])
            except Exception:
                pass

    # --- Additional small pass: append editor tokens to previous line ---
    # Make this pass iterative: run the two-step editor-token merges up to
    # `max_editor_iter` times (default 3) or until there are no more lines
    # that contain an editor token parenthetical and do NOT contain a
    # parenthesized year. This prevents leaving unresolved editor tokens
    # scattered across lines while keeping the operation bounded.
    editor_token_re = re.compile(r'^(?:eds?|red)\.?$', flags=re.I)
    # Build author-related patterns early so the editor-token pass can
    # conservatively avoid attaching lines that look like an author start.
    # We build a minimal active variant here; the full author patterns will
    # be rebuilt later for the simplified join pass as well.
    try:
        _ap_editor = build_author_patterns(FULLNAME_DETECTION)
        # author_pattern_active is a stricter pattern that matches whole
        # author-only lines; prefer it here so we avoid attaching lines
        # that are complete author headers rather than lines that merely
        # start like an author.
        author_pattern_active = _ap_editor.get('author_pattern_active')
        author_start_like_active = _ap_editor.get('author_start_like_active')
        # Looser multi-surname start-like matcher (may be None).
        author_start_like_multi = _ap_editor.get('author_start_like_multi')
        initial_editor = _ap_editor.get('initial')
    except Exception:
        author_pattern_active = None
        author_start_like_active = None
        author_start_like_multi = None
        initial_editor = None

    # Helper: stricter author-only detection used for editor-merge decisions.
    # Mirrors the conservative checks used in the non-APA pipeline's
    # `is_author_line` helper: match the full author pattern, reject if the
    # matched prefix contains digits, require initial-like tokens when the
    # match is not at the end of the line, and reject if any obvious 4-digit
    # year appears anywhere in the line.
    def is_author_line_editor(line: str, next_line: str = None) -> bool:
        if not line:
            return False
        if not author_pattern_active:
            return False
        # If the line begins with a leading comma, consult the centralized
        # comma-fragment heuristic which requires a lookahead to the next
        # physical line. If no next_line is provided, conservatively return
        # False so the editor-merge logic does not swallow stray fragments.
        if line.lstrip().startswith(','):
            if next_line:
                try:
                    # Prefer the looser multi-surname start-like matcher when
                    # available so comma-fragment attachment recognizes cases
                    # like 'de Rezende Barbosa, G. L.'; fall back to the
                    # original start-like matcher otherwise.
                    return should_attach_comma_fragment(
                        line,
                        next_line,
                        FULLNAME_DETECTION,
                        initial_editor,
                        author_start_like_multi or author_start_like_active,
                    )
                except Exception:
                    return False
            return False
        m = author_pattern_active.match(line)
        if not m:
            # If the strict author-only pattern doesn't match, allow the
            # looser multi-surname start-like matcher when the line clearly
            # indicates a continued author list (trailing comma) and there
            # is no parenthesized year or digit noise. This is a
            # conservative relaxation to handle cases like
            # 'de Rezende Barbosa, G. L.,' where the strict pattern may
            # fail but the line is clearly an author fragment.
            try:
                if author_start_like_multi and author_start_like_multi.match(line):
                    # require a trailing comma as an extra safety guard
                    if line.rstrip().endswith(',') and not YEAR_PAREN.search(line) and not re.search(r"\d", line):
                        return True
            except Exception:
                # on any error, fall through to conservative reject
                pass
            return False
        matched_prefix = m.group(0)
        # Reject if matched prefix contains any digit
        if re.search(r"\d", matched_prefix):
            return False
        after = line[len(matched_prefix):].lstrip()
        # Allow a trailing leftover that is only punctuation (e.g. '.' or ',')
        # to be treated as if there is no trailing text. This mirrors the
        # conservative relaxation in the non-APA pipeline so small trailing
        # punctuation tokens do not prevent author-line detection.
        if after and re.match(r'^[\s\.,:;\-\—\–&"\'\(\)\[\]]*$', after):
            after = ''
        # If there is trailing text after the matched prefix, ensure the
        # matched prefix contains an initial-like token; otherwise reject.
        if after:
            if initial_editor:
                try:
                    if not re.search(initial_editor, matched_prefix):
                        return False
                except re.error:
                    # On any regex issue conservatively reject
                    return False
            else:
                # If we don't have an `initial` pattern, conservatively reject
                return False
        # Reject if the line contains a parenthesized year (APA uses those)
        if YEAR_PAREN.search(line):
            return False
        return True
    try:
        max_editor_iter = int(os.environ.get('DOIREF_EDITOR_MAX_ITER', '3'))
    except Exception:
        max_editor_iter = 3

    # --- New pass: join lines that START with '&' to the previous line when
    # the previous line is detected as an author line. This is conservative:
    # only join when the previous non-empty merged entry satisfies the
    # `is_author_line_editor` predicate to avoid swallowing new references.
    try:
        if lines:
            merged_amp_start = []
            i_as = 0
            while i_as < len(lines):
                ln_as = lines[i_as]
                # consider lines that begin with an ampersand after optional whitespace
                if ln_as and ln_as.lstrip().startswith('&'):
                    prev = merged_amp_start[-1] if merged_amp_start else None
                    if prev and is_author_line_editor(prev):
                        # attach to previous
                        merged_amp_start[-1] = prev.rstrip() + ' ' + ln_as.lstrip()
                        i_as += 1
                        continue
                merged_amp_start.append(ln_as)
                i_as += 1
            lines = merged_amp_start
            if DEBUG:
                try:
                    write_debug('doiref_after_ampersand_start_merge.txt', lines)
                except Exception:
                    pass
    except Exception:
        if DEBUG:
            try:
                write_debug('doiref_after_ampersand_start_merge_error.txt', ['ERROR in ampersand-start merge'])
            except Exception:
                pass

    def _has_unresolved_editor_token(candidate_lines):
        for ln in candidate_lines:
            # ignore lines that already contain a parenthesized year
            if YEAR_PAREN.search(ln):
                continue
            for p in re.findall(r'\(([^)]*)\)', ln):
                if editor_token_re.match(p.strip()):
                    return True
        return False

    iter_e = 0
    while True:
        iter_e += 1
        merged_with_editors = []
        for idx, ref in enumerate(lines):
            # Only consider merging when there is a previous entry and the line
            # does not contain a parenthesized year.
            if idx > 0 and not YEAR_PAREN.search(ref):
                m = re.search(r'\(([^)]*)\)', ref)
                if m:
                    first_content = m.group(1).strip()
                    if editor_token_re.match(first_content):
                        # Don't merge if this line starts with Prop. or SOU
                        if starts_with_prop_or_sou(ref.lstrip()):
                            merged_with_editors.append(ref)
                            continue
                        merged_with_editors[-1] = merged_with_editors[-1].rstrip() + ' ' + ref.lstrip()
                        continue
            merged_with_editors.append(ref)

        # second pass: if the previous line contains an editor token, append the current line
        out_after_prev_editor = []
        for i, ref in enumerate(merged_with_editors):
            if i == 0:
                out_after_prev_editor.append(ref)
                continue
            prev = out_after_prev_editor[-1]
            if not YEAR_PAREN.search(ref):
                # Conservative detection: only treat the previous line as
                # editor-anchored when the LAST parenthetical matches the
                # editor token (e.g. '(Eds.)' or '(Ed.)') and there is
                # nothing but punctuation/whitespace after that closing
                # parenthesis. This avoids swallowing a following author
                # block when the editor parenthetical is embedded within
                # a longer sentence.
                prev_paren_iters = list(re.finditer(r'\(([^)]*)\)', prev))
                prev_has_editor = False
                if prev_paren_iters:
                    last_paren = prev_paren_iters[-1]
                    paren_text = last_paren.group(1).strip()
                    if editor_token_re.match(paren_text):
                        after = prev[last_paren.end():].strip()
                        # Allow only common punctuation and whitespace after
                        # the editor parenthetical. Keep the class conservative
                        # (period, comma, colon, semicolon, dash, quotes,
                        # parentheses, brackets) to avoid needing extra
                        # regex engine features.
                        if not after or re.match(r'^[\s\.,:;\-\—\–\"\'"\(\)\[\]]*$', after):
                            prev_has_editor = True

                if prev_has_editor:
                    # Do not attach if the current line starts like a Prop./SOU
                    # entry or if it looks like an author start (we don't want
                    # to swallow a whole new reference).
                    if starts_with_prop_or_sou(ref.lstrip()):
                        out_after_prev_editor.append(ref)
                        continue
                    # Prefer the stricter author-only detection: if the
                    # current line matches an author-only pattern, do not
                    # attach it. Fall back to the start-like check only if
                    # the stricter pattern is unavailable.
                    if author_pattern_active and author_pattern_active.match(ref.lstrip()):
                        out_after_prev_editor.append(ref)
                        continue
                    # Accept matches from either the strict start-like or the
                    # looser multi-surname start-like matcher to avoid
                    # swallowing a new author block.
                    if not author_pattern_active and (
                        (author_start_like_active and author_start_like_active.match(ref.lstrip()))
                        or (author_start_like_multi and author_start_like_multi.match(ref.lstrip()))
                    ):
                        out_after_prev_editor.append(ref)
                        continue
                    out_after_prev_editor[-1] = prev.rstrip() + ' ' + ref.lstrip()
                    continue
            out_after_prev_editor.append(ref)

        lines = out_after_prev_editor

        if DEBUG:
            write_debug(f'doiref_editor_iter{iter_e}.txt', lines)

        # Stop if there are no more unresolved editor tokens or we've hit the cap
        if not _has_unresolved_editor_token(lines) or iter_e >= max_editor_iter:
            break

    # --- Now run the simplified post-debug3b pipeline requested by the user ---
    # Ensure author- and editor-related regexes are available from shared helper.

    _ap = build_author_patterns(FULLNAME_DETECTION)
    author_pattern = _ap['author_pattern']
    author_start_like = _ap['author_start_like']
    author_pattern_active = _ap['author_pattern_active']
    author_start_like_active = _ap['author_start_like_active']
    author_start_like_multi = _ap.get('author_start_like_multi')
    author_start_like_fullname_space = _ap.get('author_start_like_fullname_space')
    publisher_blacklist_re = _ap.get('publisher_blacklist_re')
    first_name_whitelist = _ap.get('first_name_whitelist')
    given_name_re = _ap.get('given_name_re')
    editor_token_re = _ap['editor_token_re']
    trailer = _ap['trailer']
    initial = _ap['initial']
    numbered_pattern = re.compile(r'^(?:\d+\.\s*|\[\d+\]\s*)')

    # Write the debug3b snapshot (state before the simplified join)
    current_ref = globals().get('current_ref', '')
    dbg_lines = ['CURRENT_REF: ' + (current_ref.strip() if current_ref else ''), 'REMAINING_LINES:'] + lines
    write_debug('doiref_3b_after_author_append.txt', dbg_lines)

    # Apply the simple rule iteratively until a fixed-point (no more merges).
    # This ensures multi-line author fragments (author line -> continuation -> more continuation)
    # get fully merged even if they require multiple passes.
    def one_pass_apply(input_lines):
        out = []
        i = 0
        while i < len(input_lines):
            ln = input_lines[i].strip()
            if not ln:
                i += 1
                continue
            # If this line contains a parenthesized year anywhere, leave as-is.
            if YEAR_PAREN.search(ln):
                out.append(ln)
                i += 1
                continue
            # If it starts with an author-like pattern and contains at least two spaces,
            # append the following non-empty line. The two-space requirement reduces
            # false positives where a single capitalized token followed by a word
            # (e.g. 'Evidence') was mistaken for an author start.
            # Require at least two whitespace characters of any kind (spaces, tabs,
            # NBSP, etc.) to reduce false positives while allowing other whitespace
            # characters beyond ASCII space.
            # Ensure the candidate author line does not contain any digits to
            # avoid merging lines like 'Chapter 3' or numbered headings.
            # Treat as an author-start when any of the following hold:
            #  - strict author pattern matches, or
            #  - the active start-like matcher matches (prefers multi-surname), or
            #  - a conservative heuristic: the line ends with a comma, contains
            #    multiple commas (typical of multi-author chains), and has no digits
            #    or parenthesized year. The heuristic helps catch long
            #    comma-separated author lists that the regex may miss.
            if (
                (
                    author_pattern.match(ln)
                    or (author_start_like_active and author_start_like_active.match(ln))
                    or (ln.rstrip().endswith(',') and ln.count(',') >= 2 and not YEAR_PAREN.search(ln) and not re.search(r"\d", ln))
                )
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
            # Default: keep the line as-is
            out.append(ln)
            i += 1
        return out

    # Maximum iterations to avoid pathological infinite loops; configurable via env.
    try:
        MAX_ITER = int(os.environ.get('DOIREF_MAX_ITER', '10'))
    except Exception:
        MAX_ITER = 10

    prev = lines
    iteration = 0
    while True:
        iteration += 1
        new = one_pass_apply(prev)
        # Write a per-iteration debug snapshot so it's easy to inspect progress
        if DEBUG:
            write_debug(f'doiref_3c_iter{iteration}.txt', new)
        if new == prev:
            final_refs = new
            break
        if iteration >= MAX_ITER:
            # Cap hit: write a notice and treat the last result as final to avoid hang.
            if DEBUG:
                hdr = [
                    f'MAX_ITER reached: {MAX_ITER} iterations',
                    f'ITERATIONS_PERFORMED: {iteration}',
                    'CURRENT_OUTPUT:',
                ]
                write_debug('doiref_3c_maxiter_reached.txt', hdr + new)
            final_refs = new
            break
        prev = new

    # Write the simplified debug outputs and the final single-line references
    write_debug('doiref_3c_after_main_joining.txt', [f'ITERATIONS_PERFORMED: {iteration}'] + final_refs)
    with open(output_filename, 'w', encoding='utf-8') as f:
        for ref in final_refs:
            if STRIP_NUMBERS:
                number_prefix_re = re.compile(r'^\s*(?:\d+\.\s*|\[\d+\]\s*|\d+\s+)')
                cleaned = number_prefix_re.sub('', ref, count=1)
                f.write(cleaned + '\n')
            else:
                f.write(ref + '\n')

    # --- Additional pass: iteratively append any non-first line that does NOT
    # contain a parenthesized year to the previous line. This continues until
    # all lines contain a parenthesized year or the MAX_ITER cap is reached.
    def append_nonyear_pass(input_lines):
        out = []
        if not input_lines:
            return out
        out.append(input_lines[0])
        i = 1
        while i < len(input_lines):
            ln = input_lines[i]
            if not YEAR_PAREN.search(ln):
                # append to previous unless the current line looks like a
                # Prop. or SOU entry which should start a new reference.
                # NOTE: we intentionally no longer treat numbered-list
                # prefixes as automatic new entries here so numeric-only
                # fragments (including DOI lines like '12345. https://...')
                # will be appended to the previous reference.
                if starts_with_prop_or_sou(ln.lstrip()):
                    out.append(ln)
                else:
                    out[-1] = out[-1].rstrip() + ' ' + ln.lstrip()
            else:
                out.append(ln)
            i += 1
        return out

    prev2 = final_refs
    iter2 = 0
    while True:
        iter2 += 1
        new2 = append_nonyear_pass(prev2)
        if DEBUG:
            write_debug(f'doiref_4_iter{iter2}.txt', new2)
        if new2 == prev2:
            final_refs2 = new2
            break
        if iter2 >= MAX_ITER:
            if DEBUG:
                hdr = [
                    f'MAX_ITER reached in append-nonyear pass: {MAX_ITER} iterations',
                    f'ITERATIONS_PERFORMED: {iter2}',
                    'CURRENT_OUTPUT:',
                ]
                write_debug('doiref_4_maxiter_reached.txt', hdr + new2)
            final_refs2 = new2
            break
        prev2 = new2

    # Write final debug for this pass including iteration count
    write_debug('doiref_4_after_append_nonyear.txt', [f'ITERATIONS_PERFORMED: {iter2}'] + final_refs2)

    # Post-process: split accidental merges where a previous entry ends with a
    # bracketed qualification (e.g. '[Doktorsavhandling, ...].') followed by
    # another reference starting immediately after (for example
    # "... universitet]. Freake, H., ..."). These were observed in the
    # debug snapshots and indicate two separate references were merged. We
    # split such cases when the trailing fragment before the author looks
    # like a closing bracket + period and the following text looks like an
    # author start (conservative test using author_start_like).
    # Use the shared helper to conservatively split trailing bracketed
    # qualifications followed by an author-like start (e.g. '...]. Freake, H., ...').
    try:
        # Delegate the conservative per-fragment decision to the shared
        # helper `split_trailer_fragments`, which will internally decide
        # whether to split based on the number of parenthesized years and
        # other heuristics. This centralizes the logic so callers don't
        # duplicate the year-counting rule.
        post_split = []
        for frag in final_refs2:
            try:
                # Prefer the multi-surname matcher for trailer-splitting
                # heuristics when available.
                split_res = split_trailer_fragments([frag], author_start_like_multi or author_start_like_active)
                if split_res:
                    post_split.extend(split_res)
                else:
                    post_split.append(frag)
            except Exception:
                post_split.append(frag)
        final_refs2 = post_split
    except Exception:
        # Non-fatal: keep original final_refs2 on error
        pass
    if DEBUG:
        write_debug('doiref_4_post_split.txt', ['POST_SPLIT_RESULTS:'] + final_refs2)
    # --- Move DOI/URLs to end of each reference (extended)
    # We want to catch DOI in several forms:
    # - https://doi.org/10.xxx/... 
    # - doi:10.xxx/... (case-insensitive, optional space)
    # - bare identifier like 10.xxx/...
    # The user also marks DOIs with a [DOI] tag which can appear before or
    # after the identifier; we only move text that validates as a DOI
    # identifier (we require it to start with '10.' followed by digits and
    # a '/' and then the rest).
    # Centralized DOI helpers are provided by parsing_helpers.py
    # (extract_doi_ids and move_doi_to_end)

    # Apply DOI-moving to the final refs. `move_doi_to_end` performs its own
    # conservative normalization internally, so an explicit separate call to
    # `normalize_doi_in_fragment` is redundant.
    final_refs2 = [move_doi_to_end(r) for r in final_refs2]
    final_refs2 = [move_doi_to_end(r) for r in final_refs2]
    # Note: the previous targeted split-on-Prop rule has been replaced by a
    # general exception earlier: lines that START with a Prop. marker or
    # with a SOU YYYY:NNN entry will NOT be joined to the previous line.
    # This avoids needing an additional split pass here.

    # Optionally overwrite the public output file with the fully-merged results
    with open(output_filename, 'w', encoding='utf-8') as f:
        for ref in final_refs2:
            # Apply diaeresis error fixes as a final step
            ref = fix_diaeresis_errors(ref)
            if STRIP_NUMBERS:
                number_prefix_re = re.compile(r'^\s*(?:\d+\.\s*|\[\d+\]\s*|\d+\s+)')
                cleaned = number_prefix_re.sub('', ref, count=1)
                f.write(cleaned + '\n')
            else:
                f.write(ref + '\n')
