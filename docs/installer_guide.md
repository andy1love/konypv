# Double-Click Installer Feature

A macOS `.command` + Windows `.bat` installer that lets a user clone your repo and configure it on a new machine by double-clicking a file — no Terminal or Git knowledge required.

---

## How It Works

1. User downloads `install.command` (Mac) or `install.bat` (Windows) and double-clicks it
2. A terminal window opens and walks them through setup interactively
3. The script checks for Git, detects available drives, asks where to install, clones the repo, creates `config.json` from your template, and opens it for final review
4. User edits any project-specific config values, saves, and closes — done

---

## Files to Create

### 1. `install.command` (macOS)

```bash
#!/bin/bash
# =============================================================================
#  YOUR PROJECT installer — macOS
#  Download this file, right-click → Open, follow the prompts.
# =============================================================================

REPO_URL="https://github.com/YOUR_ORG/YOUR_REPO.git"   # ← CHANGE THIS

echo ""
echo "================================================="
echo "  Setup"
echo "================================================="
echo ""

# --------------------------------------------------------------------------
# 1. Check for git; offer to install if missing
# --------------------------------------------------------------------------
check_git() {
    command -v git &>/dev/null
}

if ! check_git; then
    echo "Git is not installed on this Mac."
    echo ""
    while true; do
        read -rp "Install it now? (Y/N): " ans
        case "$ans" in
            [Yy])
                echo ""
                echo "Opening the macOS developer tools installer..."
                echo "A popup window will appear. Click 'Install' and wait for it to finish."
                echo ""
                xcode-select --install 2>/dev/null
                echo ""
                read -rp "Press Y when the installation is complete, or N to abort: " done_ans
                case "$done_ans" in
                    [Yy]) ;;
                    *) echo "Aborted."; read -n 1; exit 1 ;;
                esac
                if ! check_git; then
                    echo ""
                    echo "Git still not detected. Please make sure the installation"
                    echo "completed fully, then run this script again."
                    read -n 1
                    exit 1
                fi
                echo "Git installed successfully."
                break
                ;;
            [Nn])
                echo "Git is required. Aborting."
                read -n 1
                exit 1
                ;;
            *)
                echo "Please enter Y or N."
                ;;
        esac
    done
fi

echo "Git found: $(git --version)"
echo ""

# --------------------------------------------------------------------------
# 2. Detect drives (internal + external)
# --------------------------------------------------------------------------
SYSTEM_VOLUMES=("Preboot" "Recovery" "VM" "Data" "Update")

get_drives() {
    for vol in /Volumes/*/; do
        name=$(basename "$vol")
        skip=false
        for sv in "${SYSTEM_VOLUMES[@]}"; do
            [[ "$name" == "$sv" ]] && skip=true && break
        done
        [[ "$name" == com.apple.* ]] && skip=true
        [[ "$skip" == false ]] && printf '%s\n' "$name"
    done
}

DRIVES=()
while IFS= read -r line; do
    DRIVES+=("$line")
done < <(get_drives)

if [ ${#DRIVES[@]} -eq 0 ]; then
    echo "No drives detected under /Volumes/."
    read -n 1
    exit 1
fi

echo "Available drives:"
echo ""
for i in "${!DRIVES[@]}"; do
    echo "  [$((i+1))] ${DRIVES[$i]}"
done
echo ""

CHOSEN_DRIVE=""
while true; do
    read -rp "Enter the number of the drive to install onto: " choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#DRIVES[@]}" ]; then
        CHOSEN_DRIVE="${DRIVES[$((choice-1))]}"
        break
    fi
    echo "Invalid choice. Enter a number between 1 and ${#DRIVES[@]}."
done

echo ""
echo "Where on this drive should the scripts be installed?"
echo "  Options:"
echo "    Press Enter      → /Volumes/$CHOSEN_DRIVE/_scripts"
echo "    Type a name      → /Volumes/$CHOSEN_DRIVE/NAME/_scripts   (e.g. MYPROJECT)"
echo "    Type a full path → /your/custom/path/_scripts              (must start with /)"
echo ""
read -rp "Subfolder name, full path, or Enter to skip: " SUBFOLDER
SUBFOLDER=$(echo "$SUBFOLDER" | sed 's/[[:space:]]*$//')

if [[ "$SUBFOLDER" == /* ]]; then
    INSTALL_ROOT="${SUBFOLDER%/}"
elif [ -n "$SUBFOLDER" ]; then
    SUBFOLDER=$(echo "$SUBFOLDER" | tr -d '/')
    INSTALL_ROOT="/Volumes/$CHOSEN_DRIVE/$SUBFOLDER"
else
    INSTALL_ROOT="/Volumes/$CHOSEN_DRIVE"
fi
INSTALL_PATH="$INSTALL_ROOT/_scripts"

echo ""
echo "Install to: $INSTALL_PATH"
echo ""
while true; do
    read -rp "Confirm? (Y/N): " confirm
    case "$confirm" in
        [Yy]) break ;;
        [Nn]) echo "Aborted."; read -n 1; exit 0 ;;
        *) echo "Please enter Y or N." ;;
    esac
done

# --------------------------------------------------------------------------
# 3. Clone repo
# --------------------------------------------------------------------------
echo ""
if [ -d "$INSTALL_PATH/.git" ]; then
    echo "Repo already exists at $INSTALL_PATH — skipping clone."
else
    echo "Cloning repo..."
    git clone "$REPO_URL" "$INSTALL_PATH"
    if [ $? -ne 0 ]; then
        echo ""
        echo "ERROR: Clone failed. Check your internet connection and try again."
        read -n 1
        exit 1
    fi
fi

# --------------------------------------------------------------------------
# 4. Create config.json
# --------------------------------------------------------------------------
TEMPLATE="$INSTALL_PATH/_py/config.template.json"   # ← CHANGE path if needed
CONFIG="$INSTALL_PATH/_py/config.json"               # ← CHANGE path if needed

if [ -f "$CONFIG" ]; then
    echo ""
    echo "config.json already exists — skipping."
else
    cp "$TEMPLATE" "$CONFIG"
    # Replace the ROOT placeholder with the actual install root
    # ← CHANGE "/Volumes/PLACEHOLDER" to match the placeholder string in your config.template.json
    sed -i '' "s|\"ROOT\": \"/Volumes/PLACEHOLDER\"|\"ROOT\": \"$INSTALL_ROOT\"|" "$CONFIG"
    echo ""
    echo "config.json created and ROOT set to $INSTALL_ROOT"
fi

# --------------------------------------------------------------------------
# 5. Open config.json for final review
# --------------------------------------------------------------------------
echo ""
echo "-------------------------------------------------"
echo "  Almost done!"
echo ""
echo "  config.json will open in TextEdit."
echo "  Review the file, fill in any required values,"   # ← CHANGE to describe your config
echo "  then save and close."
echo "-------------------------------------------------"
echo ""
read -rp "Press Enter to open config.json..."
open -a TextEdit "$CONFIG"

echo ""
echo "================================================="
echo "  Setup complete!"
echo "  Run scripts from: $INSTALL_PATH/_py/"
echo "  For future updates, double-click git_pull.command"
echo "================================================="
echo ""
echo "Done. Press any key to close."
read -n 1
```

---

### 2. `install.bat` (Windows)

```bat
@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul

set REPO_URL=https://github.com/YOUR_ORG/YOUR_REPO.git   :: ← CHANGE THIS

echo.
echo =================================================
echo   Setup
echo =================================================
echo.

:: --------------------------------------------------------------------------
:: 1. Check for git; offer to install if missing
:: --------------------------------------------------------------------------
:CHECK_GIT
where git >nul 2>&1
if %ERRORLEVEL% EQU 0 goto GIT_OK

echo Git is not installed on this computer.
echo.
:ASK_GIT_INSTALL
set /p GIT_ANS=Install it now? (Y/N):
if /i "%GIT_ANS%"=="Y" goto INSTALL_GIT
if /i "%GIT_ANS%"=="N" goto ABORT_GIT
echo Please enter Y or N.
goto ASK_GIT_INSTALL

:INSTALL_GIT
echo.
where winget >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo Installing Git via winget. This may take a minute...
    winget install --id Git.Git -e --source winget --silent --accept-source-agreements --accept-package-agreements
    echo.
    echo Refreshing PATH...
    for /f "tokens=*" %%i in ('powershell -NoProfile -Command "[System.Environment]::GetEnvironmentVariable(\"PATH\",\"Machine\")"') do set "PATH=%%i;%PATH%"
    goto CHECK_GIT
) else (
    echo winget is not available on this machine.
    echo Opening the Git download page in your browser...
    start https://git-scm.com/download/win
    echo.
    echo Download and run the installer, then come back here.
    echo.
    :WAIT_GIT
    set /p DONE_ANS=Press Y when Git installation is complete, or N to abort:
    if /i "%DONE_ANS%"=="Y" goto CHECK_GIT
    if /i "%DONE_ANS%"=="N" goto ABORT_GIT
    echo Please enter Y or N.
    goto WAIT_GIT
)

:ABORT_GIT
echo Git is required. Aborting.
pause
exit /b 1

:GIT_OK
for /f "tokens=*" %%v in ('git --version') do echo Git found: %%v
echo.

:: --------------------------------------------------------------------------
:: 2. Detect drives
:: --------------------------------------------------------------------------
echo Detecting available drives...
echo.

set DRIVE_COUNT=0

for /f "skip=1 tokens=1,2" %%a in ('wmic logicaldisk where "drivetype=2 or drivetype=3" get deviceid^,volumename 2^>nul') do (
    set DRIVE_LETTER=%%a
    set DRIVE_LABEL=%%b
    if not "!DRIVE_LETTER!"=="" (
        set /a DRIVE_COUNT+=1
        set DRIVE_!DRIVE_COUNT!_LETTER=!DRIVE_LETTER!
        set DRIVE_!DRIVE_COUNT!_LABEL=!DRIVE_LABEL!
        echo   [!DRIVE_COUNT!] !DRIVE_LETTER! !DRIVE_LABEL!
    )
)

if %DRIVE_COUNT% EQU 0 (
    echo No drives detected.
    pause
    exit /b 1
)

echo.
:PICK_DRIVE
set /p DRIVE_CHOICE=Enter the number of the drive to install onto:
if "%DRIVE_CHOICE%"=="" goto PICK_DRIVE
if %DRIVE_CHOICE% LSS 1 goto PICK_DRIVE
if %DRIVE_CHOICE% GTR %DRIVE_COUNT% goto PICK_DRIVE

set CHOSEN_LETTER=!DRIVE_%DRIVE_CHOICE%_LETTER!

echo.
echo Where on this drive should the scripts be installed?
echo   Options:
echo     Press Enter      -^> %CHOSEN_LETTER%\_scripts
echo     Type a name      -^> %CHOSEN_LETTER%\NAME\_scripts   (e.g. MYPROJECT)
echo     Type a full path -^> C:\your\custom\path\_scripts    (must start with a drive letter)
echo.
set /p SUBFOLDER=Subfolder name, full path, or Enter to skip:

set IS_ABS=0
if not "!SUBFOLDER!"=="" (
    set SECOND_CHAR=!SUBFOLDER:~1,1!
    if "!SECOND_CHAR!"==":" set IS_ABS=1
)

if "!SUBFOLDER!"=="" (
    set INSTALL_ROOT=%CHOSEN_LETTER%
) else if !IS_ABS!==1 (
    set INSTALL_ROOT=!SUBFOLDER!
) else (
    set INSTALL_ROOT=%CHOSEN_LETTER%\!SUBFOLDER!
)
set INSTALL_PATH=!INSTALL_ROOT!\_scripts

echo.
echo Install to: !INSTALL_PATH!
echo.
:CONFIRM_DRIVE
set /p CONFIRM=Confirm? (Y/N):
if /i "%CONFIRM%"=="Y" goto DO_INSTALL
if /i "%CONFIRM%"=="N" goto ABORT_INSTALL
echo Please enter Y or N.
goto CONFIRM_DRIVE

:ABORT_INSTALL
echo Aborted.
pause
exit /b 0

:: --------------------------------------------------------------------------
:: 3. Clone repo
:: --------------------------------------------------------------------------
:DO_INSTALL
echo.
if exist "!INSTALL_PATH!\.git" (
    echo Repo already exists at !INSTALL_PATH! -- skipping clone.
) else (
    echo Cloning repo...
    git clone %REPO_URL% "!INSTALL_PATH!"
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo ERROR: Clone failed. Check your internet connection and try again.
        pause
        exit /b 1
    )
)

:: --------------------------------------------------------------------------
:: 4. Create config.json
:: --------------------------------------------------------------------------
set TEMPLATE=!INSTALL_PATH!\_py\config.template.json   :: ← CHANGE path if needed
set CONFIG=!INSTALL_PATH!\_py\config.json               :: ← CHANGE path if needed

if exist "!CONFIG!" (
    echo.
    echo config.json already exists -- skipping.
) else (
    copy "!TEMPLATE!" "!CONFIG!" >nul
    :: Replace ROOT placeholder — forward slashes for Python pathlib compatibility
    :: ← CHANGE "/Volumes/PLACEHOLDER" to match the placeholder string in your config.template.json
    set ROOT_FWD=!INSTALL_ROOT:\=/!
    powershell -NoProfile -Command "(Get-Content '!CONFIG!') -replace '\"ROOT\": \"/Volumes/PLACEHOLDER\"', '\"ROOT\": \"!ROOT_FWD!\"' | Set-Content '!CONFIG!'"
    echo.
    echo config.json created and ROOT set to !INSTALL_ROOT!
)

:: --------------------------------------------------------------------------
:: 5. Open config.json for final review
:: --------------------------------------------------------------------------
echo.
echo -------------------------------------------------
echo   Almost done!
echo.
echo   config.json will open in Notepad.
echo   Review the file, fill in any required values,  :: ← CHANGE to describe your config
echo   then save and close.
echo -------------------------------------------------
echo.
pause
notepad "!CONFIG!"

echo.
echo =================================================
echo   Setup complete!
echo   Run scripts from: !INSTALL_PATH!\_py\
echo   For future updates, double-click git_pull.command
echo =================================================
echo.
pause
```

---

### 3. Make `install.command` Executable

Run this once after creating the file:

```bash
chmod +x install.command
```

Without this, macOS will refuse to run it.

---

### 4. `config.template.json` Requirement

Your repo must have a `config.template.json` that the installer can copy and patch. The ROOT key must contain a known placeholder string — this is what the installer's `sed` (Mac) and `powershell` (Windows) commands search for and replace with the actual install path.

Example:
```json
{
  "ROOT": "/Volumes/PLACEHOLDER"
}
```

> The placeholder string `"/Volumes/PLACEHOLDER"` must match exactly what the scripts search for. Change it in both the template and the installer scripts if you use something different.

Commit `config.template.json`. Add `config.json` to `.gitignore`.

---

### 5. `how_to_run_installer.md` (user-facing, include in your repo)

```markdown
# How to Run the Installer

## What you need before starting

- Internet connection

---

## Mac

1. Download **`install.command`**
2. Right-click it → click **Open** (you must right-click the first time — double-clicking will be blocked)
3. A black Terminal window will open — follow the prompts
4. When asked, type the **number** next to your drive and press Enter
5. Choose where to install:
   - Press **Enter** to install at the drive root
   - Type a **folder name** (e.g. `MYPROJECT`) to install inside that folder
   - Type a **full path** starting with `/` to install anywhere on the Mac
6. `config.json` will open at the end — fill in any required values, then save and close

That's it. You're done.

---

## Windows

1. Download **`install.bat`**
2. Double-click it
3. A black Command Prompt window will open — follow the prompts
4. When asked, type the **number** next to your drive and press Enter
5. Choose where to install:
   - Press **Enter** to install at the drive root
   - Type a **folder name** (e.g. `MYPROJECT`) to install inside that folder
   - Type a **full path** starting with a drive letter (e.g. `C:\Users\you\projects`) to install anywhere
6. `config.json` will open at the end — fill in any required values, then save and close

That's it. You're done.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| "cannot be opened because it is from an unidentified developer" | Right-click the file → Open |
| "Git is not installed" | The installer will handle this — just follow the Y/N prompts |
| "No drives detected" | Restart the installer; if it persists, screenshot and ask for help |
| Any other error | Screenshot the terminal window and ask for help |
```

---

## Customization Checklist

| What to change | Where |
|---|---|
| `REPO_URL` | Top of both installer scripts |
| Config file path (`_py/config.template.json`) | Step 4 of both scripts |
| ROOT placeholder string (`/Volumes/PLACEHOLDER`) | `config.template.json` + step 4 of both scripts |
| "Almost done" instructions | Step 5 of both scripts |
| Default branch (if not `main`) | `git_pull.command` |

---

## Key Constraints

- `install.command` is macOS only; `.command` files open in Terminal.app automatically
- `install.bat` is Windows only; `.bat` files run in Command Prompt
- The ROOT placeholder in `config.template.json` must be a unique string — `sed` does a literal find-and-replace, so make sure it won't accidentally match anything else in the file
- macOS Gatekeeper will block the first run of `install.command` if double-clicked — users must right-click → Open the first time; subsequent double-clicks work normally
- The installer skips the clone step if a `.git` folder already exists at the target path, making it safe to re-run
