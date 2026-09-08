# 前端控制台 v1.1.0 — MCP 集成说明

> 让 AI 助手（Claude Code 等任何 MCP 客户端）原生控制串口/SSH 设备、分析日志文件。
> 配置后，AI 能自动发现并使用本工具的全部能力，无需手动复制粘贴终端输出。
> 工具本身不含 AI——所有 AI 能力由外部 Claude Code 通过 MCP 提供。

---

## 一、这是什么

**前端控制台 v1.1.0** 是面向嵌入式/BSP 开发者的串口/SSH 调试 + 日志分析桌面工具（Windows，pywebview + WebView2）。

通过 **MCP（Model Context Protocol）** 集成，AI 助手可以：

- 🔌 **查看串口/SSH 连接状态**与实时输出
- ⌨️ **向设备发命令**（自动加回车）、发原始字节（Ctrl-C 中断等）
- 📜 **读取/搜索日志文件**（含用户拖进工具的任意路径日志）
- 🔍 **对比两份日志差异**（正常 vs 异常启动，定位问题）

AI 操作的是**你正在用的同一个工具**——你在 GUI 里连的串口，AI 直接就能发命令，无需重复连接。

---

## 二、配置方法

### 前置条件

- Windows 10/11
- 已安装 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)（Win11 自带，Win10 可能需手动装）
- **二选一**：拿到 `前端控制台.exe`（单文件，无需 Python 环境），或用源码运行（需 Python 3.x）

### Claude Code 配置

编辑 MCP 配置文件（二选一）：

- **用户级**（全局生效）：`~/.claude.json` 的 `mcpServers` 字段
- **项目级**（仅当前项目）：项目根目录 `.mcp.json`

**exe 分发**（推荐，其他用户无需装 Python）：

```json
{
  "mcpServers": {
    "serial-console-pro": {
      "command": "C:\\path\\to\\前端控制台.exe",
      "args": ["--mcp"]
    }
  }
}
```

**源码运行**（开发机）：

```json
{
  "mcpServers": {
    "serial-console-pro": {
      "command": "python",
      "args": ["D:\\AI\\串口控制台Pro\\src\\mcp_server.py"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

> 把路径换成实际位置。路径中的反斜杠要双写（JSON 转义）。

配置后重启 Claude Code，输入 `/mcp` 应能看到 `serial-console-pro` 已连接，16 个工具可用。

### 其他 MCP 客户端

任何支持 stdio 传输的 MCP 客户端均可配置，命令为：

```
<exe路径> --mcp
```

`--mcp` 标志让 exe 以 MCP stdio server 模式运行（不弹 GUI 窗口），通过 stdin/stdout 收发 JSON-RPC 消息。

---

## 三、工具列表（16 个）

### 🔌 连接管理

| 工具 | 说明 | 关键参数 |
|------|------|----------|
| `observe` | **最常用入口**。列出所有已连接串口/SSH + 各连接最近输出 + 前端已打开的日志 | `n`: 每连接取最近 N 行（默认 50） |
| `list_ports` | 列出系统可用串口 + 已连接列表 | 无 |
| `connect_serial` | 建立串口连接 | `port`(必填, 如 COM1), `baud`(默认 115200) |
| `connect_ssh` | 建立 SSH 连接 | `host`(必填), `username`(必填), `password`/`key_path` 二选一, `port`(默认 22) |
| `disconnect` | 断开指定连接 | `port_id`(必填) |

### ⌨️ 设备交互

| 工具 | 说明 | 关键参数 |
|------|------|----------|
| `send_command` | 向连接发命令（自动加回车），等待回显后返回新输出 | `port_id`(必填), `cmd`(必填), `wait`(默认 2 秒) |
| `send_raw` | 发原始字节，用于 Ctrl-C 中断 / Ctrl-D 结束输入 | `port_id`(必填), `bytes`(必填, 如 `[3]`=Ctrl-C) |
| `get_buffer` | 获取连接最近 N 行缓冲输出 | `port_id`(必填), `n`(默认 200) |

### 📜 日志分析

| 工具 | 说明 | 关键参数 |
|------|------|----------|
| `list_open_logs` | 列出前端（桌面 app）当前已打开的日志文件 | 无 |
| `read_log` | 读取日志（支持绝对路径或日志目录内文件名），先返回总行数再返回指定页 | `path`(必填), `offset`(默认 0), `limit`(默认 200) |
| `search_log` | 在日志中搜索关键字，返回命中行（行号+内容） | `path`(必填), `query`(必填), `limit`(默认 500) |
| `diff_logs` | 对比两份日志差异。BSP 常用于「正常启动 vs 异常启动」 | `a`(必填), `b`(必填), `mode`("summary"/"line"), `context`(默认 2) |

### 📡 TFTP 文件传输

| 工具 | 说明 | 关键参数 |
|------|------|----------|
| `tftp_status` | TFTP 服务状态：运行中/目录/文件列表/最近传输记录 | 无 |
| `tftp_start` | 启动 TFTP 服务（UDP 69），设备端即可上传/下载 | `root_dir`(可选) |
| `tftp_stop` | 停止 TFTP 服务 | 无 |
| `tftp_set_dir` | 设置/切换 TFTP 根目录 | `root_dir`(必填) |

---

## 四、架构说明（AI 必读）

### 共享后端，不要重复连接

**本 MCP server 与桌面 app 共享同一后端进程。** 你在 GUI 里手动连的串口/SSH，MCP 工具直接就能操作，反之亦然。

这意味着：

1. **先 `observe`，再操作。** `observe` 返回的 `port_id`（形如 `COM1` 或 `ssh:192.168.1.100:22`）可直接用于 `send_command`/`get_buffer`。
2. **不要重复 `connect`。** 若 app 已连某串口，再 `connect_serial` 同一端口会因占用失败——此时应改用 `observe` 复用已有连接的 `port_id`。仅在确实需要新建连接时才 `connect`。
3. **波特率固定 115200**（除非设备明确要求其他值）。COM 口号不固定，每次插拔可能变，先 `list_ports` 确认。

### 服务发现机制

MCP server 启动时不会立即连接后端（避免阻塞）。第一次工具调用时才**懒发现**后端：

1. 读 `~/.serialconsole_pro/endpoint.json` 获取后端 HTTP 地址
2. 探活 `/api/status`，若存活则复用
3. 若工具未运行，自动拉起（优先源码 `main.py`，其次 `dist/串口控制台Pro.exe`），最多等 25 秒

所以即使用户没手动开工具，AI 第一次调用也会自动拉起 GUI。

### port_id 格式

- 串口：`COM1`、`COM10`（与系统设备名一致）
- SSH：`ssh:主机IP:端口`，如 `ssh:192.168.1.100:22`

---

## 五、典型工作流

### 工作流 1：调试串口设备

```
1. observe                        → 看当前连了什么，拿到 port_id（如 COM3）
2. send_command(COM3, "ls /")     → 发命令，看回显
3. send_command(COM3, "dmesg", wait=5)  → 等更久的命令
4. send_raw(COM3, [3])            → Ctrl-C 中断卡死的命令
5. get_buffer(COM3, n=500)        → 看更多历史输出
```

### 工作流 2：分析启动日志

```
1. list_open_logs                 → 看用户拖进了哪些日志，拿到 path
2. search_log(boot.log, "error")  → 搜报错
3. search_log(boot.log, "panic")  → 搜内核恐慌
4. read_log(boot.log, offset=1200) → 看报错附近的上下文
```

### 工作流 3：对比正常 vs 异常日志

```
1. diff_logs(normal.log, abnormal.log, mode="summary")
   → 去重摘要，找异常日志多出的报错（最常用）

2. diff_logs(normal.log, abnormal.log, mode="line", context=3)
   → 行级 diff，看启动流程哪里分叉
```

### 工作流 4：SSH 调试远程设备

```
1. connect_ssh(192.168.1.100, admin, password=xxx)
   → 拿到 port_id = ssh:192.168.1.100:22
2. send_command(ssh:192.168.1.100:22, "top -n1")
3. send_command(ssh:192.168.1.100:22, "cat /var/log/syslog")
```

### 工作流 5：TFTP 传文件（设备 ↔ PC）

```
1. tftp_start(root_dir="D:\\fw")       → 启动 TFTP（UDP 69），目录 D:\fw
2. tftp_status()                        → 确认运行中 + 看目录内文件
3. 设备端（通过 send_command 让设备执行）：
   下载固件到设备: tftp -g -r uImage <PC的IP>
   设备日志推到 PC: tftp -p -l messages <PC的IP>
4. tftp_status()                        → 查看传输记录（进度/结果）
5. tftp_stop()                          → 用完停止
```

---

## 六、注意事项

### BusyBox 设备

嵌入式设备多用 BusyBox，`send_command` 的 `cmd` **尾部不要带裸数字**（会被某些 BusyBox shell 解释为文件描述符）。例如用 `cat /proc/cpuinfo` 而非 `cat /proc/cpuinfo 2`。

### 编码

- 工具输出统一 UTF-8。MCP server 已处理 Windows 默认 GBK 编码问题。
- 日志文件自动检测编码（UTF-8/GBK/Latin-1），无需手动指定。

### 自动拉起失败

若 `observe` 返回「终端控制台 Pro 未运行，且自动拉起失败」：

1. 手动双击 `串口控制台Pro.exe` 启动工具
2. 等窗口出现后再让 AI 调用

### 并发

- 多个 AI 会话可同时连同一后端，操作同一连接。
- `send_command` 是同步的（等待 `wait` 秒），并发发往同一连接可能交错——建议串行操作同一连接。

---

## 七、版本

- MCP server 版本：`0.5.0`（见 `initialize` 响应的 `serverInfo.version`）
- 协议版本：`2024-11-05`
- 传输方式：stdio（JSON-RPC over stdin/stdout）

---

## 八、给 AI 的速查卡

```
你是终端控制台 Pro 的 MCP 工具使用者。遵循以下规则：

1. 每次任务开始，先调 observe 了解当前状态（连了什么、有哪些日志）。
2. 拿到 port_id 后直接 send_command，绝不在已连接的端口上重复 connect。
3. 串口波特率默认 115200，COM 口号每次插拔可能变——先 list_ports 确认。
4. send_command 的 cmd 尾部不要带裸数字（BusyBox 陷阱）。
5. 中断卡死进程用 send_raw([3])（Ctrl-C）。
6. 日志分析先 list_open_logs 拿 path，再 read_log/search_log/diff_logs。
7. 对比正常 vs 异常日志，diff_logs mode="summary" 最有效。
8. 工具没开时第一次调用会自动拉起，最多等 25s——若失败让用户手动开。
```
