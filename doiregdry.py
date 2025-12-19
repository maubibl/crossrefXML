from lxml import etree
from datetime import datetime
import sys

# Check for command-line argument for genre override
genre_override = ''
if len(sys.argv) > 1:
    genre_override = sys.argv[1]

# Load the XML and XSLT files
xml = etree.parse('export.xml')
xslt = etree.parse('DiVA-CrossRef.xslt')

# Get the current date and time in the desired format: YYYYMMDDHHMMSS000
current_timestamp = datetime.now().strftime('%Y%m%d%H%M%S') + '000'

# Pass the timestamp and genre override as parameters to the XSLT transformation
transform = etree.XSLT(xslt)
result = transform(xml, 
                   currentDateTime=etree.XSLT.strparam(current_timestamp),
                   genreOverride=etree.XSLT.strparam(genre_override))

# Save the transformed XML to a file
today_date = datetime.now().strftime('%y%m%d%H%M')
transformed_filename = f'doireg{today_date}.xml'

with open(transformed_filename, 'wb') as f:
    f.write(
        etree.tostring(
            result, pretty_print=True, xml_declaration=True, encoding='UTF-8'
        )
    )

# Print success message
print(f"Transformation completed successfully! File saved as {transformed_filename}")
if genre_override:
    print(f"Forced doc type: {genre_override}")
