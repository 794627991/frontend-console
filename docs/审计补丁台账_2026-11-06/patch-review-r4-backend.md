# 后端补丁合理性审计报告 r4（patch-review-r4-backend）

- 审计对象：doc/patch-log.md【第 5 轮修订·后端组】R5-1 / R5-2 / R5-3 / R5-4（共 4 件，逐件裁决）
- 审计方式：白盒逐字基线核对（**本轮首要审计点：每个 diff 的上下文行与 +/- 行是否在真实文件或链内已 PASS 补丁的落地形态中逐字找得到锚点——R4-1/R4-3 两件 FAIL 的共同根因**）+ 语法/并发/边界推演 + 只读实验（真 vendor readtags.exe 6.2.0 + UTF-8 fixture、_write_json 行为矩阵、probe 三形态对照，全部在 %TEMP%/rt_audit_r6 完成，仓库零写入）
- 逐字核对手段：脚本化逐行比对（patch-log R5 各 diff 块 vs nav_index.py 现状字节 / R4-2 基线字节 / r3 修正 diff 字节），非目测
- 源码状态确认：R2~R5 各补丁均未落码（nav_index.py:760 `_run(self, args, timeout=30)` 旧签名、:76 `_write_json` 无重试无清理、:799 lookup_ci 无过滤、res_boot.py 无 codegraph probe、全仓 grep `_run_raw`/`_ascii_dump`/`_ascii_cache`/`args_of`/`_needs_ascii_bridge`/`_os_path` 代码区零命中）——本轮审计对象为补丁文本
- 环境注：Windows 10 / Python 3.14 / readtags.exe 6.2.0（vendor/ctags）；ACP=936（C-1 失明根因前提）继承 r2/r3

---

## 结论先行

**1 PASS / 2 PASS with notes / 1 FAIL。** R4 两件 FAIL 的根因（diff 未逐字对照现状）在 R5-1/R5-2 上**真修掉了**：R5-2 的 13 行 diff 与 nav_index.py:76-82 逐字基线全部吻合（机械比对 7/7 行 MATCH），R5-1 的桥分支与 r3 修正 diff 12/12 行逐字一致、lookup_ci 重申行把 R2-8 过滤与 R2-10 新签名合成了一份自洽成文。唯 R5-3 自行成文（r3 对 R4-2 只给 notes 未给 diff，无可抄基线）时**整段 +4 缩进漂移 + `_os_path` 笔误**——照抄落码 res_boot.py 在 import 期 IndentationError，比 R4-3 的运行期 NameError 死得更早。另实锤一处"注记宣称已落实、diff 未实现"：R5-1 的"lookup 桥 dump timeout 统一 60"在实测中仍为 30。

| 项 | 裁决 | 一句话裁决 |
|---|---|---|
| R5-1（R4-1 终版：_run 桥分支 + _run_raw/_ascii_dump/_ascii_cache 成文 + lookup_ci 重申 + 探针②非 ASCII 对） | **PASS with notes** | r3 修正 diff 逐字采用（12/12 行一致，`args_of`/四段死代码全消）；lookup_ci 重申行上下文/-行与现状 :798-799 逐字吻合、新调用 `["-i"], names=(name,)` 与 R2-10 调用点形态一致、过滤行与 R2-8 逐字一致——三份补丁争抢的同一行终获自洽成文；`_needs_ascii_bridge` 全仓零残留；探针②非 ASCII 对实测双命中。notes：**"timeout 统一 60"注记与 diff 不符（实测 lookup 首查 dump=30s）**；argv 续行形态与 R2-10 单行形态需落码时择一；prefix 窄化 vs r2"一律 dump"的取舍理由仍缺 |
| R5-2（R4-3 终版：_write_json 13 行 diff） | **PASS** | 4 上下文行 + 3 删除行与 nav_index.py:76-82 **逐字节全 MATCH**（含全角注释），+13 行与"13 行 diff"声称一致；R4-3 四缺陷（path,data / _threading / indent=1 / 凭空 try-finally）全部消除；无 finally、无 indent、无 _os 别名；模块级 os:25/threading:29/time:30 在场；实验 B1-B4 全矩阵复现通过（B3 110ms 重试命中 ≈ r3 的 108ms）；8 写者穷举与 r3 一致 |
| R5-3（R4-2 notes 三件落实：删 _os 别名 + with 句柄 + 空版本兜底） | **FAIL** | 三件落实方向全对（res_boot.py:28 `import os` 在场实证、with 句柄与 res_install._ver:521-526 同款、兜底+`or ""` null 边界齐）；**但 diff 文本两处硬伤：①`_os_path`（LOG:1379）全仓无定义，实测 NameError 被 `except Exception` 吞掉→版本静默丢失（R2-9 要治的病复发且无崩溃信号）；②整段相对 R4-2 基线统一 +4 缩进漂移（机械比对：全部上下文/-行无一 exact 匹配、忽略缩进才匹配）——照抄落码 res_boot.py import 期 IndentationError（实测复现），server 启动失败**。终稿裁定：该行应为 `os.path`（开发者自标待复核，本报告确认） |
| R5-4（R4-4 notes：缓存表述重写） | **PASS with notes** | "现状单查询面有效，常驻化后跨查询有效"与实例生命周期一致（:899 每次 new 实测两实例缓存独立；同实例内多查询共享实测 mtime 命中零新 dump）；r2 批评的"作用有限"低估口径已删除、"实例随 _open_tags 生命周期"的 r3 指摘已改准确。notes：①"单次查询面"易误读为"单次查询"，宜对齐 r2 原文"单请求内多查询共享（r1 乘数问题的解）"；②r2 原文"跨请求不共享是防 200MB 级常驻内存的正确取舍"半句被升级叙事替代，宜补回 |

---

## 逐件详情

### R5-1（R4-1 FAIL → 终版）——**PASS with notes**

**逐字基线核（本轮首要审计点）**：

1. **_run 桥分支（LOG:1285-1296）**：与 r3 修正 diff（patch-review-r3-backend.md:52-63）**12/12 行逐字一致**（脚本比对序列相等）。R4-1 的四段死代码（`_ql`/`_parsed`/if-pass/恒真 return）与未定义符号 `args_of` 全部不存在。
2. **上下文锚点溯源**：`if not self._exe:` / `return []` 与现状 nav_index.py:761-762 逐字吻合；`def _run(self, flags, names=(), timeout=30):` 与 argv 行不在现状文件（现状 :760 是旧签名 `args`、:763 是 `+ args` 单行）——其基线是 **R2-10 落地形态**（R2-10 为链内已 PASS 补丁，r3 现状核对亦确认"签名合并方向正确"），符合本轮方法论"上下文行以 r3 审计员给出的以现状为基线版本为准"。argv 两行续行形态（`+ flags \` 换行 `+ (["-"] + list(names) if names else [])`）可溯源至 r2 修正方向（patch-review-r2-backend.md:78-79），**非作者杜撰**；与 R2-10 单行形态语义等价（拼接核过，仅排版差异）。落码时 R2-10 单行 + R5-1 两行续行需择一，且 R2-10 的三行注释在 `return []` 与 argv 之间的插入位需与桥分支对齐（桥分支须在 argv 行之前）——note ①。
3. **_run_raw/_ascii_cache/_ascii_dump 成文段（LOG:1297-1317）**：`_run_raw` 函数体与现状 :764-769 **逐行同构**（仅 `args`→`argv_tail`），真 API 无伪代码；`_ascii_dump` 与 r2 修正方向形态一致——**模块级 os（`os.path.getmtime`），R2-8 版的函数内 `import os as _os` 已按 r3 指令删除**；`_ascii_cache = None` 类属性挂载正确（实例赋值遮蔽，不可变默认值安全）。
4. **lookup_ci 重申行（LOG:1320-1324）**：上下文行 `def lookup_ci(self, name):` 与删除行与现状 :798-799 **逐字节 MATCH**；新调用 `self._run(["-i"], names=(name,))` 与 R2-10 调用点形态逐字一致；过滤行 `low = name.lower()` + `if r and r[0].lower() == low]` 与 R2-8 diff 逐字一致——r3 指出的"三份补丁各改一次同一行、终版无法自洽成文"至此**达成单一自洽成文**（R2-8 过滤 × R2-10 签名合体）。
5. **lookup 过滤保留声明**：注记"现状 `r[0] == name` 保留 ✓"与现状 :794 逐字吻合。
6. **prefix**：R5-1 声明保持 R4-1 已写形态（LOG:1184-1192：`if not q.isascii():` 桥接 + `r[0].lower().startswith(ql)` 过滤 + 直查回退）——该形态 r3 已实证精确收窄，本轮实验复现（见下 E1-E3）。
7. **`_needs_ascii_bridge` 删除**：diff 内删除声明在位（LOG:1318）；全仓 grep（除 .git/build/dist）仅 doc/ 三份历史报告命中，**src/tests/tools 零残留** ✓（该函数从未落码，删除声明=防止从 R2-8 文本误带入）。

**实验复核（真 readtags.exe + 12 符号 fixture，含 `-l` 同名注入条目与 CI 对）**：

| 探针 | 结果 | 与 r3 对照 |
|---|---|---|
| E1 `prefix('中文函数')` | 恰 `['中文函数']` | 一致（精确收窄复现） |
| E2 `prefix('get_中文')` | 恰 `['get_中文']` | 一致 |
| E3 `prefix('Get_中文')` | `['Get_中文']` | r3 已知敏感缺口面：`prefix('get_中文')` 不含 `Get_中文`（首字窄化敏感超集不含大写变体）——维持 r3"无回归、substring 档兜底"判定 |
| E4 `lookup_ci('get_中文')` **探针②** | `['Get_中文','get_中文']` **双命中** | 一致——R5-1 把探针②改为非 ASCII 对后**验证到位**（桥分支 `-i` 保留被真实覆盖） |
| E5 `lookup_ci('中文函数')`（首字非 ASCII → dump 分支） | 恰 `['中文函数']` | 一致 |
| E6 `lookup_ci('PROBE_WORK')` | `['PROBE_WORK','probe_work']` | ASCII 直查不进桥（`_run_raw` 插桩无 dump 调用）——印证 r3"原 ASCII 探针对桥零覆盖"的判断 |
| E7 `lookup('中文函数')` | 恰 1 行精确命中 | 一致 |
| E8 `lookup('-l')` | 恰 1 行、无尖峰 | R2-10 引证复现（见新发现区 3：首版 fixture 注入行形态不当时返回空，非行为缺陷） |
| E9 `prefix('getX')` ASCII 直查 | `['getX','getX2']` 敏感口径 | 一致（R2-12 裁决维持观察口径） |
| E10 `lookup('-中文')` 桥边缘 | `[]` 干净失败 | 与 r3 新发现 1 同口径（可选封死 `_q[0] != "-"` 未采纳——留档口径，非缺陷） |
| E12 mtime 缓存 | 同实例后续查询 0 新 dump | r1 乘数问题之解实证 |
| E13 实例独立性 | 两次构建两实例、新实例 `_ascii_cache=None` | R5-4 证据（见下） |

**timeout 60 统一（审计点⑤）——注记与 diff 不符（note ②，本轮重点新发现）**：
注记声称"（lookup 桥接 dump 分支 timeout 统一 60——notes⑤）"，但被采用的 r3 diff 中 dump 分支写的是 `return self._ascii_dump(timeout)`——**透传覆盖了 `_ascii_dump(timeout=60)` 的签名默认**。实测（fresh 实例插桩）：`lookup('中文函数')` 首查 dump → `_run_raw(['-l'], timeout=30)`；`lookup_ci('中文其他')` 同为 30；仅 prefix（显式 timeout=60）为 60。即 lookup/lookup_ci 的桥 dump 实际仍是 30s。定级：r3 note b 本身判"110 万行 dump 7s 级、30s 够用"，属惯例一致性问题，不构成 FAIL；但"注记宣称已落实、diff 未实现"正是 R4-1 lookup_ci 缺失件的同型病，**必须二选一**：桥 dump 分支改 `return self._ascii_dump(max(timeout, 60))`（推荐——只影响 dump 分支），或 lookup/lookup_ci 调用点显式 `timeout=60`（会同时改 ASCII 直查超时，波及面大不推荐），并同步更正注记文字。

**notes 汇总**：①argv 续行/R2-10 注释插入位的合并次序（上述）；②timeout 60 声称未落地（上述，附修法）；③prefix 保持首字窄化、与 r2"一律 dump"建议的背离**仍未附取舍理由**（r3 三问 3 遗留；实证无回归，仅记录义务）；④`_ascii_cache` 行注释未带 r2 原文"实例级=请求级；不升级模块级（防 readtags 档常驻内存）"内存面半句（表述面由 R5-4 承担，注释可顺手补）。

**结论**：r3 FAIL 三主因（args_of、lookup_ci 缺口、四段死代码）+ 两 notes（引用件未成文、探针②）全部修复且经逐字比对与实验双重确认；余 note ② 一行修正 + 三条记录义务。**PASS with notes。**

---

### R5-2（R4-3 FAIL → 终版：_write_json 13 行 diff）——**PASS**

**逐字基线核（R4-3 教训专项）**：脚本比对 R5-2 diff 块（LOG:1338-1357）对现状 nav_index.py:76-82——

| diff 行 | 现状锚点 | 结果 |
|---|---|---|
| ` def _write_json(p, obj):` | :76 | 逐字 MATCH |
| `     os.makedirs(os.path.dirname(p), exist_ok=True)` | :77 | 逐字 MATCH（R4-3 缺失的 makedirs 行回到 diff） |
| `     # tmp 唯一化（并发写同库时固定名交错覆盖）` | :78 | 逐字 MATCH（全角注释含标点） |
| `     tmp = "%s.%d.tmp" % (p, threading.get_ident())` | :79 | 逐字 MATCH（`threading.get_ident()` 非 `_threading`） |
| `-    with open(tmp, "w", encoding="utf-8") as f:` | :80 | 逐字 MATCH |
| `-        json.dump(obj, f, ensure_ascii=False)` | :81 | 逐字 MATCH（**无 indent**） |
| `-    os.replace(tmp, p)` | :82 | 逐字 MATCH |

R4-3 四缺陷（p,obj→path,data、threading→_threading、无 indent→indent=1、凭空 try/finally 骨架）**全部消除**；`+` 行恰 **13 行**与"13 行 diff"声称一致；无 finally、无函数内 import。模块级依赖在场：`os`:25、`threading`:29、`time`:30（注记"time :30 已导入"属实）。

**应用后终态语义核**：makedirs 在 try 外（目录不可建直接传播、无 tmp 可清——行为正确，r3 新发现 3 口径维持）；清理包全段（dump TypeError 与 replace OSError 均经外层 `except Exception` → `os.remove(tmp)` → `raise`）；`if _i == 2: raise` 重试耗尽传播 PermissionError；`raise` 重抛保 traceback；8 写者 raise 语义与现状一致（调用方 except 均已兜，r3 已穷举）。

**实验复核（落码后形态 B1-B5，%TEMP%）**：

| 场景 | 结果 | 与 r3 对照 |
|---|---|---|
| B1 正常写（含中文值） | 成功、内容正确、tmp 零残留 | 一致 |
| B2 dump TypeError（set 值） | raise ✓ + tmp 清理 ✓ + 目标未误写 ✓ | 一致（清理包全段真实关闭 r2 新发现③缺口） |
| B3 读者持目标句柄 60ms | **110ms 完成**（重试命中）、零残留 | 一致（r3 实测 108ms，同数量级） |
| B4 读者持住超重试窗（400ms） | PermissionError 可见失败 + tmp 清理 + 旧内容完好 | 一致 |
| B5 深层目录不存在 | makedirs 兜住、成功写入 | 补充验证 |

**8 写者兼容**：grep 穷举 nav_api.py:232 + nav_index.py:237/:239/:391/:490/:543/:589/:1191 共 **8 处**，与 r3 穷举完全一致；全部 dict 语义、现状已能 dump 成功，R5-2 不改输入输出形态（紧凑 JSON 维持，无 indent）。

**结论**：diff 与现状逐字基线一致、机制与 r1/r2/P-7 裁决一致、实验全过、写者全兼容。**PASS**（无待落实 notes）。

---

### R5-3（R4-2 notes 三件落实）——**FAIL**

**三件落实的语义层核对（方向全对）**：
1. **`import os as _os` 删除** ✓——res_boot.py:28 `import os` 在场（本轮字节级确认 :27-32 import 块 json/os/shutil/struct/subprocess/sys），r3 note a 指出的失实注释（"res_boot.py 现无 os 导入"）随整行删除，直接用模块级 os——正确。
2. **with 文件句柄** ✓——`with open(...) as _f: _v = _j.load(_f)` 与 res_install.py:521-526 `_ver` 惯例（`with open(os.path.join(d, "lib", "package.json"), ...)`）同款；r3 note c 关闭。
3. **空版本兜底 + null 边界** ✓——`.get("version", "") or ""` 把 version=null 收敛为 ""（r3 note c 边界补齐）；`("codegraph " + _v) if _v else "codegraph 已安装"` 落实 r3 note b。

**FAIL 主因（diff 文本层两处硬伤，机械比对 + 实验双重实证）**：

1. **`_os_path` 笔误（LOG:1379）**：`with open(os.path.join(_os_path.dirname(_exe), ...)` ——`_os_path` 全仓 grep 仅命中 patch-log.md 本行及两处自标注记，r2/r3 报告中均不存在，链内任何补丁亦未定义过该名。**实验**：以补丁原句执行 → `('exception-swallowed', 'NameError', "name '_os_path' is not defined")` ——NameError 被 `except Exception: _v = ""` **吞掉**，probe 返回 ("ok", "", "codegraph 已安装")：**版本显示静默丢失，恰好复发 R2-9 要治的病，且无任何崩溃信号**（比 args_of 的硬炸更隐蔽）。终稿裁定（开发者自标请第 6 轮复核，本报告确认）：**该行应为 `os.path`**，即 `with open(os.path.join(os.path.dirname(_exe), "lib", "package.json"), encoding="utf-8") as _f:`。
2. **整段 +4 缩进漂移（R4-3"indent 私改"同型复发）**：R5-3 的全部上下文行/-行对 **R4-2 落地形态**（LOG:1202-1229，`def _probe_codegraph():` 在 0 缩进——与 res_boot.py 既有 probe 函数同构，实测 `def probe_bili():` 即模块级 0 缩进 :294）**无一 exact 匹配，全部"忽略缩进才匹配"**（机械比对输出：R5-3 的 def@4 / from@if@8 / _v@try@12 / import json@16，基线为 0/4/8/12）。uniform +4。**实验**：按 R5-3 所示缩进成文 → `compile()` 即 `IndentationError: unexpected indent`——res_boot.py **import 期炸，server 启动失败**，比 R4-3 的运行期 NameError 更早更广。标准 patch 应用同样失败（上下文行不存在）。

**FAIL 定性**：R5-3 是 R5 四件中唯一没有"r3 审计员以现状为基线的修正 diff"可逐字采用的一件（r3 对 R4-2 只给 notes）——方法论更正"上下文行以 r3 版本为准"对无 r3 版本可抄的件失去了约束力，作者自行成文时重排了整段缩进并引入 `_os_path`。R4-3 教训在此件的落点。

**修正方向（以 R4-2 落地形态为基线逐字重写——def@0，终稿 os.path）**：
```diff
-import os as _os   # 模块级（res_boot.py 现无 os 导入——R2-9 NameError 根因）
-
 def _probe_codegraph():
     from src import nav_codegraph as _ncg
     if _ncg.available():
         _v = ""
         try:
             # 版本路径抄 res_install._ver 惯例：dirname(exe)/lib/package.json
             # （无 ".."——R2-9 实证三种 bundle 形态全 404）
             import json as _j
             _exe = _ncg._cg_exe() or ""
-            _v = _j.load(open(_os.path.join(_os.path.dirname(_exe),
-                "lib", "package.json"), encoding="utf-8")).get("version", "")
+            with open(os.path.join(os.path.dirname(_exe),
+                "lib", "package.json"), encoding="utf-8") as _f:
+                _v = _j.load(_f).get("version", "") or ""
         except Exception:
             _v = ""
-        return ("ok", _v, _v and ("codegraph " + _v) or "")
+        return ("ok", _v, ("codegraph " + _v) if _v else "codegraph 已安装")
     return ("missing", "", "")
```
（此形态实验实证：真 offline_assets/codegraph/lib/package.json → `('ok', '1.6.0', 'codegraph 1.6.0')`，与 r3 实证一致；with 句柄与 _ver:521-526 同款；缩进与 res_boot.py 模块级 def 惯例一致。）

**附注（不另立 notes）**：兜底文案"codegraph 已安装"落在 ok 态 detail 槽——settings.js:866 `const detail = it.ok ? '' : ...` 短路下**永不渲染**（r3 note d 同款观察，死值无害）；ver 槽空版本的可见问题（npm shim 形态显示"✓ 已就绪"无版本）实际未被兜底解决——兜底的真实价值仅在 probe_all 调试/日志面。这是 r2 原建议自身的局限，非 R5-3 新增缺陷。

---

### R5-4（R4-4 notes：缓存表述重写）——**PASS with notes**

**生命周期一致性核（审计点）**：
- **代码事实**：_open_tags（:885-902）对 readtags 档每次 `be = _ReadtagsBackend(ld)`（:899）新建实例，不进 _tagdb_cache（:882 仅 _TagDB 常驻）；引用存活至请求处理结束。
- **实测**：两次构建 → 两实例 `is` 为 False、新实例 `_ascii_cache=None`（缓存不跨实例）；同实例内 E12——缓存填充后连续 `lookup`/`lookup_ci` 各一次，`_run_raw` 调用数零增长（mtime 键命中）。
- **多查询共享面**：symbols()（:1059 取实例 → :1088 lookup_ci / :1091 prefix / :1093 substring / :1099 push→lookup 逐候选）与 definition()（:1276 → :1279 lookup / :1282 lookup_ci 回退）都是**单次调用=单实例=多查询**——"同实例内多查询共享 dump"与代码事实一致；跨请求（新实例）不共享。
- R5-4 表述"现状单查询面有效，常驻化后跨查询有效"与上述一致；r2 批评的"作用有限"低估口径**已删除** ✓；r3 指摘的"实例随 _open_tags 生命周期"不准确表述已改为"当前 _open_tags 每次新建实例"（准确）✓；"与 _TagDB 同款"的常驻化指涉真实存在（_tagdb_cache :882）✓。

**notes**：
1. **"单次查询面"措辞**：脱离前句单独读易误解为"单次查询"——而实证恰恰是**一次请求处理期内多查询共享**（symbols() 一次调用四类查询同实例；50 候选 × push→lookup 的 r1 乘数场景即靠它收敛为 1 次 dump，E12 实证）。建议对齐 r2 原文措辞"作用域=**单请求内多查询共享（r1 乘数问题的解）**"，把乘数问题的解这一功劳写明——这正是 r2 要求重写表述的动机（防止后人误删缓存）。
2. **取舍半句缺失**：r2 原文的另一半"跨请求不共享是**防 200MB 级常驻内存的正确取舍**"（r2 实证模块级缓存 = 250~350MB Python str 常驻，复活 readtags 档要避免的 memory 档内存面）被"常驻化后跨查询有效"的升级叙事替代。升级叙事本身不错，但**未保留防常驻内存的取舍理由**——后人可能把"常驻化"当无成本升级执行。建议补回成本半句（或"常驻化需同时解决 200MB 级常驻内存"）。

**结论**：表述与实例生命周期一致、两个 r3/r2 指摘真修，方向正确；两处措辞建议落实后即闭环。**PASS with notes。**

---

## 新发现区（本轮审计过程新撞见，单列）

1. **"注记宣称已落实、diff 未实现"的再发（R5-1 timeout 60）**：R5-1 注记"（lookup 桥接 dump 分支 timeout 统一 60——notes⑤）"与其采用的 diff（`self._ascii_dump(timeout)` 透传 lookup 默认 30s）不符，实测锤实（fresh 实例 `_run_raw(['-l'], 30)`）。这与 R4-1 的"lookup_ci 注释宣称过滤却没写"同型——区别仅在本次是低危 notes 项而非过滤缺失。建议立规：**注记中"已统一/已落实/保留 ✓"类断言必须指向 diff 中的具体行**，第 6 轮起审计照此逐条对行。
2. **R5-3 无基线可抄时方法论失效**：R5-3 是本轮唯一 r3 未给修正 diff 的件，作者自行成文即发生整段缩进重排 + `_os_path` 笔误——R4-3 教训的精确复现条件是"作者手写 diff"。建议补一条方法论：**凡上一轮审计只给 notes 未给 diff 的落实件，其 diff 的上下文行/-行必须逐字复制上一轮补丁的 + 段原文（含缩进），禁止重排**。
3. **vendor readtags 6.2.0 对非标准 pattern 字段行静默跳过**：实验首版 fixture 手工注入的 `-l` 条目（pattern 字段写 `def -l();"` 而非 ctags 原生 `/^def -l():$/;"`）在 `-l` 列表动作与 `[-] -l` 名称查找下**双双不可见**（线性搜索 -s0 亦然）；换成原生形态后三形态全中。对在库 tags 无影响（ctags 产出即原生形态），但**手写 tags fixture 的实验会因此产生假阴性**——r2 引证的 `["-p","-","-l"]` → 恰 1 行在本轮正确 fixture 下复现无碍。与 R4-4 ②"vendor [-] 多 NAME 只匹配最后一个"同属 vendor 宽容度观察区，留档。
4. **`_write_json` 对 BaseException 不清理**（预置语义，非 R5-2 引入）：`except Exception:` 不捕 KeyboardInterrupt/SystemExit，Ctrl+C 打断 dump 时 tmp 残留——与现状（任何失败都残留）同口径，且发生率与影响面（一个 N 字节 tmp 文件、下次写同库时被固定名覆盖）均可忽略。留档即可，不建议扩大清理范围。

---

## 实验留存说明

全部实验在 `%TEMP%/rt_audit_r6` 搭建（真 vendor readtags.exe 6.2.0 + ctags.exe 生成的 UTF-8 fixture + `-l` 同名注入条目 + CI 探针对；`python -I` 运行；`_write_json` 行为矩阵与 probe 三形态对照均在临时目录完成，仓库零写入——`git status` 全程仅 `?? doc/` 未跟踪目录，无源码改动）。报告提交后临时目录整体清理。关键实证：

| 实验 | 结果 |
|---|---|
| R5-1 桥分支 vs r3 修正 diff | 12/12 行逐字一致（脚本比对） |
| R5-1 lookup_ci diff vs 现状 :798-799 | 上下文+删除行逐字节 MATCH |
| R5-1 终版形态 E1-E10 探针 | 全部复现 r3 实证（含探针②双命中 `['Get_中文','get_中文']`） |
| R5-1 fresh lookup 首查 dump timeout | **30s（非 60）**——注记"统一 60"未落地实证 |
| R5-2 diff vs nav_index.py:76-82 | 7/7 行逐字节 MATCH，+13 行 |
| R5-2 B1/B2/B3/B4/B5 | 成功零残留 / TypeError 清理 / 110ms 重试命中 / 超窗干净失败 / makedirs 兜底 |
| `_write_json` 写者穷举 | 8 处（nav_api:232 + nav_index:237/239/391/490/543/589/1191） |
| R5-3 笔误形态 `_os_path` | NameError 被吞 → 版本静默丢失 |
| R5-3 原样缩进 def@4 | **IndentationError（import 期）**——server 启动失败 |
| R5-3 终稿形态 os.path（真离线包） | `('ok', '1.6.0', 'codegraph 1.6.0')` |
| R5-4 实例/缓存 | 两实例独立、新实例 cache=None；同实例多查询 0 新 dump |
| 全仓 grep（args_of / _needs_ascii_bridge / _os_path / _run_raw 等） | 代码区零命中，仅 doc 历史文本 |
| readtags fixture 注入形态对照 | 非 `/^..$/;"` pattern 行被解析器静默跳过（新发现 3） |
