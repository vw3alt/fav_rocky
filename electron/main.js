const { app, BrowserWindow, screen, desktopCapturer, ipcMain } = require('electron');
const path = require('path');

let win;

function createWindow() {
  const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().workAreaSize;
  const winWidth = 212;
  const winHeight = 176;

  win = new BrowserWindow({
    width: winWidth,
    height: winHeight,
    x: screenWidth - winWidth - 40,
    y: screenHeight - winHeight - 40,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    hasShadow: false,
    icon: path.join(__dirname, 'sprites', 'rest_bg.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.setAlwaysOnTop(true, 'floating');
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.loadFile('index.html');

  // win.webContents.openDevTools({ mode: 'detach' });
}

ipcMain.handle('capture-screen', async () => {
  const sources = await desktopCapturer.getSources({
    types: ['screen'],
    thumbnailSize: { width: 1280, height: 720 },
  });
  return sources[0].thumbnail.toPNG().toString('base64');
});

ipcMain.on('set-ignore-mouse-events', (event, ignore) => {
  win.setIgnoreMouseEvents(ignore, { forward: true });
});

app.whenReady().then(() => {
  if (process.platform === 'darwin' && app.dock) {
    app.dock.setIcon(path.join(__dirname, 'sprites', 'rest_bg.png'));
  }
  createWindow();
});

app.on('window-all-closed', () => {
  // Rocky is a single-purpose widget, not a normal multi-window Mac app —
  // always quit fully when the window closes (rather than staying alive
  // in the dock, which is the usual Mac convention). This matters so the
  // launcher script can detect Rocky has exited and clean up the brain
  // server process behind it.
  app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});