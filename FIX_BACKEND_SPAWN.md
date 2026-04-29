# Backend Spawn ENOENT Error - Fix Documentation

## Issue
The PostValidation Service desktop application failed to start with the following error:
```
Could not start backend: spawn
C:\Users\VENKAT~1\AppData\Local\Temp\3D1OQRq27iPexDG7uNG4x1xg\backend.exe
ENOENT
```

## Root Cause
The `backend.exe` executable was not being properly unpacked during application installation. Instead, it remained packed inside the `app.asar` archive and was only extracted to a temporary directory at runtime, causing the file path to be inaccessible or deleted before Electron could spawn it.

## Solution
Added `backend/` to the `asarUnpack` array in `electron-builder.yml`. This configuration tells electron-builder to extract the backend directory from the app archive to a stable location on disk during installation, rather than keeping it packed.

### Change Made
**File:** `electron-builder.yml`

```yaml
asarUnpack:
  - assets/icon.ico
  - backend/    # <- Added this line
```

## How It Works

### Before (Broken)
1. Electron-builder packs backend/ into app.asar
2. At runtime, Electron temporarily extracts backend.exe to a temp directory
3. Temp file is deleted or becomes inaccessible
4. Main process tries to spawn backend.exe → ENOENT error

### After (Fixed)
1. Electron-builder unpacks backend/ to `resources/backend/` during installation
2. `electron/main.js` references `process.resourcesPath/backend/backend.exe`
3. Backend executable is always available at a stable path
4. Main process successfully spawns backend.exe

## Verification

✅ **backend.exe exists:** `dist/backend/backend.exe` (25 MB)
✅ **Configuration updated:** `electron-builder.yml` includes `backend/` in asarUnpack
✅ **Electron main process:** Correctly references `process.resourcesPath/backend/backend.exe`
✅ **Git committed:** Fix committed with detailed message

## Testing After Rebuild

After running `python build.py`, test the fix:
1. Run the built installer or portable executable
2. Application should start without backend spawn errors
3. Backend service should be accessible at `http://127.0.0.1:8000/health`

## Related Files
- `electron/main.js` - Spawns backend process
- `electron-builder.yml` - Packaging configuration
- `dist/backend/backend.exe` - PyInstaller bundled backend
- `backend_launcher.py` - Backend entry point
