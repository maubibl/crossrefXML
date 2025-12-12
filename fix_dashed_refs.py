#!/usr/bin/env python3
"""
Replace dashed placeholders (e.g., '---. ') with the author prefix from the 
previous non-dashed reference line.

Usage:
    python fix_dashed_refs.py references_nonapa.txt
    python fix_dashed_refs.py input.txt --output output.txt
    python fix_dashed_refs.py input.txt --placeholder "—. "
    python fix_dashed_refs.py input.txt --in-place

You can also set the input/output files directly in the script by modifying 
INPUT_FILE and OUTPUT_FILE below.

The script finds lines starting with a placeholder (default '---. ') and 
replaces the placeholder with the beginning of the first previous non-dashed 
line, up to and including the year (parenthesized or bare).
"""
import re
import argparse
from pathlib import Path
from parsing_helpers import (
    build_parenthesized_year_patterns,
    build_nonparenthesized_year_pattern,
)

# Set your input and output files here (can be None to use command-line arguments)
# Examples:
#   INPUT_FILE = "references_nonapa.txt"
#   OUTPUT_FILE = "references_nonapa_fixed.txt"  # or None for auto-naming
#   INPUT_FILE = None  # Use command-line arguments
INPUT_FILE = "references_nonapa.txt"
OUTPUT_FILE = "no-dash.txt"

# Build year patterns from parsing_helpers
try:
    YR_PATTERNS = build_parenthesized_year_patterns()
    YEAR_PAREN = YR_PATTERNS.get('YEAR_PAREN')
except Exception:
    YEAR_PAREN = None

try:
    YEAR_BARE = build_nonparenthesized_year_pattern()
except Exception:
    YEAR_BARE = None


def extract_author_prefix(line: str) -> str:
    """Extract the author prefix from a line (up to but NOT including the year).
    
    Searches for the first year pattern (parenthesized like '(2023)' or bare 
    like '2023') and returns everything up to (but not including) that year.
    Uses the canonical year patterns from parsing_helpers.
    
    Strips trailing commas and spaces, but preserves periods that are part of
    initials or abbreviations (e.g., "Smith, J." or "Smith, J.A.").
    
    Returns empty string if no year is found.
    """
    # Try parenthesized year pattern from parsing_helpers
    paren_year = None
    if YEAR_PAREN:
        try:
            paren_year = YEAR_PAREN.search(line)
        except Exception:
            pass
    
    # Try bare year pattern from parsing_helpers
    bare_year = None
    if YEAR_BARE:
        try:
            bare_year = YEAR_BARE.search(line)
        except Exception:
            pass
    
    # Use whichever appears first in the line
    year_match = None
    if paren_year and bare_year:
        # Both found, use the earlier one
        year_match = paren_year if paren_year.start() < bare_year.start() else bare_year
    elif paren_year:
        year_match = paren_year
    elif bare_year:
        year_match = bare_year
    
    if year_match:
        # Return everything up to (but NOT including) the year match
        prefix = line[:year_match.start()].rstrip()
        # Strip trailing commas and spaces (e.g., "Smith, J.," or "Smith, J., ")
        # but keep periods that are part of initials
        prefix = re.sub(r',\s*$', '', prefix).rstrip()
        return prefix
    
    return ""


def process_references(lines: list[str], placeholder: str = '---. ') -> list[str]:
    """Process reference lines, replacing placeholders with author prefixes.
    
    Args:
        lines: List of reference lines
        placeholder: The placeholder string to look for at line start
        
    Returns:
        List of processed lines with placeholders replaced
    """
    result = []
    last_author_prefix = ""
    
    for line in lines:
        stripped = line.lstrip()
        
        if stripped.startswith(placeholder):
            # Replace placeholder with last author prefix
            if last_author_prefix:
                # Remove the placeholder and prepend the author prefix
                rest_of_line = stripped[len(placeholder):]
                new_line = f"{last_author_prefix} {rest_of_line}"
                result.append(new_line)
            else:
                # No previous author prefix found, keep line as-is
                result.append(line)
        else:
            # Not a dashed line - extract and remember author prefix
            author_prefix = extract_author_prefix(stripped)
            if author_prefix:
                last_author_prefix = author_prefix
            result.append(line)
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description='Replace dashed reference placeholders with author prefixes'
    )
    parser.add_argument(
        'input_file',
        nargs='?',
        type=Path,
        default=None,
        help='Input file with references'
    )
    parser.add_argument(
        '--output',
        '-o',
        type=Path,
        default=None,
        help='Output file (default: input_file with .fixed.txt extension)'
    )
    parser.add_argument(
        '--placeholder',
        '-p',
        type=str,
        default='---,',
        help='Placeholder string to replace (default: "---,")'
    )
    parser.add_argument(
        '--in-place',
        '-i',
        action='store_true',
        help='Modify the input file in-place'
    )
    
    args = parser.parse_args()
    
    # Use INPUT_FILE from script if set, otherwise require command-line argument
    if INPUT_FILE is not None:
        input_file = Path(INPUT_FILE)
        # If output is provided as command-line arg, use it; otherwise use OUTPUT_FILE from script
        output_override = args.output if args.output else (Path(OUTPUT_FILE) if OUTPUT_FILE else None)
    elif args.input_file:
        input_file = args.input_file
        output_override = args.output
    else:
        print("Error: No input file specified")
        print("  Set INPUT_FILE in the script, or provide input file as argument")
        return 1
    
    # Read input file
    if not input_file.exists():
        print(f"Error: Input file not found: {input_file}")
        return 1
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Error reading input file: {e}")
        return 1
    
    # Process lines
    # Strip newlines for processing, will add back when writing
    lines_stripped = [line.rstrip('\n\r') for line in lines]
    processed = process_references(lines_stripped, args.placeholder)
    
    # Determine output file
    if args.in_place:
        output_file = input_file
    elif output_override:
        output_file = output_override
    else:
        # Default: add .fixed before extension
        stem = input_file.stem
        suffix = input_file.suffix
        output_file = input_file.parent / f"{stem}.fixed{suffix}"
    
    # Write output
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            for line in processed:
                f.write(line + '\n')
        print(f"Processed {len(lines)} lines")
        print(f"Output written to: {output_file}")
        return 0
    except Exception as e:
        print(f"Error writing output file: {e}")
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
