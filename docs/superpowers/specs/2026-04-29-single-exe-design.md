# PostValidation Service — Desktop Application Design

**Date:** 2026-04-29  
**Status:** Approved  
**Target OS:** Windows 10, Windows 11  
**Audience:** End users with no developer tools installed

---

## 1. Goal

Package the existing PostValidation Service (FastAPI backend + React frontend) as a production-grade Windows desktop application that:

- Looks and behaves like a native Windows app (title bar, taskbar icon, min/max/close)
- Requires no prerequisites from the end user
- Ships in two distribution formats: **portable exe** and **NSIS installer**
- Provides a native Windows Save As dialog for file exports

---

## 2. Architecture

```
PostValidation.exe  (Electron shell)
├── Main Process (Node.js)
│   ├── Creates the BrowserWindow
│   ├── Shows splash screen while backend boots
│   ├── Spawns backend.exe as a child process on 127.0.0.1:8000
│   ├── Kills backend.exe cleanly on window close
│   └── Exposes native Save As dialog via IPC
│
├── Renderer Process
│   └── React app loaded from embedded static files (frontend/build/)
│
└── Backend Sidecar (backend.exe — PyInstaller bundle)
    └── FastAPI + uvicorn on 127.0.0.1:8000 (localhost only)
```

The backend is bound to 127.0.0.1 only — never exposed on the local network.

---

## 3. Build Pipeline

Three sequential steps, automated by a single build.py script:

```
Step 1  npm run build
        React source → frontend/build/  (static HTML/CSS/JS)

Step 2  PyInstaller --onefile main.py
        FastAPI + all Python deps → dist/backend/backend.exe

Step 3  electron-builder
        Inputs:  frontend/build/  +  dist/backend/backend.exe  +  Electron
        Outputs:
          dist/PostValidation-1.0.0-portable.exe
          dist/PostValidation-Setup-1.0.0.exe
```

---

## 4. New Files

| File | Purpose |
|---|---|
| electron/main.js | Electron entry point — window, sidecar spawn/kill, splash |
| electron/preload.js | contextBridge exposing window.electronAPI.showSaveDialog() |
| electron/splash.html | Splash screen shown while backend boots |
| electron-builder.yml | Config for portable + NSIS targets |
| build.py | Single-command build orchestrator |
| assets/icon.ico | Windows app icon |
| backend.spec | PyInstaller spec file |

---

## 5. Changes to Existing Code

### frontend/src/services/api.js
- Hardcode baseURL to http://127.0.0.1:8000/api (remove env var fallback)

### main.py — CORS
- Add file:// and http://127.0.0.1 to allowed origins

### main.py — File save path
- Export endpoints accept an absolute save_path parameter
- FastAPI writes output directly to that path

---

## 6. User Flow

1. Double-click PostValidation.exe
2. Splash screen: "PostValidation Service — Starting..."
3. Backend spawned; health-polled at /health until ready
4. Splash fades; React UI loads
5. User works normally
6. File export: native Save As dialog → file written to chosen path
7. Window close: backend.exe killed cleanly (SIGTERM → force kill after 3s)

---

## 7. Distribution Outputs

### Portable
- Single .exe, runs from anywhere (Desktop, USB, network share)
- No installation, no registry entries

### NSIS Installer
- Standard Windows wizard
- Installs to C:\Program Files\PostValidation Service\
- Start Menu + Desktop shortcut
- Registered in Apps & Features (uninstallable)

---

## 8. Error Handling

| Scenario | Behavior |
|---|---|
| Port 8000 in use | Dialog: "Port 8000 is in use. Close the conflicting app and retry." |
| Backend timeout (15s) | Splash shows error + Retry button |
| Backend crash mid-session | Dialog offering Restart or Quit |

---

## 9. Tech Stack

| Layer | Technology |
|---|---|
| Desktop shell | Electron 30+ |
| Frontend | React 18 (existing) |
| Backend | FastAPI + uvicorn (existing) |
| Python bundler | PyInstaller 6+ |
| App packager | electron-builder 24+ |
| Installer | NSIS |

---

## 10. Out of Scope

- Auto-update (can add later via electron-updater)
- Code signing / SmartScreen certificate
- macOS or Linux builds
