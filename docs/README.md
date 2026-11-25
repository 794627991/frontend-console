# 文档索引

面向使用者的完整说明书在仓库根 **README.md**（设置 → 帮助 里打开的就是它），本目录只放开发者/技术类文档。

> 2026-11-25 整理：顶层只留活跃文档；历史文档按类别移入子目录，文件名未改，全文搜文件名仍可达。

## 活跃文档（顶层）

| 文档 | 说明 |
|------|------|
| [CLAUDE_CODE_INTEGRATION.md](CLAUDE_CODE_INTEGRATION.md) | Claude Code 接入与配置落盘细节（src 多处注释引用的设计文档） |
| [MCP_INTEGRATION.md](MCP_INTEGRATION.md) | Claude Code MCP 集成：stdio server 桥接后端、工具清单、配置方法 |
| [SSO认证与连接机制.md](SSO认证与连接机制.md) | SSO 两条链路（Lanz CAS / HikLink PC）源码级说明、加密细节、WS 协议、故障排查表 |
| [提交版本号规则.md](提交版本号规则.md) | 版本号与提交信息规范 |
| [待办_SSO密码填充_公司验收_2026-11-20.md](待办_SSO密码填充_公司验收_2026-11-20.md) | 公司侧验收待办 |
| [文档预览与AI文档工具链_需求与设计_2026-11-25.md](文档预览与AI文档工具链_需求与设计_2026-11-25.md) | 文档预览分屏 + AI 文档工具链对齐 ZCode 的需求与设计（实施与评审依据） |

## 历史归档（子目录）

| 目录 | 内容 |
|------|------|
| 审计历史/ | 全部已完结审计：散件七份（harness 0914、性能优化、v4.0.0 系列四件、技能多源安全批）+ 审计补丁台账_2026-11-06、审计补丁台账_2026-11-13（过程评审稿，66 个 md，无补丁本体；终局结论已沉淀在同期 git 提交信息）+ 审计报告_2026-11-07 |
| 设计历史/ | 已实施/已回退的设计稿（右侧会话动态面板、v4 归一重构、识图双通道、子代理窗格 UI、三角色测试、v4view 差距清单、electron 迁移方案——electron/main.js 注释引用）；代码索引三档重构_归档_20261120/（**设计已锁定、未实施**的完整评审档案，INDEX.md 是入口——将来实施该重构前必读，勿删） |
| 调研与取证/ | ZCode 机制取证四件、同类工具调研、zcode 参考架构笔记、arch 落地 v1、v318 摘要组移植备档 |
| archive/ | 三份早期交接；**architecture-policy.yaml 是活规则**（tools/architecture_check.py:26 加载，勿删）；**releases/ 是活数据**（升级门户的历史版本说明，update_server.py 读取，勿删）；其余为重建计划等历史稿 |
| 闲时审计/ | 闲时审计报告（命名 <hash>_aNNN_审计报告_<日期>.md，约定见记忆/AGENTS 相关工作流） |

> 注：模块化回归的测试材料不在 docs——说明书在 `tests/regression/docs/`，运行产物在 `tests/regression/artifacts/`（run_all.py 与 render_audit.py 写入）。

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
│   ├── proxy.py / proxy_core.py     Claude Proxy（重试代理，纯转发职责）
│   ├── lanzi/                       Lanzi 专栏（a672）：机器人 / SSO 登录 / 额度 / 负载
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
