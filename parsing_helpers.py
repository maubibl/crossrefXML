import os
import re
from debug_utils import write_debug, is_debug_enabled


# General Prop./SOU helpers
# Allow year/serial in parentheses for all markers: 'SOU 2000:11' or 'SOU (2000:11)'
prop_start_re = re.compile(r'(?i)^\s*(?:Prop\.|Proposition)\s*\(?(?:19\d{2}|20(?:0\d|1\d|2\d|30))/\d{2}:\d{1,3}\)?')
# Accept SOU or SFS markers. Allow either a space or a colon between the marker
# and the year. SFS uses a 1-4 digit serial number after the year; SOU uses
# a 1-3 digit number historically. Year range limited to approx 1900-2030.
_YEAR_SIMPLE = r'(?:19\d{2}|20(?:0\d|1\d|2\d|30))'
sou_start_re = re.compile(r'(?i)^\s*SOU[:\s]+\(?' + _YEAR_SIMPLE + r':\d{1,3}\)?')
sfs_start_re = re.compile(r'(?i)^\s*SFS[:\s]+\(?' + _YEAR_SIMPLE + r':\d{1,4}\)?')
ds_start_re = re.compile(r'(?i)^\s*Ds[:\s]+\(?' + _YEAR_SIMPLE + r':\d{1,3}\)?')


def starts_with_prop_or_sou(s: str) -> bool:
    """Return True if a line starts with a governmental Prop., SOU, SFS, or Ds marker.

    Recognized forms (case-insensitive):
        - "Prop. YYYY/NN:NNN" or "Prop. (YYYY/NN:NNN)" where YYYY is 1900-2030
        - "SOU YYYY:NNN" or "SOU (YYYY:NNN)" where YYYY is 1900-2030
        - "SFS YYYY:NNN" or "SFS (YYYY:NNN)" where YYYY is 1900-2030
        - "Ds YYYY:NNN" or "Ds (YYYY:NNN)" where YYYY is 1900-2030

    The function accepts a string `s` (may contain leading whitespace) and
    returns True when the string begins with any of these markers. This helper is
    authoritative for the codebase: callers should import and use this
    function instead of duplicating local regexes so the detection logic is
    consistent across `doiref.py` and `doiref_nonapa.py`.
    """
    if not s:
        return False
    return bool(prop_start_re.match(s)) or bool(sou_start_re.match(s)) or bool(sfs_start_re.match(s)) or bool(ds_start_re.match(s))


def is_ui_timestamp_line(s: str) -> bool:
    """Return True if a line looks like UI output or a timestamp/footer line.

    Heuristic: presence of a date like YYYY/M/D (year/month/day), a time
    like HH:MM, the word 'page' (case-insensitive), and a '#<number>' token.
    This mirrors the conservative detection used in the pipelines to skip
    UI-generated footer/header lines that sometimes appear in PDF-to-text
    conversions.
    """
    if not s:
        return False
    st = s.strip()
    if not st:
        return False
    try:
        if (
            re.search(r"\d{4}/\d{1,2}/\d{1,2}", st)
            and re.search(r"\b\d{1,2}:\d{2}\b", st)
            and re.search(r"\bpage\b", st, flags=re.I)
            and re.search(r"#\d+", st)
        ):
            return True
    except Exception:
        return False
    return False


def is_cid_marker(s: str) -> bool:
    """Return True when the line is a raw CID marker like '(cid:105)'.

    Matches forms like '(cid:105)' case-insensitively and allows optional
    surrounding whitespace. Kept conservative to avoid false positives.
    """
    if not s:
        return False
    return bool(re.match(r'^\(cid:\s*\d+\)\s*$', s.strip(), flags=re.I))


def is_hyphen_only_line(s: str) -> bool:
    """Return True when a line consists only of hyphen-like characters or whitespace.

    This centralizes the hyphen-only/artifact detection used by both pipelines.
    """
    if not s:
        return False
    return bool(re.match(r'^[\-\u00AD\u2010\u2011\u2012\u2013\u2014\u2015\u2212\s]+$', s))


def is_page_number_line(s: str, min_page: int = 50, max_page: int = 400) -> bool:
    """Return True when a stripped line is a pure integer within the page range.

    Parameters:
        s: the input line (may include whitespace)
        min_page, max_page: inclusive integer bounds for page numbers to skip
    """
    if not s:
        return False
    m = re.match(r'^\s*(\d+)\s*$', s)
    if not m:
        return False
    try:
        num = int(m.group(1))
    except Exception:
        return False
    return (min_page <= num <= max_page)


def starts_with_initials_parenthesized_year(s: str) -> bool:
    """Return True when a line starts with 1-3 initials (with or without period)
    directly followed by a parenthesized year.

    Examples matched (leading whitespace allowed):
      - "A. (2003) ..."
      - "A B (1999) ..."
      - "A.B.(2010) ..."

    The check is conservative: it prefers the cached year-inner pattern when
    available and falls back to a simple four-digit parenthesis matcher on
    error.
    """
    if not s:
        return False
    try:
        inner = _CACHED_YEAR_PATTERNS.get('YEAR_PAREN_INNER') if _CACHED_YEAR_PATTERNS else None
        if inner:
            # Require a blank space after each initial (e.g. 'A ', 'A. '),
            # disallow glued initials like 'AA' or 'A.B.' without spaces.
            pat = re.compile(rf'^\s*(?:[A-Z](?:\.)?\s+){{1,3}}\s*\({inner}\)')
            return bool(pat.match(s))
    except Exception:
        pass
    # conservative fallback: 1-3 uppercase letters optionally followed by a dot,
    # optional spaces, then a simple four-digit year in parentheses
    try:
        return bool(re.match(r'^\s*(?:[A-Z](?:\.)?\s+){1,3}\s*\(\s*(?:18|19|20)\d{2}\s*\)', s))
    except Exception:
        return False


def starts_with_initials_then_parenthesized_year_allowing_authors(s: str) -> bool:
    """Return True when a line starts with 1-3 initials and later contains
    a parenthesized year, allowing intervening author tokens before the year.

    This is a relaxed variant of `starts_with_initials_parenthesized_year` that
    accepts cases where additional author fragments (commas, ampersands,
    surname tokens) appear between the initials at the start of the line and
    the parenthesized year. It is conservative: it requires the line to begin
    with 1-3 uppercase initials (optionally followed by dots/spaces) and to
    contain a parenthesized year token soon after (bounded length).
    """
    if not s:
        return False
    try:
        inner = _CACHED_YEAR_PATTERNS.get('YEAR_PAREN_INNER') if _CACHED_YEAR_PATTERNS else None
        if inner:
            # allow up to 120 characters between the initials and the parenthesized year
            # Require spaces after each initial as above.
            pat = re.compile(rf'^\s*(?:[A-Z](?:\.)?\s+){{1,3}}[\s\S]{{0,120}}\({inner}\)')
            return bool(pat.search(s))
    except Exception:
        pass
    # conservative fallback: basic four-digit parenthesized year within a short window
    try:
        return bool(re.search(r'^\s*(?:[A-Z](?:\.)?\s+){1,3}[\s\S]{0,120}\(\s*(?:18|19|20)\d{{2}}\s*\)', s))
    except Exception:
        return False


def line_ends_with_comma_or_initial(s: str) -> bool:
    """Return True when a (non-empty) line ends with a comma or a single-letter initial.

    Matches trailing comma or a single uppercase letter optionally followed by a
    period (e.g. 'Smith, J.' or 'Smith, J'). Conservative: requires a word
    boundary before the single-letter initial so multi-letter tokens don't match.
    """
    if not s:
        return False
    t = s.rstrip()
    if not t:
        return False
    if t.endswith(','):
        return True
    # single-letter initial at end (optionally with a dot)
    try:
        return bool(re.search(r'\b[A-Z]\.?$', t))
    except Exception:
        return False


def line_ends_with_conjunction(s: str) -> bool:
    """Return True when a line ends with a literal ampersand ('&') indicating
    a continued author list.

    This matcher is deliberately strict: it only returns True when the
    (stripped) line literally ends with '&' (no trailing punctuation or
    closing brackets allowed). This avoids false positives where an
    ampersand-like token is followed by punctuation or bracketed text.
    """
    if not s:
        return False
    t = s.rstrip()
    if not t:
        return False
    try:
        # Match a literal ampersand at the very end of the (stripped) line.
        return bool(re.search(r'&$', t))
    except Exception:
        return False


def normalize_line(s: str) -> str:
    """Normalize invisible unicode and hyphen-like characters in a line.

    This helper centralizes the common normalization used across both
    pipelines (`doiref.py` and `doiref_nonapa.py`). It performs the
    following conservative normalizations:
      - Replace non-breaking spaces and narrow no-break spaces with normal spaces.
      - Remove zero-width spaces/joiners and BOM.
      - Normalize a range of dash/hyphen characters (and soft-hyphen) to ASCII '-'.
      - Collapse repeated whitespace and trim.
    """
    if not s:
        return s
    s = s.replace('\u00A0', ' ').replace('\u202F', ' ').replace('\u2060', ' ').replace('\uFEFF', ' ')
    for z in ('\u200B', '\u200C', '\u200D', '\u200E', '\u200F'):
        s = s.replace(z, '')
    for h in ('\u2010', '\u2011', '\u2012', '\u2013', '\u2014', '\u2015', '\u2212', '\u00AD'):
        s = s.replace(h, '-')
    s = re.sub(r'\s{2,}', ' ', s)
    return s.strip()


def build_author_patterns(fullname_detection: bool = False):
    """Return a dict of compiled author-related regexes and helper strings.

    Keys returned:
      - author_pattern: initials-based compiled regex
      - author_start_like: initials-based looser start matcher
      - author_pattern_active: either fullname-aware or initials pattern depending on flag
      - author_start_like_active: corresponding start-like matcher
      - editor_token_re: compiled regex for editor tokens (ed/eds/red)
      - trailer: string for trailer pattern (useful for additional matching)
      - initial: string pattern for a single initial (useful in f-strings)
    """
    UP = "A-ZÅÄÖÜÉÑÇŞŽŠĐĆČŁÓŚŹŻÁØÍÚÈÓÆØÔ"
    # Enlarged particle list to handle more multi-word surnames. Particles
    # may appear before the first surname or in between surname parts.
    PARTICLES = r'(?:von|van|der|van\s+der|de|di|av|af|de\s+la|del|dos|da|le|la|du|mac|mc|san|st|bin|ibn|d\'|l\')'
    # Build a surname token that allows up to 3 surname parts. Each part may
    # be optionally prefixed by a particle. Between surname parts allow either
    # a hyphen or 1-3 spaces. This permits forms like 'de Rezende Barbosa',
    # 'Smith-Jones', or 'van der Waals' while keeping the overall match
    # conservative (max 3 parts).
    # Allow particles in a case-insensitive way (they may be lowercase or
    # capitalized in real inputs). Wrap the particle alternation with a
    # non-capturing inline case-insensitive group so the rest of the regex
    # retains its original case sensitivity for initials and given names.
    surname_part = rf"(?:(?i:{PARTICLES})\s+)?[{UP}][\w'’\-.]+"
    surname_token = rf"{surname_part}(?: (?: {{1,3}}|-){surname_part}){{0,2}}"
    # Allow comma between surname and initials, or 1-3 spaces (semicolon NOT allowed)
    author_sep = r"(?:,\s{0,3}| {1,3})"
    # When fullname detection is active we prefer an explicit comma between
    # the surname and the given name(s) to avoid false positives like
    # publisher names ('Oxford University Press'). Use this for fullname
    # pattern construction; we'll also provide a comma-less start-like
    # matcher for a hybrid heuristic (see caller-side checks).
    author_sep_comma = r",\s*"
    # single-space (relaxed to 1-3 spaces) used in some fullname matchers
    author_sep_space = r" {1,3}"
    # Single-letter initial: require that the initial is followed by a
    # separator (space, punctuation, hyphen/slash) or end-of-string. This
    # prevents the pattern from matching the first letter of a full given
    # name (e.g. 'John' -> 'J' would no longer match). We keep the
    # optional dot after the initial as many sources use 'J.' forms.
    initial = rf"[{UP}](?:\.)?(?=(?:\s|$|[\.,;:\)\(\-&/]))"
    # Allow initials separated by either a dot/hyphen or up to three spaces.
    # This permits forms like 'D. L. H.' or 'D   L   H' (up to 3 spaces between
    # initials) which occur in some OCR/text extractions.
    initials = rf"{initial}(?:(?: {{1,3}}|[.\-]){initial}){{0,3}}"

    ELLIPSIS = r'(?:\.{3}|\.\s*\.\s*\.)'
    ETAL = r'(?:(?i:et\s+al\.?))'
    # This is a raw regex string; no interpolation is required here so a
    # plain raw string (r"") is sufficient and avoids an f-string with
    # no placeholders which flake8 flags (F541).
    # Allow up to 3 spaces around connectors/comma/and/& tokens
    sep_author_connector = r"(?: {0,3}, {0,3}| {0,3}; {0,3}| {0,3}& {0,3}| {0,3}(?i:and) {0,3}| {0,3}(?i:och) {0,3}| {0,3}, {0,3}& {0,3}| {0,3}, {0,3}(?i:and) {0,3}| {0,3}, {0,3}(?i:och) {0,3})"
    trailer = rf"(?:{sep_author_connector}(?:{ELLIPSIS}|{ETAL}|{surname_token}{author_sep}{initials}))*"

    # Compile initials-based patterns
    author_pattern = re.compile(rf"^{surname_token}{author_sep}{initials}{trailer}\b")
    author_start_like = re.compile(rf"^{surname_token}{author_sep}{initials}\b")
    # Looser multi-surname start-like matcher: allow up to three surname
    # parts (each optionally prefixed by a particle) followed by the comma
    # and initials. This helps detect lines that begin with multiple
    # comma-separated author surnames (e.g. 'de Rezende Barbosa, G. L., ...').
    try:
        author_start_like_multi = re.compile(rf"^{surname_token}{author_sep}{initials}")
    except Exception:
        author_start_like_multi = None

    # Full-firstname (one or more capitalized given name tokens) support
    given_name = r"[A-ZÅÄÖÜÉÑÇŞŽŠĐĆČŁÓŚŹŻÁØÍÚÈÓÆØÔ][a-zåäöüéñçşžšđćčłóśźżáøíúèóæøô]+"
    # Allow hyphen or up to 3 spaces between given-name tokens
    sep_gn = r"(?:-| {1,3})"
    given_name_token = given_name + rf"(?:{sep_gn}{given_name}){{0,3}}"
    # Allow 1-3 spaces before trailing initials when present
    given_name_with_initials = given_name_token + r"(?: {1,3}" + initials + r")?"
    try:
        # Require a comma separator for the strict fullname-aware detection
        # (e.g. 'Smith, John'). Break long regex constructions across
        # concatenated raw strings to satisfy line-length checks while
        # preserving the rf-string interpolation where needed.
        author_pattern_fullname = re.compile(
            rf"^{surname_token}{author_sep_comma}{given_name_with_initials}{trailer}\b"
        )
        author_start_like_fullname = re.compile(
            rf"^{surname_token}{author_sep_comma}" + given_name_token
        )
        # Looser comma-less start-like fullname matcher (captures the first
        # given-name token in group 1). This is used by caller code with
        # additional whitelist/blacklist checks to avoid publisher false
        # positives.
        author_start_like_fullname_space = re.compile(rf"^{surname_token}{author_sep_space}({given_name})")
    except Exception:
        author_pattern_fullname = None
        author_start_like_fullname = None
        author_start_like_fullname_space = None

    author_pattern_active = (
        author_pattern_fullname if (fullname_detection and author_pattern_fullname) else author_pattern
    )
    # Prefer the multi-surname start-like matcher when available so the
    # canonical `author_start_like_active` used throughout the parser
    # recognizes cases like 'de Rezende Barbosa, G. L.' by default. If
    # fullname detection is requested and a fullname start-like pattern is
    # available, keep that behavior; otherwise prefer the multi-surname
    # matcher and fall back to the original start-like pattern.
    author_start_like_active = (
        author_start_like_fullname
        if (fullname_detection and author_start_like_fullname)
        else (author_start_like_multi or author_start_like)
    )

    editor_token_re = re.compile(r'^(?:eds?|red)\.?$', flags=re.I)

    # Publisher blacklist tokens (lowercase matching) used to avoid treating
    # publisher names (e.g. 'University', 'Press') as given names in comma-less mode
    publisher_blacklist = [
        'press',
        'university',
        'publishers',
        'publisher',
        'verlag',
        'förlag',
        'ltd',
        'inc',
        'gmbh',
        'ab',
        'company',
        'co',
        'edition',
        'editions',
        'presses',
        'school',
        'college',
        'institute',
        'centre',
        'center',
        'publications',
        'Sage',
        'Elsevier',
        'Routledge',
        'Springer',
        'Wiley',
        'Cambridge',
        'Oxford',
        'Taylor',
        'Francis',
        'Palgrave',
        'Macmillan',
        'MIT',
        'Harvard',
        'Princeton',
        'Yale',
        'Studentlitteratur',
        'universitet',
        'universitetet',
        'högskola',
        'högskolan',
        'Utbildningsdepartementet',
        'söner',
    ]
    publisher_blacklist_re = re.compile(rf"(?i)^(?:{'|'.join(publisher_blacklist)})$")

    # Small first-name whitelist (lowercase) to help the comma-less heuristic
    # accept lines like 'Smith John' when 'John' is a common given name.
    first_name_whitelist = set([n.lower() for n in (
        'John', 'Jane', 'Mary', 'Michael', 'Anna', 'Lars', 'Karl', 'Maria',
        'Peter', 'Johan', 'Sven', 'Olga', 'Jose', 'Jesper', 'Paul', 'David',
        'Emma', 'Nils', 'Erik'
    )])

    # Regex for a single given-name token (used to validate the captured token)
    given_name_re = re.compile(given_name)

    return {
        'author_pattern': author_pattern,
        'author_start_like': author_start_like,
        'author_pattern_active': author_pattern_active,
        'author_start_like_active': author_start_like_active,
    'author_start_like_multi': author_start_like_multi,
        'author_start_like_fullname_space': author_start_like_fullname_space,
        'editor_token_re': editor_token_re,
        'trailer': trailer,
    # Export the relaxed initials pattern so callers using the 'initial'
    # token get the spacing-relaxed matcher (supports up to 3 initials
    # with up to 3 spaces between them).
    'initial': initials,
        'publisher_blacklist_re': publisher_blacklist_re,
        'first_name_whitelist': first_name_whitelist,
        'given_name_re': given_name_re,
    }


def should_attach_comma_fragment(fragment: str, next_line: str, fullname_detection: bool, initial: str, author_start_like_active) -> bool:
        """Decide whether a fragment that begins with a leading comma should be
        attached to the previous author line.

        Rules (balanced):
            - If `fragment` does not start with a comma after left-stripping, return False.
            - If `next_line` starts with an initial (regex anchored to start using
                the provided `initial` pattern), allow attachment.
            - Else if `fullname_detection` is True and `author_start_like_active`
                (a compiled regex) matches `next_line`, allow attachment.
            - Otherwise, do not attach.

        This helper centralizes the decision so both pipelines can reuse the
        same heuristic and be covered by unit tests.
        """
        if not fragment or not fragment.lstrip().startswith(','):
                return False
        if not next_line:
                return False
        nl = next_line.lstrip()
        try:
            # Require a word-boundary after the optional dot so we only match
            # single-letter initials like 'T.' or 'T' and not full words like
            # 'Journal' which also start with a capital letter.
            if re.match(rf'^{initial}(?:\b)', nl):
                return True
        except re.error:
                # fall back conservatively
                pass
        if fullname_detection and author_start_like_active and author_start_like_active.match(nl):
                return True
        return False


def extract_doi_ids(text: str):
    """Extract validated DOI identifier strings from text.

    Returns a list of DOI ids (without doi.org/ prefix), deduplicated in
    encounter order. This mirrors the conservative extractor previously
    embedded in the pipeline.
    """
    if not text:
        return []
    ref = text
    # Normalize duplicated doi.org prefixes
    ref = re.sub(r'(?i)(https?://(?:dx\.)?doi\.org/)(?:\s*https?://(?:dx\.)?doi\.org/)+', r'\1', ref)

    def _collapse_after_doi_org(m):
        prefix = m.group(1)
        rest = m.group(2)
        toks = re.findall(r"\S+", rest)
        if not toks:
            return prefix + rest
        first = toks[0]
        if not first.endswith(('.', '-', '_')):
            return prefix + rest
        if len(toks) > 1:
            nexttok = toks[1].strip('.,;()[]')
            if re.match(r'^[A-Z][a-z]+,?$', nexttok) or re.match(r'^[A-Z]\.?$', nexttok) or nexttok in ('&', 'and'):
                return prefix + rest
        collapsed = re.sub(r"\s+", "", rest)
        collapsed = collapsed.rstrip('.,;()[]')
        return prefix + collapsed

    ref = re.sub(r'(https?://(?:dx\.)?doi\.org/)((?:\s*\S+){1,12})', _collapse_after_doi_org, ref, flags=re.I)

    ids = []
    # DOI URLs (https://doi.org/... or https://dx.doi.org/...)
    for m in DOI_HTTP_URL_RE.finditer(ref):
        candidate = m.group(1).rstrip('.,;()[]')
        ids.append(candidate)

    # doi: prefixes (handles 'doi:10...' and split tokens 'doi: 10.' 'xxxx')
    for m in DOI_COLON_CAPTURE_RE.finditer(ref):
        part1 = m.group(1)
        part2 = m.group(2)
        if part2:
            # consider broken doi: across two tokens when first ends with split char
            if not part1.endswith(('.', '-', '_')):
                candidate = part1.rstrip('.,;()[]')
            else:
                candidate = (part1 + part2).replace(' ', '').rstrip('.,;()[]')
        else:
            candidate = part1.rstrip('.,;()[]')
        mm = DOI_HTTP_URL_RE.search(candidate)
        if mm:
            ids.append(mm.group(1).rstrip('.,;()[]'))
        else:
            ids.append(candidate)

    # bare doi-like identifiers (10.<prefix>/<suffix>)
    for m in DOI_ID_RE.finditer(ref):
        candidate = m.group(0).rstrip('.,;()[]')
        ids.append(candidate)

    # Also handle a broken two-token bare DOI like '10.1186/s12966- 020-01037-z'
    for m in DOI_BROKEN_TWO_TOKEN_RE.finditer(ref):
        first = m.group(1)
        second = m.group(2)
        if not first.endswith(('.', '-', '_')):
            continue
        cid = (first + second).replace(' ', '').rstrip('.,;()[]')
        ids.append(cid)

    seen = set()
    out = []
    for cid in ids:
        cid = cid.strip()
        if cid.startswith('[') and cid.endswith(']'):
            cid = cid[1:-1].strip()
        if cid and cid not in seen:
            seen.add(cid)
            out.append(cid)

    valid = []
    for cid in out:
        if re.match(r'^10\.\d{2,9}/[^\s\)\]\.,;]+', cid):
            if cid.endswith(('.', '-', '_')):
                continue
            valid.append(cid)

    filtered = []
    for cid in valid:
        if any((other != cid and cid in other) for other in valid):
            continue
        filtered.append(cid)
    return filtered


def move_doi_to_end(ref: str) -> str:
    """Move validated DOI(s) found in ref to canonical https://doi.org/<id>

    The function removes textual occurrences of the DOI (URL form, doi: prefix,
    or bare id) and appends the canonical URL(s) at the end of the reference.
    """
    # First, aggressively remove stray whitespace immediately following a
    # literal 'doi:' prefix (e.g. 'doi: 10.123/abc' -> 'doi:10.123/abc').
    # Doing this early helps the subsequent normalizer and extractor treat
    # doi: forms as contiguous tokens.
    try:
        # Collapse repeated 'doi:' tokens (e.g. 'doi: doi: 10...') to a single
        # 'doi:' so later normalization doesn't produce duplicate prefixes.
        ref = re.sub(r'(?i)(?:doi:\s*){2,}', 'doi:', ref)
        # case-insensitive; replace one-or-more whitespace characters after doi:
        ref = re.sub(r'(?i)\bdoi:\s+', 'doi:', ref)
    except Exception:
        # non-fatal: continue with original ref on error
        pass

    # Conservatively normalize DOI-like substrings in-place so that broken
    # tokens like '1 0.' or 'doi: 1 0.1186/...' collapse to a single
    # continuous DOI token. This makes the subsequent span-detection and
    # removal reliable.
    try:
        text = normalize_doi_in_fragment(ref)
    except Exception:
        text = ref

    # Apply a light repair pass to fix common broken DOI tokens (e.g.
    # 'https://doi. org' or misplaced '10.' fragments).
    try:
        text = fix_broken_doi_tokens(text)
    except Exception:
        # non-fatal; continue with the best-effort text
        pass

    # Split into fragments at URL/DOI boundaries and attempt conservative
    # then aggressive reattach passes so that split DOI tokens spanning
    # fragments are rejoined before extraction/removal. This mirrors the
    # workflow used in `doiref_nonapa.py` and allows callers to simply call
    # `move_doi_to_end` and get consistent behaviour.
    try:
        frags = split_urls_and_dois(text)
        frags = conservative_doi_reattach(frags)
        frags = conservative_doi_reattach_aggressive(frags)
        # Reconstruct the text from fragments using a single space separator
        # (the splitting preserved URL tokens close to their surrounding text
        # where helpful). Use the reconstructed text for subsequent DOI
        # extraction/removal.
        text = ' '.join(frag.strip() for frag in frags if frag is not None)
    except Exception:
        # on any error, fall back to the already-normalized text
        pass

    doi_ids = extract_doi_ids(text)
    if not doi_ids:
        return ref

    spans = []

    for m in DOI_HTTP_URL_RE.finditer(text):
        cid = m.group(1).rstrip('.,;()[]')
        if cid in doi_ids:
            spans.append((m.start(), m.end()))

    # Also accept bare 'doi.org/' or 'dx.doi.org/' without protocol and
    # treat them equivalently so they are removed and later replaced by the
    # canonical 'https://doi.org/<id>' URL appended at the end.
    for m in DOI_BARE_URL_RE.finditer(text):
        cid = m.group(1).rstrip('.,;()[]')
        if cid in doi_ids:
            spans.append((m.start(), m.end()))

    for m in DOI_HTTP_URL_WITH_TAIL_RE.finditer(text):
        first = m.group(1)
        second = m.group(2)
        if not first.endswith(('.', '-', '_')):
            continue
        cid = (first + second).replace(' ', '').rstrip('.,;()[]')
        if cid in doi_ids:
            spans.append((m.start(), m.end()))

    # same for bare 'doi.org/' followed by a split token (e.g. 'doi.org/ 10.123')
    for m in DOI_BARE_URL_WITH_TAIL_RE.finditer(text):
        first = m.group(1)
        second = m.group(2)
        if not first.endswith(('.', '-', '_')):
            continue
        cid = (first + second).replace(' ', '').rstrip('.,;()[]')
        if cid in doi_ids:
            spans.append((m.start(), m.end()))

    for m in DOI_COLON_CAPTURE_RE.finditer(text):
        part1 = m.group(1)
        part2 = m.group(2)
        if part2:
            if not part1.endswith(('.', '-', '_')):
                continue
            cid = (part1 + part2).replace(' ', '').rstrip('.,;()[]')
        else:
            cid = part1.rstrip('.,;()[]')
        if cid in doi_ids:
            spans.append((m.start(), m.end()))

    for m in DOI_ID_RE.finditer(text):
        cid = m.group(0).rstrip('.,;()[]')
        if cid in doi_ids:
            spans.append((m.start(), m.end()))

    for m in DOI_BROKEN_TWO_TOKEN_RE.finditer(text):
        first = m.group(1)
        second = m.group(2)
        if not first.endswith(('.', '-', '_')):
            continue
        cid = (first + second).replace(' ', '').rstrip('.,;()[]')
        if cid in doi_ids:
            spans.append((m.start(), m.end()))

    # Normalize and merge overlapping spans so we only remove each region once.
    spans = sorted(set(spans), key=lambda s: s[0])
    merged = []
    for start, end in spans:
        if not merged:
            merged.append([start, end])
            continue
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            # overlap or contiguous: extend the previous span
            merged[-1][1] = max(prev_end, end)
        else:
            merged.append([start, end])

    new_text = text
    # remove merged spans from the end to avoid shifting earlier indices
    for start, end in reversed(merged):
        new_text = new_text[:start] + ' ' + new_text[end:]

    new_text = re.sub(r'https?://(?:dx\.)?doi\.org/https?://', 'https://', new_text, flags=re.I)
    new_text = new_text.strip()
    new_text = re.sub(r'\s+', ' ', new_text)
    new_text = new_text.rstrip('.')

    # Remove any stray 'doi:' or 'doi.org/' prefixes that remain without a
    # valid DOI id following them. This cleans artifacts left after span
    # removals (e.g., a leftover 'doi:' with no id).
    try:
        new_text = _remove_stray_doi_prefixes(new_text)
    except Exception:
        pass

    # Conservative tidy-up to remove small dangling connectors left by
    # span removals (e.g. 'with and'). Keep this separate and conservative
    # to avoid altering legitimate text.
    try:
        new_text = _cleanup_dangling_after_removal(new_text)
    except Exception:
        pass

    doi_urls = [f'https://doi.org/{cid}' for cid in doi_ids]
    out = new_text
    if out:
        out = out + '. ' + ' '.join(doi_urls)
    else:
        out = ' '.join(doi_urls)
    return out.strip()


def attach_non_year_lines(refs, year_re):
    """Attach fragments that do not contain a year to the previous fragment.

    This mirrors the conservative behavior used in `doiref_nonapa.py`.
    The caller should pass a compiled `year_re` (regex) used to detect
    whether a fragment contains a year. Returns a new list.
    """
    result = []
    for ref in refs:
        if not year_re.search(ref):
            if result:
                result[-1] = result[-1].rstrip() + " " + ref.lstrip()
            else:
                result.append(ref)
        else:
            result.append(ref)
    return result


def merge_short_fragments(refs, max_spaces=2):
    """Merge fragments that are short (few spaces) into the previous fragment.

    `max_spaces` is the maximum number of space characters that a fragment
    may contain to be considered "short" and attached to the previous
    fragment. This function avoids merging fragments that start with a
    Prop./SOU marker by consulting `starts_with_prop_or_sou`.
    """
    if not refs:
        return refs
    merged = [refs[0]]
    for frag in refs[1:]:
        space_count = frag.count(' ') + frag.count('\u00A0')
        if starts_with_prop_or_sou(frag.lstrip()):
            merged.append(frag)
            continue
        if space_count <= max_spaces:
            prev = merged[-1]
            new_prev = prev.rstrip() + ' ' + frag.lstrip()
            merged[-1] = new_prev
        else:
            merged.append(frag)
    return merged


def hyphen_join_fixed_point(input_lines, audit_fp=None, max_iter_env='DOIREF_HYPHEN_MAX_ITER'):
    """Iteratively join lines ending with a hyphen-like character to the next
    non-blank line until no changes occur or a maximum iteration cap is
    reached. Returns the joined lines.

    This is a shared implementation extracted from the pipelines so both
    `doiref.py` and `doiref_nonapa.py` can reuse the same behaviour and
    diagnostics.
    """
    if not input_lines:
        return []
    # Continuation characters at end-of-line: hyphen-like and also sunderscore
    hyphen_chars = "-\u00AD\u2010\u2011\u2012\u2013\u2014\u2015\u2212_"

    def is_blank(t):
        return bool(re.match(r'^[\s\u00A0]*$', t))

    try:
        max_iter = int(os.environ.get(max_iter_env, '8'))
    except Exception:
        max_iter = 8

    prev = [ln for ln in input_lines if ln.strip()]
    # Prepare an author-start-like matcher to avoid joining when the next
    # non-blank line appears to begin an author entry. Use the canonical
    # builder to obtain a conservative author_start_like regex; fall back
    # to None if construction fails so we preserve previous behaviour.
    try:
        _ap_tmp = build_author_patterns()
        author_start_like_re = _ap_tmp.get('author_start_like')
    except Exception:
        author_start_like_re = None
    iter_n = 0
    while True:
        iter_n += 1
        out = []
        i = 0
        while i < len(prev):
            curr = prev[i]
            s = curr.rstrip()
            if s and s[-1] in hyphen_chars:
                lookahead = i + 1
                while lookahead < len(prev) and is_blank(prev[lookahead]):
                    lookahead += 1
                if lookahead < len(prev):
                    next_line = prev[lookahead]
                    # Only consult the author-start predicate when the
                    # continuation character is a slash ('/'). For other
                    # hyphen-like characters (hyphen, underscore, soft-hyphen,
                    # etc.) we don't perform the author-start guard so that
                    # legitimate word-splits are still joined.
                    last_char = s[-1]
                    try:
                        if last_char == '/' and author_start_like_re and author_start_like_re.match(next_line.lstrip()):
                            out.append(curr)
                            i = i + 1
                            continue
                    except Exception:
                        # on any error, fall back to previous behavior
                        pass
                    merged = curr.rstrip() + next_line.lstrip()
                    out.append(merged)
                    if audit_fp:
                        try:
                            msg = (
                                f"HYPHEN_JOIN iter{iter_n}: '{curr}' + '{next_line[:80]}'"
                                f" -> '{merged[:200]}'\n"
                            )
                            audit_fp.write(msg)
                            audit_fp.flush()
                        except Exception:
                            pass
                    i = lookahead + 1
                    continue
                else:
                    out.append(curr)
                    i += 1
            else:
                out.append(curr)
                i += 1
        # write debug snapshot for this iteration (only when debugging enabled)
        try:
            write_debug(f'debug_hyphen_iter{iter_n}.txt', [f'ITERATION: {iter_n}'] + out)
        except Exception:
            if is_debug_enabled():
                try:
                    with open(f'debug_hyphen_iter{iter_n}.txt', 'w', encoding='utf-8') as df:
                        df.write(f'ITERATION: {iter_n}\n')
                        for r in out:
                            df.write(r + '\n')
                except Exception:
                    pass

        if out == prev or iter_n >= max_iter:
            return out
        prev = out


def build_parenthesized_year_patterns():
    """Construct and return a dict of compiled regexes for parenthesized years.

    The returned dict contains the same keys historically used in
    `doiref.py`: YEAR_SINGLE, YEAR_PAREN_INNER, YEAR_PAREN, YEAR_PAREN_END,
    YEAR_PAREN_START, YEAR_OPTIONAL_PAREN, YEAR_BOUNDED_PRE. The patterns
    validate bounded years in the approximate range 1750--2030 and accept
    optional single-letter qualifiers and optional date parts (month+day).
    """
    # Numeric year range (1750-2030)
    YEAR_NUM = r'(?:17[5-9]\d|18\d{2}|19\d{2}|20(?:0\d|1\d|2\d|30))'
    # Single bounded year with optional single-letter suffix limited to a-p
    # (e.g. '1970a' is recognized, '1970s' is not)
    YEAR_SINGLE = YEAR_NUM + r'[A-Pa-p]?'
    YEAR_SINGLE = YEAR_NUM + r'[A-Za-z]?'

    # Month names (English full/abbr and Swedish full/abbr). Use an inline
    # case-insensitive group when inserting into larger patterns.
    MONTHS = (
        r'(?:(?i:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
        r'Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)|Oct(?:ober)?|Nov(?:ember)?|'
        r'Dec(?:ember)?|januari|februari|mars|april|maj|juni|juli|augusti|september|'
        r'oktober|november|december))'
    )

    # Optional date part: optional comma, month name and day (accept ordinal suffixes)
    # Also accept full date format like "13 July 2019"
    YEAR_DATE_PART = rf'(?:\s*,?\s*{MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?)?'
    FULL_DATE_FORMAT = rf'\d{{1,2}}\s+{MONTHS}\s+{YEAR_NUM}'

    # Recognize status tokens like (forthcoming), (in press), etc.
    STATUS_TOKENS = r'(?:(?i:forthcoming|in\s+press|submitted|unpublished|n\.?d\.?|no date|u\.?å\.?)(?:\s*(?:-\s*)?[A-Za-z])?)'

    # ISO-like numeric date (allow YYYY-MM or YYYY-MM-DD). Use strict month/day ranges.
    ISO_DATE = rf'{YEAR_NUM}-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?'

    # Double year patterns: (YYYY [YYYY]) or (YYYY/YYYY)
    DOUBLE_YEAR_BRACKETED = rf'{YEAR_SINGLE}\s*\[{YEAR_SINGLE}\]'
    DOUBLE_YEAR_SLASH = rf'{YEAR_SINGLE}/{YEAR_SINGLE}'

    # Accept either the traditional YEAR_SINGLE plus optional textual date part
    # (e.g. '1998 Jan 2') or a full date format (e.g. '13 July 2019') or an ISO-like 
    # date 'YYYY-MM-DD'. Keep the optional bracketed secondary year when present for 
    # the textual form. Also accept double year patterns: (YYYY [YYYY]) or (YYYY/YYYY)
    YEAR_PAREN_INNER = rf'(?:{DOUBLE_YEAR_BRACKETED}|{DOUBLE_YEAR_SLASH}|{FULL_DATE_FORMAT}|{YEAR_SINGLE}{YEAR_DATE_PART}(?:\s*\[{YEAR_SINGLE}\])?|{ISO_DATE})'
    YEAR_PAREN = re.compile(rf'\((?:{YEAR_PAREN_INNER}|{STATUS_TOKENS})\)')
    YEAR_PAREN_END = re.compile(rf'\((?:{YEAR_PAREN_INNER}|{STATUS_TOKENS})\)\s*$')
    YEAR_PAREN_START = re.compile(rf'^\((?:{YEAR_PAREN_INNER}|{STATUS_TOKENS})\)')
    # Build a bounded-year pre-match: initial (single capital letter with optional
    # dot and optional whitespace) followed by either a parenthesized year or a
    # comma-separated remainder. Split into prefix/suffix to avoid an overly
    # long single-line regex literal.
    _ybp_prefix = r'^[A-ZÅÄÖÜÉÑÇŞŽŠĐĆČŁÓŚŹŻÁØÍÚÈÓÆØÔ]\.?' + r'\s*'
    _ybp_suffix = rf'(?:\({YEAR_PAREN_INNER}\)(?:\s+.*)?|,\s*.*)'
    YEAR_BOUNDED_PRE = re.compile(_ybp_prefix + _ybp_suffix, re.UNICODE)
    YEAR_OPTIONAL_PAREN = re.compile(rf'\({YEAR_PAREN_INNER}\)|\({STATUS_TOKENS}\)')

    return {
        'YEAR_SINGLE': YEAR_SINGLE,
        'YEAR_PAREN_INNER': YEAR_PAREN_INNER,
        'YEAR_PAREN': YEAR_PAREN,
        'YEAR_PAREN_END': YEAR_PAREN_END,
        'YEAR_PAREN_START': YEAR_PAREN_START,
        'YEAR_OPTIONAL_PAREN': YEAR_OPTIONAL_PAREN,
        'YEAR_BOUNDED_PRE': YEAR_BOUNDED_PRE,
    }


# Cache parenthesized-year patterns to avoid repeated construction.
# Call the factory once at module load and expose a cached YEAR_PAREN
# regex for helpers that need it. If the factory fails for any reason
# keep the cache as None to preserve conservative behavior.
try:
    _CACHED_YEAR_PATTERNS = build_parenthesized_year_patterns()
    YEAR_PAREN_CACHED = _CACHED_YEAR_PATTERNS.get('YEAR_PAREN')
except Exception:
    YEAR_PAREN_CACHED = None


def build_nonparenthesized_year_pattern():
    """Return a compiled regex that conservatively matches non-parenthesized years.

    This is used by the non-APA pipeline to accept standalone-ish years like
    '2019' or '2019.' but avoid matching years embedded in longer digit
    sequences (e.g. '2019123'). The accepted range is approximately 1750--2030.
    """
    # Use the same numeric year range as the parenthesized patterns (1750-2030)
    YEAR_NUM = r'(?:17[5-9]\d|18\d{2}|19\d{2}|20(?:0\d|1\d|2\d|30))'

    # Accept ISO-like dates (YYYY-MM or YYYY-MM-DD) or just the numeric year.
    ISO_DATE = rf'{YEAR_NUM}-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?'

    # Optional single-letter suffix (e.g. '2005a')
    SUFFIX = r'(?:[A-Pa-p])?'

    # Optional punctuation: a period only when followed by a space, or comma/semicolon/colon
    PUNCT = r'(?:\.(?=\s)|[,:;])?'

    # Allow optional surrounding brackets/parentheses. Use lookarounds to avoid
    # matching years embedded in longer digit sequences.
    pattern = rf'(?<!\d)[\(\[]?(?:{ISO_DATE}|{YEAR_NUM}){SUFFIX}{PUNCT}[\)\]]?(?!\d)'
    return re.compile(pattern)


# DOI / URL canonicalization helpers shared across pipelines
# Centralized DOI/token regexes used throughout this module. Define once
# and reuse to avoid subtle divergences in DOI detection logic.
# DOI identifier: '10.' + 4-9 digits + '/' + suffix (suffix stops at common
# closing punctuation or whitespace for conservative matching).
DOI_ID_RE = re.compile(r'\b10\.\d{4,9}/[^\s\)\]\,;]+')
# HTTP DOI URL form capturing the identifier in group 1
DOI_HTTP_URL_RE = re.compile(r'https?://(?:dx\.)?doi\.org/([^\s\)\]\,;]+)', re.I)
# Bare doi.org or dx.doi.org without protocol
DOI_BARE_URL_RE = re.compile(r'\b(?:doi\.org/|dx\.doi\.org/)([^\s\)\]\,;]+)', re.I)
# doi: prefix capturing up to two tokens (the second handles split tokens)
DOI_COLON_CAPTURE_RE = re.compile(r'(?i)\bdoi:\s*\[?\s*([^\s\)\]\,;]+)(?:\s+([^\s\)\]\,;]+))?\s*\]?')
# Broken two-token bare DOI (first token ends with split char)
DOI_BROKEN_TWO_TOKEN_RE = re.compile(r'\b(10\.\d{4,9}/[^\s\)\]\,;]+)\s+([^\s\)\]\,;]+)')
# Split/search pattern used by split_urls_and_dois (covers common DOI forms)
DOI_URL_SPLIT_RE = re.compile(r'(https?://(?:dx\.)?doi\.org/\S+|dx\.doi\.org/\S+|doi\.org/\S+|doi:\S+)', re.I)
DOI_HTTP_URL_WITH_TAIL_RE = re.compile(r'https?://(?:dx\.)?doi\.org/([^\s\)\]\,;]+)\s+([^\s\)\]\,;]+)', re.I)
DOI_BARE_URL_WITH_TAIL_RE = re.compile(r'\b(?:doi\.org/|dx\.doi\.org/)([^\s\)\]\,;]+)\s+([^\s\)\]\,;]+)', re.I)
DOI_HTTP_URL_FULL_RE = re.compile(r'https?://(?:dx\.)?doi\.org/[^\s\)\]\,;:]+', re.I)


def normalize_doi_in_fragment(ref: str) -> str:
    """Conservatively normalize DOI-like substrings inside a fragment.

    This mirrors the logic previously embedded in `doiref_nonapa.py` and is
    intended to be reused by multiple pipelines to collapse common broken
    token patterns (e.g., '1 0.' -> '10.' after doi.org/, broken spacing
    between 'doi.' and 'org', or broken 'https://doi.org/1 0.1186...').
    """
    s = ref
    if re.search(r'doi', s, flags=re.I):
        # Use callable replacements to avoid backreference+digit ambiguity
        # (e.g. '\\110' being read as group 110). Lambdas safely concatenate
        # the captured prefix with the corrected '10.' token.
        s = re.sub(r'(https?://(?:dx\.)?doi\.org/)\s*1\s+0\.',
                   lambda m: m.group(1) + '10.', s, flags=re.I)
        s = re.sub(r'(?i)(doi:\s*)1\s+0\.',
                   lambda m: m.group(1) + '10.', s)
        s = re.sub(r'\b1\s+0\.(?=\d)', '10.', s)

    def _c1(m):
        pref = m.group(1)
        body = m.group(2)
        return pref + re.sub(r'\s+', '', body)

    s = re.sub(
        r'(https?://(?:dx\.)?doi\.org/)\s*(10\.[0-9]{2,9}[^\s\)\]\\,;]{0,200})',
        _c1,
        s,
        flags=re.I,
    )

    def _c2(m):
        pref = m.group(1)
        body = m.group(2)
        return pref + re.sub(r'\s+', '', body)

    s = re.sub(r'(?i)(doi:\s*)(10\.[0-9]{2,9}[^\s\)\]\\,;]{0,200})', _c2, s)

    def _c3(m):
        return re.sub(r'\s+', '', m.group(0))

    s = re.sub(r'\b10\.[0-9]{2,9}[^\s\)\]\\,;]{0,200}', _c3, s)

    # Prefix bare DOI tokens with 'doi.org/' (no 'https://' prefix) when they
    # are not already part of a URL or a 'doi:'/'doi.org' prefix. Use a small
    # look-back window to detect nearby URL/doi markers conservatively.
    def _add_doi_org_prefix(m):
        doi_token = m.group(0)
        start = m.start()
        # examine a small context before the match to avoid false positives
        pre = s[max(0, start - 30):start].lower()
        # if already part of an explicit doi/url, leave unchanged
        if any(x in pre for x in ('doi.org', 'dx.doi.org', 'doi:', 'http://', 'https://')):
            return doi_token
        # otherwise prefix with doi.org/
        return 'doi.org/' + doi_token.lstrip()

    try:
        s = re.sub(r'\b10\.[0-9]{2,9}[^\s\)\]\\,;]{0,200}', _add_doi_org_prefix, s)
        # Replace common brace-escaped underscore sequences like '{_}' or '{\\_}'
        # and similar forms used in some exports. Convert them to a plain
        # underscore so the DOI token becomes continuous.
        s = re.sub(r'\{\s*\\?_+\s*\}', '_', s)
        # Collapse stray spaces inside DOI-like sequences that may remain
        # after tokenization. For any occurrence of a DOI id/prefix followed
        # by a short (<=200) run of non-punctuation chars that may contain
        # spaces, strip the internal whitespace so the DOI becomes contiguous.
        # Collapse the common case where a DOI slash is followed by a
        # whitespace-separated token (e.g. '10.1111/ 2041-210X.13436').
        # Only collapse the immediate whitespace after the slash when the
        # following token looks like a DOI fragment (digits, letters and
        # punctuation commonly seen in DOI suffixes).
        s = re.sub(
            r'(10\.[0-9]{2,9}/)\s+([A-Za-z0-9\-\._/{}]+)',
            lambda m: m.group(1) + re.sub(r'\s+', '', m.group(2)),
            s,
        )
    except Exception:
        # If anything goes wrong, fall back to the already-normalized string.
        pass
    return s


def _remove_stray_doi_prefixes(s: str) -> str:
    """Remove leftover 'doi:' or 'doi.org/' tokens that are not followed by a valid DOI id.

    Conservative: only remove or collapse prefixes when they are not immediately
    followed by a DOI identifier. This avoids stripping legitimate DOI URLs.
    """
    if not s:
        return s

    # Fix occurrences like 'doi.org/ 10.123...' -> '10.123...' by collapsing
    # whitespace after the prefix when the following token is a DOI id.
    s = re.sub(r'(?i)\b(doi\.org/|dx\.doi\.org/)\s*(10\.[0-9]{4,9}/)', r'\2', s)

    # Remove bare prefixes 'doi.org/' or 'dx.doi.org/' when they are NOT
    # immediately followed by a DOI id (e.g. '10.'). This avoids stripping
    # valid 'doi.org/10...' forms but removes stray prefixes left behind.
    s = re.sub(r'(?i)\b(?:doi\.org/|dx\.doi\.org/)(?!\s*10\.)\s*', '', s)

    # For 'doi:' remove the prefix when it's not followed by a DOI id; if
    # followed by a DOI id collapse whitespace so the id is contiguous.
    def _doi_colon_fix(m):
        following = m.group(1) or ''
        if re.match(r'\s*(?:https?://)?(?:doi\.org/)?10\.', following, flags=re.I):
            return re.sub(r'\s+', '', following)
        return following

    s = re.sub(r'(?i)\bdoi:\s*([^\s\)\]\,;]+)?', _doi_colon_fix, s)

    # Cleanup repeated whitespace and stray punctuation left after removals
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\s+([\.,;:])', r'\1', s)
    return s


def _cleanup_dangling_after_removal(s: str) -> str:
    """Conservative cleanup after DOI span removal.

    Remove small leftover connector artifacts that commonly remain when a
    DOI span is removed from the middle of a sentence. Examples handled
    (conservative):
        - "with and" -> "with"
        - "for and"  -> "for"
        - stray duplicated punctuation/whitespace around removals

    This function is intentionally conservative to avoid changing valid
    prose. It only removes an explicit small connector token when it
    directly follows a short preposition commonly used to connect a DOI
    clause.
    """
    if not s:
        return s

    # Remove constructs like 'with and ' -> 'with ' and similar
    s = re.sub(r'(?i)\b(with|for|in|via)\s*(?:,?\s*)?(?:and|&)\s+', r'\1 ', s)

    # If removal left isolated 'and' bounded by short punctuation, drop it
    s = re.sub(r'\s+\band\b\s+(?=[\.,;:])', ' ', s)

    # Collapse repeated whitespace and fix spacing before punctuation
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\s+([\.,;:])', r'\1', s)
    return s


def split_urls_and_dois(ref: str):
    """Split a reference into pieces where URLs/DOIs occur.

    Returns a list of fragments; similar to the original local helper but
    centralized so both pipelines share the same splitting behaviour.
    """
    match = DOI_URL_SPLIT_RE.search(ref)
    if not match:
        return [ref]
    start = match.start()
    end = match.end()
    before = ref[:start].strip()
    url = ref[start:end].strip()
    after = ref[end:].strip()
    result = []
    if before:
        result.append(f"{before} {url}".strip())
    else:
        result.append(url)
    if after:
        result.extend(split_urls_and_dois(after))
    return result


def join_on_suffix_prefixes(frags, author_predicate=None, audit_fp=None):
    """Join fragments where the current fragment ends with a URL/DOI-like
    suffix and the next fragment begins with the remainder of the URL/DOI.

    This is a shared implementation extracted from `doiref_nonapa.py` so both
    pipelines can reuse the same behaviour. It conservatively avoids joining
    when the following fragment looks like an author line or begins with
    a bracket/parenthesis.

    Parameters:
        frags: list of fragment strings
        audit_fp: optional file-like object for audit logging (may be None)
    """
    if not frags:
        return frags
    out = []
    i = 0
    n = len(frags)
    # tokens to check (lowercase)
    suffixes = ('https://', 'doi.org/', 'doi.org', 'doi.', 'www.', 'doi:', 'https://www.')
    while i < n:
        curr = frags[i]
        if i + 1 < n:
            nextf = frags[i + 1]
            curr_r = curr.rstrip()
            curr_lower = curr_r.lower()
            matched = False
            for suf in suffixes:
                if curr_lower.endswith(suf):
                    # Do not join if the next fragment looks like an author line
                    # (caller can supply an author-aware predicate) or begins
                    # with '(' or '[' which likely indicates a parenthetical.
                    # If caller provided an author_predicate, consult it to
                    # avoid joining when the next fragment looks like an
                    # author start. The predicate should accept (line, next)
                    # and return True if it's an author line.
                    try:
                        if callable(author_predicate):
                            next_next = frags[i + 2] if (i + 2) < n else ''
                            if author_predicate(nextf, next_next):
                                break
                    except Exception:
                        pass
                    if nextf.lstrip().startswith(('(', '[')):
                        break

                    # Attach only the first whitespace-separated token of nextf
                    toks = nextf.lstrip().split(None, 1)
                    first = toks[0] if toks else ''
                    rest = toks[1] if len(toks) > 1 else ''

                    # join without inserting space to keep DOI/URL tokens contiguous
                    joined = curr_r + first
                    if audit_fp:
                        try:
                            msg = (
                                f"JOIN_ON_SUFFIX_FIRSTTOKEN: '{curr_r[:120]}' + '{first[:120]}'"
                                f" -> '{joined[:240]}'\n"
                            )
                            audit_fp.write(msg)
                            audit_fp.flush()
                        except Exception:
                            pass

                    out.append(joined)
                    if rest:
                        frags[i + 1] = rest.lstrip()
                        i += 1
                    else:
                        i += 2
                    matched = True
                    break
            if matched:
                continue
        out.append(curr)
        i += 1
    return out


def conservative_doi_reattach(frags):
    """Rejoin neighboring fragments when a DOI/URL appears split across boundary.

    Conservative: only rejoins when previous fragment ends like a DOI prefix
    and the next fragment begins like a DOI identifier.
    """
    trace = []
    if not frags:
        try:
            write_debug('conservative_reattach_trace.txt', ['NO FRAGMENTS'])
        except Exception:
            pass
        return frags
    out = [frags[0]]
    doi_prefix_re = re.compile(r'(?:doi\.org(?:/)?|dx\.doi\.org(?:/)?|doi:|https?://)$', flags=re.I)
    for frag in frags[1:]:
        prev = out[-1]
        curr = frag
        curr_starts_doi = bool(re.search(r'^[\s\W]*(?:10\.[0-9]+|doi\.org|dx\.doi\.org)', curr, flags=re.I))
        _prev_stripped = prev.strip()
        _prev_lower = _prev_stripped.lower()
        prev_looks_like_doi_prefix = (
            bool(doi_prefix_re.search(_prev_stripped))
            or _prev_lower.endswith(('https://', 'http://'))
            or _prev_stripped.endswith('/')
        )
        if prev_looks_like_doi_prefix and curr_starts_doi:
            curr_clean = re.sub(r'^[\s\.:;,\-\(\[\)\]]+', '', curr)
            # Preserve the conservative behavior: join using a space except when
            # the previous fragment already ends with a slash-like connector.
            # Always join DOI fragments without inserting an extra space.
            # This makes reconstructed DOI tokens contiguous (e.g. 'doi.org/' +
            # '10.1234/abcd' -> 'doi.org/10.1234/abcd') which improves later
            # extraction and canonicalization. Preserve existing trimming.
            joined = prev.rstrip() + curr_clean.lstrip()
            trace.append(f"JOINED_CONSERVATIVE: prev='{prev[:120]}' curr='{curr[:120]}' -> '{joined[:240]}'")
            out[-1] = joined
        else:
            trace.append(f"SKIPPED_CONSERVATIVE: prev='{prev[:120]}' curr='{curr[:120]}' reason='no-match')")
            out.append(frag)
    # write trace
    try:
        write_debug('conservative_reattach_trace.txt', trace)
    except Exception:
        try:
            if is_debug_enabled():
                with open('debug_conservative_reattach_trace.txt', 'w', encoding='utf-8') as df:
                    for t in trace:
                        df.write(t + '\n')
        except Exception:
            pass
    return out


def conservative_doi_reattach_aggressive(frags):
    """More aggressive reattach (kept as a separate helper).

    This implements the user's requested aggressive rules: joins when the
    FIRST fragment STARTS with a DOI-like prefix, allows '/' inside tokens,
    and accepts a token that is exactly '/'. Kept separate so callers can
    choose conservative or aggressive behavior.
    """
    trace = []
    if not frags:
        try:
            write_debug('conservative_reattach_aggressive_trace.txt', ['NO FRAGMENTS'])
        except Exception:
            pass
        return frags
    out = [frags[0]]

    # DOI-like start: use same logic as normalization for prefixes
    doi_start_re = re.compile(r'^[\s\[]*(?:https?://(?:dx\.)?doi\.org/|doi:|10\.)', flags=re.I)

    for frag in frags[1:]:
        prev = out[-1]
        prevs = prev.strip()

        # Do not join if prev ends with sentence-like separators
        if prevs.endswith((',', ';', ':')):
            trace.append(f"SKIPPED_AGGRESSIVE: prev='{prevs[:120]}' curr='{frag[:120]}' reason='prev-endswith-punct'")
            out.append(frag)
            continue

        # Require that the FIRST fragment starts like a DOI (prefix at the start)
        if not doi_start_re.search(prevs):
            trace.append(f"SKIPPED_AGGRESSIVE: prev='{prevs[:90]}' curr='{frag[:90]}' reason='prev-not-start-doi'")
            out.append(frag)
            continue

        # Clean leading punctuation/whitespace from candidate fragment
        curr_clean = re.sub(r'^[\s\.:;,\-\(\[\)\]]+', '', frag)
        if not curr_clean:
            trace.append(f"SKIPPED_AGGRESSIVE: prev='{prevs[:90]}' curr='{frag[:90]}' reason='curr-empty-after-clean'")
            out.append(frag)
            continue

        # Take the first whitespace-separated token
        token = curr_clean.split()[0].strip()

        # Allowed characters: letters, digits, '-', '.' , '_' and '/'
        if not re.match(r'^[A-Za-z0-9\-\._/]+$', token):
            trace.append(f"SKIPPED_AGGRESSIVE: token='{token}' not-allowed-chars")
            out.append(frag)
            continue

        # Special-case: token is exactly '/' -> allow join
        if token == '/':
            join_ok = True
        else:
            # Otherwise, require either at least one digit, or '_' anywhere,
            # or a '.' that is not the final character.
            has_digit = bool(re.search(r'\d', token))
            has_underscore = '_' in token
            has_internal_dot = bool(re.search(r'\.[A-Za-z0-9]', token))
            join_ok = (has_digit or has_underscore or has_internal_dot)

        # Don't join if token ends with a period (final position), UNLESS
        # the token contains an underscore, a slash, or contains another
        # period earlier in the token (e.g. '10.1000.' where an internal
        # '.' is present). In those cases joining is helpful to reconstruct
        # split DOI-like tokens.
        if token.endswith('.'):
            if '_' in token or '/' in token or token.count('.') > 1:
                # allow join despite trailing period because token contains
                # an internal sign that suggests it's part of a DOI fragment
                pass
            else:
                join_ok = False

        if not join_ok:
            trace.append(f"SKIPPED_AGGRESSIVE: token='{token}' join_ok=False")
            out.append(frag)
            continue

        # Perform the join: always concatenate without inserting an extra
        # separating space as requested by user for the aggressive case.
        joined = prev.rstrip() + curr_clean.lstrip()
        trace.append(f"JOINED_AGGRESSIVE: prev='{prevs[:120]}' curr='{curr_clean[:120]}' -> '{joined[:240]}'")
        out[-1] = joined

    # write trace
    try:
        write_debug('conservative_reattach_aggressive_trace.txt', trace)
    except Exception:
        try:
            if is_debug_enabled():
                with open('debug_conservative_reattach_aggressive_trace.txt', 'w', encoding='utf-8') as df:
                    for t in trace:
                        df.write(t + '\n')
        except Exception:
            pass
    return out


def fix_broken_doi_tokens(ref: str) -> str:
    s = ref
    s = re.sub(r'(https?://doi\.org)10\.', r"\1/10.", s, flags=re.I)
    s = re.sub(r'(https?://doi\.org)\s+10\.', r"\1/10.", s, flags=re.I)
    s = re.sub(r'https?://doi\.\s*org', 'https://doi.org', s, flags=re.I)
    s = re.sub(r'(https?://doi\.org)10(?![\d/\.])', r"\1/10", s, flags=re.I)
    return s


def ensure_space_after_canonical_doi(ref: str) -> str:
    # Match a DOI token conservatively: stop at whitespace or common closing
    # punctuation so we don't accidentally consume the following sentence
    # punctuation or words. Only insert a space when the very next character
    # after the DOI token is alphanumeric (i.e., a missing separator).

    return re.sub(r'(https?://doi\.org/[^\s\)\]\.,;:]+)(?=[A-Za-z0-9])', r'\1 ', ref)


def split_trailer_fragments(refs, author_start_like_re, min_years=2):
    """Split fragments where a trailing bracketed qualification is followed by an author.

    Example: "... universitet]. Freake, H., ..." -> split into
    ["... universitet].", "Freake, H., ..."].

    The helper is conservative: it will only attempt to split when the
    provided fragment contains at least `min_years` parenthesized year
    occurrences. This moves the "when to split" decision into the shared
    helper so callers don't need to duplicate the parenthesized-year
    counting logic.

    `author_start_like_re` should be a compiled regex (the author_start_like
    pattern from `build_author_patterns`) which is used to conservatively
    detect author-like starts on the right-hand side. The function will
    only split when the RHS matches the author-start-like pattern and the
    matched prefix contains no digits.
    """
    if not refs:
        return refs
    out = []
    split_trailer_re = re.compile(r'^(.*\]\.)\s+(.+)$')

    # obtain a parenthesized-year regex from our factory so the helper
    # uses the canonical definition; keep this local to avoid module
    # initialization order issues.
    try:
        year_re = build_parenthesized_year_patterns().get('YEAR_PAREN')
    except Exception:
        year_re = None

    for ref in refs:
        # Use cached parenthesized-year regex when available; fall back to
        # a conservative behaviour if it's not present.
        try:
            year_count = len(YEAR_PAREN_CACHED.findall(ref)) if YEAR_PAREN_CACHED is not None else 0
        except Exception:
            year_count = 0

        if year_count < (min_years or 0):
            out.append(ref)
            continue

        m = split_trailer_re.match(ref)
        if m:
            left, right = m.group(1), m.group(2)
            am = None
            try:
                am = author_start_like_re.match(right)
            except Exception:
                am = None
            if am:
                # ensure the matched author-like prefix itself contains no digits
                if not re.search(r"\d", am.group(0)):
                    out.append(left)
                    out.append(right)
                    continue
        out.append(ref)
    return out


def get_full_text(source=None, use_local_file=False, local_file_path=None,
                  use_txt_file=False, txt_file_path=None, headers=None,
                  verify=None, extractor='pymupdf', pymupdf_context_chars=2000):
    """Return full text extracted from TXT or PDF source.

    Lightweight wrapper that performs lazy imports for `requests` and
    PDF extraction libraries so callers that only need text-mode do not 
    require heavy dependencies at import time.
    
    Args:
        extractor: PDF extraction method - 'pymupdf' (default) or 'pdfminer'
        pymupdf_context_chars: When using pymupdf, include this many characters 
                               (excluding blanks) before the REFERENCES heading 
                               to avoid losing the first page of references. 
                               Default: 2000 characters
    """
    # TXT mode
    if use_txt_file:
        path = txt_file_path or source
        if not path:
            raise ValueError('TXT mode requested but no txt_file_path/source provided')
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()

    # Local PDF file
    if use_local_file:
        path = local_file_path or source
        if not path:
            raise ValueError('Local-file mode requested but no local_file_path/source provided')
        from io import BytesIO
        try:
            with open(path, 'rb') as f:
                pdf_bytes = f.read()
        except Exception as e:
            raise ValueError('Failed to read local PDF file') from e
        
        # Try requested extractor
        if extractor == 'pymupdf':
            try:
                import fitz
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                text = "\n".join([page.get_text() for page in doc])
                doc.close()
                return text
            except Exception as e:
                raise ValueError('PyMuPDF (fitz) is required for pymupdf extractor') from e
        else:  # pdfminer
            try:
                from pdfminer.high_level import extract_text as _extract_text
                return _extract_text(BytesIO(pdf_bytes))
            except Exception as e:
                raise ValueError('pdfminer.six is required for pdfminer extractor') from e

    # Remote URL
    try:
        import requests
    except Exception as e:
        raise ValueError('requests is required to fetch remote PDFs') from e

    resp = requests.get(source, headers=headers or {}, allow_redirects=True, verify=verify)
    ctype = resp.headers.get('Content-Type', '')
    if 'application/pdf' not in ctype:
        try:
            with open('downloaded_file.html', 'wb') as f:
                f.write(resp.content)
        except Exception:
            pass
        raise ValueError('The URL did not return a PDF file')

    from io import BytesIO
    
    # Try requested extractor
    if extractor == 'pymupdf':
        try:
            import fitz
            doc = fitz.open(stream=resp.content, filetype="pdf")
            text = "\n".join([page.get_text() for page in doc])
            doc.close()
            return text
        except Exception as e:
            raise ValueError('PyMuPDF (fitz) is required for pymupdf extractor') from e
    else:  # pdfminer
        try:
            from pdfminer.high_level import extract_text as _extract_text
            return _extract_text(BytesIO(resp.content))
        except Exception as e:
            raise ValueError('pdfminer.six is required for pdfminer extractor') from e


def extract_references_section(full_text, until_eof=False, require_heading=True, stop_at_allcaps=True, pymupdf_context_chars=None):
    """Locate the REFERENCES-like heading and return only the section.

    If require_heading is True a ValueError is raised when no heading is found.

    stop_at_allcaps controls whether to stop the extracted section at the
    next ALL-CAPS line (a likely section heading). Tests and TXT-mode callers
    historically prefer not to stop on ALL-CAPS when operating on a plain TXT
    input, so callers can set stop_at_allcaps=False to preserve that behavior.
    
    pymupdf_context_chars: When provided, include this many characters
                          (excluding blanks) before the REFERENCES heading.
                          This helps when PyMuPDF loses the first page.
    """
    if full_text is None:
        raise ValueError('full_text must be provided')
    text = full_text.replace('\f', '\n')
    references_heading_re = (
        r'^\s*(?:(?:[1-9]|1[0-2])\.?\s{0,3})?'
        r'(?:REFERENCES|BIBLIOGRAPHY|REFERENSER|WORKS CITED|REFERENSLISTA|LITTERATUR'
        r'|KÄLL- OCH LITTERATURFÖRTECKNING|KÄLLFÖRTECKNING|LITTERATURFÖRTECKNING|BIBLIOGRAFI'
        r'|Works Cited|Bibliography|References|Referenser|Referenslista|Litteratur'
        r'|Käll- och litteraturförteckning|Källförteckning|Litteraturförteckning|Bibliografi)\s*$'
    )
    match = re.search(references_heading_re, text, re.MULTILINE | re.IGNORECASE)
    if not match:
        if require_heading:
            raise ValueError('REFERENCES heading not found')
        return text
    
    # Calculate the start position: default behavior (non-PyMuPDF) skips the heading by
    # starting right after it. Only when pymupdf_context_chars is provided do we include
    # backward context to preserve potentially lost text.
    if pymupdf_context_chars is None or pymupdf_context_chars <= 0:
        start_idx = match.end()
    else:
        # Start at the heading and walk backward counting non-blank characters
        start_idx = match.start()
        non_blank_count = 0
        idx = start_idx - 1
        while idx >= 0 and non_blank_count < pymupdf_context_chars:
            if not text[idx].isspace():
                non_blank_count += 1
            idx -= 1
        # start_idx is now at the position we found; use it if we found enough context
        if non_blank_count == pymupdf_context_chars:
            start_idx = idx + 1
    
    # Move start_idx to the beginning of the current line to avoid cutting mid-line
    if start_idx > 0:
        start_idx = text.rfind('\n', 0, start_idx) + 1
    
    end_idx = match.end()
    if until_eof:
        return text[start_idx:]
    # Optionally stop at the next ALL-CAPS line which often denotes the next
    # section (e.g. ACKNOWLEDGEMENTS). Some callers (notably TXT-mode) prefer
    # to keep the entire remainder of the file; allow callers to disable this
    # heuristic via stop_at_allcaps=False.
    if stop_at_allcaps:
        next_section = re.search(r'^\s*[A-Z][A-Z\s\-]{5,}\s*$', text[end_idx:], re.MULTILINE)
        if next_section:
            end_idx = end_idx + next_section.start()
            return text[start_idx:end_idx]
    return text[start_idx:]


def load_and_preprocess(
    source=None,
    use_local_file=False,
    local_file_path=None,
    use_txt_file=False,
    txt_file_path=None,
    headers=None,
    verify=None,
    until_eof=False,
    stop_at_allcaps=False,
    require_heading=None,
    stop_tokens=None,
    min_page_number: int = 50,
    max_page_number: int = 400,
    audit_fp=None,
    preloaded_full_text=None,
    extractor='pymupdf',
    pymupdf_context_chars=2000,
):
    """Load full text (TXT/PDF), extract the references section and return
    a small preprocessed bundle.

    Behavior and return value:
    - By default `stop_at_allcaps` is False (do not stop at ALL-CAPS headings).
    - When `require_heading` is None it defaults to `not use_txt_file` so TXT
      inputs keep the conservative legacy behavior.
    - The function normalizes whitespace and unicode on each physical line
      and runs the shared hyphen-join fixed-point pass.

    Returns a dict with keys:
      { 'full_text', 'references_text', 'raw_lines', 'lines' }

    The optional `audit_fp` (file-like) will receive lightweight progress
    messages when provided.
    """
    if require_heading is None:
        require_heading = not use_txt_file

    # Default stop tokens historically used by the non-APA pipeline to
    # detect front-matter breaks and similar markers. These tokens were
    # present in older pipeline code and include Roman numerals and common
    # 'Paper' and 'Part' markers. Callers may override by passing an
    # iterable of strings via `stop_tokens` or pass an empty iterable to
    # disable this behavior.
    if stop_tokens is None:
        stop_tokens = {
            "I",
            "II",
            "III",
            "Paper I",
            "Paper II",
            "Paper III",
            "Paper 1",
            "Paper 2",
            "Paper 3",
            "Part II",
            "Part 2",
            "Appendix",
            "Paper I-III",
            "Paper 1-3",
            "Paper I-IV",
            "Paper 1-4",
            "Paper I-V",
            "Paper 1-5",
            "Paper I-VI",
            "Paper 1-6",
            "Bilagor",
            "Bilaga 1",
            "Appendices",
            "Appendix 1",
            "Article I",
            "Article II",
            "Article III",
            "Article 1",
            "Article 2",
            "Article 3",
            "Articles I-III",
            "Articles 1-3",
            "Articles I-IV",
            "Articles 1-4",
            "Articles I-V",
            "Articles 1-5",
            "Articles I-VI",
            "Articles 1-6", 
            "Articles",

        }
        # also accept the same tokens in ALL CAPS
        try:
            stop_tokens.update({t.upper() for t in list(stop_tokens)})
        except Exception:
            # fallback: explicitly add common uppercase variants if upper() fails
            stop_tokens.update({
            "I", "II", "III", "PAPER I", "PAPER II", "PAPER III",
            "PAPER 1", "PAPER 2", "PAPER 3", "PART II", "PART 2",
            "APPENDIX", "PAPER I-III", "PAPER 1-3", "PAPER I-IV",
            "PAPER 1-4", "PAPER I-V", "PAPER 1-5", "PAPER I-VI",
            "PAPER 1-6", "BILAGOR", "Bilaga 1".upper()
            })

    # Load full text (allow caller to pass a preloaded text to avoid
    # fetching/parsing twice). If `preloaded_full_text` is provided we
    # use it directly; otherwise call the shared `get_full_text`.
    if audit_fp:
        try:
            audit_fp.write(f"LOAD_AND_PREPROCESS: GET_FULL_TEXT source={source} use_local_file={use_local_file} use_txt_file={use_txt_file} txt_file_path={txt_file_path} preloaded={'yes' if preloaded_full_text is not None else 'no'}\n")
        except Exception:
            pass
    if preloaded_full_text is not None:
        full_text = preloaded_full_text
    else:
        full_text = get_full_text(
            source=source,
            use_local_file=use_local_file,
            local_file_path=local_file_path,
            use_txt_file=use_txt_file,
            txt_file_path=txt_file_path,
            headers=headers,
            verify=verify,
            extractor=extractor,
            pymupdf_context_chars=pymupdf_context_chars,
        )
    if audit_fp:
        try:
            audit_fp.write(f"LOAD_AND_PREPROCESS: GET_FULL_TEXT success len={len(full_text) if full_text is not None else 0}\n")
        except Exception:
            pass

    # Extract references section
    try:
        if audit_fp:
            try:
                audit_fp.write(f"LOAD_AND_PREPROCESS: EXTRACT_REFERENCES_SECTION until_eof={until_eof} stop_at_allcaps={stop_at_allcaps} require_heading={require_heading}\n")
            except Exception:
                pass
        references_text = extract_references_section(
            full_text,
            until_eof=until_eof,
            stop_at_allcaps=stop_at_allcaps,
            require_heading=require_heading,
            pymupdf_context_chars=pymupdf_context_chars if extractor == 'pymupdf' else None,
        )
        if audit_fp:
            try:
                audit_fp.write(f"LOAD_AND_PREPROCESS: EXTRACT_REFERENCES_SECTION success len={len(references_text) if references_text is not None else 0}\n")
            except Exception:
                pass
    except ValueError:
        # When heading not found, process the full text
        if audit_fp:
            try:
                audit_fp.write("LOAD_AND_PREPROCESS: EXTRACT_REFERENCES_SECTION ValueError - heading not found, using full text\n")
            except Exception:
                pass
        references_text = full_text

    # NOTE: inline CID removal was intentionally removed per user request.
    # Previously we performed an aggressive substitution removing occurrences
    # of '(cid:123)' from the entire extracted references_text. That code
    # has been deleted to avoid unintended concatenation and collapsing of
    # nearby tokens. Whole-line CID markers and UI timestamps are still
    # skipped later via `is_cid_marker` and `is_ui_timestamp_line`.

    # Split into raw lines and normalize
    raw_lines = references_text.splitlines()
    norm_lines = []
    for ln in raw_lines:
        # Lightweight pre-strip for artifact detection
        stripped = re.sub(r'\s{2,}', ' ', ln).strip()
        if not stripped:
            continue
        # Normalize early so we compare canonical forms (this ensures
        # different dash characters and similar glyphs match stop tokens
        # like 'ARTICLES I-IV' even when the source uses an en-dash).
        try:
            s_norm = normalize_line(stripped)
        except Exception:
            s_norm = stripped

        # If we encounter a stop token (exact match after normalization), stop
        # processing the rest of the extracted references section. This
        # restores the behavior previously implemented in the non-APA
        # pipeline where tokens like 'I', 'Paper I', 'Part II' signalled a
        # boundary. Only match exact tokens as defined in stop_tokens set
        # (which includes both 'Paper I' and 'PAPER I' variants).
        # Also allow for a trailing period (e.g., 'I.' or 'Paper I.').
        # Skip stop token checking when until_eof is True (user wants to
        # continue extracting until end of file regardless of stop tokens).
        if not until_eof:
            try:
                s_check = s_norm.rstrip('.')
                # Check exact match only (case-sensitive)
                is_stop = s_norm in stop_tokens or s_check in stop_tokens
                
                if is_stop:
                    if audit_fp:
                        try:
                            audit_fp.write(f"STOP_TOKEN_ENCOUNTERED: '{s_norm}'\n")
                        except Exception:
                            pass
                    break
            except Exception:
                pass

        # Skip common extraction artifacts early: hyphen-only lines and
        # standalone page-number lines. Inline CID markers are removed
        # earlier (INLINE_CID_REMOVAL) so the explicit whole-line CID
        # check is redundant and has been removed to avoid duplicate
        # audit messages.
        try:
            if is_hyphen_only_line(s_norm):
                if audit_fp:
                    try:
                        audit_fp.write(f"SKIP_HYPHEN_ONLY: '{s_norm}'\n")
                    except Exception:
                        pass
                continue
        except Exception:
            pass
        # Remove single-line CID markers and UI timestamp lines before
        # checking page-number lines. These artifact-only lines should be
        # skipped early to avoid interfering with page-number detection and
        # downstream joining heuristics.
        try:
            if is_cid_marker(s_norm) or is_ui_timestamp_line(s_norm):
                if audit_fp:
                    try:
                        audit_fp.write(f"SKIP_ARTIFACT_MARKER: '{s_norm}'\n")
                    except Exception:
                        pass
                continue
        except Exception:
            pass
        try:
            if is_page_number_line(s_norm, min_page_number, max_page_number):
                if audit_fp:
                    try:
                        audit_fp.write(f"SKIP_PAGE_NUMBER: '{s_norm}'\n")
                    except Exception:
                        pass
                continue
        except Exception:
            pass

        # Use the already-normalized string
        norm_lines.append(s_norm)

    # Apply hyphen-join fixed-point using shared implementation
    # Keep a copy of the normalized lines before performing the
    # hyphen-join fixed-point. Some callers rely on the physical-line
    # boundaries (pre-join) for further heuristics; return it as
    # `pre_hyphen_lines` so callers can opt-in to the uncollapsed view.
    pre_hyphen_lines = list(norm_lines)
    if norm_lines:
        try:
            norm_lines = hyphen_join_fixed_point(norm_lines, audit_fp=audit_fp)
        except Exception:
            # if hyphen join fails, continue with best-effort lines
            pass

    # Remove any empty lines
    norm_lines = [l for l in norm_lines if l and l.strip()]

    return {
        'full_text': full_text,
        'references_text': references_text,
        'raw_lines': raw_lines,
        # normalized physical lines before hyphen-joining (useful for
        # pipelines that need the uncollapsed view).
        'pre_hyphen_lines': pre_hyphen_lines,
        # final normalized lines after hyphen-joining (default consumer
        # behavior).
        'lines': norm_lines,
    }


def fix_diaeresis_errors(text: str) -> str:
    """Fix common diaeresis errors in text (case-insensitive).
    
    Replaces:
      - '¨o' or '¨O' with 'ö' or 'Ö'
      - '¨a' or '¨A' with 'ä' or 'Ä'
      - '¨u' or '¨U' with 'ü' or 'Ü'
    
    Examples:
      - 'f¨or' -> 'för'
      - '¨Uber' -> 'Über'
      - 'M¨unchen' -> 'München'
    """
    if not text:
        return text
    
    # Replace lowercase variants
    text = text.replace('¨o', 'ö')
    text = text.replace('¨a', 'ä')
    text = text.replace('¨u', 'ü')
    
    # Replace uppercase variants
    text = text.replace('¨O', 'Ö')
    text = text.replace('¨A', 'Ä')
    text = text.replace('¨U', 'Ü')
    
    return text
