# 后端补丁合理性审计报告 r3（patch-review-r3-backend）

- 审计对象：doc/patch-log.md【第 4 轮修订·后端组】R4-1 / R4-2 / R4-3 / R4-4（共 4 件，逐件三问裁决）
- 审计方式：白盒对照源码现状逐字核对（nav_index.py / res_boot.py / res_install.py / nav_codegraph.py / nav_api.py / settings.js 渲染区）+ 语法/并发/边界推演 + 只读实验（真 vendor readtags.exe + UTF-8 fixture、补丁文本照抄执行、_write_json 行为矩阵，全部在 %TEMP%/rt_audit_r3 完成，仓库零写入，实验后临时目录已清理）
- 源码状态确认：R2/R3 各补丁均未落码（nav_index.py:882 单槽缓存、:760 旧签名 _run、:76 _write_json 无重试无清理、res_boot MANIFEST :43-67 仍 8 kind 无 codegraph）——本轮审计对象为补丁文本
- 环境注：Windows 10 / Python 3.14.7 / readtags.exe（vendor/ctags）；环境继承 r2（ACP=936 系 C-1 失明根因前提）

---

## 结论先行

**0 PASS / 2 PASS with notes / 2 FAIL。** R2-8 的 FAIL 根因（"声明了过滤没写"）在 R4 里**只在 prefix 一侧真正修掉**，lookup_ci 一侧仍是注释声明；且 R4-1 桥分支混入了未定义符号 `args_of`——照抄落码则中文查询两条主路径（Ctrl+T 前缀、F12 跳转）必炸 NameError。R4-3 机制正确但 diff 上下文行与现状大面积不符，照抄落码 `_threading` NameError 使 8 个写者全灭。

| 项 | 裁决 | 一句话裁决 |
|---|---|---|
| R4-1（R2-8 FAIL 合并形态终版：_run 桥分支+prefix 调用点过滤） | **FAIL** | prefix 的 lower 过滤真写出来了（实验实证精确收窄）、flags 透传矩阵自洽、-i 保留价值实证；**但桥分支 `args_of` 是全仓无定义的未定义符号（照抄 → prefix/lookup 中文查询 NameError），lookup_ci 的 lower 精确过滤只在注释里宣称、diff 未重申（纯 R4-1 应用 → 全库符号污染复活，实验实证 9 符号全出）**——四调用点齐备性在文本层面不成立 |
| R4-2（R2-9 FAIL probe 契约终版：(state,ver,detail) + 模块级 _os + 无 ".."） | **PASS with notes** | 契约对齐（ok 态 ver 渲染 / missing 态 detail 留空让 MANIFEST.fix 出场，实验矩阵四格全过）+ 版本路径 = res_install._ver 同款无 ".."（offline_assets 实证 1.6.0）+ `_os` NameError 消除；notes：`import os as _os` 的注释"res_boot.py 现无 os 导入"失实（:28 已有 `import os`）、ok 态空版本无"已安装"兜底、裸 open 未 close |
| R4-3（P-7 裁决回写：_write_json 本体化重试+清理包全段） | **FAIL** | 机制设计正确且实验全行为矩阵通过（TypeError 清理/重试成功/重试耗尽干净失败）；**但 diff 上下文行与现状 :76-82 大面积不符（p,obj→path,data、threading→_threading、无 indent→indent=1、凭空出现 try/finally 骨架、makedirs 行缺失）——照抄落码 `_threading` NameError，8 个写者一次调用即炸** |
| R4-4（新发现纳入：⬇ 清单/rebind 多 NAME 留档/缓存表述更正） | **PASS with notes** | ①settings.js:788/:1661 两处 ⬇ 实证在位、归前端组职责划清 ✓；②vendor 多 NAME 留档与"转义位后恒单查询名"复核成立 ✓；③"缓存作用有限"的表述**延续了 r2 新发现④批评的低估口径**——半落实，需按 r2 原文重写 |

---

## 逐件详情

### R4-1（R2-8 FAIL → 合并形态终版）——**FAIL**

**现状核对**：_ReadtagsBackend（nav_index.py:750-828）与 r2 审计一致：_run :760-769（旧签名 `args`，无桥无转义）、lookup :790-796（有 `r[0] == name`）、lookup_ci :798-799（无 Python 过滤）、prefix :801-802（无过滤）、substring/by_path/files :804-825（`-l` 全量+各自过滤）；实例 :899 每次新建。R4-1 的 diff 基于 R2-10 新签名 `_run(self, flags, names=(), timeout=30)`——签名合并方向正确。

**三问**：

1. **是否正确解决问题——方案层对，落地文本层不能安全落地。**
   - ✅ **R2-8 FAIL 主因（prefix 桥接零过滤）在 prefix 侧真修了**。R4-1 prefix diff 写出了 `r[0].lower().startswith(ql)` 过滤。修正形态实验（真 readtags + 9 符号 fixture）：`prefix('中文函数')` → 恰 `['中文函数']`（r2 实证的"全库任意符号直进面板"不再发生）；`prefix('get_中文')` → 恰 `['get_中文']`；ASCII 直查维持现状敏感口径（`prefix('getX')` → `['getX','getX2']`）——与 R2-12 裁决（桥接路径必修 lower、ASCII 直查维持观察）逐字一致。
   - ✅ **flags 透传矩阵自洽且 -i 保留有价值**。语义矩阵：lookup（`[]`→`[]`）、lookup_ci（`["-i"]`→`["-i"]`）、prefix（`["-p"]`→`[]`，桥分支自加 `-p 首字`）。实验：`lookup_ci('get_中文')` → `['Get_中文','get_中文']`（`-i -p g` CI 叠加超集 + lower 精确过滤双命中——R2-8 无差别丢 -i 导致的 CI 丧失真恢复）；`lookup('-l')` → 恰 1 行无尖峰（R2-10 转义位在合并形态下正常）。
   - ❌ **`args_of` 未定义符号（硬伤，FAIL 主因）**。桥分支行 `if "-i" in flags or "-p" in [f for f in args_of(flags)]:`——全仓 grep 无 `args_of` 定义。该行是可执行代码非注释。按调用点推演 + 照抄落码实验：prefix 桥路径 flags 过滤后为 `[]` → `"-i" in []` False → 求值右操作数 → **NameError**；lookup 桥路径 flags 本就是 `[]` → 同样 NameError；仅 lookup_ci 因 or 短路幸免。实验实证：照抄 R4-1 diff 后 `prefix('中文函数')` 与 `lookup('中文函数')` 均 `NameError: name 'args_of' is not defined`。传播面：symbols()（:1088-1093，无 try）→ nav_api :357 except → `{"ok":false,"err":"name 'args_of' is not defined"}`；definition()（:1279/:1282）→ nav_api :338 同款——**Ctrl+T 中文前缀与 F12 中文符号两条主路径从现状"静默 0 行"变"必报错"**。r2 修正方向代码里没有这个 if-pass 段：R4-1 声称"r2 已给实现"，实为作者改写时混入的说明性伪代码。
   - ❌ **四调用点过滤齐备性（审计点①）逐条核**：
     - lookup：桥透传 + 现状 `r[0] == name` 精确过滤 ✓ 齐备（前提是能执行到）；
     - **lookup_ci：不齐备**。R4-1 注释宣称"调用方（prefix/lookup_ci）自带 lower/CI 过滤"，但 diff 只写了 prefix 的过滤，lookup_ci 的 lower 精确过滤（R2-8 diff 中的 `low = name.lower()` + `if r and r[0].lower() == low`）**未重申**。链路上它存在于 R2-8 文本、R2-10 重写过调用行（行尾 `if r and ...` 悬空省略号依赖 R2-8 残留）、R4-1 终版却不再包含——三份补丁各改一次同一行，"终版"无法自洽成文。实验实证：仅按 R4-1 应用时 `lookup_ci('中文函数')` → **全库 9 符号全出**（`['-l','Application','Get_中文','apple_pie','getX','getX2','get_中文','中文其他','中文函数']`）——R2-8 FAIL ①的 definition 决策链污染（:1282 lookup_ci 回退面 + :1088 symbols exact 面）原样复活；
     - prefix：齐备 ✓（见上）；
     - substring/by_path/files：names 为空不进桥 → 各自既有过滤 ✓ 齐备。
   - 桥分支残留垃圾：`_ql = _q.lower()` 与 `_parsed = [...]` 两个死变量、"原始行透传"写成 `[l for l in _lines if True]` 恒真过滤——**"声明了过滤没写"（R2-8 FAIL 根因）的残影在桥内再现**（虽然职责切分下桥内确实不需要过滤，但这三段应当删除而非保留为死代码）。
2. **是否引入新问题——是（两条硬伤 + 两 notes）。**
   - args_of NameError（上述，照抄落码中文查询必炸）；
   - lookup_ci 过滤缺口（上述，纯 R4-1 应用=污染复活）；
   - note a：合并形态的引用件未成文——`self._run_raw(...)` / `self._ascii_dump(timeout)` / `_ascii_cache` 被 R4-1 桥分支引用，但其定义段（R2-8 diff 中的）未声明保留形态；`_needs_ascii_bridge` 被 R4-1 内联判定取代后去留未交代（保留即死代码且引用旧签名 `args`）。照"R2-8 其余部分继续有效"解读可跑（实验 B 即按 R2-8 定义 + R4-1 桥分支搭建），但终版文本应一页写全；
   - note b：lookup 桥接 dump 分支的 timeout 沿用 lookup 默认 30s（prefix 桥显式 60s）——110 万行 dump 7s 级 30s 够用，但与 substring/by_path 的 60s 惯例不一致，超时即静默空结果，建议统一 60。
3. **是否遗漏更优方案——一处（有限，不构成 FAIL 主因）。** r2 修正方向建议 prefix 桥接"一律 dump"（CI 覆盖均匀 + 与同请求 substring 共享 `_ascii_cache`，边际成本≈0）；R4-1 保留首字符 `-p` 窄化——`Get_中文` 型大写开头混合名在 prefix 档漏（`-p g` 敏感超集不含大写变体）。现状该场景本就 0 行（argv 损坏），不构成回归，且 substring 档（:1093）兜底可见——但与 r2 建议的背离未附取舍理由。另：丢 `-p` 非必需（r2 实验 `-p -p g` 重复无害）但无害（桥分支自加 `-p 首字`），不算错。

**审计点④（两探针能否验证到位）**：①prefix 精确性（非 ASCII 前缀不得返回全库）——到位 ✓，R4-1 落地后该探针可验证（实验 B 已按修正形态复演通过）；②lookup_ci CI 命中（PROBE_WORK→probe_work）——**验证不到位**：'PROBE_WORK' 是 ASCII，`_needs_ascii_bridge` 判据 `not _q.isascii()` 不命中 → 走常规 `[-]` 转义路径，验证的是 readtags 原生 `-i` + R2-10 转义 + lower 过滤，**对 R4-1 特有的"桥分支 -i 保留"零覆盖**（实验：`lookup_ci('PROBE_WORK')` 在 ASCII 查询下根本不进桥）。r2 原探针是 `_be.lookup_ci('get_中文')` 在库含 `Get_中文` 时应命中——应改回非 ASCII 对（实验 B：修正形态下 `['Get_中文','get_中文']` 双命中即验证到位）。

**修正方向（保持 r2 职责切分，删死代码、补 lookup_ci、成文引用件）**：
```diff
     def _run(self, flags, names=(), timeout=30):
         if not self._exe:
             return []
+        _q = next((n for n in names if n), "")
+        if _q and not _q.isascii():
+            flags = [f for f in flags if f not in ("-p", "-l")]
+            if _q[0].isascii():
+                return self._run_raw(flags + ["-p", _q[0]], timeout)
+            return self._ascii_dump(timeout)
         argv = [self._exe, "-s1", "-e", "-n", "-t", self._tags] + flags \
                + (["-"] + list(names) if names else [])
         ...
```
（桥分支删 `_ql`/`_parsed`/if-pass/恒真 return 四段死代码——桥只做"绕编码+透传"。）同步三件：①重申 lookup_ci 过滤行 `low = name.lower()` + `if r and r[0].lower() == low`；②成文保留声明 `_ascii_cache`/`_ascii_dump`（模块级 os，勿函数内再 import）/`_run_raw` 三构件按 r2 修正方向形态、`_needs_ascii_bridge` 删除；③探针②改为非 ASCII CI 对。

---

### R4-2（R2-9 FAIL → probe_codegraph 按契约终版）——**PASS with notes**

**现状核对**：res_boot.py 顶部 import 块 :27-32（json/os/shutil/struct/subprocess/sys）——**os 已导入**；MANIFEST :43-67（8 kind 全有 `fix` 键）；probe_all :324-354（:340 `st, ver, detail = _PROBES[k]()` try 内、:346-348 `m["fix"]` try 外）；probe_bili :294-298 惯例 `("ok","","")/("missing","","")`；消费端 settings.js :861-867——:863 `it.ver` 仅 ok 态渲染、:866-867 `const detail = it.ok ? '' : esc(it.detail || it.fix || '')` 仅非 ok 态渲染；res_install._ver :521-526（`os.path.join(d, "lib", "package.json")`，**无 ".."**，`.get("version") or ""`）；nav_codegraph._cg_exe :48-51（bundle 场景返回 `<bundle>/node.exe` 全路径）。

**三问**：

1. **是否正确解决问题——是，R2-9 三坑全修实。**
   - ✅ **契约槽位归位**（渲染矩阵实验四格全过）：ok+版本 → "✓ 已就绪 1.6.0"（ver 槽 :863 渲染）；ok+版本空 → "✓ 已就绪"（不崩，见 note b）；missing → detail 槽空串 → :867 `detail || fix` fallback **MANIFEST.fix 渲染**——R2-9"fix 指引死路"真关闭，probe_bili 惯例对齐；unknown 兜底路径（probe_all try 内捕获 → detail=str(e) 渲染）不受影响。
   - ✅ **版本路径 = res_install._ver 同款无 ".."**：`dirname(_cg_exe())/lib/package.json`。三形态复核：①开发态 offline_assets——本机实证 `offline_assets/codegraph/lib/package.json` version=**1.6.0**，ok 三元组 `('ok','1.6.0','codegraph 1.6.0')`；②APPDATA 安装态（res_install 直铺位 `codegraph-win32-x64` 与 npm 嵌套位同构 `<bundle>/lib/package.json`）——r2 磁盘实证存在，路径拼接一致；③npm shim（`which codegraph` → `APPDATA/npm/codegraph.cmd`）→ dirname=`APPDATA/npm` → package.json 不存在 → except → `_v=""` → "已就绪"无版本（可接受回落）。`_cg_exe()` 返回 None 的防御分支（`or ""`）不炸（join 空串→相对路径→FileNotFoundError→except）。
   - ✅ **`_os` NameError 消除**：补 `import os as _os` 后 `_os.path.join` 可解析（虽然方式冗余，见 note a）。
   - ✅ MANIFEST 保持 R2-9 的 fix 键——:348 `m["fix"]`（try 外）不再 KeyError，r1 崩溃坑不复活；probe_all :340 三元解包兼容；hard=False → preflight_gate 无启动面变化（r2 已核，无变化）。
2. **是否引入新问题——无硬伤，四 notes。**
   - note a：**`import os as _os` 的注释失实**——"res_boot.py 现无 os 导入——R2-9 NameError 根因"：res_boot.py:28 **已有 `import os`**。R2-9 的 NameError 根因是 `_os` 别名未定义，不是 os 未导入。照抄可跑（同名模块双别名）但误导后人；正确修法（r2 修正方向即如此）：直接用模块级 `os.path.join`，零新增 import。
   - note b：ok 态 `_v` 空时无 "已安装" 兜底（r2 修正方向 `v or "已安装"`）——npm shim 形态显示"✓ 已就绪"无版本，可接受但不如 r2 建议。
   - note c：`open()` 裸开未 close；`.get("version", "")` 与 _ver 惯例 `.get("version") or ""` 的 null 边界差异（version=null 时 `_v=None` → ver 槽 None → 前端 falsy 不渲染，不崩——实验实证）——风格项。
   - note d：ok 态 detail 槽 `"codegraph " + _v` 永不渲染（:866 `it.ok ? ''` 短路）——死值无害，但说明作者对契约仍有一处理解残留。
3. **是否遗漏更优方案——无**。R4-2 已采纳 r2 修正方向主干（ver 槽放版本、missing 三空、fix 归 MANIFEST、路径无 ".."）；未采纳的仅 `_os` 别名与"已安装"兜底两点（notes 已列）。

---

### R4-3（P-7 裁决回写：_write_json 本体化 + 清理包全段）——**FAIL**

**现状核对**：`_write_json`（nav_index.py:76-82）真实现状——签名 `(p, obj)`、:77 `os.makedirs(os.path.dirname(p), exist_ok=True)`、:79 `tmp = "%s.%d.tmp" % (p, threading.get_ident())`、:80-81 `json.dump(obj, f, ensure_ascii=False)`（无 indent）、:82 `os.replace(tmp, p)`——**无 try/except/finally 结构**。调用方穷举 grep：8 处（nav_index :237/:239 rebind meta、:391 manifest、:490/:1191 gen_files、:543 symbols、:589 build meta + nav_api :232 reindex meta），全部 dict 类型。`import time` :30 ✓、`import threading` :29 ✓、`import os` :25 ✓。

**三问**：

1. **是否正确解决问题——机制层对、落地文本层错（FAIL 主因）。**
   - ✅ **机制设计与 r1/r2 裁决一致**（本体化单点覆盖 8 写者 + 只对 replace 段重试 + 清理包 dump/replace 全段 + raise 传播）。以现状为基线的修正形态实验全矩阵通过：
     | 场景 | 结果 |
     |---|---|
     | B1 正常写 | 成功，tmp 零残留 |
     | B2 dump TypeError | raise ✓ + tmp 清理 ✓（残留 []）+ 目标文件未被误写 ✓ |
     | B3 读者持目标句柄 60ms | 重试第 2/3 次命中，108ms 完成，tmp 零残留 |
     | B4 读者持住超重试窗（~150ms） | PermissionError 可见失败 + tmp 清理 + 旧内容完好 |
     （B2/B4 实证 r2 新发现③的"TypeError 也留 tmp"缺口被清理段真实关闭；B4 顺带实证 3×50ms 对持句柄秒级读者只是概率缓解——meta 读者窗口毫秒级故够用，与 r2 对 R2-13 的判定同口径。）
   - ✅ **8 写者兼容**：全部 dict、现状已能 dump 成功；R4-3 不改 raise 语义（TypeError/OSError 本就传播——reindex work :236 except、definition/symbols 端点 :338/:357 except 均已兜）；本体化消除 r2 指出的"调用点循环版三处口径分裂"。json.dump TypeError 清理路径 ✓、time 导入存在性 ✓（:30）。
   - ❌ **diff 上下文行与现状大面积不符（FAIL 主因）**。补丁的上下文行写的是另一个函数：`def _write_json(path, data):`（现状 `p, obj`）、`tmp = ... % (path, _threading.get_ident())`（现状 `threading.get_ident()`；**`_threading` 在 nav_index.py 无定义**）、`json.dump(data, f, ensure_ascii=False, indent=1)`（现状无 indent）、`try:`/`except Exception:`/`finally: pass`（**现状不存在此结构**）；现状 :77 的 `os.makedirs` 也不在 diff 中。标准 patch 应用必失败；照上下文行重写函数则**首次调用即 `NameError: name '_threading' is not defined`（实验实证）**——8 写者全灭（build/reindex/rebind/symbols/gen_files 全炸），比不修更糟。
2. **是否引入新问题——照抄落码即三条。**
   - `_threading` NameError（致命，上述）；
   - `indent=1` **未要求的格式变更**：全部 8 写者输出从紧凑变缩进（实验：同一对象 8B→13B，实际 meta/symbols 按行数膨胀）；_read_json 兼容但文件体积、_dir_size 类统计与 diff 噪声俱增，非补丁目标；
   - `finally: pass` 冗余（try/except raise 已完备，finally 无资源可清）；`import os as _os` 函数内冗余（模块顶 :25 已有 os——r2 对 R2-8 同款已 note"模块顶 os，勿再 import"，重犯且用别名）。
3. **是否遗漏更优方案——无**。本体化即 r1 裁决最优选点；缺的是把 diff 写在真实现状上。

**修正方向（以现状 :76-82 为基线重写）**：
```diff
 def _write_json(p, obj):
     os.makedirs(os.path.dirname(p), exist_ok=True)
     # tmp 唯一化（并发写同库时固定名交错覆盖）
     tmp = "%s.%d.tmp" % (p, threading.get_ident())
-    with open(tmp, "w", encoding="utf-8") as f:
-        json.dump(obj, f, ensure_ascii=False)
-    os.replace(tmp, p)
+    try:
+        with open(tmp, "w", encoding="utf-8") as f:
+            json.dump(obj, f, ensure_ascii=False)
+        for _i in range(3):                        # P-7/D-2：并发读者窗口重试
+            try:
+                os.replace(tmp, p); break
+            except OSError:
+                if _i == 2: raise
+                time.sleep(0.05)                   # time :30 已导入
+    except Exception:
+        try: os.remove(tmp)                        # 清理包全段（含 dump TypeError）
+        except OSError: pass
+        raise
```
（无 finally；不加 indent；不引 _os 别名——模块级 os/time/threading 全在。此形态即实验通过形态。）

---

### R4-4（新发现纳入三条）——**PASS with notes**

1. **settings.js:788/:1661 两处 ⬇ 归入 P-21**——落实 ✓。本轮实证两处在位（:788 `<button ... id="rsOnlineGo" ...>⬇ 在线安装所选</button>`、:1661 `res.innerHTML = '<div class="dd-sub">⬇ 下载并校验中…...'`），与 r2 新发现①的定位一致；归前端组 r3 执行、更新 P-21 位置列表——职责划清，后端无作用面。
2. **vendor readtags `[-]` 多 NAME 只匹配最后一个 → 留档观察**——落实 ✓。与 r2 新发现②原文一致；"对 R2-10 无影响：转义位后恒单查询名"复核成立（R2-10 四调用点 names 全单元素；R4-1 桥分支 `-p _q[0]` 亦单 NAME）。
3. **R2-8 风险注"缓存作用域低估"表述更正**——**半落实**。r2 新发现④要求的定性是"作用域=**单请求内多查询共享（r1 乘数问题的解）**，跨请求不共享是**防常驻内存的取舍**"。R4-4 写出的是"缓存仅单次调用面内有效——**作用有限**如实记录"："单次调用面内有效"方向对（≈单请求共享），但结论措辞"作用有限"延续了被批评的低估口径——照此落档会误导后人删缓存，从而复活 r1 FAIL ③的"50 候选 × 全量 dump"乘数问题。需按 r2 原文重写。措辞细节："实例随 _open_tags 生命周期"不准确——实例生命周期是"请求处理期"（:899 每次 _open_tags new 实例，引用存活至请求结束）。

---

## 新发现区（本轮审计过程新撞见，单列）

1. **R4-1 桥分支对 `'-中文'` 型查询（首字符 `-` 且含非 ASCII）返回空且 readtags 打 stderr**：桥分支 `-p _q[0]` 只保证 `_q[0]` ASCII、不保证非 `-`。实验：`readtags -s1 -e -n -t tags -p -` → `no action specified: specify one of NAME, -l or -D`（exit=1，stdout 空）→ `_run_raw` 返回 [] → 调用点过滤后空结果。失败态干净（无崩溃无污染，与现状中文 argv 损坏的 0 行同口径），留档即可；若要封死，桥分支加 `_q[0] != "-"` 判据转 dump 分支（一行，可选）。
2. **桥分支"取第一个非空名"与 vendor"多 NAME 匹配最后一个"的潜在分叉**：`_q = next((n for n in names if n), "")` 取第一个，vendor 直查路径 `[-] + names` 匹配最后一个——现调用点全单名无影响；未来若有人批量传名，桥接与直查行为将静默分叉。与 R4-4 ②的留档合并记录："批量传名前必须先复核，且需同时改桥分支取名逻辑"。
3. **`_write_json` 的 `os.makedirs` 在 try 外**（现状 :77，R4-3 修正方向保持）：makedirs 失败（目录不可建）时无 tmp 可清、直接传播——行为正确，但注意 rebind :237/:239 的 meta 写在目录改名**之后**，若 makedirs 因新目录已存在且权限异常而失败属重试覆盖不到的面（低概率，失败态干净——改名已成功、meta 未写，重跑 rebind 可恢复）。留档。
4. **probe_all 缓存把 unknown 态异常文本落盘**（:343，pre-existing，r2 新发现⑤已留档）——本轮确认 R4-2 落地后 `_probe_codegraph` 不再产生 NameError 类输入源，该观察项对本 kind 关闭，其他 kind 维持留档。

---

## 实验留存说明

全部实验在 `%TEMP%/rt_audit_r3` 搭建（UTF-8 码点序 tags fixture：9-11 符号名，含中文/混合名/`-l` 同名注入条目；`python -I` 运行，仅调用只读函数与临时目录写入，仓库零写入），实验后已整体清理。关键实证：

| 实验 | 结果 |
|---|---|
| R4-1 照抄：`prefix('中文函数')` | **NameError: name 'args_of' is not defined** |
| R4-1 照抄：`lookup('中文函数')` | **NameError**（flags=[] → or 短路不成立） |
| R4-1 照抄：`lookup_ci`（无过滤） | 全库 9 符号 `['-l','Application','Get_中文',…]`（污染复活） |
| 修正形态：`prefix('中文函数')` / `prefix('get_中文')` | 恰 `['中文函数']` / 恰 `['get_中文']` |
| 修正形态：`lookup_ci('get_中文')` | `['Get_中文','get_中文']`（**-i 保留 CI 价值实证**） |
| 修正形态：`lookup_ci('PROBE_WORK')` | `[]`（ASCII 不进桥——探针②验证不到位实证） |
| 修正形态：`lookup('-l')` | 恰 1 行（转义位无尖峰） |
| R4-3 照抄 | **NameError: name '_threading' is not defined** |
| R4-3 修正形态：dump TypeError | raise + tmp 清理 + 目标未误写 |
| R4-3 修正形态：读者持句柄 60ms | 重试 108ms 成功、零残留 |
| R4-3 修正形态：读者超重试窗 | PermissionError 可见失败 + tmp 清理 + 旧内容完好 |
| indent=1 对比 | 8B→13B（未要求格式变更） |
| offline_assets/codegraph/lib/package.json | version=1.6.0；ok 三元组 `('ok','1.6.0','codegraph 1.6.0')` |
| 渲染矩阵（settings.js:863/:866-867 模拟） | ok+ver 显示 / ok 空 ver 无兜底不崩 / missing→MANIFEST.fix 渲染 / unknown→detail 渲染 |
| `readtags -p -`（'-中文' 桥边缘） | "no action specified" exit=1 → stdout 空 → 空结果（失败态干净） |
