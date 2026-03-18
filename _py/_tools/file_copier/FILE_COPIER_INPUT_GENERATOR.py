#!/usr/bin/env python3

'''
FILE COPIER INPUT GENERATOR
Generates a .txt file formatted for use with FILE_COPIER scripts.
Searches recursively in a source directory for files matching filenames from a CSV.
'''

import os
import csv

def clean_path(path):
    """Clean up path from drag-and-drop: remove quotes and escaped spaces"""
    path = path.strip()
    # Remove quotes if user drags/drops (common on macOS)
    path = path.strip('"').strip("'")
    # Remove escaped spaces (backslash before space)
    path = path.replace('\\ ', ' ')
    return path

print('''\n\n\n
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
FILE COPIER INPUT GENERATOR
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
''')

# Prompt user for source directory to search recursively
source_dir = clean_path(input("\nDrag/Drop SOURCE directory to search recursively: \n"))

if not os.path.isdir(source_dir):
    print(f"Error: Source directory does not exist: {source_dir}")
    exit(1)

# Prompt user for CSV file containing filenames
csv_path = clean_path(input("\nDrag/Drop CSV file containing filenames to search for: \n"))

if not os.path.isfile(csv_path):
    print(f"Error: CSV file does not exist: {csv_path}")
    exit(1)

# Read filenames from CSV
filenames_to_find = []
try:
    with open(csv_path, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            # Add all non-empty values from the row
            filenames_to_find.extend([cell.strip() for cell in row if cell.strip()])
except Exception as e:
    print(f"Error reading CSV file: {e}")
    exit(1)

if not filenames_to_find:
    print("Error: No filenames found in CSV file")
    exit(1)

# Debug: Show first few filenames with their repr to see any hidden chars
print(f"\nDEBUG: First 3 filenames from CSV (with repr):")
for i, name in enumerate(filenames_to_find[:3]):
    print(f"  [{i}] {repr(name)}")

# Create a case-insensitive lookup dictionary (lowercase filename -> original case)
filenames_lower = {name.lower(): name for name in filenames_to_find}
filenames_lower_set = set(filenames_lower.keys())

print(f"\nSearching for {len(filenames_to_find)} filename(s): {', '.join(filenames_to_find[:5])}{'...' if len(filenames_to_find) > 5 else ''}")

# Prompt for destination directory (for output file naming)
dest_dir = clean_path(input("\nDrag/Drop DESTINATION directory (for reference/output file naming): \n"))

# Generate output filename from CSV filename
csv_dir = os.path.dirname(csv_path)
csv_basename = os.path.basename(csv_path)
csv_name_without_ext = os.path.splitext(csv_basename)[0]
output_file = os.path.join(csv_dir, f"{csv_name_without_ext}_copier_input.txt")

# Recursively search for matching files
print("\nSearching for files...\n")
found_paths = []
found_filenames = set()
files_checked = 0
sample_files_seen = []

for root, dirs, files in os.walk(source_dir):
    for file in files:
        files_checked += 1
        # Collect some sample filenames for debugging
        if files_checked <= 10:
            sample_files_seen.append((file, file.lower()))
        # Case-insensitive comparison
        if file.lower() in filenames_lower_set:
            full_path = os.path.join(root, file)
            found_paths.append(full_path)
            found_filenames.add(file.lower())
            print(f"Found: {full_path}")

# Debug output
print(f"\nDEBUG: Checked {files_checked} files total")
if sample_files_seen:
    print(f"DEBUG: Sample files seen (first 10):")
    for filename, filename_lower in sample_files_seen:
        match_status = "MATCHES!" if filename_lower in filenames_lower_set else "no match"
        print(f"  {repr(filename)} -> {repr(filename_lower)} [{match_status}]")

# Report results
print(f"\n\nSearch complete!")
print(f"Found {len(found_paths)} file(s) matching {len(found_filenames)} unique filename(s)")

missing_filenames = filenames_lower_set - found_filenames
if missing_filenames:
    print(f"\nWarning: {len(missing_filenames)} filename(s) not found:")
    for name_lower in sorted(missing_filenames):
        # Show original case from CSV
        original_name = filenames_lower.get(name_lower, name_lower)
        print(f"  - {original_name}")

# Write results to output file
if found_paths:
    with open(output_file, 'w') as f:
        for path in found_paths:
            f.write(path + '\n')
    print(f"\nOutput file created: {output_file}")
    print(f"Contains {len(found_paths)} file path(s), ready for FILE_COPIER scripts")
else:
    print("\nNo matching files found. Output file not created.")

print("\n\n...DONE...\n\n")

