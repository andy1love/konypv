#!/usr/bin/env python3

'''
### v2 - Redo.
### v1 - Make sure your paths in the .txt looks like like this for DIRs:
/Volumes/SV-VFX/VFX/shottree/ANY/ANY0300/stereo/ANY0300_comp_v122_s006_left
'''

print('''\n\n\n
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
FILE COPIER v02
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
''')

import os
import shutil

def clean_path(path):
    """Clean up path from drag-and-drop: remove quotes and escaped spaces"""
    path = path.strip()
    # Remove quotes if user drags/drops (common on macOS)
    path = path.strip('"').strip("'")
    # Remove escaped spaces (backslash before space)
    path = path.replace('\\ ', ' ')
    return path

# function to copy files and directories
def copy_files(source, dest):
    if os.path.isfile(source):
        # If source is a file, copy it directly
        dest_file_path = os.path.join(dest, os.path.basename(source))
        if os.path.exists(dest_file_path):
            print(f"Skipping - Already Exists: {os.path.basename(source)}")
            return
        shutil.copy2(source, dest_file_path)
        print(f"Copied: {source}")
    elif os.path.isdir(source):
        # If source is a directory, copy recursively with progress
        total_size = 0
        for root, dirs, files in os.walk(source):
            for file in files:
                path = os.path.join(root, file)
                total_size += os.path.getsize(path)
        copied_size = 0
        for root, dirs, files in os.walk(source):
            for file in files:
                source_path = os.path.join(root, file)
                dest_path = os.path.join(dest, os.path.relpath(source_path, source))
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(source_path, dest_path)
                copied_size += os.path.getsize(source_path)
                if total_size > 0:
                    progress = round(copied_size / total_size * 100, 2)
                    print(f"{progress}% complete")
        print(f"Copied directory: {source}")
    else:
        print(f"Skipping - Path does not exist: {source}")

# Prompt user for the file path containing list of source files/directories
input_path = clean_path(input("\nDrag/Drop .txt containing list of SOURCE files/directories: \n"))

# Read the source paths from the text file
with open(input_path, 'r') as f:
    lines = f.readlines()
    source_paths = [line.strip() for line in lines if line.strip()]
    
# Prompt user for the destination path where files will be copied to
dest_path = clean_path(input("\nDrag/Drop path for the DESTINATION directory: \n"))

# copy files and directories from the source paths to the destination path
print("\nHere we go...\n")
for source_path in source_paths:
    if not os.path.exists(source_path):
        print(f"Skipping - Bad Source Path: {source_path}")
        continue
    copy_files(source_path, dest_path)

print("\n\nDone!")
