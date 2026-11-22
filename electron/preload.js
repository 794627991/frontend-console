'use strict';
// 壳形态前端桥（P2）：win-controls.js 壳分支经此走 IPC（contextBridge 受控
// 面，页面拿不到完整 ipcRenderer）。旧 pywebview 形态下本文件不加载
//（页面无 fcShell，win-controls 自动走旧链）
//
// ⚠ P3 网页 tab：外站内容的 WebContentsView **绝不能配本 preload**——
// pywebview 兼容层会给任意页面文件对话框能力（本机单用户信任模型只覆盖
// 自家 UI）
const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('fcShell', {
  isShell: true,
  // 'min' | 'max'（toggle 语义，终态经 onState 推回）| 'close'（托盘语义）
  winCtl: (act) => ipcRenderer.send('fc:win-ctl', act),
  // 立即取一次窗态 {max:boolean}
  getState: () => ipcRenderer.invoke('fc:win-state-get'),
  // 订阅窗态推送（maximize/unmaximize 事件 → {max:boolean}）
  onState: (cb) => ipcRenderer.on('fc:win-state', (_e, st) => cb(st)),
  // 打开 DevTools（后端日志窗「原 F12」按钮的壳形态通道，独立窗）
  openDevtools: () => ipcRenderer.send('fc:devtools'),
  // 拖放文件的绝对路径（Electron 32 起 File.path 移除，webUtils 是唯一正道）
  pathForFile: (f) => webUtils.getPathForFile(f),
  // 文件关联双击（--open-file）：壳解析 argv 后推给前端智能分发
  onOpenFile: (cb) => ipcRenderer.on('fc:open-file', (_e, p) => cb(p)),
  // 截图覆盖窗（P4）：主窗收到后端 SSE snip_open / 📷 按钮后打开
  openSnip: () => ipcRenderer.invoke('fc:snip-open'),
  // 截图页 ↔ 壳握手：hello=listener 就绪（此后 arm 可达）；ready=底图已
  // 画完（壳此刻才 show，杜绝黑屏）；arm=壳下发底图裁剪偏移 {x,y}
  snipHello: () => ipcRenderer.send('fc:snip-hello'),
  snipReady: () => ipcRenderer.send('fc:snip-ready'),
  // 底图取失败：绝不 reveal 纯黑覆盖层（黑层一旦上屏，下次抓屏抓到的
  // 就是它自己 → 黑屏死循环，用户实锤）。通知壳立即隐藏本窗
  snipFail: (reason) => ipcRenderer.send('fc:snip-fail', reason),
  onSnipArm: (cb) => ipcRenderer.on('fc:snip-arm', (_e, d) => cb(d)),
  // 覆盖窗自身句柄（十进制字符串数组）——窗口识别探测时排除自己
  snipHwnds: () => ipcRenderer.invoke('fc:snip-hwnds'),
  // guest（webview）里 window.open/target=_blank 的路由落点：主进程按
  // webContents 类型 deny 后推送过来（元素级 handler 在 webview 上不存在）
  onWebTabOpen: (cb) => ipcRenderer.on('fc:webtab-open', (_e, url) => cb(url)),
  // 密码保存/填充：存储由主进程 safeStorage 完成；保存提示只含 origin/user，
  // 候选弹层只含用户名，选中后才下发密码。
  onPwSavePrompt: (cb) => ipcRenderer.on('fc:pw-save-prompt', (_e, info) => cb(info)),
  pwSave: (id) => ipcRenderer.invoke('fc-pw:save', id),
  pwDiscard: (id) => ipcRenderer.invoke('fc-pw:discard', id),
  // 选择式填充：点登录框 → 主进程推候选（无密码）→
  // 用户选中后 pwFill 才把密码下发到 guest preload。
  onPwSuggest: (cb) => ipcRenderer.on('fc:pw-suggest', (_e, info) => cb(info)),
  onPwSuggestHide: (cb) => ipcRenderer.on('fc:pw-suggest-hide', (_e, info) => cb(info)),
  pwFill: (id, index) => ipcRenderer.invoke('fc-pw:fill', id, index),
  pwSuggestClose: (id) => ipcRenderer.invoke('fc-pw:suggest-close', id),
  // 🔑 站点菜单：当前页已存密码的列表/显示/删除/填充
  pwSiteList: (origin) => ipcRenderer.invoke('fc-pw:site-list', origin),
  pwSiteReveal: (origin, user) => ipcRenderer.invoke('fc-pw:site-reveal', { origin, user }),
  pwSiteDelete: (origin, user) => ipcRenderer.invoke('fc-pw:site-delete', { origin, user }),
  pwSiteFill: (body) => ipcRenderer.invoke('fc-pw:site-fill', body || {}),
});

// pywebview js_api 兼容层（壳形态）：既有调用点（打开/对比/计算器/文件树
// 选目录/日志选择）零改动。签名对齐 main.py FileBridge
contextBridge.exposeInMainWorld('pywebview', {
  api: {
    pick_any: () => ipcRenderer.invoke('fc:pick', {})
      .then((a) => (a && a[0]) || ''),
    pick_log: () => ipcRenderer.invoke('fc:pick', {
      filters: [{ name: 'Log Files', extensions: ['log', 'txt', 'out'] }],
    }).then((a) => (a && a[0]) || ''),
    pick_two: () => ipcRenderer.invoke('fc:pick', { multi: true }),
    pick_dir: () => ipcRenderer.invoke('fc:pick-dir'),
    // Win32 原生剪贴板读取的等价物（search.js 粘贴链；Electron 无权限弹窗问题）
    read_clipboard: () => ipcRenderer.invoke('fc:clipboard-read'),
    // 图片文件写系统剪贴板（拖图进 claude 终端链，等价 CF_DIB）
    copy_image_to_clipboard: (p) => ipcRenderer.invoke('fc:clipboard-write-image', p),
    // 首次关闭提示的「知道了」——壳托盘语义下无此流程，空实现保调用不炸
    tray_confirm_hide: () => {},
    // 截图覆盖窗的 pywebview js_api 等价面（screenshot.html 零改动消费）
    snip_done: (b64) => ipcRenderer.invoke('fc:snip-done', b64),
    snip_save_as: (dataUrl) => ipcRenderer.invoke('fc:snip-save-as', dataUrl),
    snip_cancel: () => ipcRenderer.invoke('fc:snip-cancel'),
  },
});
