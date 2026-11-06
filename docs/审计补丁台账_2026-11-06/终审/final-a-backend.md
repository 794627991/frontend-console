# 终审 A（白盒·后端）——e1e2067（a393，28 补丁全量落盘）

- 对象：`git show e1e2067` 全部后端改动（nav_index/nav_api/vcs/server/res_boot/build/claude_default/update_server/harness），9 文件 py_compile 全过（9/9 OK）。
- 纪律：只读——源码/配置/索引库零触碰（git 终态 clean，见文末）；验证 fixture 全部在 `%TEMP%\final_a_be\`；真实库只读未连（sqlite 档验证全部用 TEMP 自建 fixture，未打开根库连接）。
- 已知口径：不重复报 R28-R35 台账、28 实锤、10 轮补丁审计、干跑 12 发现（`doc/patch-apply-backend.md` "本轮新发现"段、`.zcode/tmp/audit_round35.md` 含 a391/a392 复验附章）。

---

## 一、结论先行

**新实锤 4 件：P3×1 + P4×3。**

28 补丁的落码主体质量好：P-7/P-18/P-10/P-23 的行为矩阵本轮全部实测通过，P-1 的多槽结构与双建收敛正确，P-15 三端点归位无漏。问题集中在**三个缝隙**：

1. **P-1 把 a391 修复承诺的 orphan 保护静默撤销了**——换库/重建瞬间锁外 `_old.close()` 会杀并发线程持有的旧连接（本轮线程实验实证 ProgrammingError），这是 S35-3 场景①在新的多槽形态下回归；
2. **P-4 中文桥的 dump 路径丢了行号与 kind**（readtags `-l` 输出无扩展字段，本轮实测）——首字符非 ASCII 的符号 F12 会跳到第 0 行，干跑矩阵 E1-E12 只断言了名字所以没暴露；
3. **P-13 家族修复不完整 + 干跑蓝本的配套要求有 4 处没执行**——rebind 端点 api 层仍会 500 HTML，蓝本 5.2 明文写的注释同步/调序/前置关连接三项配套落空。

| # | 分级 | 主题 | 位置 |
|---|---|---|---|
| FA-1 | **P3** | P-1 撤销 orphan 保护：`_get_tagdb` 锁外 `_old.close()` 杀并发持有者的在途/后续查询（实证 ProgrammingError → 500） | nav_index.py:999-1007 |
| FA-2 | **P4** | P-4 中文桥 dump 路径丢 line/kind：中文开头符号 definition 跳转行号 0、面板 kind 空（实测 `('a.c', 0, '')`） | nav_index.py:797、851-862；definition :1343-1347 |
| FA-3 | **P4** | P-13 家族不完整：rebind 端点 api 层无捕获——外部占用时 500 HTML，且目录已迁移+meta 未写=半迁移态 | nav_api.py:194 ↔ nav_index.py:247-252 |
| FA-4 | **P4** | 干跑蓝本 5.2 明文配套项 4 处未落实（A.2 注册行注释契约、:1342 注释同步、R35-4 注释保留、A.6 调序） | res_boot.py:328、nav_index.py:1342、nav_api.py:80/159/208 |

---

## 二、环境与方法

- 静态：`git show e1e2067` 逐文件 diff 直读 + 现状源码（HEAD=e1e2067）全量核对 `_run`/`_close_tagdb`/`_write_json`/`delete_lib`/`rebind`/`_build_tag_db`/`probe_all` 的全部引用面。
- 动态（全部 TEMP，`python -I` 隔离）：
  - V1（P-1 并发）：双库 fixture + Barrier 双建 + mtime 换库 + 在途引用竞态线程；
  - V2（P-18/P-4）：monkeypatch 捕获 argv 的转义矩阵 + **真跑 vendor readtags 6.2.0**（两轮，第一轮暴露 fixture 缺 pattern 列全空，修正后有效）；
  - V3（P-7）：`_write_json` 正常/TypeError 清理/60ms 读者重试/400ms 超窗四场景；
  - V4（P-10）：AST 抽取 `_probe_codegraph` + stub `nav_codegraph` 四形态；
  - V5（P-9）：AST 定位 nav_keys 块 + 前端 nav.js:672 六键发送确认。
- 语法/铁律：9 文件 py_compile 过；后端新增行扫描无 emoji（命中皆为全角标点/中文注释）。

---

## 三、实锤逐件

### FA-1（P3）：P-1 撤销 orphan 保护——`_get_tagdb` 锁外 `_old.close()` 杀并发持有者（实证）

**位置**：nav_index.py:999-1007（`_get_tagdb` 尾部）。

**代码直读**：a391（R35-3 修复）的 `_get_tagdb` 明确承诺（docstring 第③条）"换库不立即关旧连接（在途查询可能持有——close 会杀在途 execute）——挂 orphan 列表，`_close_tagdb` 统一回收"。P-1 重写把 orphan 机制整体删除：同库 key 变化（tags.db mtime 变）时，`_old.close()` 在**锁外立即执行**——不等在途查询、不挂列表。`_TagDB.close()`（:772-776）依旧不拿 `self._lock`，与 `_q`（:730-732 持锁 execute）可自由交叠。

**V1 线程实证**（TEMP 双库 fixture，Python 3.14.7）：

| 探针 | 结果 |
|---|---|
| 双线程同 key 首建（Barrier 对齐） | 单对象 single=True，双建收敛正确，无泄漏 |
| 两库交替查询 | 多槽各持常驻连接（cache_n=2），无孤儿 |
| tags.db mtime 变化后取连接 | 缓存换新 ✓，**旧连接立即被关**（`old._q` → ProgrammingError，非 orphan 保活） |
| **在途引用竞态**：线程持旧连接等待，主线程触发 mtime 变化 + `_get_tagdb` 换库 | 持有者再 `_q` → **`ProgrammingError: Cannot operate on a closed database.`** |

**触发链**（全部是 P-1 之后的新常态）：
1. build/reindex 进行期间（前置 `_close_tagdb` 后、replace 完成前），并发查询（F12/Ctrl+T）重新建连入缓存；
2. build/reindex 完成 `os.replace` 改 mtime；
3. 下一个任意查询调 `_get_tagdb` → 发现 key 变化 → 建新连接 → 锁外关 `_old`；
4. 步骤 1 里还活着的查询线程（symbols 单次请求内有 lookup_ci/prefix/substring 多次 `_q` 的间隙；大库 substring LIKE 全扫 78-159ms 更宽）在间隙里执行 `_q` → ProgrammingError → Flask 500。

**与已知台账的边界**：a391 复验把"锁外 close 窗口"记为观察项时，指认的是 **`_close_tagdb` 一处**（触发面"切档/重建瞬间+恰有旧连接在途"）。P-1 之后：①`_get_tagdb` 新增了**第二个**锁外 close 入口，且触发条件从"显式调 `_close_tagdb` 的操作"扩大到"任何查询线程发现 mtime 变化就顺手关旧"；②orphan 机制（a391 对该窗口的结构性防御）被删除。这是保护语义的回退，不是同一已知项的复述。干跑报告 P-1 节只测了"触发线程自己等待 582-668ms、其他库不陪等"，**没有测持有旧连接的第三方线程的结局**（行为表两行都只记录触发线程与其他库的延迟）。

**最小修方向**（不代改，供下轮）：`_old` 改挂延迟回收列表（恢复 orphan 语义，`_close_tagdb` 统一关）；或 `_TagDB.close()` 内拿 `self._lock` 并接受全局串行代价；或引用计数（借出/归还）。

### FA-2（P4）：P-4 中文桥 dump 路径丢失 line/kind——中文开头符号跳转行号 0

**位置**：nav_index.py:797（桥分支 `_ascii_dump`）、:851-857（lookup）、:820-829（dump 实现）。

**机制**：桥分支对首字符非 ASCII 的查询走 `_ascii_dump` = `_run_raw(["-l"])`。实测（vendor readtags 6.2.0，`cat -A` 原始输出）：**`-l`（list）输出只有 `name\tpath\tpattern` 三列，不带 `-e/-n` 扩展字段（kind/line）**。dump 行经 `_parse` 后 lineno=0、kind=''。

**V2b 实测**（fixture 含 8 个符号，其中'中文函数'为中文开头）：

```
lookup('中文函数')   → [('a.c', 0, '')]        # line=0, kind=''
prefix('中文函数')   → ['中文函数']             # 名字对（push 后再 lookup 补位置——同样 0/''）
lookup('get_中文')   → 走 -p g 前缀 raw 路径，带扩展字段，不受影响
```

**影响链**：definition（:1343 `cands = _be.lookup(symbol)` → :1396-1398 `{"line": lineno, "kind": kind}`）——**F12 中文开头符号跳到第 0 行/文件头**；symbols 面板的 `push(name) → lookup(name)` 同样 line=0、kind 徽标空。lookup_ci 兜底（:1346-1347）同样落 dump，救不回。

**为什么干跑没发现**：干跑 P-4 行为矩阵 E1-E12 **全部只断言名字命中**；真实大库交叉核对用的 `test_replay_dedup末轮边界` 首字符是 't'（ASCII）→ 走 `-p t` 前缀路径**有**扩展字段（`test_v4feed.py:352` 行号正确）——恰好绕开了纯中文开头的 dump 路径。

**触发面**：readtags 档 + 库中存在首字符非 ASCII 的符号（Python 3/JS 允许 Unicode 标识符，中文函数名真实存在）+ F12/Ctrl+T。修复前这类符号全盲（零结果），修复后能找到但位置错——方向正确、字段缺口是新引入。

**最小修方向**：dump 路径的行补一次 `-e -n` 直查（对 dump 命中的名字逐个 `_run_raw(["-e","-n","-",name])`，量小）；或 dump 缓存时改用能带扩展字段的列举形态（若 readtags 支持）。

### FA-3（P4）：P-13 修了 delete 的 api 层，rebind 的同类异常面裸奔——500 HTML + 半迁移态

**位置**：nav_api.py:183-195（nav_rebind 裸调）↔ nav_index.py:247-252（目录 `os.replace` 之后 `_write_json` meta）。

**代码直读**：P-13 干跑修正（A.4）给 nav_delete 补了 `except OSError → 200 {ok:false, err}`；nav_rebind 的 `ok, msg = nav_index.rebind(old_root, new_root)`（:194）**无任何捕获**。R2-11 只在 nav_index 层加了前置 `_close_tagdb`（防自身连接），防不了外部句柄（用户资源管理器/杀毒/编辑器占用新库目录 meta.json）与 `_write_json` 重试耗尽后的 PermissionError——任一抛出 → 端点 500 HTML，与干跑给 delete 记的"500 HTML 两个极端都不对"同款形态。

**半迁移态**：rebind 在 `os.replace(ld, new_ld)`（目录已改名）**之后**才 `_write_json(new_ld/meta.json)`。若写失败（P-7 重试 100ms 耗尽后抛出），落盘的 meta.json 仍是旧内容（root=old_root）躺在 new_ld 里 → list_libs 显示 root=old、reachable=False，且 md5(old) 目录已不存在 → 删不干净、绑不上去的可见孤儿。概率低（新目录刚建、`_write_json` 有重试），但结构性。

**与已知台账的边界**：干跑新发现 6 记的是 **delete** 的部分删除孤儿（meta 先删）；rebind 端点的 api 层与半迁移态无人审过（R2-11 干跑只验证了"查询过的库 rebind 成功"的正路径）。

**最小修方向**：nav_rebind 套同款 `except OSError` 捕获返回 `{ok:false, err}`；meta 落盘失败时回滚目录名或至少返回可操作错误。

### FA-4（P4）：干跑蓝本 5.2 的明文配套项有 4 处未随落码执行

落码整体忠实于蓝本（P-23 一词修正、P-13 A.4、P-1 A.3 锁外 close、P-4/P-18 合成终版含 `ql` 行、P-10 注册行——本轮全部实测确认落实）。但蓝本 5.2/各节**明文要求同步执行**的配套项有 4 处落空：

| # | 蓝本要求（patch-apply-backend.md） | 现状 | 后果 |
|---|---|---|---|
| 1 | 5.2 谨慎批 P-10："使用合成终版，含注册行，**并顺手把注释改为 `(state, ver, detail)`**"（A.2 也写明台账原文 `(state, fix, detail)` 与实际契约不符） | res_boot.py:328 注释仍写 `# S37-6：三元组 (state, fix, detail)` | 契约误导后来者（实际消费 state/ver/detail，fix 由 MANIFEST 渲染——probe_all :363-374、settings.js :867 实证） |
| 2 | 5.2 谨慎批 P-1："**删改 R35-3 docstring 的第③条和 :1339 的注释**，保留 R35-4 注释" | R35-3 docstring ✓ 已删；**:1342 注释（原 :1339）"由 _tagdb_cache 生命周期管理（换库时关旧）"原样残留**；R35-4 两行注释（损坏库回退说明）被 post-image 丢弃，未按蓝本保留 | 注释与多槽新语义脱节；`except Exception: return None` 的回退意图失去说明 |
| 3 | 5.2 立即批 P-15："**建议顺手把 isabs 判断挪到空判定之后（附录 A.6）**" | 三端点（nav_api.py:80-83/159-162/208-211）isabs 均在 `if not root:` 之前 | 空 root 报"root 须为绝对路径"（应为"缺 root"）——文案错位，触发面=API 直调（前端恒发非空） |
| 4 | R35 复验（audit_round35.md a391 节最小修）："**顺带 `_build_tag_db` 开头也调 `_close_tagdb()`**（覆盖 build 阶段 4 的 memory/readtags 分支 remove 路径）" | `_build_tag_db` 开头（:639-641）只有 tmp 自删，无 `_close_tagdb` | build 运行中（阶段 1-3 数分钟）并发查询重建的连接，挡住阶段 4 非 sqlite 分支的 `os.remove(db)`（:589-593 静默 pass）→ db 残留、sizes 与档位不符（该后果 R35 复验已记"不崩但 db 残留"，此处仅记建议未落实的事实） |

注：第 3、4 项的**后果本身**在台账中已有记录（干跑"轻微问题"、R35 复验观察），不作为新问题重复计分；本实锤计的是**蓝本明文配套项的执行完整性**——干跑终审的产出被选择性执行，后续维护者会误以为蓝本要求已全部落地。

---

## 四、各重点项核验矩阵（无实锤区）

**① P-1 多槽缓存（除 FA-1 外）**：双建收敛（V1 single=True）、多槽隔离、锁一致性（`_tagdb_cache`/`_tagdb_keys` 全部操作在 `_cache_lock` 内，`_close_tagdb` 锁内 clear 双 dict 锁外关）、"他者先到"分支锁内 `db.close()`（自建连接无并发持有者，不会锁内长等）、新连接先入缓存后关 `_old`（顺序正确，close 不影响新连接服务）——全部正确。句柄收益（交替 100 次 +2）与干跑一致。

**② P-18/P-4 转义矩阵（除 FA-2 外）**：V2 实测 argv 与行为全对——`lookup('-l')`→`['-','-l']` 1 行（原全量 dump）；`prefix('-l')`→`['-l']`（原全库）；`lookup_ci`→`['-i','-',name]`；`files()/substring`→`['-l']`（names 空，`-` 转义位正确省略）；中文桥 `prefix('get_中文')` 走 `-p g`、纯中文走 dump；`lookup('-中文')` 干净失败 []；**首字符 `-` 的中文查询**（`-p -` 形态）实测返回 0 行，无全量尖峰。全部 7 处 `_run` 调用点（lookup/lookup_ci/prefix×2/substring/by_path/files）签名兼容，无旧形态残留。

**③ P-7 `_write_json`**：V3 四场景全过——正常写（含中文）、dump TypeError → tmp 清理+抛出、60ms 读者 → 64ms 重试成功、400ms 读者 → 107ms 干净失败+旧内容完好+tmp 清理。无嵌套调用（`_write_json` 不自嵌套）；异常传播正确（清理后 raise，调用方 nav_api:254/nav_index 8 处写者行为兼容）。

**④ P-13/P-15**：delete api 捕获与 A.4 蓝本一致（OSError → 200 {ok:false}）；delete_lib 前置关连接 ✓；rebind 前置关连接（R2-11）✓；P-15 三端点（build/reindex/delete）归位正确、cg_delete 未动=蓝本声明的取舍范围。

**⑤ P-10 + settings.js**：V4 四形态契约全对（bundle→`('ok','9.9.9','codegraph 9.9.9')`、exe=None→`('ok','','codegraph 已安装')`、未装→`('missing','','')`、exe 路径坏→ok 空版本）；MANIFEST 含 codegraph ✓、注册行 ✓、res_boot 顶部 `import os` 在场（无 NameError 面）；存量 `.fcpk.json` last_probe 缺 codegraph 不阻塞（probe_all :361-368 miss 即实时探测并写回）；settings.js :862-867 渲染矩阵（ok→ver、非 ok→`detail||fix`）与 missing 态留空 detail 的契约吻合。

**⑥ P-23**：两处同款（build.py :288-293/:343-348）、`from shutil import which` 修正生效形态、`_npm` 空串短路（`if _npm else ""`）——与 A.5 蓝本一致，无新问题（函数内 from-import 与顶部 `import shutil` 并存属冗余，同 P-13 的 `import shutil as _sh`，干跑已记）。

**⑦ 其余**：P-2 memory 档 `k.lower().startswith(q)`（调用点唯一、q 已 lower）✓；P-8 双形态清单判定（精确+lower，空集安全侧全保留）✓；P-17 reindex sizes 同步与 build 自身的条件 db 项（:605-608）口径一致 ✓；P-19 quote 默认 safe='/' 保留路径分隔 ✓；P-20 docstring 纯注释（干跑 AST 哈希已证）✓；P-9 前端 nav.js:672 六键发送、fsym 面板在场，兼容 ✓；P-21 后端 4 处 emoji 替换（update_server portal）无遗漏、新增行无 emoji ✓；harness 版本号 a393 ✓。

---

## 五、观察项（非实锤，供下轮跟踪）

1. **`_close_tagdb` 全库关语义的影响面**（P-1 交互）：多槽后任一库的 build/reindex/delete/rebind、`_invalidate_cache`、`_build_tag_db` replace 重试（:700）都会关**所有**已查询库的连接——其他库在途查询的 close 窗口与 FA-1 同机制（触发面=任何库的操作瞬间+任意他库在途查询），外加全部库首查重建连接的 PRAGMA/mmap 抖动。干跑 4.1 见到语义变化但按"也更不可或缺"正面表述，未记风险面。
2. **`_ascii_cache` 实例级不跨请求**：`_open_tags` 每次调用 new `_ReadtagsBackend`（:972-975），缓存只活在单次请求内（symbols 的 lookup_ci+prefix 两次 dump 合一，E12 口径达成）；跨请求的中文查询每次重新全量 dump。与 R35 观察项 5 的 `-l` 家族（substring/by_path/files 每请求全扫）同族。另：缓存写成类属性默认值+实例赋值形态，易被误读为跨实例缓存。
3. **reindex 非 sqlite 分支 `os.remove(db)` 裸调**（nav_api.py:243）：前置 `_close_tagdb` 已防自身连接，但外部句柄占用时任务失败（err 落槽可重试，非永久）——与 build 阶段 4 的 try 兜底口径不一致。
4. **`lookup` 空名 edge**：`names=("",)` 时 `_q=""` 走正常分支拼 `["-",""]`——上游 api 层有非空校验，未触发；记录备查。
5. **P-9 旧客户端五键 400**（"nav_keys.fsym 不能为空"）：已知行为变化维持（前端同批升级为六键，nav.js:672 实证）。
6. R35 观察项延续未动：假进度恒 94%、reindex percent 从 80 起跳、`code_files` 字段名语义、readtags `-l` 大库 stdout 峰值、`_MemBackend` limit 口径、by_path 小写盘符形态、readtags 档 ascii prefix 大小写敏感（与 memory 档 P-2 修复后的口径差异——memory 命中 FooBar、readtags 不命中，R35 已记"三档行为差异"维持）。

---

## 六、已知不重复报清单（本轮核对口径）

R28-R35 台账全部实锤（S35 系列六件+S36-1）已闭环销案；干跑 12 发现（P-23 模块调用、P-1 锁内 close 卡顿、P-4 ql 行、P-4/P-18 运行期硬依赖、P-10 注册行、P-13 api 层一句话、P-15 双命中、四件缩进、存量库 sizes 失真）已全部在落码中修正（本轮 V2/V3/V4 实测确认）；干跑 P-13"部分删除孤儿"（meta 先删）、P-15"cg_delete 范围外取舍"、P-2/P-9/P-13/R2-11 缩进归位、rebind 落盘时序（meta 落盘放到改名之后的**正向**设计）维持已知记录。

---

## 七、环境终态

- `git status`：clean（本报告为 doc/ 下新增文件，属交付物）。
- 真实索引库零触碰：全程未连接根库/未调用 8867/未读写 `D:\Frontend Console\nav\`；sqlite 验证全部用 `%TEMP%\final_a_be\` 自建 fixture。
- 验证产物留存：`C:\Users\gaoyi13\AppData\Local\Temp\final_a_be\`（v1_p1_conc.py / v2_p18_p4.py / v2b_real.py / v3_p7_p10.py 及 fixA/fixB/fixRT/fixRT2/wj/cg fixture）——均为 TEMP 一次性数据，可随时删除。
- py_compile 9/9 OK；后端新增行 emoji 扫描 0 命中。
