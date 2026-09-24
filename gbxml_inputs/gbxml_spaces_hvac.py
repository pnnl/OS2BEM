import pandas as pd
from lxml import etree
import os
import json

# Run this script whenever a new Revit Systems Analysis gbXML export is available.
# Keep the source gbXML file beside this script and update gbxml_file below when needed.
# The generated mappings are written to the OS2BEM root for use by the schedule and HVAC tools.

#gbxml_file = "gbxml_DD_hvac.xml"                           #####
gbxml_file = "gbxml_cd_hvac.xml"                            #####
script_dir = os.path.dirname(os.path.abspath(__file__))
os2bem_dir = os.path.dirname(script_dir)
gbxmlfile_path = os.path.join(script_dir, gbxml_file)
# Parse the gbXML file
tree = etree.parse(gbxmlfile_path)
root = tree.getroot()
#print(root)

# Define the namespace used in the gbXML file
namespace = {"gb": "http://www.gbxml.org/schema"}

# Find all <Space> elements
space_elements = root.findall(".//gb:Space", namespaces=namespace)

# Initialize variables to store extracted data
space_id_refs = []
space_names = []
zone_space_mapping = {}

# Create zone id-name mapping dict
zone_id_mapping = {}
zones = root.findall(".//gb:Zone", namespaces=namespace)
for zone in zones:
    zone_id = zone.get("id")
    zone_name_elem = zone.find(".//gb:Name", namespaces=namespace)
    zone_name = zone_name_elem.text if zone_name_elem is not None else ""
    zone_id_mapping[zone_id] = zone_name

# Loop through each <Space> element and extract data
for space in space_elements:
    space_id_ref = space.get("id")
    space_name = space.find(".//gb:Name", namespaces=namespace)

    zone_id = space.get("zoneIdRef")
    zone_name = zone_id_mapping[zone_id]
    if zone_name not in zone_space_mapping:
        zone_space_mapping[zone_name] = []
    zone_space_mapping[zone_name].append(space_name.text if space_name is not None else "")

    # Append data to the respective lists
    space_id_refs.append(space_id_ref if space_id_ref is not None else "")
    space_names.append(space_name.text if space_name is not None else "")

# Create a DataFrame
data = {"id": space_id_refs, "space": space_names}
df = pd.DataFrame(data)

# Print the DataFrame
#print(df)

# Save the space mapping for OS2BEM tools
if  gbxml_file == "gbxml_DD_hvac.xml":
    df.to_csv(os.path.join(os2bem_dir, "gbxml_spaces_DD_hvac.csv"), index=False)
elif gbxml_file == "gbxml_cd_hvac.xml":
    df.to_csv(os.path.join(os2bem_dir, "gbxml_spaces_cd_hvac.csv"), index=False)

# Save the zone-space mapping for the schedule generator
with open(os.path.join(os2bem_dir, "gbxml_zone_space_mapping.json"), "w") as f:
    json.dump(zone_space_mapping, f, indent=4)

print(f"Generated mapping file in {gbxml_file}")
