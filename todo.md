# 全面代码审查 todo（2026-09-04 21:00 工作流审查）

> 审查方式：6 个子系统并行找 bug → 每项独立对抗验证（反驳式），仅保留验证无法推翻的问题。
> 37 个 agent、约 187 万 tokens；候选 31 项，确认 28 项，去重后 **25 项**（3 被反驳剔除）。
> 范围：src/ 后端 + web/js/ 前端，分支 feat/g-level-history-ssh @ c33be1a。
> 以下仅记录待修项，行号为审查时快照。⚠ 含多个数据丢失级 bug，建议优先处理【严重】组。

---

## 🔴 严重（8 项）——数据丢失/崩溃

> ✅ **2026-09-05 全部修复完成**（#1–#9，含 #21 一并处理），审查情况见各项「修复审查」。

### 1. 【✅已修】数据目录二次迁移零拷贝直切空目录（数据丢失）
- **位置**：`src/server.py:552`（migrate/check/get 多处；fe-interaction 组在 604 行重复报告，同一根因）
- **问题**：`from src.app_state import DATA_DIR` 按值绑定进 server 模块；迁移成功只写 `_st.DATA_DIR` 和 `global LOG_DIR`，server 自己的 `DATA_DIR` 永远停在 import 时的旧路径。
- **失败场景**：启动时 DATA_DIR=A，迁移 A→B 成功（A 被自动删除）；**不重启**再迁移到 C：目标校验用陈旧 A 比对通过，`A\logs` 等已不存在 → 全部静默跳过，copied=[] → 照常写 config.data_dir=C 返回成功。真实数据孤立在 B，重启后工具从空 C 启动 = 用户视角数据全丢。且 GET /api/data_dir 一直显示已删除的 A，用户无从发现。
- **修法**：migrate 切换段补 `global DATA_DIR; DATA_DIR = target`（与 LOG_DIR 同款），或 server.py 全部改经 `_st.DATA_DIR` 属性访问消除双绑定。

### 2. 【✅已修】迁移不拦截「目标嵌套在当前数据目录内」——rmtree 连新副本一起删（数据丢失）
- **位置**：`src/server.py:501`（check）、`server.py:540`（migrate）
- **问题**：两处只做 abspath 全等比较，无嵌套/前缀判定；迁移完成后 `rmtree(old_data_dir)`（623 行）会把嵌套在源内的新目标连同刚复制的数据一并删除。
- **失败场景**：当前 D:\data，用户选 D:\data\新位置（原生对话框允许）→ 复制校验全过 → 写 config → rmtree(D:\data) 连新副本一起删 → 全量数据丢失，重启后 makedirs 重建空目录。选 logs 子目录变体同样成立。
- **修法**：check 与 migrate 双侧加嵌套判定：`t.startswith(s + os.sep) or s.startswith(t + os.sep)` 即拒绝。

### 3. 【✅已修】启动归位：顶层复制后 rmtree 整个旧日志目录（数据丢失）
- **位置**：`src/app_state.py:95`（`_migrate_legacy_user_data`）
- **问题**：legacy 目录只做顶层 listdir + copy2：子目录抛 IsADirectoryError 被裸 except 吞掉、复制失败文件静默跳过；只要 merged>0（跨三个目录共享的计数器）就 rmtree 整个旧目录——未复制的子目录与失败文件连带永久删除，违反 docstring「复制成功才删旧文件」契约。发生在 import 阶段，零日志零提示。
- **失败场景**：serial_logs 下用户手工归档的子目录 old\（30 个日志）：顶层 20 个文件复制成功 → rmtree → old\ 内 30 个日志随目录被删。
- **修法**：rmtree 前重新 listdir 核对 final_logs 覆盖了全部条目，未覆盖则保留；子目录递归复制；merged 改为 per-directory 计数。

### 4. 【✅已修】hex 可编辑文件 >512KB：保存即截断整个文件（数据丢失）
- **位置**：`web/js/hex-viewer.js:135`（log-backend 与 fe-interaction 两组重复确认，同一根因）
- **问题**：editable 路径单次 `fetchChunk(0, size)` 整读，但后端 `hex_files.py:48` 硬钳 READ_CHUNK=512KB → conn.bytes 只有前 512KB 而 conn.size 仍是完整大小。byteAt 越界返回 undefined → BigInt(undefined) 抛 TypeError，滚动渲染崩溃；_hxSave 按 conn.bytes 写回，后端 os.replace 无长度校验。
- **失败场景**：打开 2MB .bin 固件（≤16MB 可编辑）→ 滚过 0x80000 界面冻结 → 改一字节 Ctrl+S → 2MB 文件被替换成 512KB，1.5MB 数据永久丢失且无报错。
- **修法**：前端按 HEX_CHUNK 分块循环 fetchChunk 拼接至 conn.size；hex_save 写回前校验 raw 长度与 meta size 一致，不一致拒绝保存（双保险）。

### 5. 【✅已修】拖入/最近打开外部 .note 文件：打开空白，保存即覆盖毁原文件（数据丢失）
- **位置**：`web/js/editor.js:1217`（openFileSmart edit 分支）
- **问题**：`/api/ed/open` 返回 JSON 字符串后直接 buildEditorTab，没像 openEditorFile（724 行）那样先 JSON.parse；_edInitContent 要求对象 → 空块初始化、onDisk=true。
- **失败场景**：拖入外部 .note 备份笔记 → 编辑器打开为空白 → 随手 Ctrl+S → 原文件被写回 `{"blocks":[]}`，原始笔记永久丢失。「最近打开」extPath 路径同样命中。
- **修法**：openFileSmart edit 分支对 .note 做 JSON.parse（失败兜底空对象），或统一在 buildEditorTab 入口对 isNote 且 content 为字符串时先解析。

### 6. 【✅已修】Intel HEX 保存超 64KB 地址回绕——保存即毁固件（数据丢失）
- **位置**：`web/js/hex-viewer.js:693`（_hxSave ihex 回写）
- **问题**：只发 type 00 数据记录、地址字段 `(off & 0xFFFF)`，从不发 type 04 扩展线性地址记录；镜像超 64KB 后所有记录地址回绕（0x10000→0x0000）。校验和经 &0xFF 掩码恰好与截断地址自洽，文件能静默通过任何校验检查——破坏更隐蔽。
- **失败场景**：打开 128KB 固件 .hex，改一字节 Ctrl+S → 后半 64KB 数据地址全部回绕，烧录时写到错误地址，固件文件损坏（os.replace 无备份）。
- **修法**：保存时维护扩展段，off 跨 0x10000 边界先输出 `:02000004 XXXX` 扩展记录；地址与校验统一只用低 16 位。

### 7. 【✅已修】serial_cli 默认命令 cmd_overview 未定义，直接 NameError 崩溃
- **位置**：`src/serial_cli.py:254`
- **问题**：main() 默认分支调用 cmd_overview(url)，但全文件无 `def cmd_overview`；need_running() 的 sys.exit(1) 之后（135-158 行）残留一段引用未定义 url 的死代码——正是丢失了函数头的 cmd_overview 函数体。
- **失败场景**：后端运行时执行 `python src/serial_cli.py`（docstring 第一用法）→ NameError 崩溃，overview/obs/o 三种默认用法全挂。
- **修法**：把 135-158 行死代码取出恢复为 `def cmd_overview(url):`，删 sys.exit 后残留。

### 8. 【✅已修】MCP stdin 未重配 UTF-8：含中文/emoji 的工具参数全部乱码
- **位置**：`src/mcp_server.py:759`
- **问题**：只 reconfigure 了 stdout/stderr，stdin 保持 Windows 管道默认 GBK。Claude Code 按 MCP stdio 规范写 UTF-8 JSON，Python 按 GBK 解码出乱码+孤立代理字符（\udcad）。**验证者已在运行中的工具上实证复现**：`read_log(path="中文…")` 返回 `'utf-8' codec can't encode character '\udcad'…surrogates not allowed`。exe 模式（main.py:155）已包 utf-8 不受影响，源码模式无保护。
- **失败场景**：本项目路径本身含「串口控制台」——read_log/search_log/diff_logs/send_command（"echo 你好"）凡带中文参数必然失败或发乱码字节给设备。
- **修法**：758-762 同一 try 块补 `sys.stdin.reconfigure(encoding="utf-8")`。

### 9. 【✅已修】start() 先启动读线程后开日志：_start_log 异常时句柄/线程泄漏，COM 口占死
- **位置**：`src/base_conn.py:276`（配合 server.py:217-221）
- **问题**：start() 顺序 _io_open() → 读线程 → _start_log()，后者 makedirs/open 无异常保护；api_connect 在 _ports_lock 里构造失败只转 500，半构造对象（已开串口句柄+读线程+SSH keepalive）无人 close。
- **失败场景**：LOG_DIR 指向的网络盘掉线后点连接 → 500「连接失败」，但 COM3 已被占用，再连报 PermissionError，泄漏读线程持续空转直到退出工具。SSH 场景泄漏完整活会话。
- **修法**：start() 内 try/except _start_log 失败降级（log_fp=None 继续跑）不让异常逃逸；或 api_connect except 分支对半构造对象调 close() 再返回 500。

---

## 🟡 中等（12 项）——功能失效/误导/越界

> ✅ **2026-09-05 全部修复完成**（#10–#21），审查情况见文末「中等+轻微组修复审查记录」。

### 10. 【✅已修】AI 全局流补丁只挂 SerialPort——SSH 输出永远不进 /api/ai/stream
- **位置**：`src/server.py:89`（补丁）+ `src/ssh_conn.py:68`（两组独立发现，同一根因）
- **问题**：`SerialPort.append_line = _patched_append` 只 shadow 了串口类，SSHConnection 继承未打补丁的基类方法；_broadcast_to_ai 唯一调用点就是这个补丁。base_conn.py:71 注释明言设计意图覆盖所有连接。本分支正是 SSH 功能分支。
- **失败场景**：AI 订阅 /api/ai/stream 后连 SSH 跑命令：一行都不到，误判设备无输出；sense.js 感知面板 SSH 端口连筛选 chip 都不出现，而 observe/get_buffer 直读 buf 正常——极难排查。
- **修法**：补丁改挂 `BaseConnection.append_line`，serial/ssh 一并覆盖。

### 11. 【✅已修】/api/log/<name> 无路径穿越防护（反斜杠可逃出 LOG_DIR）
- **位置**：`src/server.py:651`
- **问题**：唯一没走 _resolve_log_path 的日志路由；Flask 默认转换器只挡 `/` 不挡 `%5C`（解码为 `\`），Windows 上反斜杠是合法分隔符，`..\` 可逐级逃出读数据盘任意文件。
- **修法**：改 `path = _resolve_log_path(name); if not path: return 404`，与其他 8 个日志路由统一防线。

### 12. 【✅已修】httpfile 下载服务：盘符相对名（C:xxx）绕过 root_dir 限制
- **位置**：`src/httpfile.py:63`
- **问题**：校验只拒 /、\、.、..，不拒冒号；`os.path.join(root, 'C:xxx')` 在 Windows 直接返回 'C:xxx' 丢弃 root（已实测确认）；服务绑 0.0.0.0:8081 对局域网设备开放。
- **失败场景**：局域网任意主机请求 `http://<PC_IP>:8081/C:config.json` → 可越界读进程 CWD/盘根下平铺文件。
- **修法**：校验追加拒绝含 `:` 的 name，或拼接后 realpath 必须位于 root 之下再放行。

### 13. 【✅已修】close() 期间读线程在 _io_reconnect 内部：新 SSH 会话被创建并永久泄漏（幽灵会话）
- **位置**：`src/ssh_conn.py:109`
- **问题**：close() join 超时仅 1s，而 _io_reconnect 内部 sleep(1~60s) + connect(timeout=10) 都不检查 self.alive；重连成功后读线程才发现 alive=False 退出，新会话无人关闭。
- **失败场景**：网络抖动重连期间点断开 → 幽灵会话占掉嵌入式设备（dropbear 通常限 1~2 个会话）名额，之后怎么连都失败直到工具退出。
- **修法**：_io_reconnect 的 sleep 后、_io_open 前检查 `if not self.alive: return False`；_io_open 成功赋值句柄前再检查一次。

### 14. 【✅已修】MCP：HTTPError 被当 URLError 处理——后端 4xx/5xx 全部误报「工具可能已关闭」
- **位置**：`src/mcp_server.py:815`
- **问题**：HTTPError 是 URLError 子类；后端所有 500/404（认证失败/文件不存在/重复 disconnect）都进「后端瞬断重试」分支：清 URL 缓存+原样重发（connect_ssh 场景重复一次完整 SSH 握手，非幂等）+最终上报「后端通信失败…工具可能已关闭」。server.py 精心写的中文错误分类对 MCP 侧是死代码。
- **失败场景**：connect_ssh 密码错 → AI 收到「工具可能已关闭」，误诊为桌面工具没运行，转去拉起 app。
- **修法**：URLError 之前先 `except urllib.error.HTTPError`：读响应体 err 字段直接作为工具结果返回，不重试。

### 15. 【✅已修】connect_ssh 明文密码经 mcp_report 展示在前端状态面板
- **位置**：`src/mcp_server.py:835`（_args_summary）
- **问题**：tools/call 后把完整 args JSON 上报 /api/ai/mcp_report，password/key_path 无脱敏；SSH 参数 JSON 通常不足 120 字符截断上限，密码完整保留；_mcp_calls 常驻 50 条，sense.js 5s 轮询渲染「最近调用」。
- **失败场景**：AI 连设备后，SSH 密码明文出现在 MCP 状态面板，同屏旁观/截屏即泄露。
- **修法**：_args_summary 中对 password/key_path 替换为 "***"。

### 16. 【✅已修】search_log 提示「用 offset 续搜」但工具没有 offset 参数
- **位置**：`src/mcp_server.py:364`
- **问题**：has_more 提示用 offset 续搜，但 inputSchema 只有 path/query/limit，_dispatch 忽略未知参数 → AI 按提示续搜拿回与第一次完全相同的命中，误读为续页，永远翻不到 500 名之后。后端 /api/log_search 的 offset+count_total 能力存在但 MCP 层没接。
- **修法**：给 tool_search_log 加 offset 透传（inputSchema + _get 参数表），或改提示只说提高 limit。

### 17. 【✅已修】索引共享状态无读保护：并发 build 重置 offsets 时在途 search/get_page 直接 IndexError
- **位置**：`src/log_index.py:106`（配合 app_state.py:190）
- **问题**：build() 只在锁内，search/get_page 的读取循环在锁外逐迭代实时读 self.offsets[i]；全量重扫第 106 行 `self.offsets=[0]` 重绑后 total 到 117 行才更新——在途循环按旧 total 索引 1 元素数组 → IndexError → 500。_append_scan 异常路径（154-159 行）清空 offsets 同理。
- **失败场景**：G 级日志 20s 全量搜索期间日志被外部截断（`type nul > log`）→ 另一 tab 翻页触发重扫 → 搜索线程 IndexError 500。
- **修法**：循环前把 offsets/total 各取局部快照；半态修复：新 list 构建后整体替换而非原地清空。

### 18. 【✅已修】搜索稀疏窗口 3×RES_WIN 边界滞回死区：永久「加载中」+ 无限回载循环
- **位置**：`web/js/log-viewer.js:475`
- **问题**：resEnsureRange 滞回只看浏览点 hitIdx 是否在窗口内；hitIdx ∈ [resWinEnd-5, resWinEnd) 时 inWin=true 不换窗，但可视/预载区已越过 resWinEnd → 回载响应被窗口过滤全部丢弃 → renderLogResults 再触发 resEnsureRange 发现同段缺失再发 → 无限循环。验证者确认实际影响带比报告更宽（约 2000 命中宽）。
- **失败场景**：200 万命中下滚动到第 300,000 号附近停下 → 可视区永久「✳ 加载中…」，前端无限循环请求，直到滚过边界。
- **修法**：滞回判断前先检查 `needEnd > resWinEnd || needStart < resWinStart` 强制扩窗/换窗。

### 19. 【✅已修】doLogSearch 无取消/代次机制：取消的搜索复活 + 新词回车被静默吞掉
- **位置**：`web/js/log-viewer.js:431`
- **问题**：全量扫描（G 级数秒）置 searching=true 但无代次令牌；清空输入框复位状态不能取消在途请求，响应到达无条件写回旧词结果并自动跳转；扫描期间新词回车命中 `if (ls.searching) return` 被静默吞掉。讽刺的是 resFetchRange 已实现 myQ 代次比对，唯独全量首扫没有。
- **失败场景**：搜「foo」扫描中清空输入框 → 数秒后 foo 的结果列表/计数复活、主视图自动跳转，与空输入框自相矛盾；改输「bar」回车 → 无反馈，最终展示 foo 的结果。
- **修法**：加代次令牌 ls.searchGen++，响应回来比对 gen 与当前输入值不一致即丢弃；清空时同步作废在途搜索。

### 20. 【✅已修】侧栏 ✕ 对 hex 标签走 closeConnection，绕过脏确认
- **位置**：`web/js/sidebar.js:149`
- **问题**：关闭分派 isLog?closeLogViewer : isEdit?closeEditorTab : closeConnection——hex（meta.kind==='hex'）落入 closeConnection，不检查 conn.dirty 直接清理并发一个必 404 的 /api/disconnect；标签栏 ✕ 则走 closeEditorTab 有脏确认。同一 tab 两个入口行为不一致。
- **失败场景**：hex 查看器改了若干字节（标题带 *），点侧栏该项 ✕ → 无确认直接关闭，修改全丢。
- **修法**：分派补 hex 分支走 closeEditorTab；closeConnection 兜底检查 confirmClose。

### 21. 【✅已修——随 #4 一并】hex 查看器渲染崩溃补充（与 #4 同文件不同路径）
- **位置**：`web/js/hex-viewer.js:168-173`（byteAt）+ grpVal
- **问题**：editable 路径 byteAt 对 ≥512KB 偏移返回 undefined，grpVal 的 `BigInt(undefined)` 抛 TypeError 且发生在 canvas.innerHTML 清空前 → 旧行 DOM 原地保留、滚过去空白（只读窗口模式有 return 0 兜底，editable 无）。
- **修法**：与 #4 一并处理；byteAt 越界返回 0 做防御。

---

## 🟢 轻微（5 项）——体验/累积

> ✅ **2026-09-05 全部修复完成**（#22–#26），审查情况见文末「中等+轻微组修复审查记录」。

### 22. 【✅已修】keepalive 停止标志在旧线程醒来前被重置——重连一次净增一个线程
- **位置**：`src/ssh_conn.py:56`
- **问题**：重连时 `_keepalive_stop=True` 后 join(timeout=1)，旧线程阻塞在 sleep(30) 必超时；随后标志被重置 False，旧线程醒来把新连接当自己的继续跑——多次闪断后数十个 keepalive 并发 send_ignore。
- **修法**：改 per-thread threading.Event；sleep(30) 拆成可中断小段轮询；绝不在 join 超时后重置标志。

### 23. 【✅已修】文件同尺寸替换/轮转穿越旧尺寸时索引静默错位
- **位置**：`src/log_index.py:67`
- **问题**：仅凭 cur_size==_built_size 判「未变」；同路径替换为更大新文件后 _append_scan 从旧文件行偏移切入新文件中部，错位偏移被 _save_cache 持久化跨重启存活，页面持续乱码无报错。.idx 加载仅凭 mtime 采信，同尺寸原地替换不失效。
- **修法**：.idx 头部记录建索引时文件大小+首 4KB 哈希，加载对比；cur_size==_built_size 时校验文件尾哈希。

### 24. 【✅已修】分栏拖拽/窗口 resize 不重渲染搜索结果列表
- **位置**：`web/js/log-viewer.js:640`（_splitUp）+ terminal-core.js:299
- **问题**：两处只调 renderLogSlice 主视图；容器拉高不触发 scroll，renderLogResults 的相等性短路继续成立 → 底部新增区域空白。作者在 toggleLogSearchPane 已知此问题（展开时复位 resRenderStart），拖拽/resize 是遗漏。
- **修法**：_splitUp 与 resize 处理对 log 连接同时复位 `ls.resRenderStart=-1` 并调 renderLogResults。

### 25. 【✅已修】waitResHitThenJump 无代次校验不去重：并发轮询后到者覆盖落点
- **位置**：`web/js/log-viewer.js:529`
- **问题**：轮询器不校验 searchQ/searchIdx 是否已被改变、不撤销前一个轮询器；3s 窗口内再回车「下一个」会双轮询，后完成者覆盖主视图落点，与列表高亮不一致。
- **修法**：timer 存 ls._jumpTimer，新跳转前 clearInterval；轮询体校验 hitIdx === ls.searchIdx。

### 26. 【✅已修】C 系语言正则大纲统一取 m[2]，但 c 组规则只有 1 个捕获组
- **位置**：`web/js/editor.js:491`
- **问题**：struct/class/函数三条正则只有 1 个捕获组（名字在 m[1]），统一取 m[2]=undefined → .js/.ts/.java/.go/.rs 等文件大纲全部显示「函数 undefined」「类 undefined」（.c/.cpp 走 tree-sitter 不受影响）。
- **修法**：c 组正则补第二捕获组，或取名改用 `m[m.length-1]`。

---

## 备注
- 被对抗验证反驳剔除的 3 项未收录（1 项验证 agent 被安全分类器拦截，未定）。
- 修 #1/#2/#4/#5/#6 时建议顺手补测试：均属「先复制后删除」类路径，改完用假数据目录回归（严禁真实数据当测试对象）。
- exe 分发需重打包（python src\build.py）才会带上修复。

## ✅ 严重组修复审查记录（2026-09-05）

| # | 修法 | 审查结论 |
|---|------|---------|
| 1 | migrate 切换段补 `global DATA_DIR, STATE_DIR, CMD_LIB_FILE`（与 LOG_DIR 同款），函数体首行声明 | 初版 global 放函数中部触发 SyntaxError（used prior to global declaration），已移至函数首；现 server 与 _st 双绑定同步更新 |
| 2 | check/migrate 双侧加 `tgt.startswith(cur+sep) or cur.startswith(tgt+sep)`（大小写归一） | 初版 check 端漏 lowercase，已补；两侧判定对称 |
| 3 | os.walk 递归复制 + unmerged 清单，rmtree 前核对全覆盖，计数改 per-directory | 初版 unmerged 未 per-directory 复位，前一目录失败会阻止后一目录删除（保守方向，但已改精确计数） |
| 4 | 前端分块循环 fetchChunk 拼 Uint8Array(size)；后端 hex_save 长度校验拒绝不一致写回 | 审查发现后端校验会误伤 ihex（文本长度≠镜像长度），已加 .hex/.ihx 例外 |
| 5 | buildEditorTab 入口统一兜底：isNote 且 content 为字符串先 JSON.parse（失败置 null） | 覆盖拖入与「最近打开」全部入口，比只改 openFileSmart 单点更稳 |
| 6 | 保存时维护 extSeg，跨 64KB 边界先发 `:02000004 XXXX`，校验和仅低 16 位自洽 | 首块 seg=0 也发扩展记录（合法，个别烧录器更稳）；EOF 记录保持 |
| 7 | 死代码恢复为 `def cmd_overview(url):`，need_running 内 sys.exit 后残留清除 | overview/obs/o 三种用法恢复可用 |
| 8 | 758 同一 try 块补 `sys.stdin.reconfigure(encoding="utf-8")` | 源码模式与 exe 模式行为对齐 |
| 9 | start() 内 try/except _start_log 降级 log_fp=None；api_connect 串口/SSH except 分支均 close() 半构造对象兜底 | 双保险：异常不逃逸 + 逃逸了也回收 |
| 21 | byteAt editable 分支 `conn.bytes[i] ?? 0` 越界兜底 | 随 #4 分块修复后理论上不再越界，保留防御 |

语法校验：py_compile 全过（server/app_state/hex_files/serial_cli/mcp_server/base_conn），node --check 全过（hex-viewer/editor）。未做运行时回归（工具正在运行，改动需重启后端生效）。

## ✅ 中等+轻微组修复审查记录（2026-09-05）

| # | 修法 | 审查结论 |
|---|------|---------|
| 10 | 补丁改挂 `BaseConnection.append_line` | SerialPort 未覆盖 append_line（已核实无 `def append_line`），serial/ssh 经基类一并覆盖；补丁在两个子类 import 后执行，绑定安全 |
| 11 | `/api/log/<name>` 改走 `_resolve_log_path` | 与其余 8 个日志路由统一防线；绝对路径 + LOG_DIR 内规范化双重校验 |
| 12 | httpfile `_serve` 校验追加拒绝含 `:` 的 name | posixpath.basename 本会剥掉 `C:` 前缀，此校验为纵深防御；`:xxx`（无盘符冒号名）同被拒 |
| 13 | `_io_reconnect` 退避 sleep 改 1s 可中断循环 + `_io_close`/`_io_open` 前后共 3 处 alive 检查，`_io_open` 后发现已 close 立即 `_io_close` 回收 | 幽灵会话窗口全关闭；退避期间断开最迟 1s 退出 |
| 14 | 新增 `_BackendError` + `_httperr_msg`；HTTPError 先于 URLError 捕获，读响应体 err 字段直接返回；重试路径的二次 `_dispatch` 也补 HTTPError 捕获 | 审查发现初版内层重试再遇 HTTPError 会落外层 URLError 分支又误报，已补；`from None` 不暴露双层 traceback |
| 15 | `_args_summary` 对 password/key_path 值替换为 `***`（构造脱敏副本再 dumps） | 原始 args 不动（上报摘要才脱敏）；截断逻辑保持 |
| 16 | tool_search_log 加 offset 参数（inputSchema+描述+_dispatch 透传），count_total 按 offset 切换，结果提示返回 next_offset 续搜游标 | 审查发现初版把 offset 误描述为「命中序号」——后端 offset 是行偏移游标，已改正确语义并在输出中回传 next_offset |
| 17 | get_page/search/ts_list/search_page 读路径局部快照 offsets，total 按 `len(offsets)-1` 钳制 | 审行时回归发现纯快照仍会捕获 (旧 total, 新 offsets) 交叉态 IndexError——快照后按 offsets 实际长度钳制才自洽；ts_list/search_page 审查发现同缺陷一并修。并发重扫 3 读者×30 重建压力测试 0 异常 |
| 18 | `resEnsureRange` 滞回前先判 `needStart/needEnd` 越窗（outOfWin）强制换窗 | 覆盖验证者实测的 ~2000 命中宽影响带；滞回正常路径不受影响 |
| 19 | doLogSearch 加 `ls.searchGen` 代次令牌：清空输入/换词 gen++ 作废在途响应；同词重复回车仍忽略 | 审查发现初版代次判断含冗余分支，已简化；清空输入的 input 事件处同步 gen++ 作废（含 loadLogViewer 复位处） |
| 20 | sidebar 分派 isEdit 补 `|| kind==='hex'`；desc 加 hex 标识 | closeEditorTab 走 conn.confirmClose（hex tab 有 _hxConfirm）实现脏确认；_edCloseNow/_edStatText 对 hex conn（无 monaco/ta/isNote）安全降级 |
| 22 | `_keepalive_stop` 改 per-thread `threading.Event`，`_io_open` set 旧 evt + 配新 evt，绝不重置；sleep(30) 拆 300×0.1s 可中断 | 审查发现初版入口有一段冗余的 300×0.1s 等待循环，已删（改后首个 keepalive 立即发，随后 30s 周期） |
| 23 | `_head_hash`（首 4KB md5，追加不误伤）+ build 入口哈希校验；.idx 升 v2 头部 `<total><built_size><32B 指纹>`，加载对比 | 初版用末 4KB 哈希——审查发现追加场景文件尾必变会误伤正常追加，改首 4KB；初版 `_append_scan` 引用了 build 作用域的 head 变量 NameError 被 except 吞掉（运行时回归捕获，已改为不重算）；另发现全量扫描路径从未设 `_loaded=True` 的既有 bug（被 .idx 加载路径掩盖），已补。回归 7 场景全过 |
| 24 | `_splitUp` 与 window resize 对 log 连接复位 `resRenderStart=-1` 并调 renderLogResults | renderLogResults 为全局函数（非模块化脚本），terminal-core.js 可直接调用 |
| 25 | waitResHitThenJump：timer 存 `ls._jumpTimer` 先 clearInterval 再启新；轮询体校验 searchQ/searchExcludeQ/searchIdx | closeLogViewer 补 clearInterval 清理残留轮询器 |
| 26 | `_outlineCodeEntries` 取名改 `m[m.length-1]`（py 组 2 捕获组取 m[2]、c 组 1 捕获组取 m[1]） | 未改正则（改正则会牵动 3 条规则的组结构），取最后捕获组对两组统一正确 |

运行时回归：log_index.py 7 场景全过（建索引/追加续扫/同尺寸替换全重扫/.idx v2 往返/替换后不采信/加载后续扫/并发重扫 0 异常），测试用临时目录假数据。其余文件 py_compile + node --check 全过；前端交互逻辑未做运行时回归（需重启后端+刷新页面验证）。

遗留说明：
- 改动需重启后端进程 + 前端强刷才生效；MCP server 需重启 Claude Code 会话或重连。
- exe 分发需重打包（python src\build.py）。
- #17/#23 的锁-free 快照方案为保守正确性（缺行留给下次读取），不追求读到中断瞬间的完美一致。

