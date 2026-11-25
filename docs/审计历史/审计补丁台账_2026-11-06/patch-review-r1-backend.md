# 后端补丁合理性审计报告（patch-review-r1-backend）

- 审计对象：doc/patch-log.md 中 16 件后端类补丁提案（P-1/2/3/4/6/7/8/9/10/13/15/17/18/19/20/23）
- 审计方式：白盒对照源码现状（行号/内容漂移核对）+ 推演应用后行为（语法/并发/边界/与既有机制交互）+ 实证实验（vendor readtags.exe、sqlite URI、本机 ACP）
- 环境注：本机 ACP=936（GBK），与实锤 D 组/C-1 的复现环境一致；实证脚本均在系统临时目录搭建并已清理，未触碰任何源码
- 全程只读；本报告为审计产物

---

## 结论先行

**13 PASS（其中 7 件附小改建议）/ 3 FAIL**。

| 补丁 | 裁决 | 一句话裁决 |
|---|---|---|
| P-1 多槽缓存重构 | PASS with notes | 结构正确根治泄漏源；锁内 close 在途连接面收窄但未消除，建议 close 挪锁外 + LRU 上限 |
| P-2 memory prefix lower | PASS | 一行修正确，调用方已 lower 实证 |
| P-3 build 前置 close + replace 重试 | PASS with notes | 与 reindex 模式对齐、语法/导入可行；建议 close→sleep 换序、回退分支补 tmp 清理 |
| P-4 readtags 中文 ASCII 桥 | **FAIL** | 桥思路正确（根因实证成立），但 lookup_ci 桥接路径缺精确过滤（全量误当精确，污染 definition/symbols 决策链）+ -l 全量无实例缓存（面板刷新 N×全量） |
| P-6 _db_busy 备选守卫 | PASS with notes | 作为备选记录成立；主案应取 P-3（P-6 整窗口降级 UX 代价远大于 P-3 窄窗重试） |
| P-7 meta.json replace 重试 | PASS with notes | 选点裁决：改 `_write_json` 本体（单点覆盖全部写者 + tmp 清理天然归属） |
| P-8 网络盘 ! 按清单判定 | PASS | 现状/作用域/语义精确化全部吻合，失败侧安全 |
| P-9 nav_keys 补 fsym | PASS | 四方口径核实齐全（GET 默认/前端默认/POST/冲突检查自动覆盖） |
| P-10 codegraph 注册 MANIFEST | **FAIL** | `"desc"` 键触发 probe_all `m["fix"]` KeyError（/api/res/status 崩）；probe 返回 2 元组解包 3 元组 → 状态恒 unknown |
| P-13 delete 前关连接 | PASS with notes | 方向正确；nav_api 侧必须补 try/except diff（现状无捕获 → 500），P-1 落地后应细粒度 pop(ld) |
| P-15 isabs 守卫 | PASS with notes | 选点正确（_under_roots abspath 归一证实 D-5 面）；建议先空判定再 isabs，并声明 status/rebind 未覆盖的取舍 |
| P-17 sizes.db 同步 | PASS | 插入点变量齐备、两方向覆盖完整（行号 2 行漂移，内容一致） |
| P-18 readtags `-` 转义 | **FAIL** | 两种形态均有实证反例：形态一毁 prefix，形态二（startswith 分离）对 lookup("-l") 尖峰原样保留；修正形态已实证（调用点分离 + `[-]`） |
| P-19 sqlite URI quote | PASS | 四形态实证：no-quote 撞 '#' 失败、quote 全通过（含 ':' → %3A 解码回正常） |
| P-20 docstring 同步 | PASS | 现状逐字吻合，新文案与 R34-2 实际语义（整条目替换）核实一致 |
| P-23 npm which 全路径 | PASS with notes | 机理正确、两处现状逐字吻合；`import shutil` 冗余（模块顶已有） |

---

## 逐件裁决详情

### P-1（D-1 多槽缓存重构）——PASS with notes

**现状核对**：位置 :905-955 准确。`_get_tagdb`（905-936）/`_close_tagdb`（942-955）与真实代码一致；diff 的 `-` 行与 :915 `key = (ld, os.path.getmtime(tags_p), os.path.getmtime(db_p))` 逐字吻合。现状引文块中 `_tagdb_cache` 行的注释措辞与实际（:882 `# (ld, tags_mtime, db_mtime) → _TagDB`）不同——diff 本身无漂移，不影响应用。`_tagdb_orphans` 全仓引用核实：仅 nav_index.py :933/:939/:949/:950（即 _get_tagdb/_close_tagdb 两函数内），补丁"grep 全仓仅两处"论断成立。

**三问**：
1. **正确解决问题**——是。泄漏根源（换 key 必产孤儿）被结构消除：同库复用、跨库各持、无"被顶掉"连接。D-1 的 attack_leak.py 留存于 `.zcode/tmp/resdfx/scripts/`（已核实存在），验证步骤可操作。
2. **新问题**——两点需注意：①`_old.close()` 在**锁内**执行且可能有在途查询（同库重建低频场景）。与现状对比：`_close_tagdb` 本就在锁外 close 含在途可能连接，该风险类在现状已存在，本补丁是"新增一个 close 点"而非"引入新风险类"；但 R35-3 docstring 明言"close 会杀在途 execute"，补丁把 close 挪进锁内与该注释的意图相悖。建议：锁内只取引用并摘槽，close 挪锁外（与 `_close_tagdb` 同型）。②慢线程竞态：T1 读旧 mtime（K1）→ 重建发生 → T2 装入 K2 → T1 持锁时 `_tagdb_keys.get(ld) != K1` 落入 `_old.close()` 分支 → **关掉 T2 的新连接并装入指向旧文件的 K1 连接**。下一次查询按当前 mtime 计算即 miss 自愈，损害为一个查询窗口的陈旧连接——与现状单槽同型竞态（现状会把 db2 挂 orphan），非回归，但可顺手改为"锁内重读 mtime，key 不新鲜则弃用自建"。
3. **更优方案**——多槽即治本方向，无更小改法可替代（孤儿列表 LRU 化只是缓解）。建议补充：连接数上限（LRU 8 库）防长会话多库驻留。

**notes 清单**：
- `_get_tagdb` 的 R35-3 docstring（:906-909）描述 orphan 机制，补丁未同步更新——修订时一并替换。
- 风险注只算了 mmap 面：`_TagDB.__init__` 还有 `PRAGMA cache_size=-65536`（**64MB 页缓存/连接**），N 库驻留理论上限 N×64MB priv。"个位数库"假设下可接受，LRU 上限时一并考虑。
- `_close_tagdb` 多槽版语义变为"关全部库"——build/reindex/delete 均可接受（全关重开代价小），P-13 的细粒度 pop(ld) 是可选优化。
- 64 位进程（spec target_arch 默认 + 本机 64 位），256MB mmap 虚拟/连接不构成地址空间压力。

---

### P-2（S37-1 memory prefix lower）——PASS

**现状核对**：:845-853 `_MemBackend.prefix`，`if k.startswith(q):` 在 :848，逐字吻合。

**三问**：①q 已被调用方 lower 实证——`symbols()` :1063 `qlow = (q or "").strip().lower()`，:1091 `_be.prefix(qlow, limit*2)` 是 prefix 的唯一后端调用点；`k.lower().startswith(q)` 与 R35-1 sqlite 档（:713-720 lower 范围比较）口径对齐。②无新问题：空查询不会到达（:1084-1085 提前返回）；每键一次 lower 分配对 <20 万符号库毫秒级。③无更优方案（一行即最优）。

---

### P-3（S37-2 build 前置 _close_tagdb + 阶段 4 replace 重试）——PASS with notes

**现状核对**：nav_api.py:103-106 `work()` 与引文一致（reindex 侧 :214 `nav_index._close_tagdb()` 前置模式存在，"与 reindex 对齐"论断成立）；nav_index.py:555-567 阶段 4 try/except 与 :671 `os.replace(tmp, db_path)` 逐字吻合。语法/导入可行：`time`（:30）、`_close_tagdb`（:942）均就绪；`except OSError` 覆盖 WinError 5（PermissionError）与 32（SharingViolation）。

**三问**：①正确切断 S37-2 静默降级链入口 ✓；3 次全失败 raise → 被 build :559 捕获 → 回退 readtags + meta 落盘（既有优雅降级保留）✓。②新问题：a) 全失败路径 `tags.db.tmp` 残留仍在（回退分支 :563-567 只删 db_path 不删 tmp）——建议回退分支顺带 `os.remove(db_path + ".tmp")`（best-effort）；b) retry 内 `time.sleep(0.05)` 后才 `_close_tagdb()`，功能等价但建议换序为 close→短 sleep→replace（先释放句柄再让 Windows 句柄表沉降）；c) close 与 replace 之间并发查询重开连接的窗口仍在（重试×3 是概率性缓解，非封闭）——这正是 P-6 备选的存在理由，取舍见 P-6。③更优方案：无（P-3 + P-6 备选的组合已是完备选项集）。

**验证可操作性**：sqlite 档查询后点重建 → meta.backend=sqlite / 无 tmp 残留——可操作 ✓（配合 P-1 落地后重跑 D 组攻击 2）。

---

### P-4（C-1 readtags 中文 ASCII 桥）——**FAIL**

**实证基础**（本机 ACP=936，vendor/ctags/readtags.exe，UTF-8 排序 tags fixture）：
- `中文函数` 精确查 → 0 行；`-i 中文函数` → 0 行；`-p 中` → 0 行——**C-1 失明根因实证成立**，ASCII 桥方向正确。
- `-p g` → `getX/getX2/get_中文`——首字符 ASCII 时 `-p` 超集方案成立 ✓。
- readtags --help 官方语义：`-i/--icase-match`、`-p/--prefix-match` 为 **NAME action 的无参 modifier**；`[-]` = "arguments after this as NAME(s) even if they start with -"。

**FAIL 理由（两处实打实的缺陷）**：
1. **lookup_ci 桥接路径缺精确过滤（正确性回归）**。`_run_ascii_bridge` 的 `-l` 分支把 flags 原样带上：lookup_ci 的 flags=`["-i"]` → argv 尾 `["-i","-l"]` → readtags 把 `-l` 当 ACTION（-i 是无参 modifier）→ **全量列出**（实证 10 行全量）。而补丁写明"lookup_ci：过滤不变"——现状 lookup_ci（:798-799）**没有**任何 Python 侧过滤。后果链：`symbols()` :1088 `_exact_names = {r[0] for r in _be.lookup_ci(qlow)}` → 全库符号被当成精确命中 → exact[:limit] 推入结果（Ctrl+T 对中文查询返回任意 50 个符号）；`definition()` :1282 的 lookup_ci 回退链拿到任意候选排序后 `auto=True` **可能直跳错误定义**。
2. **-p 分支同样污染 lookup_ci**：`["-i","-p","g"]` 虽能返回 g* 超集（modifier 可叠加，实证通过），但 lookup_ci 无精确过滤 → 超集误当精确，同 1 的后果。
3. **性能：-l 全量无实例缓存**。桥后每次非 ASCII lookup 都是全量 dump；`symbols()` 的 push()（:1099）对每个候选名各调一次 `_be.lookup(name)` → 50 候选 × 全量 = 面板刷新分钟级（6M 行库 7s/次 × 50）。patch-log 风险注只按"单次 -l"估了量级，漏了乘数。

**修正方向（修订轮采纳）**：
- a) 桥接时 flags 只保留后端自有 modifier，`-l` 分支不带 `-i`（或干脆 flags 仅收 `["-i"]` 且仅在确实需要时保留——见 P-18 修正形态的统一设计：用户可控串一律走 `[-]` 后 NAME 位）。
- b) lookup_ci 桥接路径补 `r[0].lower() == name.lower()` 过滤（prefix 的 Python 过滤补丁已写明 ✓，lookup_ci 必须补 ✗）。
- c) `_ReadtagsBackend` 实例级缓存 -l 全量解析结果（如 `self._l_cache`），lookup/lookup_ci/prefix 桥接共用一次 dump（后端对象按请求创建，同一请求内多查询共享）。
- d) 验证步骤补一条"中文 lookup_ci 精确性探针"：`_be.lookup_ci('中文函数')` 应恰返回 1 个名字族，而非全库。

**附注（不改裁决）**：根因措辞欠精确——CreateProcessW 本身传宽字符命令行无损；损毁发生在 ANSI main() 的 CRT 启动转换（ACP=936 下中文以 GBK 字节到达 argv，与 tags 文件的 UTF-8 字节永失配；非 ACP 字符则替换 '?'）。ASCII-only argv 对两种机理均有效，修法不受影响。

---

### P-6（S37-3 _db_busy 备选守卫）——PASS with notes

**三问**：①结构性封窗确实消除竞态本体（查询拿不到 db → 兜底档），且 tags 文件在 build 中走 tmp+replace（:400/:450 实证），兜底读旧文件一致性有保障（replace 瞬间毫秒级窗口除外）。②新问题：窗口口径——补丁把 add 放在"build/reindex 的 db 操作前"，若覆盖整个 build（分钟级），期间全部 sqlite 库查询降级 readtags（0.2s/次）或 memory（全量载入），UX 代价远大于 P-3 的阶段 4 窄窗重试；`_get_tagdb` 入口 `if ld in _db_busy` 无锁读（GIL 下 set 成员判定原子，实践可接受，但与 add/discard 的锁口径应统一走 _cache_lock）；忘记 discard 的永久降级靠 finally，补丁已声明。③取舍裁决：**维持 P-3 主案**。P-6 的真实价值是"若重试在持续并发查询下仍撞"的结构性兜底——若实施，窗口应收窄到阶段 4 前后（db 文件操作面），而非整个 build。

---

### P-7（D-2 meta.json replace 重试）——PASS with notes（选点裁决：改 _write_json 本体）

**现状核对**：reindex work 收尾 `_write_json(os.path.join(ld, "meta.json"), meta)` 在 nav_api.py:232（`ld`、`time` 均在作用域 ✓）；`_write_json`（nav_index.py:76-82）tmp 命名 `%s.%d.tmp % (p, get_ident())`，**except 路径无 tmp 清理**——补丁对现状的判断准确。

**选点裁决**：**改 `_write_json` 本体**（retry 参数或默认内置），理由：①单点覆盖全部写者——build meta（:589）、symbols.json（:543）、gen_files.json（:1191）、rebind meta（:237/:239）、reindex（nav_api:232）；②tmp 是 `_write_json` 创建的，清理天然归属本体（try/except 包 os.replace + except 里 best-effort `os.remove(tmp)`）；③调用方循环版会让 build/reindex/rebind 三处口径分裂。形态建议：只对 `os.replace` 段做 3×50ms 重试（open/write 失败如磁盘满不是本实锤机理，重试无害但不必掩盖）。

---

### P-8（S37-4 网络盘 ! 按清单判定）——PASS

**现状核对**：vcs.py:396-399 逐字吻合；`sym`/`sym_low` 在 :393-394 就绪，作用域正确。

**三问**：①语义精确化正确：svn:special 清单内的 `!` 才是"链接目标不可达"（SMB 展开必然态），清单外 `!` 是真删除——假阴性消除且 symlink 的 M 分支（:400）判定口径一致。②新问题：清单查询失败（SQLITE_BUSY）→ 空集 → `!` 全保留 = 回到误报侧——与 `_svn_symlink_paths` "空集=不过滤（安全侧）" 注释一致，误报可见优于静默丢改动，方向正确；`~` 分支为死代码（映射表 :377-379 无 obstructed，:380 `if not st: continue` 已滤）——补丁保留无害，注释已说明。③无更优方案。性能：per-file set 查询 O(1) ✓。

---

### P-9（S37-5 nav_keys 补 fsym）——PASS

**现状核对**：server.py:1476 逐字吻合。

**四方口径核实**：①GET 默认（:1383-1387）默认 dict 含 fsym——但仅当 cfg **无** nav_keys 键时生效；存量 5 键配置返回原 dict 无 fsym。②前端兜底实证：nav.js:507 `NAV_KEYS` 默认含 `fsym: 'ctrl+shift+o'`，loadNavKeys → applyKeys（:665）按 `if (cfg[k])` 逐键覆盖——响应缺 fsym 时前端默认存活 ✓（patch-log"GET 走默认合并已有兜底"的机理实际在前端默认，结论不变）。③POST：nav.js:665 前端按六键发送，现状 `_NK_KINDS` 缺 fsym 导致其被静默丢弃——补丁后落盘 ✓。④冲突检查 `len(set(_nk_out.values())) != len(_NK_KINDS)` 自动覆盖六键 ✓；方向键校验的 back/fwd 白名单不受影响 ✓。无回归面。

---

### P-10（S37-6 codegraph 注册 res_boot.MANIFEST）——**FAIL**

**现状核对**：MANIFEST（res_boot.py:43-66）8 kind 无 codegraph 属实；res_install.ORDER 已含 codegraph（:36）+ `_INSTALLERS`（:832）+ 名称映射（:841 与提议 name 一致）→ **单装路径在加入 MANIFEST 后自动生效**，"res_api probe_all 无需改"论断正确（res_api.py:46/51 直接消费 MANIFEST）。

**FAIL 理由（提议 diff 两处硬伤）**：
1. **`"desc"` 键破坏 probe_all**：probe_all :348 `items.append({..., "fix": m["fix"]})` ——codegraph 条目无 `fix` → **KeyError，且该行在 `_PROBES[k]()` 的 try 之外** → probe_all 整体抛错 → /api/res/status 崩，外部依赖页全灭。前端渲染面同样只用 `it.detail || it.fix`（settings.js:867），`desc` 永不显示。**必须用 `"fix"` 键**。
2. **probe 返回 2 元组**：probe_all :340 `st, ver, detail = _PROBES[k]()` 按 3 元组解包 → 提议 lambda 的 `("ok", "") / ("missing", "未安装")` 触发 ValueError（被 :341-344 捕获）→ codegraph 状态**恒 "unknown"**，已装/未装永远显示不出来。
3. 惯例：`_PROBES`（:301-304）是具名函数映射（probe_bili 同型），`__import__` lambda 背离同文件惯例且无必要。

**修正形态（精确 diff）**：
```diff
     {"kind": "bili", "name": "billion-context 压缩引擎", "hard": False,
      "fix": "离线资源包内解包（约 200MB，代理面板开关控制启用）"},
+    # S37-6（P3）：a386 铺了安装器但没进面板清单——外部依赖页无此项，
+    # 错误文案"设置→外部依赖安装"成死路
+    {"kind": "codegraph", "name": "Claude 代码图引擎（codegraph）", "hard": False,
+     "fix": "离线资源包内解包（约 250MB，自带 node 运行时，无需 npm）"},
 ]
```
```diff
+def probe_codegraph():
+    """codegraph 引擎探测：bundle（资源包/npm 位）或 which 任一可用即 ok"""
+    from src.nav_codegraph import available as _cg_ok   # 延迟导入防依赖链
+    if _cg_ok():
+        return "ok", "", ""
+    return "missing", "", "未安装（资源包安装或 npm 全局）"
+
 _PROBES = {"webview2": probe_webview2, "dotnet": probe_dotnet,
            "node": probe_node, "git": probe_git, "claude": probe_claude,
            "onlyoffice": probe_onlyoffice,
-           "pydeps": probe_pydeps, "bili": probe_bili}
+           "pydeps": probe_pydeps, "bili": probe_bili,
+           "codegraph": probe_codegraph}
```
（`nav_codegraph.available()` 返回 bool 已核实，:78；probe 成本为文件存在性检查 + which，廉价 ✓。hard=False 不阻断主流程 ✓。）

---

### P-13（D-4 delete 前关连接 + ignore_errors=False）——PASS with notes

**现状核对**：delete_lib（nav_index.py:202-207）`shutil.rmtree(ld, ignore_errors=True)` :205 逐字吻合；nav_delete（nav_api.py:145-167）现状返回 `jsonify({"ok": nav_index.delete_lib(root)})` 且**无 try/except**。

**三问**：①入口关连接解锁 + 失败如实报，两端修成立（P-1 多槽后连接按 ld 常驻，不关则 tags.db 锁死 rmtree）。②新问题：a) **ignore_errors=False 的 OSError 在 nav_delete 现状会直接变 Flask 500 HTML**——补丁只在 prose 里写"api 层捕获 OSError"，无 diff——修订轮必须补全：`try: ok = nav_index.delete_lib(root) except OSError: return jsonify({"ok": False, "err": "部分删除失败（文件被占用），请重试"}), 200`（保持 200 + ok:false 与端点既有错误风格一致）；b) rmtree 中途失败可能已删 meta.json → 库从 list_libs 消失变不可见孤儿——"请重试"文案仍有效（残留文件二次删除可清），但验证步骤应覆盖此态。③细粒度裁决：**P-1 落地后取细粒度**——锁内 `_tagdb_cache.pop(ld, None)` + `_tagdb_keys.pop(ld, None)` 取引用、锁外 close（避免误杀其他库在途连接）；P-1 未落地前全局 `_close_tagdb()` 可接受。另：`import shutil as _sh` 冗余——nav_index.py:27 顶部已 `import shutil`。

---

### P-15（D-5 isabs 守卫）——PASS with notes

**现状核对**：`_under_roots`（file_tree.py:73-81）:77 `os.path.abspath(str(path)...)` 归一证实 D-5 面（相对形态撞 CWD 可过门卫落登记根）；三端点 root 解析行号吻合（build :76 / delete :153 / reindex :191——reindex 的 `import os` 在函数内 :188 且先于判定 ✓；build/delete 的 os 为模块级 ✓）。`root=123/{}/True/相对` 经 `str()` 后均非 isabs → 400 ✓。

**notes**：①顺序——提议 diff 把 isabs 放在 `if not root` **之前**：空串 `os.path.isabs("") == False` 会吃掉"缺 root"语义、报错文案错位；建议先空判定再 isabs。②收口面声明——nav_status（nav_api.py:41，只读浅探测）与 nav_rebind 的 old_root/new_root 是同类面（依赖 abspath 钉 CWD），P-15 未覆盖；低危（status 只读、rebind 有 _guard(new_root)+库存在校验），建议至少在补丁或注释中声明取舍，或一并加行。

---

### P-17（S37-9 sizes.db 同步）——PASS

**现状核对**：nav_api.py:230-232（补丁写 229-233，2 行漂移，内容一致）。插入点变量齐备：`os`（:188 函数内 import）、`db`（:216）、`meta`（:215）。**三问**：①切 sqlite 加项（`_build_tag_db` 后 getsize 即新库尺寸 ✓）/切其他档删项（:227-228 已删 db）——两方向与 build() 全量重写 sizes（:585-588）对齐 ✓。②无新问题：`meta.get("sizes") or {}` 防 None ✓；list_libs 的 `sum(sizes.values())` 消费口径不变 ✓。③无更优方案（build 后统一重算 sizes 是备选，侵入更大）。

---

### P-18（S37-7 readtags `-` 转义）——**FAIL**

**官方语义核实**（readtags --help，vendor 实机）：`[-] NAME...`——"-" indicates arguments after this as NAME(s) even if they start with -。`-i`/`-p` 是 NAME action 的无参 modifier。

**FAIL 理由（两形态均有实证反例）**：
1. **形态一** `[..., "-"] + args`：prefix("getX") → `["-","-p","getX"]` → `[-]` 后全按 NAME → 精确查名字 "-p" 与 "getX" → **prefix 档全面归零**（回归一切正常前缀查询）。
2. **形态二**（startswith 分离，补丁最终倾向形态）：lookup("-l") → `args=["-l"]` 全被归入 `_flags`、`_names=[]` → **无 `[-]`** → argv=[base,"-l"] → "-l" 仍当 ACTION → **全量 1.2GB 尖峰原样保留——S37-7 的头号场景恰好未被修复**。prefix("-l") 同型（`["-p","-l"]` → modifier + ACTION -l → 全量 dump，Python 过滤救不回内存尖峰）。

**修正方向（实证通过的形态）**：分离必须发生在**调用点**——后端自己知道哪个是自有 modifier、哪个是用户可控查询；`_run` 增加查询名通道：
```python
def _run(self, flags, timeout=30, names=()):
    argv = [self._exe, "-s1", "-e", "-n", "-t", self._tags] + flags
    if names:
        argv += ["-"] + list(names)
    ...
# 调用点：lookup → _run([], names=[name])；lookup_ci → _run(["-i"], names=[name])
#         prefix → _run(["-p"], names=[q])；substring/by_path/files 维持 _run(["-l"])
```
**实证**（vendor readtags.exe）：`["-p","-","-l"]` → 恰返回 `['-l']`（无尖峰精确命中）；`["-i","-","-l"]` → `['-l']`；`["-i","-p","-","-l"]` → `["-l"]`；`["-p","-","getX"]` → prefix 正常返回 getX/getX2 ✓。该形态与 P-4 修正版统一（flags 仅后端自有、用户串一律走 `[-]` 后 NAME 位），一处修 lookup/lookup_ci/prefix 全部注入面的论证在修正形态下成立。验证步骤（Ctrl+T 查 `-l`/`-i` → 空结果无尖峰）对修正版有效。

---

### P-19（S37-8 sqlite URI quote）——PASS

**现状核对**：vcs.py:184 逐字吻合（`uri=True` 已在）。

**实证**（四目录形态 × 三 URI 形态，临时目录）：no-quote 对 `#` 目录失败（OperationalError——被 `_svn_symlink_paths` 的 except 捕获 → 返回空集 → 过滤静默失效，与 S37-8 实锤症状链一致）；`quote(p)`（默认 safe="/"）四形态**全部通过**，含 `:` 被 %3A 编码后 sqlite 解码回 `D:/` 正常打开。`%` 单独出现（非法转义如 `%s`）现状侥幸存活，但合法转义序列（如目录名含 `%20`）会截断——quote 一并根治。**验证建议**：fixture 除 `%` 目录外加一个 `#` 目录（同为触发面，实证已证）。无新问题（quote 对常规 ASCII 路径无变化，实证 plain 形态通过）。

---

### P-20（S37-10 docstring 同步）——PASS

**现状核对**：claude_default.py:353-358 docstring 与补丁现状引文逐字吻合。新文案语义核实：R34-2（:380-384）为**整条目替换**（`servers["codegraph"] = _want`）→ "用户对该条目的自定义（env/args）会在每次 provision 被重置"准确；:362 "同事设备装资源包后首次 provision 自动补"与"未装时静默跳过（资源包安装后首次 provision 自动补）"一致。删去已失效的"幂等只补缺不覆盖"正确。纯注释无行为风险。

---

### P-23（S37-12 npm root -g 改 which 全路径）——PASS with notes

**现状核对**：build.py:288-289 与 :341-342 两处 `subprocess.check_output(["npm", "root", "-g"], ...)` 逐字吻合（补丁位置准确）。

**三问**：①机理正确：list 形态 CreateProcess 不解析 .cmd，npm 无 npm.exe → FileNotFoundError → `except Exception: pass` → 自定义前缀候选从未生效（死分支），`shutil.which` 经 PATHEXT 命中 npm.cmd 全路径后 CreateProcess 可执行 → 死分支复活 ✓；which 失败 → `_npm=""` → out="" → `if out:` 不追加候选 → 默认 APPDATA 位原逻辑保留 ✓（且两处均处于既有 try 内，异常面不变）。②新问题：无（args 固定，无 .cmd 参数注入面）。③notes：a) `import shutil as _sh_which` 冗余——build.py:5 顶部已 `import os, sys, subprocess, shutil`；b) "Windows 恒 FileNotFoundError" 略过头（volta 等工具会产 npm.exe shim，旧代码此类机器本可工作）——不影响修法正确性与兼容性。公共 helper（两处去重）为可选优化。

---

## 新发现区（审补丁过程中顺带发现，单列不计入本轮）

1. **rebind 的目录改名在关连接之前（nav_index.py:236 vs :240）**：`os.replace(ld, new_ld)` 先于 `_invalidate_cache()`。该库被查询过则 sqlite 连接常驻（现状：cache/orphan；P-1 后：多槽常驻）——Windows 下带打开句柄的目录改名失败 → rebind 直接抛错。P-13 只给 delete 补了 `_close_tagdb`，**rebind 同样需要**（校验通过后、改名前）。建议作为 D-4 的姊妹项立案。
2. **readtags 档 prefix 大小写敏感（R35-1 口径缺口）**：`symbols()` 以 qlow（已 lower）调 `_be.prefix`（:1091），readtags `-p` 为字节级敏感匹配——实证 `-p appl` 只返回 `apple_pie`，`Application` 永不命中。S37-1/P-2 只修了 memory 档；sqlite 档有 idx_lower；**readtags 档的混合名前缀查询静默漏结果**。readtags 无原生 icase-prefix——修法需 `-p` 双形态（q[0] 原样/反转大小写各查一次合并）或 `-l` 全量（慢档口径）。注意 P-4 的 Python 侧过滤救不回 readtags 根本没返回的行。
3. **build() :450 `os.replace(tags_tmp, tags)` 无重试**：与 S37-2/S37-3 同类窗口——并发 `_load_tags`/readtags 读者持 tags 句柄时 replace 失败 → build 失败（无重试无兜底）。窗口毫秒级（远小于 sqlite 常驻连接），实锤概率低，但 P-3 落地后可顺手同款 3×50ms 重试。
4. **P-15 收口面外的相对路径入口**：nav_status（nav_api.py:41）与 nav_rebind 的 old_root（:175）同样依赖 `_under_roots` 的 abspath 归一——相对形态可过门卫。status 只读低危；rebind 有 new_root 门卫 + 库校验。声明取舍或一并加行。
5. **非中文 locale 部署的 readtags 全盲面（观察项）**：本机 ACP=936，GBK 可表示路径中文 → `-t <中文路径>` 可用；若 ACP=1252 类机器把 DATA_DIR 配置到非 ASCII 路径，CRT ANSI 转换损毁 `-t` 参数 → readtags 档**连 ASCII 查询也 0 行**（静默）。P-4 桥不覆盖 `-t` 路径面。当前单机目标下无实际影响，留档。
6. **`_TagDB` cache_size=-65536（64MB 页缓存/连接）**：P-1 多槽后 N 库驻留的 priv 上限是 N×64MB（补丁风险注只计了 mmap 面）——"个位数库"假设下可接受，若做 LRU 上限一并核算。

---

## 实验留存说明

本轮实证均在系统临时目录（`%TEMP%/rt_audit`）搭建：readtags fixture 为手工生成的 UTF-8 排序 tags 文件（含 `-l`/`-i`/中文/混合名共 10 条），sqlite URI 测试为临时 wc.db；实验后已整体清理，仓库内未写入任何文件（本报告除外）。关键实证记录：

| 实验 | 结果 |
|---|---|
| `readtags -s1 -e -n -t tags 中文函数` | 0 行（C-1 失明实证） |
| `readtags ... -p 中` | 0 行 |
| `readtags ... -p g` | getX / getX2 / get_中文（P-4 桥超集可行） |
| `readtags ... -i -l` | 全量 10 行（P-4 桥 -l 分支污染 lookup_ci 实证） |
| `readtags ... -p appl` | 仅 apple_pie（readtags 档 prefix 大小写敏感实证） |
| `readtags ... - -l` | `['-l']`（官方 `[-]` 转义成立） |
| `readtags ... -p - -l` / `-i - -l` / `-i -p - -l` | 均 `['-l']`（P-18/P-4 修正形态通过） |
| `readtags ... -p - getX` | getX / getX2（修正形态 prefix 正常） |
| sqlite URI：`#` 目录 no-quote | OperationalError（过滤静默失效链） |
| sqlite URI：quote 四形态 | 全通过（含 `%3A` 解码回 D:/） |
