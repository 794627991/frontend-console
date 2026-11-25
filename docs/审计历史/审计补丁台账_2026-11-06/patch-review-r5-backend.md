# 后端补丁合理性审计报告 r5（patch-review-r5-backend）· 第 6 轮修订收官终审

- 审计对象：doc/patch-log.md【第 6 轮修订·后端组】R6-1 / R6-2 +【第 6 轮修订补充】R6-2 精确化一行 + R6-3（方法论入档），共 3 件逐件裁决
- 审计方式：白盒逐字基线核对（收官终审零容忍锚点漂移——**全部 diff 上下文行/-行/+行脚本化逐行比对**，非目测）+ 只读实验（%TEMP%/r5_audit/exp，`python -I` 运行，仓库零写入）
- 对照基线三源：①src/res_boot.py 与 src/nav_index.py **现状字节**；②链内已 PASS 补丁落地形态（R4-2 / R2-10 / R5-1 文本）；③r4 审计员修正 diff（patch-review-r4-backend.md:114-134）
- 源码状态确认：R2~R6 各补丁均未落码（res_boot.py:43-67 MANIFEST 8 kind 无 codegraph、:301-304 _PROBES 无注册、全文件无 `_probe_codegraph`；nav_index.py:760 `_run(self, args, timeout=30)` 旧签名、:790-796 lookup 现状 `self._run([name])`）——**本轮审计对象为补丁文本**（与 r4 报告同口径），"R4-2 已落形态"指链内已 PASS 补丁的 + 段最终形态基线
- 现状锚点实证（本轮逐一复核）：res_boot.py:28 `import os` 在场；:294 `def probe_bili():` 模块级 0 缩进惯例；nav_codegraph.py:78 `available()` / :48 `_cg_exe()` 真实存在（bundle 场景返回 `<bundle>/node.exe` 全路径）；res_install.py:521-526 `_ver` 惯例 `with open(os.path.join(d, "lib", "package.json"), encoding="utf-8")` + `.get("version") or ""`；真离线包 `offline_assets/codegraph/node.exe` 与 `codegraph/lib/package.json`（version=**1.6.0**）同级同构——dirname(exe)/lib/package.json 拼接命中真文件

---

## 结论先行

**1 PASS / 2 PASS with notes / 0 FAIL。** 两件收官件的核心锚点全部坚实：R6-1 的落码蓝本（r4 审计员修正 diff）对 R4-2 应用形态 **17/17 行 EXACT**（机械比对），终稿 compile 无 IndentationError、真 bundle 形态运行 `('ok', '1.6.0', 'codegraph 1.6.0')`、missing 三空契约过 settings.js:867 渲染矩阵；R5-3 两坑在本机**双双复现**（def@4 缩进 → `IndentationError: unexpected indent`；`_os_path` → NameError 被 `except Exception` 吞 → `('ok', '', 'codegraph 已安装')` 版本静默丢失）并被终稿消除。R6-2 精确化一行对 R5-1 + 段 **12 缩进逐字 EXACT**，实验矩阵：lookup/lookup_ci 桥 dump 30→**60**（注记"统一 60"真落地）、prefix 桥（显式 60）不变、ASCII 直查 30 原样——非桥路径零影响实证。

R6-2 裁决 **PASS**（干净）。R6-1 裁决 **PASS with notes**：终稿内容正确且锚点坚实，**但 patch-log 块内 diff 是 r4 修正 diff 的失真转写**——`-` 段第 1 行丢了 `os.path.join(`（三处基线均无锚点）、缺 `-import os as _os` 删除对、缺注释两行、return ok 旧形态 -/+ 对改为上下文表示；落码蓝本由 LOG:1473「r4 报告内的修正 diff 为准」兜底指定，照抄块内上下文+段成文产物仍正确（不会炸），故不构成 FAIL——但这已是"注记宣称与文本实体不符"的第 3 例（R4-1 lookup_ci 注记、R5-1 timeout 注记、R6-1 采用声明）。R6-3 裁决 **PASS with notes**：方法论条文已入档，但相对 r4 建议原文**收窄两处**（丢"/-行"、丢"含缩进，禁止重排"），收窄处恰在本轮 R6-1 的 `-` 行失真上失去约束力；另 R6-3 关联的 R5-4 表述替换声明"更正为 r2 原文口径"但 R5-4 段文本未实际替换（文档性欠账）。

| 项 | 裁决 | 一句话裁决 |
|---|---|---|
| R6-1（R5-3 终版：_probe_codegraph os.path 修正） | **PASS with notes** | r4 修正 diff（落码蓝本）对 R4-2 基线 17/17 EXACT，双坑消除实证（compile OK + 真包 `('ok','1.6.0','codegraph 1.6.0')`）、missing 三空过 :867 渲染矩阵（detail\|\|fix → MANIFEST.fix）；notes：块内 diff 转写失真 4 处（- 行丢 `os.path.join(` 无锚点为最重）——蓝本以 r4 报告为准已由 LOG:1473 指定，照抄块内成文产物仍正确 |
| R6-2（R6-2 精确化：`self._ascii_dump(max(timeout, 60))` 一行） | **PASS** | `-` 行对 R5-1 + 段 12 缩进逐字 EXACT（新方法论模范落实）；max 语义实验矩阵 30→60/60→60/90→90/120→120，ASCII 直查 30 原样、substring/by_path/files 不经过该行——非桥路径零影响实证；行尾注释把注记断言钉进 diff 具体行 |
| R6-3（方法论补丁文档性核验：逐字复制规则入档） | **PASS with notes** | 条文已入档（LOG:1508）且 R6-2 是其模范落实；notes：①条文相对 r4 原文收窄（丢"/-行"与"含缩进，禁止重排"）——恰在本轮 R6-1 `-` 行失真处失去约束力，建议补全；②R6-3 的 R5-4 表述替换（LOG:1489"更正为 r2 原文口径"）在 patch-log R5-4 段（:1393）未实际执行 |

---

## 逐件详情

### R6-1（R5-3 FAIL → 终版：res_boot.py _probe_codegraph 的 os.path 修正）——**PASS with notes**

**审计点①：r4 修正 diff 与 R4-2 已落形态基线逐字核（脚本比对，非目测）**

r4 审计员修正 diff（patch-review-r4-backend.md:114-134，21 行）的全部上下文行与 `-` 行对 [R4-2 应用后形态]（patch-log.md:1202-1229 的 + 行与上下文行合成，即"R4-2 落地形态"）——**17/17 行 EXACT**，含全角注释与行尾注释逐字节：

| r4 diff 行 | 对 R4-2 应用形态 | 结果 |
|---|---|---|
| `-import os as _os   # 模块级（res_boot.py 现无 os 导入…）` | :1202 + 行 | EXACT |
| （空行） | :1203 | EXACT |
| `def _probe_codegraph():`（@0） | :1204 上下文 | EXACT（与 res_boot.py:294 probe_bili 同构 def@0） |
| `    from src import nav_codegraph as _ncg` | :1205 | EXACT |
| `    if _ncg.available():` | :1206 | EXACT |
| `        _v = ""` / `        try:` | :1216/:1217 | EXACT ×2 |
| `            # 版本路径抄 res_install._ver 惯例…` / `            # （无 ".."…）` | :1218/:1219 | EXACT ×2 |
| `            import json as _j` / `            _exe = _ncg._cg_exe() or ""` | :1220/:1221 | EXACT ×2 |
| `-            _v = _j.load(open(_os.path.join(_os.path.dirname(_exe),` + 次行 | :1222/:1223 | EXACT ×2 |
| `        except Exception:` / `            _v = ""` | :1224/:1225 | EXACT ×2 |
| `-        return ("ok", _v, _v and ("codegraph " + _v) or "")` | :1226 | EXACT |
| `    return ("missing", "", "")` | :1227 | EXACT |

`+` 段 4 行（终稿增量）与 R6-1 块内 diff 的 + 段 2 行经精确比对：**R6-1 的 2 行 + 行与 r4 + 段前 2 行逐字 EXACT**。落码蓝本锚点坚实。

**审计点②：os.path.join 语义（dirname(exe)/lib/package.json）**

- 与 res_install.py:521-526 `_ver` 惯例**同款逐字**（`os.path.join(d, "lib", "package.json")`，无 ".."，with 句柄，`.get(...) ... or ""` null 边界）。
- 真离线包结构实证：`offline_assets/codegraph/` 下 `node.exe` 与 `lib/package.json`（version=1.6.0）同级同构——`os.path.dirname(_exe)/lib/package.json` 命中真文件；实验（仿真 `_cg_exe()` 指向 fake bundle/node.exe）返回 `('ok', '1.6.0', 'codegraph 1.6.0')`，与 r4 实证一致。
- 防御分支：`_cg_exe()` 返回 None → `or ""` → join("") 相对路径 → FileNotFoundError → except → `_v=""`，不炸（r2/r4 已实证，形态未变）。

**审计点③：NameError / IndentationError 双坑确认消除（双坑均在本机复现后验证消除）**

| 实验（%TEMP%/r5_audit/exp，`python -I`） | 结果 |
|---|---|
| R5-3 原文缩进（def@4）成文 → `py_compile.compile(doraise=True)` | **FAIL：`IndentationError: unexpected indent`（import 期，server 启动失败）**——r4 复现一致 |
| R5-3 内容体（`_os_path` 保留、缩进归位使其可执行）→ 运行 | **`('ok', '', 'codegraph 已安装')`**——NameError 被 `except Exception: _v=""` 吞，版本静默丢失——r4 复现一致（R2-9 要治的病无信号复发） |
| R6-1 终稿整段（def@0、`os.path`）→ compile | **OK**——IndentationError 消除 |
| R6-1 终稿整段 → bundle 可用运行 | **`('ok', '1.6.0', 'codegraph 1.6.0')`**——NameError 消除、版本真显示 |

**审计点④：missing 态 ("missing","","") 契约与 settings.js:867 渲染矩阵**

- 终稿 missing 行 `return ("missing", "", "")` 为上下文行（未改动），与 R4-2 终态一致；实验：available()=False → `('missing', '', '')` ✓。
- web/js/settings.js 渲染矩阵现状：:861-863 ok 态 badge "✓ 已就绪" + `it.ver ? ver` 槽；:864-865 非 ok 态 badge "✗ 缺失"（state!=outdated）；**:866-867 非 ok 态 detail 槽 `esc(it.detail || it.fix || '')`**。missing 三空 → detail=""（falsy）→ 回落 **MANIFEST.fix**（链内 R2-9/R4-2 保留态文案"安装离线资源包（或设置→外部依赖安装单装）"）→ fix 指引可见——R2-9"fix 指引死路"维持关闭，probe_bili 惯例对齐。与 R4-2 契约注释（LOG:1228-1229）逐字一致。
- r4 附注口径维持：ok 态兜底文案"codegraph 已安装"在 :866 `it.ok ? ''` 短路下不渲染（死值无害，probe_all 调试面有价值）——R6-1 未改此行为，一致。

**notes（R6-1 块内 diff 与 r4 修正 diff 的转写失真——不改变终稿裁定，但须留档）**

R6-1 声称"采用 r4 审计员修正 diff——以 R4-2 落地形态为基线逐字"，但块内 diff（LOG:1456-1471，16 行）**不是** r4 修正 diff（21 行）的逐字转写，机械比对 4 处实质差异：

1. **`-` 段第 1 行 `with open(_os_path.dirname(_exe),` 三处基线均无锚点（最重的一处）**。R5-3 + 段原文（LOG:1379）是 `with open(os.path.join(_os_path.dirname(_exe),`——块内 `-` 行**丢了 `os.path.join(`**（8 字符）；R4-2 应用形态对应位置是 `_v = _j.load(open(_os.path.join(...` 两行（完全不同）；现状源码无此函数。即该 `-` 行是凭空文本——第 5 轮方法论（上下文行/-行须在真实文件或链内已 PASS 形态中逐字找到锚点）检验不过，属 R4-3/R5-3"凭空行"病型在删除行上的复发。缓解：`-` 行是删除行，照抄块内上下文+段成文的**终稿产物仍正确**（凭空行不会进入代码），与 R4-3/R5-3 的"照抄上下文行→直接写出崩溃代码"有实质区别。
2. **缺 `-import os as _os` 删除对两行**：从 R4-2 全形态出发落码者若只看块内 diff，会残留 `import os as _os` 死行（无害但与 r4 终稿不一致）。
3. **缺两行注释上下文**（`# 版本路径抄 res_install._ver 惯例…`/`# （无 ".."…）`）：r4 终稿含此两行，块内终稿无——落码产物差两行注释。
4. **return ok 旧形态 -/+ 对改为上下文行表示**：块内 diff 的实际文本基线是"R5-3 文本（R5-3 的语义修正保留）+ R4-2 缩进体系（def@0，归位 -4）"的混合体，而非自称的"R4-2 落地形态"——上下文行锚点实况：10 行对 R4-2 应用形态 EXACT、2 行（`_v = _j.load(_f)...` 与 return ok 新形态）对 R5-3 + 段内容一致（缩进归位）。

缓解（为何仍 PASS）：LOG:1473「（r4 报告内的修正 diff 为准——终稿 os.path 已裁定。）」明确指定权威蓝本为 r4 报告 diff，而该蓝本 17/17 EXACT + 实验复证全过；块内 diff 按上下文+段拼接出的终稿与 r4 终稿**代码行级完全一致**（仅差两行注释与一行死 import）。R5-3 三件语义落实（删 _os 别名→note a、with 句柄→note c、空版本兜底→note b/c）在终稿全部保持。**落码唯一蓝本裁定：patch-review-r4-backend.md:114-134 的 diff 原文，块内 diff 不得单独作为落码依据。**

---

### R6-2（R6-2 精确化：`self._ascii_dump(max(timeout, 60))` 一行）——**PASS**

**审计点①：位置与现状锚点**

- `-` 行 `            return self._ascii_dump(timeout)` 对 R5-1 + 段（LOG:1293）**逐字 EXACT（含 12 空格缩进）**——正是 R6-3 入档规则（notes 落实件的 - 行逐字复制上轮 + 段原文）的模范落实。该行在 R5-1 全文本中**唯一**（`_ascii_dump` 其余出现仅 :1308 签名行），落码定位无歧义。
- 位置标注「_ReadtagsBackend.lookup 桥接 dump 分支」：按**行为链路**口径准确（lookup/lookup_ci 的非 ASCII 查询经 `_run` 桥分支触发 dump——r4 实测 lookup('中文函数') 首查 dump 即此行）；字面代码位置在 `_ReadtagsBackend._run` 桥分支（R5-1 成文段 LOG:1293），沿用 r4 报告与 R5-1 注记的既有口径，非新偏差，不构成缺陷。
- `_ascii_dump` 签名默认 `timeout=60`（LOG:1308）在场——原透传 `timeout`（lookup/lookup_ci 链=30）覆盖签名默认正是 r4 锤实的注记失实根因。

**审计点②：语义（timeout 注记与 diff 对齐）——实验矩阵**

仿真类按 R5-1 成文段终稿形态搭建（插桩 `_run_raw` 记录 timeout，%TEMP%/r5_audit/exp）：

| 场景 | R6-2 前形态（透传） | R6-2 后形态（max） | 判定 |
|---|---|---|---|
| lookup('中文函数') 桥 dump | `(['-l'], 30)` | `(['-l'], 60)` | **注记"统一 60"真落地** |
| lookup_ci('中文其他') 桥 dump | `(['-l'], 30)` | `(['-l'], 60)` | 同上 |
| lookup_ci('中文函数') 桥 -i 保留 | 30 | 60 | 同上 |
| prefix('中文前缀') 桥（调用点显式 timeout=60，LOG:1188） | 60 | 60 | 不变 ✓ |
| max 边界 | — | max(30,60)=60、max(60,60)=60、max(90,60)=90、max(120,60)=120 | 只抬不降 ✓ |

`+` 行 `return self._ascii_dump(max(timeout, 60))   # R6-2：timeout 注记与 diff 对齐` 与 r4 推荐（patch-review-r4-backend.md:56「桥 dump 分支改 `return self._ascii_dump(max(timeout, 60))`（推荐——只影响 dump 分支）」）核心表达式逐字一致，行尾注释把注记断言钉进 diff 具体行——第 5 轮新发现 1 的立规（"注记断言必须指向 diff 中的具体行"）已按规落实。

**审计点③：max 对非桥路径零影响**

- ASCII 直查路径（lookup('getX') → `_run_raw(['-', 'getX'], 30)`）：不经过桥分支 return 行，实验 timeout=30 原样 ✓。
- substring/by_path/files（现状 :807/:818/:825 显式 timeout=60）：names 为空不进桥（R3/r4 已证），不经过该行 ✓。
- ASCII 首字分支 `_run_raw(flags + ["-p", _q[0]], timeout)`（LOG:1292）：不经过该行 ✓。
- 理论边界（留档）：若未来调用方向 `_run` 传 `timeout=None`，现状透传形态=无限 dump（subprocess.run(timeout=None) 合法），R6-2 形态=`max(None, 60)` TypeError——现调用链无任何 None 传参，纯理论，不构成缺陷。

---

### R6-3（方法论补丁文档性核验：notes 落实件逐字复制规则的入档确认）——**PASS with notes**

- **主体已入档**：LOG:1508 第 2 条「notes 落实件的上下文行必须逐字复制上轮 `+` 段原文（R5-3 是唯一没有 r3 修正 diff 可抄的件，手写即复发 R4-3 教训——import 期 IndentationError 比 R4-3 的运行期 NameError 更早更狠）」——背景括号与 r4 报告 FAIL 定性（R5-3 无基线可抄、缩进重排+_os_path、IndentationError 更早更狠）逐项一致 ✓。本轮 R6-2 的 `-` 行即按此规逐字复制 R5-1 + 行（12 缩进 EXACT）——规则可执行且已被执行 ✓。
- **note ①（条文收窄）**：入档版相对 r4 建议原文（patch-review-r4-backend.md:161「其 diff 的**上下文行/-行**必须逐字复制上一轮补丁的 + 段原文**（含缩进），禁止重排**」）**丢了两处限定**：`/-行` 与「（含缩进），禁止重排」。收窄不是纯措辞问题——R6-1 的 `-` 行失真（丢 `os.path.join(`）恰是 `-` 行未被条文约束、缩进/内容重排未被明令禁止的直接适用缺口（同轮入档、同轮踩空）。建议收官前把条文补全为 r4 原文口径；另注意条文与本件（R6-1）存在一个内在张力需要显式说明：R5-3 + 段的缩进本身是 FAIL 主因，"逐字复制含缩进"在缩进漂移件上应精确化为"**内容逐字复制，缩进以最近已 PASS 基线（R4-2 形态 def@0 体系）为准**"——R6-1 的缩进归位正是这样做的（除 os.path.join( 丢失外）。
- **note ②（R5-4 表述替换未执行）**：R6-3 关联件（LOG:1488-1490）声明缓存表述「更正为 r2 原文口径：'单请求内多查询共享 / 防常驻内存取舍'——patch-log R5-4 段替换该两句（文档性）」，但 R5-4 段（LOG:1393）文本**未实际替换**（仍是"现状单查询面有效，常驻化后跨查询有效"）——"注记宣称已更正、文本未更正"的文档版同型病（第 3 例，见新发现 1）。r4 对 R5-4 的两条 notes（单请求内多查询共享 + 防常驻内存取舍半句）因此仍为待落实状态。文档性欠账，收官前把 R5-4 段两句替换掉即可闭环。

---

## 新发现区（本轮审计过程新撞见，单列）

1. **"注记宣称与文本实体不符"第 3 例（R6-1 采用声明）**：R4-1 的"lookup_ci 注释宣称过滤却没写"、R5-1 的"timeout 统一 60 注记 vs diff 30s"、R6-1 的"逐字采用 r4 修正 diff vs 块内转写失真 4 处"——三代同型，前两例由第 5 轮立规（注记断言须指向 diff 具体行）治理，但该规对"**采用声明**"类注记（声称与上一轮报告逐字一致）无覆盖。建议收官冻结 patch-log 前二选一：把 R6-1 块内 diff 整体替换为 r4 报告 :114-134 原文（最干净），或在块内 diff 前加显式标注「块内 diff 为缩进归位示意，- 段系示意转写，落码/复验一律以 r4 报告修正 diff 原文为准」（现 L1473 括号注语义偏弱，未点破 - 段失真）。
2. **R6-2 原版（lookup 调用点改法）残留未标注废弃**：LOG:1481-1485 的原版 diff 仍全文在档，其 `-` 行 `for line in self._run([], names=(name,)):` 对现状 nav_index.py:792（`self._run([name])`）**不符**（锚点=R2-10 链内形态，未落码），且语义上会同时改 lookup 的 ASCII 直查超时（r4 已判"波及面大不推荐"）。它已被【第 6 轮修订补充】的精确化版取代，但补段未写"原版作废"字样——落码者若先读后读顺序错乱，有误用原版风险。建议在原版 diff 处加一行「（已废弃——被【第 6 轮修订补充】精确化版取代，勿落）」。
3. **R5-3 双坑复现数据留档**（收官终审的"病因存档"）：def@4 缩进 → `IndentationError: unexpected indent`（compile 期，比 R4-3 运行期 NameError 更早更狠——r4 判词实证）；`_os_path` → NameError 被 `except Exception` 吞 → probe 返回 `('ok', '', 'codegraph 已安装')`（版本静默丢失、零崩溃信号）。两坑在 R6-1 终稿形态下双双消除（compile OK + `('ok', '1.6.0', 'codegraph 1.6.0')`）。后续任何对 `_probe_codegraph` 的再修订，照此二形态即可快速回归。

---

## 实验留存说明

全部实验在 `%TEMP%/r5_audit`（比对脚本 cmp_diffs.py + exp/ 目录）搭建：仿真 `src/nav_codegraph.py`（available/_cg_exe 与真模块 :48/:78 同签名）+ fake bundle（node.exe + lib/package.json v1.6.0）+ R6-1 终稿/R5-3 双坑三形态文件 + `_ReadtagsBackend` 终稿仿真类（R5-1 成文段形态 + R6-2 一行，插桩 `_run_raw`）；`python -I` 运行，真离线包仅只读核（offline_assets/codegraph 结构与 package.json version）。`git status` 全程仅 `?? doc/`，仓库零写入。关键实证汇总：

| 实验 | 结果 |
|---|---|
| r4 修正 diff vs R4-2 应用形态（R4-2 基线） | 17/17 行 EXACT（脚本比对） |
| R6-1 + 段 vs r4 + 段前 2 行 | EXACT |
| R6-1 `-` 段第 1 行锚点 | R4-2 形态 / R5-3 + 段 / 现状源码三处均无（丢 `os.path.join(`） |
| R6-1 `-` 段第 2 行 / 上下文 5 行 vs R5-3 + 段 | 内容一致、缩进统一归位 -4 |
| R6-1 终稿 compile | OK（IndentationError 消除） |
| R5-3 原缩进形态 compile | IndentationError: unexpected indent（复现） |
| R5-3 内容体（_os_path）运行 | ('ok', '', 'codegraph 已安装')——NameError 被吞（复现） |
| R6-1 终稿 bundle 运行 / missing | ('ok', '1.6.0', 'codegraph 1.6.0') / ('missing', '', '') |
| 真离线包 dirname(exe)/lib/package.json | offline_assets/codegraph/lib/package.json，version=1.6.0 |
| R6-2 `-` 行 vs R5-1 + 段 | 12 缩进逐字 EXACT |
| R6-2 timeout 矩阵 | 桥 dump 30→60（lookup/lookup_ci）、prefix 60 不变、ASCII 直查 30 原样、max 只抬不降 |
| settings.js:866-867 渲染 | 非 ok 态 `it.detail \|\| it.fix` → missing 三空回落 MANIFEST.fix（fix 指引可见） |
| 全仓 grep `_os_path` | 仅 doc/ 历史文本（patch-log R5-3/R6-1 段），代码区零命中 |
| git status | 仅 ?? doc/，零源码改动 |

（临时目录 %TEMP%/r5_audit 于报告提交后整体清理。）
