#!/bin/bash
# Run once after first clone to apply Finder color tags to all scripts.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

python3 -c "
import plistlib, subprocess, os

SCRIPT_DIR = '$SCRIPT_DIR'

FILE_TAGS = {
    'proxy_maker.py':       ('Blue',   4),
    'proxy_packager.py':    ('Purple', 3),
    'sync_pools.py':        ('Yellow', 5),
    'wipe_sdcard.py':       ('Red',    6),
    'workflow_launcher.py': ('Green',  2),
}

def tag(path, name, idx):
    data = plistlib.dumps([f'{name}\n{idx}'], fmt=plistlib.FMT_BINARY)
    subprocess.run(
        ['xattr', '-wx', 'com.apple.metadata:_kMDItemUserTags', data.hex(), path],
        check=True
    )
    print(f'  tagged {os.path.basename(path)} -> {name}')

PY_DIR = os.path.dirname(SCRIPT_DIR)  # one level up: _scripts/_py/

tagged_any = False
for base, (name, idx) in FILE_TAGS.items():
    full = os.path.join(PY_DIR, base)
    if os.path.exists(full):
        tag(full, name, idx)
        tagged_any = True
    else:
        print(f'  skipped {base} (not found)')

if tagged_any:
    tag(PY_DIR, 'Green', 2)
"

echo ""
echo "Done. Press any key to close."
read -n 1
