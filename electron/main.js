'use strict';

const { app, BrowserWindow, dialog, session } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const http = require('http');

const isDev = !app.isPackaged;
let mainWindow = null;
let splashWindow = null;
let backendProcess = null;
let isQuitting = false;

function backendExePath() {
  return isDev
    ? path.join(__dirname, '..', 'dist', 'backend', 'backend.exe')
    : path.join(process.resourcesPath, 'app.asar.unpacked', 'backend', 'backend.exe');
}

function frontendIndexPath() {
  return path.join(app.getAppPath(), 'frontend', 'build', 'index.html');
}

function iconPath() {
  return isDev
    ? path.join(__dirname, '..', 'assets', 'icon.ico')
    : path.join(process.resourcesPath, 'icon.ico');
}

function spawnBackend() {
  const exePath = backendExePath();
  const exeDir = path.dirname(exePath);
  const dataDir = path.join(app.getPath('appData'), 'PostValidation');

  let logStream = null;
  try {
    fs.mkdirSync(dataDir, { recursive: true });
    logStream = fs.createWriteStream(
      path.join(dataDir, 'backend.log'),
      { flags: 'a' }
    );
    logStream.on('error', (err) => {
      console.error(`[main] backend log write error: ${err.message}`);
    });
    logStream.write(`\n--- PostValidation backend started ${new Date().toISOString()} ---\n`);
  } catch (err) {
    console.error(`[main] Could not open backend log: ${err.message}`);
  }

  backendProcess = spawn(exePath, [], {
    windowsHide: true,
    cwd: exeDir,
    stdio: logStream ? ['ignore', 'pipe', 'pipe'] : 'ignore',
    env: { ...process.env, POSTVALIDATION_DATA_DIR: dataDir },
  });

  if (logStream) {
    backendProcess.stdout.pipe(logStream, { end: false });
    backendProcess.stderr.pipe(logStream, { end: false });
    backendProcess.on('close', () => logStream.end());
  }

  backendProcess.on('error', (err) => {
    if (!isQuitting) showCrashDialog(`Could not start backend: ${err.message}\nPath: ${exePath}`);
  });

  backendProcess.on('exit', (code) => {
    if (!isQuitting && code !== 0) showCrashDialog(`Backend exited (code ${code}).`);
  });
}

function killBackend() {
  if (!backendProcess) return;
  backendProcess.kill('SIGTERM');
  setTimeout(() => {
    if (backendProcess && !backendProcess.killed) backendProcess.kill('SIGKILL');
  }, 3000);
  backendProcess = null;
}

function showCrashDialog(detail) {
  dialog.showMessageBox({
    type: 'error',
    title: 'PostValidation Service',
    message: 'The backend service stopped unexpectedly.',
    detail,
    buttons: ['Restart App', 'Quit'],
  }).then(({ response }) => {
    if (response === 0) { app.relaunch(); app.quit(); }
    else app.quit();
  });
}

function waitForBackend(timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    function attempt() {
      const req = http.get('http://127.0.0.1:8000/health', (res) => {
        if (res.statusCode === 200) resolve(); else retry();
      });
      req.on('error', retry);
      req.setTimeout(500, () => { req.destroy(); retry(); });
    }
    function retry() {
      if (Date.now() >= deadline) reject(new Error('Backend did not respond within 15 s.'));
      else setTimeout(attempt, 500);
    }
    attempt();
  });
}

function isPortInUse() {
  return new Promise((resolve) => {
    const req = http.get('http://127.0.0.1:8000/health', () => resolve(true));
    req.on('error', () => resolve(false));
    req.setTimeout(1000, () => { req.destroy(); resolve(false); });
  });
}

function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 480, height: 280,
    frame: false, resizable: false, center: true,
    icon: iconPath(),
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  splashWindow.loadFile(path.join(__dirname, 'splash.html'));
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280, height: 800,
    minWidth: 900, minHeight: 600,
    show: false,
    title: 'PostValidation Service',
    icon: iconPath(),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      webSecurity: true,
    },
  });
  mainWindow.loadFile(frontendIndexPath());
  mainWindow.once('ready-to-show', () => {
    if (splashWindow && !splashWindow.isDestroyed()) { splashWindow.close(); splashWindow = null; }
    mainWindow.show();
    mainWindow.maximize();
  });
  mainWindow.on('closed', () => { mainWindow = null; });
}

function registerDownloadHandler() {
  session.defaultSession.on('will-download', (_event, item) => {
    item.once('done', (_e, state) => {
      if (state !== 'completed')
        dialog.showErrorBox('Download Failed', 'The file could not be saved.');
    });
  });
}

app.whenReady().then(async () => {
  registerDownloadHandler();
  createSplashWindow();

  const portBusy = await isPortInUse();
  if (portBusy) {
    if (splashWindow) splashWindow.close();
    dialog.showErrorBox('Port Already In Use',
      'Port 8000 is already in use.\n\nClose the conflicting app and try again.');
    app.quit();
    return;
  }

  spawnBackend();

  try {
    await waitForBackend(15000);
    createMainWindow();
  } catch (err) {
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
    dialog.showErrorBox('Startup Failed',
      `Backend did not start.\n\n${err.message}`);
    app.quit();
  }
});

app.on('before-quit', () => { isQuitting = true; killBackend(); });
app.on('window-all-closed', () => { isQuitting = true; killBackend(); app.quit(); });
