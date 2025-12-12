import subprocess
import sys
import os
import argparse
from dotenv import load_dotenv

# Auto-load environment variables from .env file
load_dotenv()

parser = argparse.ArgumentParser(description='Run Crossref CSV pipeline and optionally save references to txt files.')
# Default ON; provide explicit OFF switch and propagate to child script
parser.add_argument('--save-references-txt', dest='save_refs_txt', action='store_true', help='Enable saving per-DOI references txt (default).')
parser.add_argument('--no-save-references-txt', dest='save_refs_txt', action='store_false', help='Disable saving per-DOI references txt.')
parser.set_defaults(save_refs_txt=True)
args = parser.parse_args()

# Step 1: Run the CSV to XML transformation script
print("Running CSV to XML transformation...")
cmd = [sys.executable, "csv-crossref.py"]
if getattr(args, 'save_refs_txt', True):
    cmd.append('--save-references-txt')
else:
    cmd.append('--no-save-references-txt')
result = subprocess.run(cmd, check=True)
print("Transformation complete.")

# Step 2: Upload the XML using crossref-upload-tool.jar
xml_path = "crossref_output.xml"
username = os.environ.get('CROSSREF_USERNAME')
password = os.environ.get('CROSSREF_PASSWORD')
# Update this path to the actual location of the JAR on your system
jar_path = os.path.expanduser("~/Documents/Crossref_XML/crossref-upload-tool.jar")

if not username or not password:
    print("Error: CROSSREF_USERNAME and CROSSREF_PASSWORD environment variables must be set.")
    print("See GITHUB_SECURITY.md for setup instructions.")
    sys.exit(1)

try:
    subprocess.run(
        [
            "java",
            "-jar",
            jar_path,
            "--user",
            username,
            password,
            "--metadata",
            xml_path,
        ],
        check=True,
    )
    print("File uploaded to CrossRef successfully!")
except subprocess.CalledProcessError as e:
    print(f"Error during upload: {e}")
