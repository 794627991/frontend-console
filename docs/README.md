# 文档索引

面向使用者的完整说明书在仓库根 **`README.md`**（设置 → 帮助 里打开的就是它），本目录只放开发者/技术类文档。

| 文档 | 说明 |
|------|------|
| [SSO认证与连接机制.md](SSO认证与连接机制.md) | SSO 两条链路（Lanz CAS / HikLink PC）源码级说明、加密细节、WS 协议、故障排查表 |
| [MCP_INTEGRATION.md](MCP_INTEGRATION.md) | Claude Code MCP 集成：stdio server 桥接后端、工具清单、配置方法 |
| [CLAUDE_CODE_INTEGRATION.md](CLAUDE_CODE_INTEGRATION.md) | Claude Code 接入与配置落盘细节 |
| [同类工具调研报告.md](同类工具调研报告.md) | 开源串口/SSH 终端与日志工具横向对比 |
| [性能优化审计报告.md](性能优化审计报告.md) | 前端渲染与串口读路径的对抗性性能审计 |
| [提交版本号规则.md](提交版本号规则.md) | 版本号与提交信息规范 |
| 其余 `审计_*` / `交接_*` / `取证_*` / `设计_*` | 历史审计、交接与逆向取证记录（按日期归档，仅作追溯） |

## 项目结构

```
├── web/                             前端（index.html + style.css + skins.css + js/，原生 JS 无框架）
│   ├── js/harness/                  Claude 对话界面（v4 管线：store/bridge/render）
│   └── vendor 由仓库根 vendor/ 提供   Monaco / tree-sitter / markdown-it 等
├── vendor/                          第三方库本地托管
├── src/                             全部 Python 源码
│   ├── main.py                      桌面应用入口（pywebview + Flask）
│   ├── server.py                    HTTP 后端（串口/SSH/Telnet/文件/日志/设置）
│   ├── worker_app.py                Claude 后端独立进程（harness / proxy / hiklink）
│   ├── mcp_server.py                MCP stdio server（Claude Code 集成）
│   ├── harness/                     Claude 会话管线（session / routes / v4feed / lifecycle）
│   ├── proxy.py / proxy_core.py     Claude Proxy（重试代理 + 额度）
│   ├── lanz_quota.py                Lanz 额度客户端（CAS 登录）
│   ├── hiklink_bot.py               HikLink 机器人（PC 登录 + WS）
│   ├── app_state.py                 共享状态 + 路径常量
│   ├── base_conn.py / serial_conn.py / ssh_conn.py / telnet_conn.py   连接层
│   ├── log_index.py                 G 级日志行偏移索引
│   ├── tftp.py / httpfile.py        TFTP/HFS 传输
│   ├── editor_files.py / hex_files.py / file_tree.py / notes_index.py   文件能力
│   ├── vcs.py / vcs_remote.py       版本控制（git/svn + SSH 加速）
│   ├── skills_repo.py / claude_default.py / claude_setup.py             Claude 配置与技能
│   └── build.py                     PyInstaller 打包脚本
├── ico/                             应用图标
├── docs/                            技术文档（本目录）
├── data/                            默认数据目录（日志/笔记/缓存/凭据）
├── run.bat                          源码启动
└── 前端控制台.spec                  PyInstaller 打包配置
```
