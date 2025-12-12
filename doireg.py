import subprocess
from lxml import etree
from datetime import datetime
import xml.etree.ElementTree as ET
import re
import sys
import os
from dotenv import load_dotenv

# Auto-load environment variables from .env file
load_dotenv()

# Load the XML and XSLT files (local export.xml)
xml = etree.parse('export.xml')
xslt = etree.parse('DiVA-CrossRef.xslt')

# Get the current date and time in the desired format: YYYYMMDDHHMMSS000
current_timestamp = datetime.now().strftime('%Y%m%d%H%M%S') + '000'

# Get depositor information from environment variables
depositor_name = os.environ.get('CROSSREF_DEPOSITOR_NAME', 'malmo:malmo')
depositor_email = os.environ.get('CROSSREF_EMAIL', 'depositor@example.com')

# Pass the timestamp and depositor info as parameters to the XSLT transformation
transform = etree.XSLT(xslt)
result = transform(xml, 
                   currentDateTime=etree.XSLT.strparam(current_timestamp),
                   depositorName=etree.XSLT.strparam(depositor_name),
                   depositorEmail=etree.XSLT.strparam(depositor_email))

# Save the transformed XML to a file
transformed_filename = 'doireg.xml'

with open(transformed_filename, 'wb') as f:
    f.write(etree.tostring(result, pretty_print=True, xml_declaration=True, encoding='UTF-8'))

# Print success message
print(f"Transformation completed successfully! File saved as {transformed_filename}")

# Upload the file to CrossRef using crossref-upload-tool.jar
username = os.environ.get('CROSSREF_USERNAME')
password = os.environ.get('CROSSREF_PASSWORD')
jar_path = "crossref-upload-tool.jar"  # Path to the JAR file

if not username or not password:
    print("Error: CROSSREF_USERNAME and CROSSREF_PASSWORD environment variables must be set.")
    print("See GITHUB_SECURITY.md for setup instructions.")
    sys.exit(1)

try:
    subprocess.run(
        [
            "java", "-jar", jar_path,
            "--user", username, password,
            "--metadata", transformed_filename
        ],
        check=True
    )
    print("File uploaded to CrossRef successfully!")
except subprocess.CalledProcessError as e:
    print(f"Error during upload: {e}")

# Parse XML
tree = ET.parse('export.xml')
root = tree.getroot()

# Namespaces (adjust if needed)
ns = {'mods': 'http://www.loc.gov/mods/v3'}

# Find the fulltext URL
url = None
for loc in root.findall('.//mods:location', ns):
    url_elem = loc.find('mods:url[@displayLabel="fulltext"]', ns)
    if url_elem is not None:
        url = url_elem.text.strip()
        break

# Find the DOI
doi = None
for ident in root.findall('.//mods:identifier[@type="doi"]', ns):
    doi = ident.text.strip()
    break

if not url or not doi:
    raise Exception("Could not find fulltext URL or DOI in export.xml")

# Use the part after the first '/' in the DOI as the filename, if available
# e.g. for '10.1234/abcd.efg' use 'abcd.efg'
doi_suffix = None
if doi and '/' in doi:
    doi_suffix = doi.split('/', 1)[1]

if doi_suffix:
    # sanitize suffix: allow word chars, dash, dot; replace others with underscore
    safe_suffix = re.sub(r'[^\w\-.]', '_', doi_suffix)
    output_filename = f"{safe_suffix}.txt"
else:
    # fallback to sanitized full DOI if no suffix found
    safe_doi = re.sub(r'[^\w\-.]', '_', doi) if doi else 'output'
    output_filename = f"{safe_doi}.txt"

# Call doiref.py with URL and output filename using the current Python executable
# Inspect the source XML for a numeric <extent> element and, if present,
# derive page-range hints for doiref.py. Behavior:
#  - If extent contains only digits, use that value as `--max-page-number`
#    but clamp it to [30, 800].
#  - Set `--min-page-number` to extent - 50, but at least 30.
extent_val = None
try:
    for ext in root.findall('.//mods:extent', ns):
        if ext is None or ext.text is None:
            continue
        txt = ext.text.strip()
        if re.match(r'^\d+$', txt):
            try:
                extent_val = int(txt)
            except Exception:
                extent_val = None
            break
except Exception:
    extent_val = None

cmd = [
    sys.executable,
    os.path.join(os.path.dirname(__file__), 'doiref.py'),
    url,
    output_filename,
]
if extent_val is not None:
    # clamp and compute values
    max_page = max(30, min(extent_val, 800))
    min_page = max(30, extent_val - 50)
    # ensure min_page <= max_page
    if min_page > max_page:
        min_page = max(30, max_page - 50)
    cmd.extend(['--min-page-number', str(min_page), '--max-page-number', str(max_page)])

subprocess.run(cmd)
