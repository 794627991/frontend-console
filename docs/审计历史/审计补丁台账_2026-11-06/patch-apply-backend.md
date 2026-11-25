# 后端补丁干跑应用终审报告（patch-apply-backend）

- 审计对象：doc/patch-log.md 后端 16 件补丁的**终版 diff**（P-1/2/3/4/7/8/9/10/13+R2-11/15/17/18/19/20/23/R2-13），终版出处按任务清单取（P-4=R5-1、P-7=R5-2、P-10=R6-1 以 r4 报告修正 diff 为蓝本、P-18=R2-10+R6-2）
- 审计方式：把 diff 真实应用到源码副本，逐件 py_compile，再做 orig/work 双副本行为对照。
  - diff 文本由脚本按台账行号**程序化提取**，没有手抄。
  - 每个上下文行和删除行都在当前阶段副本中做锚点定位。
  - nav_index.py 七件按依赖序逐件叠加，每阶段留快照；另做逆序叠加和依赖倒置的冲突检查。
- 环境：Windows 10 19045 / Python 3.14.7 / ACP=936 / vendor readtags 6.2.0 / sqlite 3.50.4 / Flask 3.1.3
- 工作区：`%TEMP%\patch_apply_be\`（= `C:\Users\gaoyi13\AppData\Local\Temp\patch_apply_be\`）

**铁律核验（报告提交前最后一步执行）**：

1. 7 个目标源文件的 SHA256 与开工基线逐一比对，`sha256sum -c` 结果为 7/7 OK。
2. `git status` 显示 src/、tests/、vendor/ 无改动，只有会话前就存在的 `?? doc/`。
3. 真实索引库 `D:\Frontend Console\nav\*` 的 meta.json/tags.db 修改时间仍为 2026-11-05，均早于本次会话。
4. 8867 服务器只发了 GET 只读查询；`/api/resources/status` 内部会写 `.fcpk.json` 缓存，所以没有调用，改为直接读状态文件。
5. 副本树使用 stub 版 `app_state`。原因是真实 app_state 在 import 时会执行迁移逻辑，而用户配置的 `data_dir=D:\Frontend Console`，直接导入会让 `_nav_root()` 指向真实索引库。

---

## 一、结论先行

**16 件全部可以落到副本上，16/16 py_compile 通过**；nav_index.py 的 10 个叠加阶段也逐阶段编译通过。但只有 **7 件**能按台账 diff 逐字节应用，并且应用后行为正确、没有新问题。

| 裁决 | 件数 | 补丁 |
|---|---|---|
| **APPLY-CLEAN**（逐字节可用、行为对） | 7 | P-3、P-7、P-8、P-17、P-19、P-20、R2-13 |
| **DIFF-MISMATCH**，归位或合成后行为对 | 5 | P-2、P-9（缩进级）；P-4、P-18、P-10（链式合成） |
| **DIFF-MISMATCH**，落位后仍有新问题 | 3 | P-1、P-13（同条的 R2-11 自身干净）、P-15 |
| **APPLY-ISSUES**（字面可用，补丁本身有缺陷） | 1 | **P-23** |

### 终版裁决表

"字面"列取值：L 表示逐字节命中；W 表示仅缩进不同、锚点唯一；S 表示 diff 里有占位符或凭空上下文，需人工语义落位。

| 补丁 | 目标 | 字面 | 编译 | 行为（orig → work） | 裁决 | 分批 |
|---|---|---|---|---|---|---|
| P-1 | nav_index | S（整块 0 命中，7 处对不上） | OK | 交替 400 次：400 活连接 / 399 孤儿 / 句柄 +800 → 2 / 0 / +4。新问题：锁内 close 导致**跨库查询陪等 534–593ms** | DIFF-MISMATCH → APPLY-ISSUES | 谨慎批（带 3 行修正） |
| P-2 | nav_index | W（diff 8 空格，现状 12） | OK | `prefix('foo')` 从 `[]` 变为 `['FooBar']` | DIFF-MISMATCH（缩进）→ CLEAN | 立即批 |
| P-3 | nav_api + nav_index | L + L | OK | S37-2 端到端：重建后 sqlite 静默降为 readtags、残留 tmp → 保持 sqlite、零残留 | **APPLY-CLEAN** | 立即批 |
| P-4（R5-1） | nav_index | S（argv 续行上下文对不上；prefix 依赖的 `ql` 行只在已作废的 R2-8 里） | OK | 中文查询从全盲变为 E1–E12 全对；真实大库结果与服务器 sqlite 基准一致 | DIFF-MISMATCH → 合成后 CLEAN | 谨慎批（与 P-18 同批） |
| P-7（R5-2） | nav_index | L（old 7 行逐字节） | OK | 原来 tmp 残留、遇读者立即失败 → 现在清理干净、109ms 重试命中、超窗干净失败 | **APPLY-CLEAN** | 立即批 |
| P-8 | vcs | L | OK | 网络盘上的真删文件原被当误报吞掉 → 现在可见 | **APPLY-CLEAN** | 立即批 |
| P-9 | server | W（diff 0 缩进，现状 8） | OK | fsym 原被静默丢弃、冲突漏检 → 现在落盘、冲突返回 400 | DIFF-MISMATCH（缩进）→ CLEAN | 立即批 |
| P-10（R6-1） | res_boot | S（四层链）；r4 蓝本本身 L，old 17 行 | OK | 外部依赖面板无 codegraph → 五种形态契约全对 | DIFF-MISMATCH（链式）→ 合成后 CLEAN | 谨慎批 |
| P-13 + R2-11 | nav_index | S + S | OK | delete 残留 tags.db → 删净；rebind WinError 5 → 成功。新问题：**外部锁时 delete 返回 HTTP 500** | P-13：DIFF-MISMATCH → APPLY-ISSUES；R2-11：→ CLEAN | P-13 暂缓批；R2-11 立即批 |
| P-15 | nav_api | S（上下文误中非目标端点 cg_delete） | OK | 相对、数字、布尔 root 原会真的启动建库任务 → 400；空 root 报错文案错位（轻） | DIFF-MISMATCH → APPLY-ISSUES（轻） | 立即批（建议调序） |
| P-17 | nav_api | L | OK | 切到 sqlite 少计 20480、切回又多计 → 每一步误差都是 0 | **APPLY-CLEAN** | 立即批 |
| P-18（R2-10） | nav_index | L×3；lookup_ci 子段对不上 | OK | `lookup('-l')` 原全量 dump → 1 行；`prefix('-l')` 原返回全库 → `['-l']` | DIFF-MISMATCH → 合成后 CLEAN | 谨慎批（与 P-4 同批） |
| P-19 | vcs | L | OK | `#`、`%20` 目录过滤原静默失效 → 7 种目录形态全对 | **APPLY-CLEAN** | 立即批 |
| P-20 | claude_default | L（位置漂移 3 行） | OK | 去掉 docstring 后函数体 AST 哈希不变 | **APPLY-CLEAN** | 立即批 |
| **P-23** | build | L（两处） | OK | **补丁后抛 `TypeError: 'module' object is not callable` 且被吞掉，补丁无效**；改一个词后生效 | **APPLY-ISSUES** | **暂缓批** |
| R2-13 | nav_index | L | OK | 原来失败 1 次就建库失败 → 失败 ≤2 次能成功，3 次干净失败 | **APPLY-CLEAN** | 立即批 |

### 本轮新发现（r1–r5 都没有记录）

1. **P-23 照原样落码无效，部分机器还会回归**。diff 写的是 `import shutil as _sh_which` 加 `_sh_which("npm")`，等于把模块当函数调用。异常被外层 `except Exception: pass` 吞掉，所以 S37-12 原封不动。对已有 npm.exe shim 的机器（例如 volta），旧代码本来能工作，现在会恒失败。r1 只记了"import 冗余"，判了 PASS with notes。改一个词 `from shutil import which as _sh_which` 后实测两处都生效。
2. **P-1 存在两类问题**。
   - **diff 字面对不上**：与现状有 7 处不符（行尾注释、不相邻的声明行、被省略的 docstring 和注释、单行与四行写法差异）。r1 说"diff 本身无漂移"，但它只核对了 :915 一行。
   - **锁内 close 引发全局卡顿**：`_old.close()` 会阻塞，直到同一连接上的在途语句执行完。实测中在途查询本身照常完成，r1 担心的"close 杀在途查询"在 Python 3.14 上并不发生。问题在于这个 close 发生在全模块共享的 `_cache_lock` 里，等待期间所有库的查询都被一起卡住，实测 534–593ms，orig 只要 2ms。改成锁外 close 后跨库查询恢复到 1–2ms，已实测。
   - **审计记录不符**：台账终态表写 P-1"r4 后端 PASS"，但 r3/r4/r5 报告里没有出现 P-1；它只在 r1 审过一次，r1 的 notes 没有任何修订轮落实。
3. **P-4 的"一页写全"漏了一行**。prefix 桥分支用到的 `ql = q.lower()` 只出现在已作废的 R2-8 的 `+` 行（PL:948）里；R4-1 把它当上下文行，R5-1 没有收录。照 R5-1 加 R4-1 落码时如果漏掉这一行，所有非 ASCII 前缀查询（中文 Ctrl+T）都会 NameError，已实测。纯 ASCII 查询不受影响，所以英文回归测不出来。
4. **P-4 与 P-18 是只在运行期才暴露的硬依赖**。R5-1 的 lookup_ci 段 `-` 行对现状逐字吻合，单独应用会字面成功，py_compile 也通过，但运行时**所有** lookup_ci 调用（包括 ASCII）都抛 `TypeError: unexpected keyword argument 'names'`，已实测。所以两件必须同一批落码。
5. **P-10 的注册行在终版链里只以上下文形态出现过**。`_PROBES["codegraph"] = _probe_codegraph` 在 R2-9 里是上下文行，R4-2 和 R6-1 蓝本都没有它。漏写后 codegraph 会静默显示为 `unknown`，detail 是 `'codegraph'`，已实测。另外这一行的注释写的是 `(state, fix, detail)`，与实际契约 `(state, ver, detail)` 不符。
6. **P-13 的 api 层只有一句话描述，没有 diff**。外部句柄占住库文件时，work 版 `/api/nav/delete` 返回 **500 HTML**，orig 是 200 `{ok:true}` 静默残留。而且 rmtree 中途失败时 meta.json 已被删掉，库会从列表消失，成为不可见孤儿（两边都会出现）。按 r1 建议补上 api 层捕获后，实测返回 200 `{ok:false}`，释放后重试能删净。
7. **P-15 的两行上下文 `root=…` 加 `if not root:` 在全文件命中两处**：一处是目标 nav_delete（:153-154），另一处是**非目标**的 nav_cg_delete（:315-316）。真正的目标 build、reindex 却没有这种相邻结构，机械替换会改错位置、漏掉正确位置。
8. **缩进级不符照抄必炸**。P-2、P-9、P-13、R2-11 四件，如果把 `+` 行原样粘贴，四件都在 import 期 IndentationError，已实测，与 R5-3 FAIL 同一类。必须按现状缩进归位。
9. **真实数据佐证**：4 个真实库的 `/api/nav/libs` 尺寸全部失真（S37-9）。主工程库 f93dd 少计 110,833,664 B（约 105.7MB），211c57 多计 12,080 B。P-17 只修正之后的切档，**不会回填存量库**，落码后需要对这些库做一次 reindex 或重建。

---

## 二、方法与判定口径

- **副本树**：`orig\`（原样）和 `work\`（叠加终版）两棵树，各含完整 src/、vendor/ctags/、tests/test_vcs.py，app_state 换成 stub，所有路径钉在副本树内。行为探针在 orig、work 上各起独立进程运行，并用 `python -I` 隔离。
- **应用引擎**：脚本是 `scripts\engine.py`，按台账或 r4 报告的行号区间提取 diff，逐行给出锚点状态：EXACT、WS（仅空白不同）或 ABSENT。
  - **L 模式**：上下文行加删除行组成的连续块逐字节唯一命中。
  - **W 模式**：去掉缩进后唯一命中，`+` 行按实测缩进差重新缩进。
  - **S 模式**：diff 含 `...` 占位、伪代码上下文或凭空行，按脚本里写明的锚点落位；可用时取 diff 的 post-image（上下文行加 `+` 行）重建。
- **叠加顺序**（nav_index.py）：P-7(R5-2) → P-2 → P-1 → P-13 → R2-11 → P-3(idx) → R2-13 → P-18(R2-10) → P-4(R5-1 + R4-1 prefix 形态) → R6-2 精确化一行。每阶段的快照在 `stages\nav_index\01..10_*.py`。
- **裁决口径**：
  - APPLY-CLEAN：L 模式，编译通过，行为正确。
  - DIFF-MISMATCH：diff 与现状对不上（逐行记录），并注明归位或合成之后的结果。
  - APPLY-ISSUES：应用后出现新问题，或补丁本身有缺陷。
  - 缩进级不符也记为 DIFF-MISMATCH，因为台账方法论第 3 条明确"含缩进"，R5-3 也正是因缩进漂移判 FAIL。

---

## 三、逐件详情

### P-1（D-1，P1）多槽缓存——DIFF-MISMATCH → 落位后 APPLY-ISSUES

**终版出处**：PL:51-123。**这件从未被整体应用过，也只审过一次（r1）**。

**字面应用**：整块 0 命中，空白容错也是 0 命中。7 处不符如下：

| # | 台账行 | diff 写法 | 现状 | 判定 |
|---|---|---|---|---|
| 1 | PL:52 | `-_tagdb_cache = {"key": None, "db": None}` | :882 同一句，但带行尾注释 `# (ld, tags_mtime, db_mtime) → _TagDB` | ABSENT |
| 2 | PL:53 | `-_tagdb_orphans = []`，写成与上一行相邻 | 实际在 :939，夹在 _get_tagdb 与 _close_tagdb 之间，相距 57 行 | 位置不符 |
| 3 | PL:61→62 | `def _get_tagdb` 之后直接接 `db_p = …` | 中间有 :906-909 共 4 行 R35-3 docstring | 上下文缺行 |
| 4 | PL:77→78 | `except Exception:` 之后直接接 `return None` | 中间有 :925-926 两行 R35-4 注释 | 删除块缺行 |
| 5 | PL:81 | `-            db.close()` | :930 带行尾注释 `# 他者先到——弃用自己的` | ABSENT |
| 6 | PL:106→108 | `def _close_tagdb` 之后直接接 `with _cache_lock:` | 中间有 :943-944 两行 R35-2 docstring | 上下文缺行 |
| 7 | PL:115-116 | `try: d.close()` / `except Exception: pass` 两行写法 | :952-955 是四行展开写法 | ABSENT |

**落位方式**：声明区整行替换，`_tagdb_orphans` 行连同其后两个空行一并删除；_get_tagdb 和 _close_tagdb 按 diff 的 post-image 整函数重建。

**完整性核对**：

- 全文件 grep `_tagdb_orphans`、`_tagdb_cache["key"]`、`_tagdb_cache["db"]`：**零残留**。
- 新结构 `_tagdb_cache`、`_tagdb_keys` 的引用全部在三个函数之内，无测试依赖旧结构（tests/ 零引用）。
- post-image 会丢掉以下现状文字：R35-3 docstring 4 行（其中第③条"挂 orphan 列表"在 P-1 后本来就失实）、R35-4 注释 2 行（说明损坏库为何回退，**建议保留**）、R35-2 docstring 2 行（被新的一行 docstring 取代）。
- definition() 里 :1339 的注释"由 _tagdb_cache 生命周期管理（换库时关旧）"在 P-1 后失实，diff 没有覆盖。

**行为对照**（fixture 是两个真实小库的只读拷贝）：

| 探针 | orig | work |
|---|---|---|
| 两库交替 200 轮（400 次切换）后 | 新建 400 个连接 / 400 个存活 / **399 个孤儿** / 句柄 **+800** | 新建 2 个 / 2 个存活 / 无孤儿 / 句柄 +4 |
| 调用 `_close_tagdb()` 后 | 存活 0，句柄回到基线 | 存活 0，句柄回到基线 |
| 同库 tags.db mtime 变化 | 旧连接进孤儿列表，仍然打开 | 旧连接被关闭 |
| 竞态："他者先到"分支 | 关掉自建连接、返回他者的 | 同 orig |
| **在途查询期间同库重建**（T1 跑 800ms 慢查询） | 触发线程 1–3ms，**其他库查询 2ms** | 触发线程 582–668ms，**其他库查询 534–593ms** |
| 同上，改为锁外 close 的变体 | — | 其他库查询 1–2ms，只有触发线程自己等待（612–636ms） |

另有一个测量说明：首次测句柄时，ctypes 没有声明 argtypes，64 位伪句柄被截断，`GetProcessHandleCount` 调用失败，读数恒为 0。正是 res_boot.py 文档里警告过的那个坑。改为显式声明类型后重测，才得到上表的 +800 / +4。

**裁决**：泄漏的根因确实被结构性消除。但存在三类问题：diff 字面不可用；锁内 close 是新的全局阻塞点（触发条件是"同库 mtime 变化但没有经过 `_close_tagdb`"，频率低，可能出现在 build/reindex 的 replace 与 `_invalidate_cache` 之间的窗口，或外部修改了库文件）；docstring 和注释欠账。**建议按附录 A.3 改为锁外 close 后再落码**，并同步处理 R35-3 docstring 和 :1339 注释。r1 notes 里的 LRU 上限：用户现有 4 个库，暂时不必做。

### P-2（S37-1）memory 档 prefix 大小写——DIFF-MISMATCH（缩进级）→ 归位后 CLEAN

- **终版出处**：PL:146-147。W 模式：diff 的 `-` 行缩进 8 空格，现状 :848 在 for 循环内是 12 空格，缩进差 +4，锚点唯一。照抄 `+` 行会触发 `IndentationError: expected an indented block after 'for'`，已实测。
- **行为**：`_MemBackend.prefix('foo')` 从 `[]` 变为 `['FooBar']`，`prefix('foob')` 同样。fixture 是真实库 7e436 的只读拷贝。
- **前提核实**：全仓 `.prefix(` 只有一个调用点 symbols():1152，传入的是 `qlow`（已 lower）。所以直接调 `prefix('Foo')` 在 work 下返回 `[]` 不构成问题。

### P-3（S37-2+S37-3）build 前置关连接 + 阶段 4 replace 重试——APPLY-CLEAN

- **字面**：api 段 PL:172-178 在 nav_api.py:103 命中（old 4 行）；idx 段 PL:182-192 在 nav_index.py:671 命中。`def work():` 在文件中出现 3 次，但带上下文的整块唯一。
- **S37-2 端到端**（Flask 测试客户端，真跑 vendor ctags）：
  1. 先以 sqlite 档建库；
  2. 通过 `/api/nav/definition` 查询一次，服务端缓存住连接；
  3. 再经 API 重建。

  | | orig | work |
  |---|---|---|
  | 重建后 meta.backend | **readtags**（静默降级） | sqlite |
  | 日志 | `tags.db 构建失败（[WinError 5] 拒绝访问…）——回退 readtags 模式` | 正常完成 |
  | tmp 残留 | `tags.db.tmp` | 无 |
  | 重建期间 `_close_tagdb` 调用次数 | 1（只有收尾那次） | 2（前置一次加收尾一次） |

- **直接调用 `_build_tag_db`，且目标库连接已缓存**：orig 14ms 抛 `PermissionError(5)` 并残留 tmp；work 67ms 成功（第 2 次重试前 `_close_tagdb` 释放了连接）。
- r1 的两条 notes 没有落实，都属于轻微项：close 与 sleep 的先后顺序；3 次全失败时回退分支不删 tmp（下次建库开头会自删，可自愈）。

### P-4 终版 R5-1（C-1 中文桥）——DIFF-MISMATCH → 与 P-18 合成后 CLEAN

**终版出处**：R5-1（PL:1283-1327），加上 R5-1 所说"prefix 过滤保持 R4-1 已写形态"（PL:1184-1192），加上 R6-2 精确化一行（PL:1506-1507）。

| 段 | 台账行 | 结果 |
|---|---|---|
| `_run` 桥分支 | PL:1285-1295 | **0 命中**：上下文是 argv 两行续行写法，而 R2-10 落地后是 3 行注释加单行 argv。按 r4 note① 落位到 `return []` 之后、R2-10 注释之前，语义等价 |
| `_run_raw`、`_ascii_cache`、`_ascii_dump` | PL:1297-1318 | 纯 `+` 段，落位在 `_run` 之后、`@staticmethod _parse` 之前 |
| lookup_ci 重申段 | PL:1320-1324 | L（现状 :798-799 逐字吻合） |
| prefix（R4-1 形态） | PL:1184-1192 | **0 命中**：上下文 `ql = q.lower()` 不在 `_ReadtagsBackend.prefix` 里（同样的文本只在 `_TagDB.prefix`:717 和 substring:805 出现），**唯一出处是已作废 R2-8 的 `+` 行 PL:948**。取 post-image 落位 |
| R6-2 | PL:1506-1507 | L（与 R5-1 的 `+` 段 12 空格缩进逐字吻合） |

**行为**：fixture 由真 ctags 生成 12 个 UTF-8 符号，另注入一个原生格式的 `-l` 条目。spy 记录每次 readtags 的参数尾部、超时和输出行数。

| 探针 | orig | work |
|---|---|---|
| E1 `prefix('中文函数')` | `[]` | `['中文函数']`（dump，超时 60） |
| E2 `prefix('get_中文')` | `[]` | `['get_中文']`（`-p g`） |
| E3 `prefix('Get_中文')` | `[]` | `['Get_中文']` |
| E4 `lookup_ci('get_中文')` | `[]` | `['Get_中文','get_中文']`（`-i -p g`，保留 -i 的价值得到验证） |
| E5 `lookup_ci('中文函数')` | `[]` | `['中文函数']`（dump，超时 60） |
| E6 `lookup_ci('PROBE_WORK')` | 双命中 | 双命中（走 `[-]` 转义直查） |
| E7 `lookup('中文函数')` | `[]` | 1 行（dump，**超时 60**，R6-2 生效） |
| E10 `lookup('-中文')` | `[]` | `[]`（干净失败，与 r3 新发现 1 同口径） |
| E11 `substring('中文')` | 4 个 | 4 个（不变） |
| E12 同实例 lookup、lookup_ci、prefix 各一次 | 3 次子进程，全部 0 行 | **1 次 dump**，被复用 |

**真实库交叉核对**（只读）：对真实大库 f93dd（110MB tags）直接调 `_ReadtagsBackend.lookup('test_replay_dedup末轮边界')`，orig 返回 `[]`，work 返回 `test_v4feed.py:352`，耗时 233ms。8867 服务器的 sqlite 档对同一符号的答案也是 `test_v4feed.py:352`，两者完全一致。

**链路隐患（均已实测）**：

1. 漏掉 `ql` 行时，`prefix('中文函数')` 和 `prefix('get_中文')` 抛 `NameError: name 'ql' is not defined`，纯 ASCII 的 `prefix('getX')` 正常。
2. 只应用 R5-1 而不带 P-18 时，lookup_ci 段字面命中、编译通过，但运行时 `lookup_ci('PROBE_WORK')` 和 `lookup_ci('中文函数')` 都抛 `TypeError: _run() got an unexpected keyword argument 'names'`。
3. R4-1 块里的 PL:1183 是一行注记，却写成了 `+` 行；照抄会触发 `SyntaxError: invalid character '（'`。

**裁决**：合成后的形态与 r3/r4/r5 的实验矩阵逐项吻合，行为正确；但台账里没有一份可以直接照抄的完整终版。合成终版见附录 A.1。

### P-7 终版 R5-2（D-2）`_write_json` 本体化——APPLY-CLEAN

- **字面**：在 :76 命中，old 7 行逐字节吻合，复现了 r4 的"7/7 MATCH"。`+` 行 13 行。
- **行为**（B1–B5）：

  | 场景 | orig | work |
  |---|---|---|
  | B1 正常写入（含中文） | 成功，无残留 | 成功，无残留 |
  | B2 dump 时 TypeError（值为 set） | 抛出，**残留 tmp** | 抛出，**tmp 已清理**，目标文件未被误写 |
  | B3 读者持有目标文件 60ms | 4ms 内 **PermissionError(5) 加残留 tmp** | **109ms 重试成功**，无残留 |
  | B4 读者持有 400ms | 立即失败并残留 tmp | 106ms 后可见失败，tmp 已清理，**旧内容完好** |
  | B5 深层目录不存在 | 成功 | 成功 |

- 签名 `(p, obj)` 不变，8 处写者不受影响。

### P-8（S37-4）网络盘 `!` 只在符号链接清单内隐藏——APPLY-CLEAN

- **字面**：PL:374-381 在 vcs.py:396 命中。
- **行为**：monkeypatch `_run`，喂入构造的 svn XML，并把 `_is_network_drive` 置为 True。

  | 场景 | orig | work |
  |---|---|---|
  | 清单为 {lnk, lnk_m, sub/lnk2} | 只保留 `foo.c:M`，隐藏 4 个，**真删的 `really_deleted.c` 被吞** | 保留 `really_deleted.c:!` 和 `foo.c:M`，隐藏 3 个（`Sub/LNK2` 经小写比对命中清单） |
  | 清单查询失败（空集） | 仍然无条件隐藏 3 个 | 隐藏 0 个，全部保留（安全侧） |

- **回归**：test_vcs 沙箱版在 orig 和 work 上都是 **32 PASS / 0 FAIL**。沙箱版只把两处 `from src.server import app` 换成注册了 vcs_bp 的迷你 Flask 应用（与该测试自己的 `t_changes_shallow` 写法相同），断言不变。

### P-9（S37-5）nav_keys 白名单补 fsym——DIFF-MISMATCH（缩进级）→ 归位后 CLEAN

- **字面**：W 模式，diff 是 0 缩进，现状 :1476 在 `api_theme` 内的 if 块里是 8 缩进。照抄会触发 `IndentationError: unexpected indent`，已实测。
- **行为**：用 AST 从两棵树的 `api_theme` 中抽出 `_HK_RE` 赋值和整个 nav_keys 块，单独执行。

  | 场景 | orig | work |
  |---|---|---|
  | POST 六键、fsym=f4 | 200，**fsym 被丢弃**，只存 5 键 | 200，6 键全部落盘 |
  | fsym 与 sym 冲突 | 200，冲突没检出 | 400"跳转快捷键不能为空且互不冲突" |
  | 旧客户端只发五键 | 200 | 400"nav_keys.fsym 不能为空" |

- **兼容性**：现行前端 nav.js:665 按六键发送，所以兼容。
- **现网状态**（只读）：真实 config.json 里 nav_keys 只存了 3 个键（def/ref/sym），`GET /api/theme` 原样返回这 3 个，前端用自己的默认值补齐。

### P-10 终版 R6-1（S37-6）codegraph 进入 MANIFEST——DIFF-MISMATCH（链式）→ 合成后 CLEAN

**四层链逐层应用**：

| 层 | 台账行 | 结果 |
|---|---|---|
| P-10 原文：MANIFEST | PL:415 上下文 `{"kind": "onlyoffice", ...},` | ABSENT（`...` 是占位符，且现状末项是 bili :63-64），落位在 MANIFEST 的 `]` 之前 |
| P-10 原文：lambda 注册 | PL:425 | 纯 `+` 行，落位在 `_PROBES` 字典之后 |
| R2-9：MANIFEST desc 改 fix | PL:965-970 | L |
| R2-9：具名函数加注册行 | PL:985 上下文 `_PROBES["codegraph"] = _probe_codegraph …` | **ABSENT**（P-10 落地后那里是 lambda），改为用具名函数加该行替换 lambda |
| R4-2 | PL:1202-1229 | L（old 12 行） |
| **R6-1 r4 蓝本** | R4:114-134 | **L，old 17 行**，复现 r5 的"17/17 EXACT" |
| R6-1 台账块内转写（仅做核对，未应用） | PL:1457-1472 | 4 行 ABSENT（PL:1464/1465/1468/1471），整块 0 命中，印证 r5 的判断"块内 diff 不得作为落码依据" |

**行为**（monkeypatch `nav_codegraph.available` 和 `_cg_exe`；真 offline_assets 只读）：

| 形态 | `_probe_codegraph()` 返回 |
|---|---|
| fake bundle | `('ok','1.6.0','codegraph 1.6.0')` |
| 真 offline_assets | `('ok','1.6.0','codegraph 1.6.0')` |
| npm shim 形态 | `('ok','','codegraph 已安装')` |
| `_cg_exe` 返回 None | `('ok','','codegraph 已安装')` |
| 未安装 | `('missing','','')` |

- **probe_all(use_cache=False)**：codegraph 一行的 detail 为空，fix 为 MANIFEST 文案。按 settings.js:866-867 的 `detail||fix` 逻辑，渲染出 fix 指引；codegraph 进入 soft_missing。
- orig 的 MANIFEST 只有 8 个 kind。现网 `.fcpk.json` 的 last_probe 也只有 8 个 kind，没有 codegraph。
- **漏写注册行的变体**：state 为 `unknown`，detail 为 `'codegraph'`，异常被 probe_all 的 try 吞掉，不会报错。
- **预期中的行为变化**：未安装 codegraph 的机器会多出一条 soft_missing（与 bili 同款，可通过 `/api/resources/ignore` 忽略）。这正是 S37-6 的目的，不算缺陷。合成终版见附录 A.2。

### P-13（D-4）+ R2-11——P-13：DIFF-MISMATCH → APPLY-ISSUES；R2-11：DIFF-MISMATCH（占位）→ CLEAN

**字面**：

- P-13：PL:508 `def delete_lib(...):` 是占位符（ABSENT），PL:511 是 `...`；PL:512 的 `-` 行是 4 空格，现状 :205 在 if 块内是 8 空格（WS）。
- R2-11：PL:1033 是 `...改名...` 占位，没有可定位的上下文。按 r2 note a，落位在异库分支内、`os.replace(ld, new_ld)` 的前一行，缩进归位到 8。
- 两件的 `+` 行照抄都会 IndentationError，已实测。

**行为**：

| 场景 | orig | work |
|---|---|---|
| 被查询过的库，直接调 delete_lib | 返回 True，但**残留 tags.db**（D-4） | 目录被删净 |
| 同上，走 API | 200 `{ok:true}`，有残留 | 200 `{ok:true}`，目录已删 |
| tags 文件被外部句柄占住，直接调 | 返回 True，静默残留 | 抛 PermissionError(32)，**部分删除**：meta.json 等已删，tags 和 tags.db 留下 |
| 同上，走 API | 200 `{ok:true}`，库已不在列表中 | **500 text/html**，库已不在列表中 |
| R2-11：查询过的库 rebind | **PermissionError(5)**，旧目录还在 | 成功，目录已迁移 |

**问题**：

1. r1 要求 api 层捕获必须写成 diff（"修订轮必须补全"），但台账只有 PL:516 一句话描述；按台账方法论第 2 条"无 diff=未落实"，这部分未落实。
2. 部分删除后 meta.json 先没了，库变成不可见孤儿。只有 root 仍在登记根内时，才能经门卫再次删除。
3. `import shutil as _sh` 是冗余导入（:27 已导入）。

按 r1 建议补上 api 层捕获（附录 A.4），实测外部锁时返回 200 `{ok:false, err:"部分删除失败（文件被占用），请重试"}`，释放后重试返回 200 `{ok:true}` 且目录删净。

### P-15（D-5）`_guard` 拒绝非绝对路径——DIFF-MISMATCH → APPLY-ISSUES（轻）

- **字面**：两行上下文在全文件命中两处：nav_delete（:153-154，目标）和 **nav_cg_delete（:315-316，非目标）**。build（:76→:77）和 reindex（:191→:192）的 root 行后面接的是 backend 行，不存在这种相邻结构。语义落位为：三个目标端点各自 `if not root:` 的前一行。
- **行为**：使用真实 file_tree 门卫，stub 配置把临时根登记为 tree_roots，CWD 设为该根。build 的实际调用打桩，防止真跑垃圾任务。

  | root 取值 | orig build | work 三端点 |
  |---|---|---|
  | `"proj"`（相对） | 200，**以 'proj' 真启动任务** | 400"root 须为绝对路径" |
  | `123` | 200，**以 '123' 真启动任务** | 400 |
  | `True` | 200，**以 'True' 真启动任务** | 400 |
  | `{}` | 400"缺 root" | 400（文案变化） |
  | `""` | 400"缺 root" | 400"root 须为绝对路径"（**文案错位**） |
  | 绝对路径 | 正常 | 正常 |

  delete 和 reindex 在 orig 下对相对路径分别返回 `ok:false` 和"该目录没有索引库"，危害较小，work 统一返回 400。

- 范围外：cg_delete、status 对相对路径照旧放行，r1 note② 已声明这是取舍。
- **轻微问题**：r1 note①（先判空再判 isabs）没有采纳，空 root 的报错文案因此错位。建议顺手调序，见附录 A.6。

### P-17（S37-9）reindex 补 sizes.db——APPLY-CLEAN

- **字面**：PL:587-596 在 nav_api.py:230-232 命中（台账写 :229-233，漂移 1 行）。
- **行为**：先以 memory 建库，再依次 reindex 到 sqlite、memory、readtags、sqlite，每步立即取值，比较 `list_libs.size` 与磁盘真值。

  | 步骤 | orig 偏差 | work 偏差 |
  |---|---|---|
  | memory 建库 | 0 | 0 |
  | 切到 sqlite | **−20480**（缺 db 项） | 0 |
  | 切到 memory | 0 | 0 |
  | 切到 readtags | 0 | 0 |
  | 切到 sqlite | **−20480** | 0 |

  另一条序列（sqlite 建库后切到 memory）中，orig 的 sizes 仍保留已删除的 db=20480（**多计**），work 会剔除。
- **真实数据**（只读）：f93dd 少计 110,833,664 B；7e436 和 82077 各少计 20,480 B；211c57 的 sizes.db=20480，而磁盘上是 8400，多计 12,080 B。**存量库需要 reindex 或重建一次才能纠正**。

### P-18 终版 R2-10（S37-7）readtags 参数转义——DIFF-MISMATCH → 与 P-4 合成后 CLEAN

**字面**：

| 段 | 台账行 | 结果 |
|---|---|---|
| `_run` 签名与 argv | PL:995-1003 | L（old 4 行） |
| lookup | PL:1006-1010 | L |
| prefix | PL:1014-1016 | L |
| lookup_ci | **PL:1012** | **ABSENT**：`-` 行是 `… if r and ...]`，以 R2-8 形态为基线且带 `...` 占位；改由 R5-1 lookup_ci 段取代 |
| substring/by_path | PL:1018-1019 | `-`/`+` 同文，是 no-op；PL:1017 `def substring/by_path（-l 无查询名）：` 是伪代码上下文 |

files() 等仍用旧调用形式 `_run(["-l"], timeout=60)`，与新签名兼容。

**行为**：

| 探针 | orig | work |
|---|---|---|
| E8 `lookup('-l')` | 参数尾 `-l`，**全量 dump**（fixture 12/12 行；真实大库即 1.2GB 尖峰） | 参数尾 `- -l`，1 行 |
| E8b `prefix('-l')` | 返回**全库 12 个符号** | `['-l']` |
| E9 `prefix('getX')` | `getX`、`getX2` | `getX`、`getX2`（ASCII 大小写敏感口径维持 R2-12 观察项） |

**裁决**：必须与 P-4 一起落码，见附录 A.1。

### P-19（S37-8）sqlite URI 编码——APPLY-CLEAN

- **字面**：PL:634-637 在 vcs.py:184 命中。
- **行为**：每个目录下建一个 `.svn\wc.db`（NODES 表含 svn:special 行），调用 `_svn_symlink_paths`：

  | 目录名 | orig | work |
  |---|---|---|
  | `plain` | 正确 | 正确 |
  | `wc#hash` | **`[]`（过滤静默失效）** | 正确 |
  | `wc%20sp` | **`[]`（被解码成不存在的路径）** | 正确 |
  | `wc%pct` | 正确 | 正确 |
  | `wc 空格` | 正确 | 正确 |
  | `wc&amp` | 正确 | 正确 |
  | `中文目录` | 正确 | 正确 |

- test_vcs 沙箱版 32 PASS / 0 FAIL。

### P-20（S37-10）docstring 同步——APPLY-CLEAN

- **字面**：PL:651-659 在 claude_default.py:357 命中（台账写 :353-358，漂移 3 行，内容逐字吻合）。
- **行为**：`_register_codegraph_mcp` 去掉 docstring 后，函数体的 AST 哈希在两棵树上相同（`cfda13dd39b0b4cf`），确认是纯注释改动。

### P-23（S37-12）npm root -g 改用 which 全路径——APPLY-ISSUES（补丁无效）

- **字面**：两处（:288-289、:341-342）逐字命中，按 diff 写明的"两处同款"全部替换。
- **行为**：用 AST 抽出两处的 try 块单独执行，暴露原本被吞掉的异常。本机 npm 是 `C:\Program Files\nodejs\npm.CMD`，没有 npm.exe。

  | 形态 | 被吞掉的异常 | 自定义前缀候选是否追加 |
  |---|---|---|
  | orig | `FileNotFoundError [WinError 2]` | 否（S37-12 实锤） |
  | **work（台账原样）** | **`TypeError: 'module' object is not callable`** | **否，补丁无效** |
  | 改一个词：`from shutil import which as _sh_which` | 无异常；`_npm` 解析为 `npm.CMD` | **是**，两处都追加（codegraph-win32-x64 位、claude-code 位） |

- **回归面**：有 npm.exe shim 的机器（volta 等），旧代码本来能工作，按台账原样落码后会恒失败（r1 note b 提到过这类机器）。
- **裁决**：台账先改这一个词（或直接用模块顶已导入的 `shutil.which`），否则不应落码。修正形态见附录 A.5。

### R2-13 build:450 tags.tmp→tags replace 重试——APPLY-CLEAN

- **字面**：PL:1046-1052 在 nav_index.py:450 命中。
- **行为**：只对 `tags.tmp` 的 `os.replace` 注入失败，真跑完整 `build()`（vendor ctags、临时工程）。

  | 注入失败次数 | orig | work |
  |---|---|---|
  | 1 | 尝试 1 次，PermissionError | 尝试 2 次，成功 |
  | 2 | 尝试 1 次，PermissionError | 尝试 3 次，成功 |
  | 3 | 尝试 1 次，PermissionError | 尝试 3 次，干净失败 |

---

## 四、合并冲突记录

### 4.1 nav_index.py（7 件、10 个阶段）

- **正序**：P-7 → P-2 → P-1 → P-13 → R2-11 → P-3(idx) → R2-13 → P-18 → P-4 → R6-2，10 个阶段全部 py_compile 通过。终态 SHA256 前缀为 `d8c3470c56c63e98`。
- **文本不相交**：七件改动的函数各不相同：
  - P-7：`_write_json`（:76）
  - P-13：`delete_lib`（:202）
  - R2-11：`rebind`（:236）
  - R2-13：`build` 阶段 2（:450）
  - P-3：`_build_tag_db` 末尾（:671）
  - P-18/P-4/R6-2：`_ReadtagsBackend`（:750-828）
  - P-2：`_MemBackend.prefix`（:848）
  - P-1：声明区与两个函数（:882、:905-955）
- **可交换性实测**：把独立组逆序叠加（R2-13 → P-3 → R2-11 → P-13 → P-1 → P-2 → P-7，再接 P-18 → P-4 → R6-2），终态 SHA256 与正序**逐字节相同**。
- **硬依赖倒置实测**：

  | 倒置方式 | 结果 |
  |---|---|
  | P-4 先于 P-18 | R5-1 桥分支锚点 `def _run(self, flags, names=(), timeout=30):` 不存在，应用失败 |
  | R6-2 先于 P-4 | R6-2 的 `-` 行无锚点，**静默落空**；终态 grep `max(timeout, 60)` 为 0 处，超时修正丢失 |
  | 只应用 R5-1 lookup_ci 段 | 字面成功、编译通过，运行期 TypeError（见 P-4 节） |

- **语义依赖**（文本上不冲突）：P-1 让每个被查询过的库都保持常驻连接，原来只有最后一个查询库有常驻连接。因此 P-3、P-13、R2-11 这些"文件操作前关连接"的补丁，在 P-1 之后保护范围从一个库扩大到所有库，也更不可或缺。`_close_tagdb` 在 P-1 后的语义是"关闭全部库连接"，而且是在锁外 close，所以 P-3 的重试、P-13、R2-11 调用它都没有全局卡顿问题。只有 P-1 自身 `_get_tagdb` 里的 `_old.close()` 在锁内。

### 4.2 nav_api.py（3 件）

P-3(api) → P-15 → P-17。P-3 与 P-15 都改 `nav_build`，但位置不同：P-15 在入口参数校验处，P-3 在 `work()` 内部。P-17 改 reindex 的收尾；P-7 只改 `_write_json` 本体，不动 nav_api:232 这个调用点，**两者没有冲突**。逐阶段编译全部通过。

### 4.3 res_boot.py（P-10 四层链）

P-10 原文 → R2-9 → R4-2 → R6-1（r4 蓝本），每层的上下文都是上一层的 post-image。有两处断点：P-10 原文的 onlyoffice 占位，以及 R2-9 的注册行凭空上下文。都按语义接上后，R4-2 和 r4 蓝本都能字面命中。**建议落码时不要逐层重放，直接使用附录 A.2 的合成终版**。

### 4.4 其余文件

vcs.py 上 P-8（:396）与 P-19（:184）不相交；server.py、claude_default.py、build.py 各只有一件补丁。都没有冲突。

---

## 五、最终建议

### 5.1 建议应用顺序（依赖序）

1. **P-7（R5-2）**：`_write_json` 本体化。8 处写者受益，后续写 meta 的补丁都经过它。
2. **P-3（api+idx）→ R2-11 → R2-13**：文件操作前关连接和 replace 重试。先把"关连接"这一层铺好，再上 P-1。
3. **P-2**；nav_api 的 **P-15 → P-17**；**P-8 → P-19**；**P-9**；**P-20**。互相独立，次序任意，可交换性已实测。
4. **P-18 → P-4 → R6-2**：**必须在同一次提交里落码**，使用附录 A.1 的合成终版，其中必须包含 `ql` 行。
5. **P-10**：使用附录 A.2 的合成终版，其中必须包含注册行。
6. **P-13（修订版）→ P-1（修订版）**：P-1 会扩大"被查询过的库"的范围，因此 P-13 的完整修复（含 api 层）应当在 P-1 之前，或至少同一批落码。
7. **P-23（修订版）**：与其他补丁无依赖。

### 5.2 分批

- **立即批（11 个单元）**：P-7、P-3、R2-11、R2-13、P-2、P-17、P-15、P-8、P-19、P-9、P-20。
  - 字面可用的直接照抄。
  - P-2、P-9、R2-11 按现状缩进落码，不要原样粘贴 `+` 行。
  - P-15 建议顺手把 isabs 判断挪到空判定之后（附录 A.6）。
- **谨慎批（3 组，共 4 件）**：
  - **P-18+P-4+R6-2**：一组，使用合成终版，必须同一次提交。
  - **P-10**：使用合成终版，含注册行，并顺手把注释改为 `(state, ver, detail)`。
  - **P-1**：带附录 A.3 的锁外 close 修正；删改 R35-3 docstring 的第③条和 :1339 的注释，保留 R35-4 注释；在 P-13 修订版之后或同批落码。
- **暂缓批（2 件，台账先修补丁本身）**：
  - **P-23**：修正那一个词。
  - **P-13**：补上 api 层的捕获 diff（附录 A.4），否则外部锁场景会从"静默 200"变成"500 HTML"。

### 5.3 落码前台账需要修订的事项

1. P-23：`import shutil as _sh_which` 改为 `from shutil import which as _sh_which`（已实测）。
2. P-13：补 nav_api 的 OSError 捕获 diff（已实测）。可选的后续增强：让 meta.json 最后删除，避免产生不可见孤儿。
3. P-4/P-18：给出一份逐字可抄的 `_ReadtagsBackend` 合成终版，显式包含 `ql = q.lower()`；同时标注 R2-10 的 lookup_ci 子段作废，以及 PL:1183 那行注记不是代码。
4. P-10：合成终版中显式写出注册行，并改正注释里的契约描述。
5. P-1：锁外 close（已实测）、docstring 和注释同步；终态表"r4 后端 PASS"更正为"r1 PASS with notes，notes 未落实"。
6. P-2、P-9、P-13、R2-11：在 diff 的缩进上标注"按现状缩进"，或者直接改为现状缩进（照抄会 IndentationError，已实测）。
7. P-17：落码后对现有失真的库做一次 reindex 或重建（主工程库 f93dd 少计 105.7MB）。

---

## 附录 A：合成终版与修正形态（审计附件，干跑实测通过；台账采纳后以台账为准）

### A.1 `_ReadtagsBackend`（P-18 + P-4 + R6-2 合成终版，即 work 副本实际形态）

方法级 post-image。`_parse`、substring、by_path、files 不变。

```python
    def _run(self, flags, names=(), timeout=30):
        if not self._exe:
            return []
        _q = next((n for n in names if n), "")
        if _q and not _q.isascii():
            flags = [f for f in flags if f not in ("-p", "-l")]
            if _q[0].isascii():
                return self._run_raw(flags + ["-p", _q[0]], timeout)
            return self._ascii_dump(max(timeout, 60))   # R6-2：timeout 注记与 diff 对齐
        # R2-10：flags 与查询名分离放调用点——用户查询串一律过 `[-]` 转义位
        # （readtags help：`[-] NAME...` 之后所有参数按 NAME 解析，`-l` 查询
        # 实证 `["-p","-","-l"]` 恰返回 ['-l'] 无尖峰）
        argv = [self._exe, "-s1", "-e", "-n", "-t", self._tags] + flags + (["-"] + list(names) if names else [])
        try:
            pr = subprocess.run(argv, capture_output=True, timeout=timeout,
                                creationflags=0x08000000)
            return pr.stdout.decode("utf-8", "replace").splitlines()
        except (subprocess.TimeoutExpired, OSError):
            return []

    def _run_raw(self, argv_tail, timeout):
        argv = [self._exe, "-s1", "-e", "-n", "-t", self._tags] + argv_tail
        try:
            pr = subprocess.run(argv, capture_output=True, timeout=timeout,
                                creationflags=0x08000000)
            return pr.stdout.decode("utf-8", "replace").splitlines()
        except (subprocess.TimeoutExpired, OSError):
            return []

    _ascii_cache = None   # (tags_mtime, lines)——C-1 桥接专用 dump 缓存

    def _ascii_dump(self, timeout=60):
        try:
            _mt = os.path.getmtime(self._tags)
        except OSError:
            return []
        if self._ascii_cache and self._ascii_cache[0] == _mt:
            return self._ascii_cache[1]
        lines = self._run_raw(["-l"], timeout)
        self._ascii_cache = (_mt, lines)
        return lines

    def lookup(self, name):
        rows = []
        for line in self._run([], names=(name,)):
            r = self._parse(line)
            if r and r[0] == name:
                rows.append((r[1], r[2], r[3]))
        return rows

    def lookup_ci(self, name):
        low = name.lower()
        return [r for r in (self._parse(l) for l in self._run(["-i"], names=(name,)))
                if r and r[0].lower() == low]

    def prefix(self, q, limit):
        ql = q.lower()
        if not q.isascii():
            _lines = self._run(["-p"], names=(q,), timeout=60)   # 桥接（dump 或 -p 首字）
            out = [r for r in (self._parse(l) for l in _lines)
                   if r and r[0].lower().startswith(ql)][:limit]
            return out
        return [r for r in (self._parse(l) for l in self._run(["-p"], names=(q,))) if r][:limit]
```

### A.2 res_boot.py（P-10 合成终版）

MANIFEST 末项 bili 之后、`]` 之前：

```python
    # S37-6（P3）：a386 铺了安装器但没进面板清单——外部依赖页无此项，
    # 错误文案"设置→外部依赖安装"成死路
    {"kind": "codegraph", "name": "Claude 代码图引擎（codegraph）",
     "hard": False,
     "fix": "安装离线资源包（或设置→外部依赖安装单装）"},
```

`_PROBES = {…}` 字典之后：

```python
def _probe_codegraph():
    from src import nav_codegraph as _ncg
    if _ncg.available():
        _v = ""
        try:
            # 版本路径抄 res_install._ver 惯例：dirname(exe)/lib/package.json
            # （无 ".."——R2-9 实证三种 bundle 形态全 404）
            import json as _j
            _exe = _ncg._cg_exe() or ""
            with open(os.path.join(os.path.dirname(_exe),
                "lib", "package.json"), encoding="utf-8") as _f:
                _v = _j.load(_f).get("version", "") or ""
        except Exception:
            _v = ""
        return ("ok", _v, ("codegraph " + _v) if _v else "codegraph 已安装")
    return ("missing", "", "")
    # 契约：missing 态 detail/ver 留空——fix 指引文案由 MANIFEST.fix 渲染
    # （settings.js:867 非 ok 态 detail||fix 即命中）


_PROBES["codegraph"] = _probe_codegraph   # S37-6：三元组 (state, ver, detail)
```

这里注释写成 `(state, ver, detail)`，是本报告建议的更正；台账原文是 `(state, fix, detail)`，与实际契约不符。

### A.3 P-1 修正：锁外 close（变体树 work_p1fix 实测，跨库陪等 534–593ms 降到 1–2ms）

```diff
         _old = _tagdb_cache.get(ld)
-        if _old is not None:
-            try: _old.close()   # 同库 mtime 变化（重建）——旧连接此处关闭安全
-            except Exception: pass
         _tagdb_cache[ld] = db
         _tagdb_keys[ld] = key
+    if _old is not None:   # 锁外关闭：close 会等在途语句结束，在锁内会让全库查询陪等
+        try: _old.close()
+        except Exception: pass
     return db
```

### A.4 P-13 的 api 层捕获（nav_api.py 的 nav_delete 末行；变体树 work_p13api 实测返回 200 `{ok:false}`，重试可删净）

```diff
-    return jsonify({"ok": nav_index.delete_lib(root)})
+    try:
+        ok = nav_index.delete_lib(root)
+    except OSError:
+        return jsonify({"ok": False, "err": "部分删除失败（文件被占用），请重试"}), 200
+    return jsonify({"ok": ok})
```

### A.5 P-23 一词修正（两处同款；实测 `npm.CMD` 解析成功，候选路径成功追加）

```diff
-        import shutil as _sh_which
+        from shutil import which as _sh_which
```

### A.6 P-15 调序（可选；恢复空 root 时的"缺 root"文案）

```python
    if not root:
        return jsonify({"ok": False, "err": "缺 root"}), 400
    if not os.path.isabs(root):   # D-5（P4）
        return jsonify({"ok": False, "err": "root 须为绝对路径"}), 400
```

---

## 附录 B：留存物（`C:\Users\gaoyi13\AppData\Local\Temp\patch_apply_be\`）

| 路径 | 内容 |
|---|---|
| `_baseline_sha256.txt` | 7 个目标源文件的开工基线，最终核验 7/7 OK |
| `orig\`、`work\` | 原样副本树与终版副本树（均为 stub app_state） |
| `work_p1fix\`、`work_p13api\` | P-1 锁外 close 修正、P-13 api 层捕获的验证变体 |
| `stages\nav_index\01..10_*.py` | nav_index 逐阶段快照；`stages\<文件>\` 为其余文件的阶段快照 |
| `scripts\engine.py` | 应用引擎 |
| `scripts\chain_nav_index.py`、`scripts\chain_others.py` | 叠加链脚本 |
| `scripts\order_check.py` | 逆序与依赖倒置检查 |
| `scripts\probe_*.py`、`scripts\setup_fixtures.py` | 行为探针与 fixture 搭建 |
| `logs\nav_index_chain.json`、`logs\other_chains.json` | 每段的锚点表、应用模式、阶段 diff |
| `logs\probe_*_{orig,work}.json`、`logs\p1_inflight.txt`、`logs\server_8867_readonly.json` | 行为对照原始数据 |
| `logs\final_diffs\*.diff` | 终版副本相对原样副本的统一 diff（nav_index +103/−43、nav_api +16、vcs +7/−2、server ±1、res_boot +24、claude_default +4/−3、build +14/−4） |
| `logs\final_work_sha256.txt` | 终版副本的 SHA256 |
