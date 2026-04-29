const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  onBackendCrash: (callback) =>
    ipcRenderer.on('backend-crash', (_event, message) => callback(message)),
});
