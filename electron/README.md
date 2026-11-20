# Electron 壳（P1 打包 + P2 窗控/托盘 + P3 网页 tab）

方案：`docs/electron迁移方案_2026-11-20.md`。本目录是 Electron 壳，
拉起 Python 后端（`src/main.py --headless`）并承载 web UI。
当前形态：P0 服务链、P1 electron-builder/NSIS 安装包、P2 无边框窗控与托盘、
P3 网页 tab + 内置密码选择式填充。旧 pywebview 形态仍由根目录 `run.bat` 启动。

## 开发跑法

```bash
cd electron
npm install        # 首次（Electron ≈100MB，下载慢可设 ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/）
npm start          # 壳拉起 python src/main.py --headless 并开窗
```

环境变量（均可省略）：

| 变量 | 作用 |
|---|---|
| `FC_PYTHON` | 指定 Python 解释器真身路径（默认自动绕开 WindowsApps 商店 shim 取 PATH 里第一个真身） |
| `FC_BACKEND_CMD` | 完整覆盖后端命令，JSON 数组，如 `["python","src/main.py","--headless"]` |
| `FC_ENDPOINT_FILE` | endpoint.json 路径覆盖（壳与后端同读；默认 `~/.serialconsole_pro/endpoint.json`） |

## 从远端拉取后直接用（公司环境）

```bat
git pull
run_shell.bat
```

- `electron/node_modules/` **不入库**（`electron/.gitignore` 已排除）。首次运行
  脚本自动 `npm install`，若 Electron 本体没下全再补跑
  `node node_modules\electron\install.js`。
- 需要 **Node.js 22.12+ / npm**（`electron@45.4.1` 的 engines 硬要求；低版本
  `npm install` 会被引擎校验拦住）；后端 Python 依赖沿用 `run.bat` 的环境。
- 公司网络访问不了 npm/Electron 镜像时：用 `打包壳.bat` 产出的安装包（后端
  exe + 壳已内置），或提前带 npm 缓存；源码 clone 本身不含 `node_modules`。
- 密码存储走 `safeStorage`/DPAPI，绑定 Windows 用户与机器；换机器后首次登录
  需重新保存一次。
- SSO 相关验收事项见 `docs/待办_SSO密码填充_公司验收_2026-11-20.md`。

## 行为要点（与方案对照的实测结论）

- **就绪判据**：spawn 前删 endpoint.json → 轮询读文件，`boot_ms` 晚于
  spawn 时刻 + `/api/status` 200 才开窗。不校验 pid 相等——PATH 前置
  WindowsApps 商店 shim 时壳的 child 是转发层、真后端是孙进程，pid 必然
  错位（实测实锤）
- **退出矩阵**：
  - 关窗 → `window-all-closed` → `will-quit` → taskkill /T /F 树杀
  - 壳被强杀 → 后端 `FC_SHELL_PID` 探活（main.py headless 分支）2s 内
    自杀，Job Object 内核级收割 worker——双向零残留已实测
  - 后端死 → 壳弹错框退出
- **弹框全部走异步 `dialog.showMessageBox`**：`showErrorBox` 是原生模态、
  阻塞主进程直到用户点掉（实测会卡住后续退出）
- **后端 stdout 收不到东西是正常的**：backend_log 在进程内截走进内存
  环形缓冲（诊断面板可见）；壳自身日志落 `~/.serialconsole_pro/electron-shell.log`

## P1（打包）布局约定

`resolveBackend()` 打包形态约定后端 exe 放 `resources/backend/`，
electron-builder extraResources 配置随 P1 定。
