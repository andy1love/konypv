# Dependencies

## Required

### Python 3
Used to run all scripts in `_py/`.

**Check if installed:**
```bash
python3 --version
```

**Install:** Download from [python.org](https://www.python.org/downloads/) or via Homebrew:
```bash
brew install python
```

---

### ffmpeg
Required by `proxy_maker.py` to encode proxy video files.

**Check if installed:**
```bash
ffmpeg -version
```

**Install via Homebrew (recommended):**
```bash
brew install ffmpeg
```

**Install via direct download:** [ffmpeg.org/download.html](https://ffmpeg.org/download.html)

---

### Git
Required to clone the repo and pull updates via `git_pull.command`.

**Check if installed:**
```bash
git --version
```

**Install:** Run `xcode-select --install` in Terminal (macOS). The installer script handles this automatically.

---

## Optional

### DaVinci Resolve + Scripting API
Required only for `auto_import_media_to_res.py` (auto-import media into Resolve).

- Install DaVinci Resolve from [blackmagicdesign.com](https://www.blackmagicdesign.com/products/davinciresolve)
- The Scripting API is included with Resolve — no separate download needed
- Set the correct API paths in `config.json` under `resolve_api_paths`

Default paths (macOS):
```
/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules
/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/ExternalControl/Scripts
```
