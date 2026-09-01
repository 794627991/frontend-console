# 串口控制台 Pro 分支版本

本目录包含两个修复版本，基于不同分支独立修复。**主目录 `D:\AI\串口控制台Pro` 的代码未改动**，运行中的串口工具不受影响。

## ⚠️ 测试前必读

两个版本都有**单实例锁**（Global mutex），与主目录的工具互斥。测试分支版本前，必须先关闭主目录正在运行的工具：

```bash
# 通过 endpoint.json 读出 PID 精确关闭（绝不能用 taskkill //IM python.exe，会杀代理）
# 当前主目录工具 PID 见 ~/.serialconsole_pro/endpoint.json
# 关闭后双击分支版本的 run.bat 启动
```

---

## v0.2-fix（基于 v0.2-legacy，DOM 终端版）

**分支**：`fix/v0.2.9-tab-input`
**启动**：双击 `v0.2-fix\run.bat`

### 修复内容

1. **tab 补全通用提示符识别**
   - 之前 `appendLine` 硬编码 `startsWith('# ')`，只认 `# ` 提示符
   - 现在用通用正则识别 `#`/`$`/`>` 提示符，支持 `root@host:#`、`~/dir #`、`/ #` 等带前缀形态
   - 纯提示符重绘（补全无结果）也同步清空 termBuf
   - 不含提示符的 redraw 行（进度条等）当普通行显示，不清 termBuf

2. **去重复回显**
   - Enter 不再手动 append 命令行到输出区（设备会本地回显，手动 append 会重复）

3. **输入框增高美观**
   - 高度 38px → 120px，内容贴底显示（像真终端）
   - 字号 13→14px，行高 1.6，光标 28px，padding 加大

---

## v0.3-fix（基于 v0.3.0，xterm.js 终端版）

**分支**：`fix/v0.3.1-sense`
**启动**：双击 `v0.3-fix\run.bat`

### 修复内容

1. **感知异常修复（核心）**
   - **根因**：v0.3.0 的 `_reader_loop` 全屏模式（top/htop）会 `continue` 跳过 buf 追加，AI 调 `/api/ai/buffer` 拿不到数据——"终端开了但获取不到数据"
   - **修复**：全屏模式不再抑制 buf。无论是否全屏，都执行 `_push_raw` + 行切分入 buf。AI 始终能感知串口数据
   - `screen_mode` 仅控制前端 xterm 全屏提示条显示/隐藏，不影响数据采集
   - 前端 xterm.js 走 raw 流，全屏渲染不受影响

2. **合并 v0.2-legacy 全部后续功能**
   - 日志目录可配置：`/api/log_dir`(GET/POST) + `/api/log_dir/open`，前端日志库面板加目录输入框
   - LOG_DIR 优先级：环境变量 > config.json > ~/.serialconsole_pro/logs
   - 修复 `find_and_focus_existing_window`：`IsWindowVisibleW`→`IsWindowVisible`，加 64 位句柄类型声明
   - 加 `_old_instance_alive` 探活，处理强杀后 mutex 残留
   - spec excludes 排除 cryptography/ssl 等重依赖加速启动
   - build.py 改用 spec 文件打包

---

## 验证感知修复

v0.3.1 的感知修复已通过逻辑测试验证：全屏期间 buf 行数比 v0.3.0 多（不丢失刷新帧）。

实际测试方法：启动 v0.3-fix → 连串口 → 在设备上运行 `top` → 用 `serial_cli.py buf COM1 50` 确认能拿到 top 的输出数据（v0.3.0 在 top 期间拿不到）。

## Git 分支

- `fix/v0.2.9-tab-input` — v0.2-fix 的修复提交
- `fix/v0.3.1-sense` — v0.3-fix 的修复提交
- worktree 在 `.wt/v0.2-fix` 和 `.wt/v0.3-fix`（可保留继续开发）
