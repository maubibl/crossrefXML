import certifi
import os

# Path to certifi's CA bundle
certifi_bundle = certifi.where()
# Path to your downloaded intermediate certificate
geant_intermediate = "geant_ca4.pem"
# Path for the combined bundle
combined_bundle = "combined_ca.pem"

# Combine the two files
with open(combined_bundle, "wb") as out_f:
    with open(certifi_bundle, "rb") as certifi_f:
        out_f.write(certifi_f.read())
    with open(geant_intermediate, "rb") as interm_f:
        out_f.write(interm_f.read())