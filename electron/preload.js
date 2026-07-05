const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('rockyVision', {
  captureScreen: () => ipcRenderer.invoke('capture-screen'),
});
contextBridge.exposeInMainWorld('rockyWindow', {
  setIgnoreMouseEvents: (ignore) => ipcRenderer.send('set-ignore-mouse-events', ignore),
});