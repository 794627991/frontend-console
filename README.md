# 前端控制台 v1.1.0

面向嵌入式 BSP/驱动调试的串口 & SSH 终端 + 日志/文件工具。pywebview + Flask，单 exe 无依赖，Windows 原生窗口。

## 启动

- **桌面快捷方式**（推荐）：双击「前端控制台」
- **源码运行**：双击 `run.bat`（= `pythonw src\main.py`）
- **打包 exe**：`python src\build.py` → `dist\前端控制台.exe`

单实例：二次启动自动聚焦已有窗口。

## 核心功能

| 功能 | 说明 |
|------|------|
| 多串口/SSH | 同时多连接，每连接独立 tab/缓冲/日志；ANSI 全彩、全屏应用（menuconfig 等）检测 |
| 命令库 | 常用命令保存复用，跨端口持久（`cmdlib.json`，跟工具目录走） |
| TFTP/HFS 文件传输 | TFTP(RFC1350) + HTTP 下载双服务，同目录一个开关，端口 8081 可配；传输记录含来源标签 |
| 日志查看器 | G 级日志秒开：行偏移索引 + 虚拟列表；搜索/跳转/过滤，缩放模式翻阅 |
| 日志对比 | 正常 vs 异常启动日志 diff（行级/摘要两模式），BSP 定位利器 |
| 文本编辑器 | Monaco，C/JSON 大纲树（嵌套折叠）、语法高亮；<20M 编辑，>30M 自动阅读器 |
| Hex 查看器 | bin/未知文件 16 进制查看/编辑：字节选区、多类型数据检视（Int/Float/LEB128…）、大小端、HxD 式查看方式（hex/十进制 × 8/16/32/64 位分组）、搜索、Intel HEX 解析回写 |
| 文件对比 | Monaco DiffEditor 双栏 diff（VSCode 同款内核，零新增引擎）：顶栏「🔀 对比」选两份；并排/内联、折行、F7 上一处/下一处差异、折叠未变化区域、A/B 互换、差异行数统计；MCP `compare_files` 可让 AI 直接拉起对比 tab |
| 回放 | 终端输出录制/回放，时序重现 |
| Claude Code 集成 | **MCP server 内置于工具**：Claude Code 可直接 observe/send_command/read_log 等操作串口与日志（无需任何 AI 配置在工具内，AI 能力完全由外部 Claude Code 通过 MCP 提供）；另有命令行桥 `serial_cli.py`（见 docs/MCP_INTEGRATION.md） |

## 目录结构

```
├── web/                前端（index.html + style.css + js/，原生 JS 无框架）
├── src/                全部 Python 源码（入口 main.py，后端 server.py）
├── ico/                应用图标
├── vendor/             第三方库本地托管（Monaco/tree-sitter，离线可用）
├── docs/               开发文档（MCP 集成/调研/审计报告）
├── files/              用户笔记（运行时生成，不入库）
├── cmdlib.json         命令库（用户数据，不入库）
└── run.bat             源码启动
```

## 数据目录

`~/.serialconsole_pro/`：endpoint.json（服务发现）、config.json（配置）。串口日志默认也在此的 `logs/`，但可配置到任意目录（日志库界面可改，当前配置指向工具目录 `serial_logs/`，便于随工具备份）。

## Claude Code 直连（MCP）

工具**内置 MCP server**，两种形态都支持，无需在工具里配置任何 AI：

- **源码运行**：Claude Code 配置 `{"mcpServers": {"serial-console-pro": {"command": "python", "args": ["D:\\AI\\串口控制台Pro\\src\\mcp_server.py"]}}}`
- **exe 分发**（其他用户无需装 Python）：`{"mcpServers": {"serial-console-pro": {"command": "C:\\path\\to\\前端控制台.exe", "args": ["--mcp"]}}}`

工具没开时 MCP 会自动拉起工具。也可用命令行桥 `python src\serial_cli.py`。详见 `docs/MCP_INTEGRATION.md`。
