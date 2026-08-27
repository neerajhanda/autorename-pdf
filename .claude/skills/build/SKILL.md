---
name: build
description: Build the EXE and distribution package. Use when the user wants to create a release build.
user-invocable: true
allowed-tools:
  - Bash
  - Read
  - Glob
---

# Build Distribution Package

Build the PyInstaller EXE and create the distribution ZIP.

## Steps

1. Activate the venv:

```bash
source venv/Scripts/activate
```

2. Ensure dependencies are installed. PyInstaller lives in `requirements-dev.txt`,
   not `requirements.txt` — installing only the latter fails the prerequisite check:

```bash
pip install -r requirements-dev.txt
```

3. Run the build script:

```bash
python build.py            # CLI + GUI + ZIP, signed
python build.py --nosign   # same, unsigned (no Azure Trusted Signing setup needed)
python build.py --cli-only # CLI EXE only, skips GUI + packaging
```

4. Verify the output:
   - Check `Releases/AutoRename-PDF-Portable-{version}.zip` exists, where `{version}`
     comes from `gui/package.json`. The ZIP is versioned, not dated.
   - Do NOT look for `dist/autorename-pdf.exe` — the final `cleanup()` step deletes
     `dist/` and `build/`. It only exists mid-build.
   - Report the file size.

5. If build fails:
   - Check for import errors or missing modules
   - Verify PyInstaller is installed
   - Check `build.py` for hardcoded paths that may need updating

## Notes

- Signing does **not** skip gracefully. If the Azure Trusted Signing DLib or
  `metadata.json` is missing, `sign_file()` hard-exits with code 1. Use `--nosign`
  when no signing setup is available.
- The ZIP is flat and contains: `autorename-pdf-gui.exe`, `autorename-pdf-cli.exe`,
  `setup.ps1`, `config.yaml.example`, `harmonized-company-names.yaml.example`, `.env.example`
- Do NOT include config.yaml (contains API keys) in any build output

## Prerequisites

A full build needs all of these on Windows — `check_prerequisites()` fails fast if any are missing:

| Tool | Needed for | Skipped by `--cli-only`? |
|------|-----------|--------------------------|
| PyInstaller | CLI EXE | No |
| pnpm + Node | Tauri frontend | Yes |
| Rust + MSVC toolchain | Tauri GUI compile | Yes |
| signtool + Azure CodeSigning DLib | Signing | No (use `--nosign`) |
