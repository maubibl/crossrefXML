import pandas as pd
from lxml import etree
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import re
import csv
import traceback
import subprocess
import argparse
import os
from dotenv import load_dotenv

# Auto-load environment variables from .env file
load_dotenv()

# Load CSV, force certain columns to be strings
string_cols = ['YEAR', 'VOLUME', 'ISSUE', 'FIRST PAGE', 'LAST PAGE']
# CLI: toggle saving reference section to per-DOI txt files
parser = argparse.ArgumentParser(description='Generate Crossref XML from DOI.csv and optionally save references to txt files.')
# Default ON; provide an explicit OFF switch
parser.add_argument('--save-references-txt', dest='save_refs_txt', action='store_true', help='Enable saving references to per-DOI txt files (default).')
parser.add_argument('--no-save-references-txt', dest='save_refs_txt', action='store_false', help='Disable saving references to per-DOI txt files.')
parser.set_defaults(save_refs_txt=True)
args = parser.parse_args()

# Optional env override: CSV_SAVE_REFS_TXT accepts 1/true/yes/on or 0/false/no/off
env_override = os.environ.get('CSV_SAVE_REFS_TXT')
if env_override is not None:
    val = env_override.strip().lower()
    SAVE_REFS_TXT = val in ('1', 'true', 'yes', 'on')
else:
    SAVE_REFS_TXT = bool(getattr(args, 'save_refs_txt', True))

df = pd.read_csv('DOI.csv', sep=';', dtype={col: str for col in string_cols}, quoting=csv.QUOTE_ALL)


# Create XML root
schema_loc = (
    "http://www.crossref.org/schema/5.4.0 "
    "https://www.crossref.org/schemas/crossref5.4.0.xsd"
)

root = etree.Element(
    'doi_batch',
    attrib={
        'version': "5.4.0",
        '{http://www.w3.org/2001/XMLSchema-instance}schemaLocation': schema_loc,
    },
    nsmap={
        None: "http://www.crossref.org/schema/5.4.0",
        'xsi': "http://www.w3.org/2001/XMLSchema-instance",
        'jats': "http://www.ncbi.nlm.nih.gov/JATS1",
        'fr': "http://www.crossref.org/fundref.xsd",
        'mml': "http://www.w3.org/1998/Math/MathML",
        'xlink': "http://www.w3.org/1999/xlink",
        'mods': "http://www.loc.gov/mods/v3"
    }
)
# Create <head> element under root
head = etree.SubElement(root, 'head')
doi_batch_id = etree.SubElement(head, 'doi_batch_id')
doi_batch_id.text = str(datetime.now().strftime("%Y%m%d%H%M%S"))  # Unique ID based on current timestamp
timestamp = etree.SubElement(head, 'timestamp')
timestamp.text = str(datetime.now().strftime("%Y%m%d%H%M%S")) + "000"  # Current timestamp in required format
depositor = etree.SubElement(head, 'depositor')
depositor_name = etree.SubElement(depositor, 'depositor_name')
depositor_name.text = os.environ.get('CROSSREF_DEPOSITOR_NAME', 'malmo:malmo')
email = etree.SubElement(depositor, 'email_address')
email.text = os.environ.get('CROSSREF_EMAIL', 'depositor@example.com')
registrant = etree.SubElement(head, 'registrant')
registrant.text = os.environ.get('CROSSREF_REGISTRANT', 'Malmö University')

# Create <body> element under root
body = etree.SubElement(root, 'body')

# Determine groupby columns based on presence of 'VOL'
groupby_cols = ['JOURNAL', 'YEAR', 'ISSUE']
if 'VOL' in df.columns:
    groupby_cols.append('VOL')

grouped = df.groupby(groupby_cols, dropna=False)

for group_keys, group in grouped:
    # Filter the group to only rows with a valid DOI
    valid_articles = group[
        (
            group['DOI'].notna()
            & (group['DOI'].astype(str).str.strip().str.lower() != 'nan')
            & (group['DOI'].astype(str).str.strip() != '')
        )
    ]
    if valid_articles.empty:
        continue  # Skip this group if no valid articles

    # Now create <journal> and <journal_issue> as before
    # Unpack group keys based on number of columns
    if 'VOL' in df.columns:
        journal_name, year_val, issue_val, volume_val = group_keys
    else:
        journal_name, year_val, issue_val = group_keys
        volume_val = ''  # Set to empty string if VOL is missing

    journal = etree.SubElement(body, 'journal')
    journal_metadata = etree.SubElement(journal, 'journal_metadata')
    journal_title = etree.SubElement(journal_metadata, 'full_title')
    journal_title.text = str(journal_name)
    if 'ABBRIVIATION' in df.columns:
        abbrev_title_val = str(group.iloc[0]['ABBRIVIATION']).strip()
        if abbrev_title_val and abbrev_title_val.lower() != 'nan':
            abbrev_title = etree.SubElement(journal_metadata, 'abbrev_title')
            abbrev_title.text = abbrev_title_val
    issn = etree.SubElement(journal_metadata, 'issn', media_type='electronic')
    issn_val = str(group.iloc[0]['ISSN']).strip()
    issn.text = issn_val.upper()

    journal_issue = etree.SubElement(journal, 'journal_issue')
    if 'ISSUE TITLE' in df.columns:
        issue_title_val = str(group.iloc[0]['ISSUE TITLE']).strip()
        if issue_title_val and issue_title_val.lower() != 'nan':
            issue_titles = etree.SubElement(journal_issue, 'titles')
            issue_title = etree.SubElement(issue_titles, 'title')
            issue_title.text = issue_title_val

    # Add publication_date at the issue level
    publication_date = etree.SubElement(journal_issue, 'publication_date', media_type='online')
    pub_dates = group['PUBLICATION DATE'].dropna().unique()
    if len(pub_dates) == 1 and str(pub_dates[0]).strip().lower() != 'nan' and pub_dates[0] != '':
        year_str, month_str, day_str = str(pub_dates[0]).strip().split('-')
        month = etree.SubElement(publication_date, 'month')
        month.text = month_str
        day = etree.SubElement(publication_date, 'day')
        day.text = day_str
        year = etree.SubElement(publication_date, 'year')
        year.text = year_str
    else:
        year = etree.SubElement(publication_date, 'year')
        year.text = str(year_val)

    # Add volume if present
    vol_val = str(volume_val).strip()
    if vol_val and vol_val.lower() != 'nan':
        journal_volume = etree.SubElement(journal_issue, 'journal_volume')
        volume = etree.SubElement(journal_volume, 'volume')
        volume.text = vol_val

    # Add issue if present
    if issue_val and str(issue_val).lower() != 'nan':
        issue = etree.SubElement(journal_issue, 'issue')
        issue.text = str(issue_val)

    # Add all articles for this issue
    for _, row in group.iterrows():
        doi_val = str(row['DOI']).strip() if 'DOI' in df.columns else ''
        if not doi_val or doi_val.lower() == 'nan':
            continue  # Skip this row if DOI is missing

        lang_val = str(row['LANG']).strip() if 'LANG' in df.columns else 'en'
        journal_article = etree.SubElement(journal, 'journal_article', publication_type="full_text", language=lang_val)
        titles = etree.SubElement(journal_article, 'titles')
        title = etree.SubElement(titles, 'title')
        title.text = str(row['TITLE'])

        # Add Contributors
        contributors = etree.SubElement(journal_article, 'contributors')
        max_authors = 10  # Adjust as needed for your data

        for i in range(1, max_authors + 1):
            org_col = f'AU{i} ORGANIZATION'
            last_name_col = f'AU{i} LAST NAME'
            first_name_col = f'AU{i} FIRST NAME'
            affiliation_col = f'AU{i} AFFILIATION'
            orcid_col = f'AU{i} ORCID'

            # Check for organization contributor
            if org_col in df.columns:
                org_val = str(row[org_col]).strip()
                if org_val and org_val.lower() != 'nan':
                    sequence = "first" if i == 1 else "additional"
                    org_elem = etree.SubElement(
                        contributors,
                        'organization',
                        sequence=sequence,
                        contributor_role="author",
                    )
                    org_elem.text = org_val
                    continue  # Skip person logic if organization is present

            # Check for person contributor
            if last_name_col in df.columns and first_name_col in df.columns:
                last_name = str(row[last_name_col]).strip()
                first_name = str(row[first_name_col]).strip()
                if (
                    last_name
                    and last_name.lower() != 'nan'
                    and first_name
                    and first_name.lower() != 'nan'
                ):
                    sequence = "first" if i == 1 else "additional"
                    author = etree.SubElement(
                        contributors,
                        'person_name',
                        sequence=sequence,
                        contributor_role="author",
                    )
                    given_name = etree.SubElement(author, 'given_name')
                    given_name.text = first_name
                    surname = etree.SubElement(author, 'surname')
                    surname.text = last_name
                    if affiliation_col in df.columns:
                        affiliation_val = str(row[affiliation_col]).strip()
                        if affiliation_val and affiliation_val.lower() != 'nan':
                            affiliations = etree.SubElement(author, 'affiliations')
                            institution = etree.SubElement(affiliations, 'institution')
                            institution_name = etree.SubElement(institution, 'institution_name')
                            institution_name.text = affiliation_val
                            malmo_variants = ["malmö university", "malmö universitet"]
                            if any(variant in affiliation_val.lower() for variant in malmo_variants):
                                institution_id = etree.SubElement(institution, 'institution_id', type="ror")
                                institution_id.text = "https://ror.org/05wp7an13"
                                institution_id = etree.SubElement(institution, 'institution_id', type="isni")
                                institution_id.text = "https://isni.org/isni/0000000099619487"
                                institution_id = etree.SubElement(institution, 'institution_id', type="wikidata")
                                institution_id.text = "https://www.wikidata.org/wiki/Q977781"
                    if orcid_col in df.columns:
                        orcid_val = str(row[orcid_col]).strip()
                        if orcid_val and orcid_val.lower() != 'nan':
                            orcid = etree.SubElement(author, 'ORCID')
                            orcid.text = f"https://orcid.org/{orcid_val}"
        # Add Abstract if it exists
        if 'ABSTRACT' in df.columns:
            abstract_val = str(row['ABSTRACT']).strip()
            if abstract_val and abstract_val.lower() != 'nan':
                # Use 'ABSTRACT LANG' if it exists and has a value, otherwise use lang_val
                if 'ABSTRACT LANG' in df.columns:
                    abstract_lang = str(row['ABSTRACT LANG']).strip()
                    if abstract_lang and abstract_lang.lower() != 'nan':
                        lang_to_use = abstract_lang
                    else:
                        lang_to_use = lang_val
                else:
                    lang_to_use = lang_val

                abstract = etree.SubElement(
                    journal_article,
                    '{http://www.ncbi.nlm.nih.gov/JATS1}abstract',
                    attrib={'{http://www.w3.org/XML/1998/namespace}lang': lang_to_use}
                )
                abs = etree.SubElement(abstract, '{http://www.ncbi.nlm.nih.gov/JATS1}p')
                abs.text = abstract_val

        # Add <publication_date> element
        publication_date = etree.SubElement(journal_article, 'publication_date', media_type='online')
        pubdate_str = str(row['PUBLICATION DATE']).strip()
        if pubdate_str and pubdate_str.lower() != 'nan':
            yearval, monthval, dayval = pubdate_str.split('-')
            month = etree.SubElement(publication_date, 'month')
            month.text = monthval
            day = etree.SubElement(publication_date, 'day')
            day.text = dayval
            year = etree.SubElement(publication_date, 'year')
            year.text = yearval
        else:
            year = etree.SubElement(publication_date, 'year')
            year.text = str(int(float(row['YEAR']))) if pd.notnull(row['YEAR']) else ''  # Fallback to YEAR column

        # Add <pages> element if FIRST PAGE is present and non-empty
        if 'FIRST PAGE' in df.columns:
            first_page_val = row['FIRST PAGE'] if pd.notnull(row['FIRST PAGE']) else ''
            last_page_val = row['LAST PAGE'] if pd.notnull(row['LAST PAGE']) else ''
            if first_page_val and first_page_val.lower() != 'nan':
                pages = etree.SubElement(journal_article, 'pages')
                first_page = etree.SubElement(pages, 'first_page')
                first_page.text = first_page_val
                if last_page_val and last_page_val.lower() != 'nan':
                    last_page = etree.SubElement(pages, 'last_page')
                    last_page.text = last_page_val

        # Add <doi_data> element
        doi_data = etree.SubElement(journal_article, 'doi_data')
        doi = etree.SubElement(doi_data, 'doi')
        doi.text = str(row['DOI'])
        resource = etree.SubElement(doi_data, 'resource')
        resource.text = str(row['LINK TO ARTICLE'])
        if 'LINK TO PDF' in df.columns:
            pdf_link = str(row['LINK TO PDF']).strip()
            if pdf_link and pdf_link.lower() != 'nan':
                pdf_collection = etree.SubElement(doi_data, 'collection', property="crawler-based")
                pdf_item = etree.SubElement(pdf_collection, 'item', crawler="similarity-check")
                pdf_resource = etree.SubElement(pdf_item, 'resource')
                pdf_resource.text = pdf_link

        # Optionally save References section to a txt file named after DOI
        if SAVE_REFS_TXT:
            link_to_article = str(row['LINK TO ARTICLE']).strip()
            doi_val = str(row['DOI']).strip()
            if link_to_article and doi_val and doi_val.lower() != 'nan':
                print(f"Processing DOI: {doi_val}, URL: {link_to_article}")
                try:
                    response = requests.get(link_to_article, timeout=10)
                    print(f"HTTP status: {response.status_code}, Content length: {len(response.text)}")
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, 'html.parser')

                    # Find references container
                    ref_div = soup.find('div', class_='references')
                    references = []
                    if ref_div:
                        print("Found <div class='references'>")
                        for tag in ref_div.find_all(['p', 'h6']):
                            ref_text = tag.get_text(separator=' ', strip=True)
                            if ref_text:
                                references.append(ref_text)
                    else:
                        print("No <div class='references'> found, trying heading fallback...")
                        heading = soup.find(lambda tag: tag.name in ['h2', 'h4'] and 'references' in tag.text.lower())
                        if heading:
                            print("Found heading with 'References'")
                            for sibling in heading.next_siblings:
                                if getattr(sibling, 'name', None) in ['h2', 'h4']:
                                    break
                                if getattr(sibling, 'name', None) in ['p', 'h6']:
                                    ref_text = sibling.get_text(separator=' ', strip=True)
                                    if ref_text:
                                        references.append(ref_text)
                        else:
                            print("No heading with 'References' found.")

                    print(f"Number of references found: {len(references)}")
                    # Extract the part after the last '/' in the DOI for the filename
                    if '/' in doi_val:
                        file_part = doi_val.split('/')[-1]
                    else:
                        file_part = doi_val

                    safe_file_part = re.sub(r'[^\w.-]', '_', file_part)

                    if references:
                        with open(f"{safe_file_part}.txt", "w", encoding="utf-8") as f:
                            f.write(doi_val + "\n")
                            for ref in references:
                                f.write(ref + "\n")
                        print(f"Saved references to {safe_file_part}.txt")
                    else:
                        print(f"No references found for DOI {doi_val}")
                        # Fallback: if we have a LINK TO PDF, try extracting references using doiref.py
                        pdf_link_fallback = str(row['LINK TO PDF']).strip() if 'LINK TO PDF' in df.columns else ''
                        if pdf_link_fallback and pdf_link_fallback.lower() != 'nan':
                            # Use the part after the first '/' in the DOI as filename base (match doireg behavior)
                            if '/' in doi_val:
                                doi_suffix = doi_val.split('/', 1)[1]
                            else:
                                doi_suffix = doi_val
                            safe_suffix = re.sub(r'[^\w\-.]', '_', doi_suffix)
                            fallback_output = f"{safe_suffix}.txt"
                            print(
                                f"No HTML references — falling back to doiref.py using PDF link: "
                                f"{pdf_link_fallback} -> {fallback_output}"
                            )
                            try:
                                subprocess.run(['python3', 'doiref.py', pdf_link_fallback, fallback_output], check=True)
                                print(f"doiref.py finished, output file: {fallback_output}")
                            except Exception as e:
                                print(f"doiref.py failed for DOI {doi_val}: {e}")
                except Exception as e:
                    print(f"Could not fetch references for DOI {doi_val}: {e}")
                    traceback.print_exc()

# Write to XML file
tree = etree.ElementTree(root)
tree.write('crossref_output.xml', pretty_print=True, xml_declaration=True, encoding='UTF-8')
