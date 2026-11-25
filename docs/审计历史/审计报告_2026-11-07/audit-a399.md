# 对抗式审计报告：提交 1f5b004（a399 退出后进程残留 + rg.exe 占用根治）

- 审计对象：`git show 1f5b004 -- src/main.py`（+99 行；HEAD 即 1f5b004，src/main.py 工作树无额外改动）
- 方法：白盒逐行读 diff + 1f5b004 与父提交 b190089 双版本对照 + 交互链推演（tray.py / worker_app.py / updater.py / perf_boost.py / snip.py / proxy_usage.py / hex_files.py 全部只读核对）
- 性质：只找问题不修复，未改任何源码

## 结论先行

**实锤 2 项（P0×1、P1×1）+ 轻 ISSUE 1 项 + RISK 7 项。**

最严重的问题不是新增代码写错，而是一次编辑事故：**`def _dirty_quit_check(window):` 定义行被误删**，函数体变成 `_do_real_cleanup()` 尾部 `os._exit(0)` 之后的死代码，而调用点还在——托盘「退出」点了没反应（NameError 被 tray 吞掉只记日志），默认「关闭到托盘」用户的唯一正常退出路径瘫痪。第二个实锤：`taskkill /PID <自己> /T /F` 的 `/T` 树杀**包含指定进程自身**，taskkill 成功时主进程直接被 TerminateProcess——排在它后面的 `worker_app.manage_stop()`（worker 优雅收尾 + **proxy base_url 回滚**）、`perf_boost.restore_and_exit()`（电源计划还原）、主打收尾的 `os._exit(0)` 大概率全部执行不到，退出码从 0 变 1。

三层根治的**机制本身**（Job Object 参数、绑杀语义、os._exit 位置的三路径覆盖）核对为正确；坏在执行顺序与一次误删。

---

## 一、实锤

### 实锤 1（P0）`def _dirty_quit_check` 定义行被误删——托盘退出功能整体瘫痪

- 证据：父提交 b190089 `src/main.py:1086` 有 `def _dirty_quit_check(window):`；1f5b004 全文件 `grep -c "def _dirty_quit_check"` = **0**。其函数体（脏检查 docstring、`evaluate_js` 探测、`MessageBoxW` 确认）在 diff 中显示为紧跟新加的 `os._exit(0)` 之后——物理上并入了 `_do_real_cleanup()` 函数体，缩进 8 空格，语法合法（docstring 是表达式语句），**py_compile 不报**。
- 调用点未删：`_quit_with_check`（1f5b004 版 1215 行）`if not _dirty_quit_check(window):` → **运行时 NameError**（局部名未绑定，非 UnboundLocalError——函数根本不存在于该作用域）。
- 触发链：托盘菜单「退出」→ tray.py `_fire._safe`（src/tray.py:352-358，daemon 线程包 try/except，异常仅 `_log("托盘回调异常")`）→ `_quit_with_check` 第一行 NameError → `_real_quit` 永不置位、`_try_destroy` 永不执行。**每次点退出都失败，窗口留在托盘态，用户只能任务管理器强杀**（强杀时 Job Object 兜底倒是生效——但这是把正常退出逼成强杀）。
- 波及路径：`_quit_with_check` 是 `hide_to_tray(on_quit=...)` 的唯一退出回调（src/tray.py:503-515），即默认 `close_to_tray=true` 用户的全部退出动作。`close_to_tray=false` 的 on_closing 直退路径与 updater 路径不走此函数，不受波及。
- 讽刺点：本提交修「退出后残留」，实锤 1 让「退出」本身失效。

### 实锤 2（P1）taskkill /T /F 自杀——后续全部优雅清理大概率被剥夺

- 代码（`_kill_child_processes`，1f5b004 版 598-609 行）：
  ```python
  subprocess.run(["taskkill", "/PID", str(os.getpid()), "/T", "/F"], ...)
  ```
- taskkill 语义：`/F` 强杀**指定 PID 本身**，`/T` 额外扩展到其子树。`/PID <自己>` = 100% 自杀。taskkill 枚举树快照后逐个 TerminateProcess（taskkill 有自我保护，最后杀根=主进程）→ 主进程被强杀，退出码 1，Python 层无任何感知。
- 后果链（`_do_real_cleanup` 内 taskkill 之后排的全是正经清理，1f5b004 版 1154-1183 行）：
  1. `worker_app.manage_stop()` 执行不到/必然失败：worker 已被树杀（F 杀），HTTP POST `/worker_shutdown`（src/worker_app.py:534 起）ConnectionRefused → except → **跳过 proxy base_url 回滚直连、逐会话 kill_proc、hiklink_bot 停止**。worker_app.py a116 修复注释明载此坑的后果：「base_url 长期指向已死端口，下次开 Claude Code 直接连不上」。默认 worker 隔离形态（非 CLAUDE_INLINE）下回滚**只**依赖这条链。
  2. `perf_boost.restore_and_exit()` 执行不到：config 开了 `power_plan` 的用户，电源计划停留在高性能不还原（src/perf_boost.py:148-152，`_apply_power(False)` 没跑）。
  3. 主打的 `os._exit(0)` 执行不到——「清理全部完成后硬退」的设计意图落空，退出码 0 变 1。
  4. 子进程清场目标本身仍达成（taskkill 已杀 + Job Object 内核兜底），**丢的是优雅收尾**。
- 触发条件：走到 `_do_real_cleanup` 且 taskkill 可用（Windows 默认必有）。taskkill 失败/超时（5s）时 except 兜底，后续清理正常——即行为不确定、取决于环境。
- 另注：该调用同时 F 杀常驻截图窗与 WebView2 渲染进程，剥夺其 WM_CLOSE 优雅关闭（snip 心跳文件靠 660s 过期兜底，见 RISK 7）。

### 实锤 3（P2，轻）os._exit(0) 跳过 atexit 的手动补调清单不全

全仓 atexit 注册 6 处，`_do_real_cleanup` 补调对照：

| atexit 注册 | 手动补调 | 兜底情况 |
|---|---|---|
| main.py:1484 `perf_boost.restore_and_exit` | ✅ 补了 | （但被实锤 2 抢先） |
| worker_app.py:528 `manage_stop` | ✅ 补了（顺序在 taskkill 后，见实锤 2） | — |
| proxy.py:1783 `_atexit_rollback` | ⚠️ 仅 CLAUDE_INLINE=1 时经 `proxy_shutdown` 等价覆盖 | inline 正常；worker 隔离形态本就不归主进程管，但 worker 侧回滚依赖实锤 2 同一条被掐的链 |
| **main.py:905 `kill_snip_windows`（截图窗收编）** | ❌ 未补 | snip 窗是 Popen 子进程（src/snip.py:592）→ Job/taskkill 可杀 + 子进程 Flask 探活自杀兜底，轻 |
| **hex_files.py:547 `_diff_pool_shutdown`（diff 进程池）** | ❌ 未补 | 池进程在树内被杀，在途 diff 结果丢（退出场景可接受），轻 |
| **proxy_usage.py:186 `_recorder.flush`（用量统计落盘）** | ❌ 未补 | 有 60s 周期落盘循环（src/proxy_usage.py:88-98），最多丢 ≤60s 增量；inline 形态 os._exit 跳过、worker 形态被 F 杀同样跳过，轻 |

---

## 二、逐项核对（按审计要点）

### 1. Job Object 正确性 —— PASS（1 个死代码 + 2 个 RISK）

- **结构体**：`_IO_COUNTERS` 六个 `c_uint64` 字段名与顺序 = winbase.h `IO_COUNTERS` ✓；`_BASIC_LIMIT` 九字段（两个 c_int64 时间限、c_uint32 LimitFlags、两个 c_size_t 工作集、c_uint32 ActiveProcessLimit、c_size_t Affinity、c_uint32 PriorityClass/SchedulingClass）与 `JOBOBJECT_BASIC_LIMIT_INFORMATION` 完全一致 ✓；`_EXTENDED_LIMIT` 嵌套顺序（BasicLimitInformation + IoInfo + 四个 c_size_t）= `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` ✓。ctypes 默认 native 对齐与 MSVC 一致，x64 sizeof=144、x86=112 均正确，无 padding 错位。
- **class 9**：`JobObjectExtendedLimitInformation = 9` ✓（枚举序：…8=BasicAndIoAccounting，9=ExtendedLimit）。
- **0x2000**：`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000` ✓。
- **Assign 失败场景**：进程已在 Job 时 Win8+ 支持嵌套 Job，不失败；Win7 单 Job 限制会失败但被 `except Exception: pass` 兜住（走 taskkill 二层）。PyInstaller bootloader 不建 Job，打包 exe 从 Explorer 启动无碍。用户环境 Win10 19045，失败概率低，且失败有兜底——PASS。
- **`_job_handle` 保命**：ctypes 返回的是 int，全局变量持有，Python GC 不"关闭"内核句柄（句柄生命周期只受 CloseHandle/进程退出控制）——保存的意义是语义上防误关，无 GC 风险 ✓。故意不 CloseHandle 是正确设计（关了 = 提前触发 KILL_ON_JOB_CLOSE），进程退出时内核回收 ✓。
- RISK 6：`import ctypes.wintypes as _wt` 导入后全程未用（死 import，无碍）。
- RISK 2：四个 WinAPI 调用均未设 `restype`/`argtypes`（默认 c_int，32 位截断语义）。x64 下若内核句柄值 ≥2^31 会截断——Windows 句柄表实际达不到该量级，极低概率；`GetCurrentProcess` 伪句柄 (HANDLE)-1 经 c_int(-1) 符号扩展恰好还原为全 F，负负得正安全。

### 2. os._exit(0) 位置与副作用 —— 机制 PASS，路径覆盖被实锤 1 打断

- **三条路径推演**（无实锤 1 的前提下）：
  1. 托盘退出：`_quit_with_check` → 脏检查 → `_real_quit=True` → `_try_destroy` → 后台线程 `window.destroy()` → closing（GUI 线程）flag 分支 → `quit_tray()` + `_do_real_cleanup()` → os._exit(0) ✓——**但第一步就死于实锤 1 的 NameError，此路径实际瘫痪**。
  2. `close_to_tray=false` 直退：on_closing → `_do_real_cleanup()` → os._exit(0) ✓。
  3. 升级重启：`updater.run_update()` → `os.startfile(bat)`（detached）→ Timer 0.8s → `_request_quit` → flag + `w.destroy()` → closing flag 分支 → `_do_real_cleanup()` ✓。
- **os._exit 跳过 atexit 后已手动调了哪些/漏了哪些**：见实锤 3 清单（漏 3，均有兜底，轻）。
- **pywebview 清理被抢先**：`_do_real_cleanup` 同步跑在 closing 回调（GUI 线程）内，on_closing 的 `return True` 排在 cleanup 之后——pywebview 收到 True 后的 FormClosed/WebView2 shutdown/COM 收尾全部被 os._exit/taskkill 抢掉。资源由内核TerminateProcess 全量回收，无泄漏；**WebView2 渲染进程是主进程子进程**（WebView2Loader 进程内创建，父=主进程）→ 已在 Job 树内，被内核/taskkill 兜杀，无残留风险——此点设计成立。
- **`_try_destroy` 兜底 `os._exit(0)` 与 cleanup 末尾的重复**：非冲突，防御性双保险；cleanup 里的先生效，兜底的到不了。但见 RISK 1——若 cleanup 中途抛异常，两处都到不了。

### 3. taskkill /T /F 自杀风险 —— ISSUE（实锤 2，详见上）

`/T` 树杀含自己，100% 成立；`/T` 同时把 manage_stop 的服务对象（worker）先杀掉，使后续优雅收尾必然失败。正确形态应只杀子进程（枚举排除自身）或排到 manage_stop/perf restore 之后。

### 4. perf_boost.restore_and_exit —— PASS

src/perf_boost.py:148-152：仅 `stop()` + `_apply_power(False)` 还原电源计划，**无 os._exit/sys.exit/raise SystemExit**——函数名里的 "exit" 不会抢先，后续 `os._exit(0)` 可达（前提：没被实锤 2 的 taskkill 抢先）。内部抛异常有外层 try 兜住。

### 5. 非 Windows 环境 —— PASS

`ctypes.windll` 在 POSIX 的 ctypes 模块上不存在 → AttributeError → 被 `_setup_job_object` 的 `except Exception` 捕获。`_kill_child_processes` 里 taskkill 不存在 → FileNotFoundError；`creationflags=0x08000000` 在 POSIX subprocess 直接 ValueError——均被捕获，不阻断。

### 6. 与既有退出链的交互 —— PASS 为主，3 个 RISK

- `close_all_ports()`（src/server.py:212，同步关 port）、`clear_endpoint()`/`_clean_webview_cache()`（自带 try，同步）——无异步操作被 os._exit 截断的问题 ✓。
- 升级链：`os.startfile(bat)` 经 ShellExecute，父进程非本进程 → **不继承 Job、不在 taskkill 树内**，os._exit 不会杀升级流程 ✓；bat 自带 `taskkill /f /im` 兜底 + ren 30s 重试（src/updater.py:130-160），主进程清理耗时（taskkill 5s + manage_stop 最长 ~10s）在 30s 窗口内 ✓。
- RISK 5：closing 回调（GUI 线程）同步跑最长 ~15s 清理 → 关窗瞬间白窗/无响应期变长（升级场景 bat 30s 重试可兜）。
- RISK 1（重要）：`_do_real_cleanup` 顶部 `close_all_ports()` 裸调无 try（`p.close()` 可抛）——任一前置步骤抛异常 → 尾部 `os._exit(0)` **不达** → 主进程滞留（原始 bug 复活）；on_closing 路径下异常还会让 closing 回调无返回值（pywebview 按 falsy 处理=阻止关闭）。宣称「防清理挂起」，实际只防「慢」不防「抛」。既有结构弱点，但与本提交「末尾硬退」的设计叠加后值得记录。
- RISK 3：`os.startfile` 拉起的 bat 在个别环境（某些 shell/终端继承 Job 链）理论上可能入 Job → 主进程退出时升级进程被内核杀断升级。极低概率（ShellExecute 常规不经调用者 CreateProcess）。

### 7. 语法/逻辑 —— 编译 PASS，运行时死代码（实锤 1）

- py_compile 通过（复核）：死代码在语法上是 `_do_real_cleanup` 的合法语句序列，docstring 退化为普通表达式语句——**编译期不报、运行期 NameError 才炸**的典型。
- `_dirty_quit_check`（调用点）相对 `os._exit` 的时序：本应在托盘路径先于 `_try_destroy` 执行，现在因函数不存在直接抛异常；物理上其原函数体位于 `os._exit(0)` 之后成为永不可达死代码。
- 全部 exit 路径清理完整性汇总：路径 2/3（close_to_tray=false、升级）可达 os._exit(0) 但大概率先死于 taskkill 自杀（实锤 2）；路径 1（托盘）死于 NameError（实锤 1）；三条路径的 atexit 补调缺口见实锤 3。

---

## 三、新发现（审计要点之外）

1. **`--claude-worker` 子进程也各自建 Job 并加入自身**（main() 第一行对所有模式生效）：Win8+ 嵌套 Job 无碍且形成双保险（主 Job 杀全树 + worker Job 杀自己子树）；Win7 下 Assign 失败静默跳过，可接受。
2. **`--audit-hook`/`--mcp-ask` 等主实例派生的短命子进程同样入主实例 Job**：主实例退出时在飞 hook 被杀——均为本就要退出的短命进程，无实际影响。
3. **`--selftest` 不经 main()**（`if __name__ == "__main__"` 里先分流，src/main.py:1560-1563）→ 不建 Job——自检进程无子进程，无碍。
4. **update.bat 里 `taskkill /f /im msedgewebview2.exe`（src/updater.py:159）**：升级时无差别强杀**全系统** msedgewebview2.exe（包括其他在用 WebView2 的应用）——非本提交引入，顺带记录。

---

## 四、总表

| # | 级别 | 发现 | 触发条件 |
|---|---|---|---|
| 实锤 1 | **P0** | `def _dirty_quit_check` 定义行误删 → 托盘退出 NameError 全瘫，脏检查丢失 | 点托盘「退出」（默认 close_to_tray=true 唯一退出路径） |
| 实锤 2 | **P1** | taskkill /PID self /T /F 自杀 → manage_stop（base_url 回滚）、perf_boost 还原、os._exit(0) 全跑不到，退出码变 1 | 走到 _do_real_cleanup 且 taskkill 可用 |
| 实锤 3 | P2 | os._exit 跳 atexit 的补调漏 3 项（snip 窗/diff 池/用量 flush） | 走到 os._exit(0) |
| RISK 1 | 中 | cleanup 前置步骤裸调无 try，抛异常则 os._exit 不达 → 残留回归 | close_all_ports 等抛异常 |
| RISK 2 | 极低 | ctypes 未设 restype，x64 句柄理论截断 | 句柄 ≥2^31（实际达不到） |
| RISK 3 | 极低 | startfile 的升级进程理论入 Job 被杀断升级 | 特殊 shell/Job 继承环境 |
| RISK 4 | 低 | Win7 嵌套 Job 不支持 → Assign 静默失败 | 仅 Win7 用户 |
| RISK 5 | 低 | closing GUI 线程同步清理 ~15s 白窗 | 退出时 worker 慢退 |
| RISK 6 | 低 | `_wt` 死 import | — |
| RISK 7 | 低 | taskkill F 杀剥夺 snip/WebView2 优雅关闭，心跳文件靠 660s 过期 | 退出时有常驻截图窗 |

**修复方向提示（仅供参考，本审计不改码）**：实锤 1 需恢复 def 行；实锤 2 需把 taskkill 换成「枚举子 PID 排除自身」或移到 manage_stop/perf restore 之后、os._exit 之前；实锤 3 在 os._exit 前补三个 flush/收编调用。

（审计人：对抗式审计；日期：2026-11-06；范围：仅 1f5b004 对 src/main.py 的改动及其交互链）
