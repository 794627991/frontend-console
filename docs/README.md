# 文档索引

| 文档 | 说明 |
|------|------|
| [MCP_INTEGRATION.md](MCP_INTEGRATION.md) | Claude Code MCP 集成：stdio server 桥接后端、工具清单、配置方法 |
| [同类工具调研报告.md](同类工具调研报告.md) | 开源串口/SSH 终端与日志工具横向对比（Tabby/electerm/PuTTY 等） |
| [性能优化审计报告.md](性能优化审计报告.md) | 前端渲染与串口读路径的对抗性性能审计记录 |

## 项目结构（前端控制台 v1.1.0）

```
├── web/                             前端（index.html + style.css + js/，原生 JS 无框架）
├── vendor/                          第三方库本地托管（Monaco/tree-sitter 等）
├── src/                             全部 Python 源码
│   ├── main.py                      桌面应用入口（pywebview + Flask）
│   ├── server.py                    HTTP 后端（多串口/SSH + AI 接入层）
│   ├── mcp_server.py                MCP stdio server（Claude Code 集成）
│   ├── serial_cli.py                命令行直连桥（buf/send/watch）
│   ├── build.py                     PyInstaller 打包脚本
│   ├── app_state.py                 共享状态 + 路径常量
│   ├── base_conn.py / serial_conn.py / ssh_conn.py   连接层
│   ├── log_index.py                 G 级日志行偏移索引
│   ├── tftp.py / httpfile.py        TFTP/HFS 文件传输
│   ├── editor_files.py / hex_files.py                编辑器/hex 查看器后端
│   └── ansi_utils.py                ANSI 处理 + 行分类
├── ico/                             应用图标
├── docs/                            文档（本目录）
├── run.bat                          源码启动（pythonw src\main.py）
└── 前端控制台.spec                   PyInstaller 打包配置
```
