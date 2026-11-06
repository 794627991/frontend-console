# 后端补丁合理性审计报告 r2（patch-review-r2-backend）

- 审计对象：doc/patch-log.md【第 2 轮修订·后端组】R2-8~R2-13（重写/补强 5 件 + 待裁决 1 件）+ R2-3~R2-7 涉后端项落实核验
- 审计方式：白盒对照源码现状逐字核对（行号漂移全部指认）+ 语法/并发/边界推演 + 只读实证（vendor readtags.exe 行为实验、真 `_parse` 直调、offline_assets 布局核对，均在系统临时目录/只读完成，仓库零写入）
- 源码状态确认：P-1/P-3/P-13 等第 1 轮补丁均未落码（nav_index.py:882 仍单槽缓存、:103 build work 无前置 close、:205 delete 仍 ignore_errors=True）——本轮审计对象为**补丁文本**，与"台账是补丁唯一载体"铁律一致
- 环境注：本机 ACP=936（与 r1/C-1 复现环境一致）；实验后临时目录已清理
- R2-3/R2-4/R2-5/R2-7 为纯前端文件（nav.js/style.css/editor.js/monaco-bridge.js），本轮只核 R2-6（update_server.py 属后端）与 P-7 选点，其余移交 r2-frontend

---

## 结论先行

**0 PASS / 3 PASS with notes / 2 FAIL；另 1 件待裁决项（R2-12）给出裁决，2 件落实核验（1 确认 / 1 缺口）。**

| 项 | 裁决 | 一句话裁决 |
|---|---|---|
| R2-8（P-4 重写·ASCII 桥 v2） | **FAIL** | lookup_ci 过滤成立、definition 决策链已净；但 **prefix 桥接路径零过滤（全量垃圾直进面板，比现状"空结果"更糟）**——diff 声明的过滤没写出来（ql 未使用、注释落在 return 后不可达）；且与 R2-10 的合并形态缺失、-i 一并丢弃丧失 CI 叠加 |
| R2-9（P-10 重写·res_boot probe） | **FAIL** | r1 两个崩溃坑（KeyError/ValueError）真消除 ✓；但 **三元组槽位错位**（missing 分支 fix 文案塞进 ver 槽、detail="codegraph" 反而遮蔽 fix；ok 分支版本串放 detail——settings.js:867 `it.ok ? '' : detail||fix` 实证 ok 态 detail **根本不渲染**，版本功能两头全灭）+ 版本读取路径差一级（`..` 多跳，三种 bundle 形态全 404）+ `_os` 未定义（NameError 被吞） |
| R2-10（P-18 重写·flags/names 分离） | PASS with notes | 机制正确且 r1 实证复验通过（`[-]` 转义位/4 调用点/`-l` flag 位全核对）；notes：与 R2-8 的合并形态必须成文、substring/by_path 两行 diff 是 no-op 展示行、vendor 二进制多 NAME 只匹配最后一个（留档） |
| R2-11（rebind 前置 _close_tagdb） | PASS with notes | :236 位置准确、机理成立；notes：宜放进"异库分支内、os.replace 前一行"；并发重开窗与 readtags 子进程句柄类不在覆盖面；失败态干净（改名原子先行，meta 未写） |
| R2-13（build:450 tags replace 重试） | PASS with notes | 位置 :450 准确、不加 _close_tagdb 正确（tags 无常驻句柄）；notes："窗口毫秒级"表述不准（readtags -l dump 可持句柄秒级~60s），3×150ms 是概率缓解非封闭；失败=可见任务失败，状态一致 |
| R2-3~R2-7 落实核验（涉后端） | 1 ✓ / 1 缺口 | R2-6/P-21 后端五处行号逐字精确 ✓；**P-7 选点裁决未回写台账**（r1 已裁"改 _write_json 本体"，P-7 原文仍两选一待裁决）→ 列第 3 轮修订 |
| R2-12（prefix 大小写待裁决） | **裁决：维持观察（不升级全量桥）+ 桥接路径 lower 过滤为 R2-8 必修件** | 详见文末 |

---

## 逐件详情

### R2-8（P-4 重写：readtags 中文 ASCII 桥修正版）——**FAIL**

**现状核对**：`_ReadtagsBackend`（nav_index.py:750-828）与 R2-8 假设的现状一致：_run :760-769（无桥、无转义）、lookup :790-796（有 `r[0] == name` 过滤）、lookup_ci :798-799（**无** Python 过滤，r1 FAIL ①成立）、prefix :801-802（无过滤）、substring/by_path/files :804-825（`-l` 全量 + 各自过滤）。实例创建点 _open_tags:899——**每次 _open_tags 都 new 新实例**（R2-8 风险注"实例随调用短命"属实）。

**三问**：

1. **是否正确解决问题——主害已修，次害新增。**
   - ✅ lookup_ci 桥接路径补 `r[0].lower() == low` 过滤：直调实证（真 `_parse` + 全量 dump 模拟桥后链路），`lookup_ci('中文函数')` 过滤后恰返回 `['中文函数']`；definition 决策链（:1279-1283 lookup→lookup_ci 回退）拿到的候选回到真名族，auto 直跳（:1392-1397）不再被全库符号污染——r1 FAIL ①的**definition 侧**修复成立。
   - ✅ `-p` 首字符超集 + lookup 精确过滤链实证通过：`-p g` 超集 → `r[0]=='get_中文'` 过滤 → 恰 1 行。
   - ❌ **prefix 桥接路径零过滤（新污染面，回归）**。现状 prefix('中文函数')：readtags 失明 → 0 行 → 面板干净。R2-8 桥后：`_needs_ascii_bridge` 命中 → dump 分支返回**全量行** → prefix 的 return（:802 原样保留）`[:limit]` 直取**全库任意符号**。直调实证：`prefix('中文函数') 桥接无过滤 → ['-l', 'Application', 'Get_中文', 'apple_pie', 'getX', ...]`——中文查询的 Ctrl+T 前缀档从"空"变"垃圾"。ASCII 首字符混合名同型：`prefix('get_中文') 桥接 → -p g 超集全量直出`（应只出 `get_中文`）。**关键：R2-8 的 diff 并没有把过滤写出来**——`+ ql = q.lower()` 是未使用变量，其下三行注释位于 `return` 之后（不可达死代码），return 行未动。注释宣称"bridge 后过滤统一 lower（本行起效于桥接路径）"，但 diff 无任何一行过滤代码。r1 FAIL ①说的是"definition/symbols 决策链"两个面：R2-8 修了 lookup_ci（definition 侧 + symbols 的 `_exact_names` :1088），**symbols 的 prefix 面（:1091）原样暴露在新污染下**。
   - ✅ _ascii_dump mtime 实例缓存：设计正确（键=(mtime) 与 _tags_cache:973 同源；mtime 变化即失效，与 build replace 后自动对齐）。作用域评估见下"内存面"。
2. **是否引入新问题——三处。**
   - prefix 污染（上述，正确性回归，FAIL 主因）。
   - **与 R2-10 的合并形态缺失**：R2-8 的 diff 基于旧 `_run(self, args, timeout=30)` 签名与旧 argv 构造（无 `[-]` 转义）；R2-10 把同一函数改成 `_run(self, flags, names=(), timeout=30)`。两补丁改写同一函数头，机械叠加直接冲突（R2-8 桥分支引用的 `args` 在 R2-10 签名下不存在）。R2-10 尾注"ASCII 桥（R2-8）内部同样按新签名"是意向不是代码——**合并形态必须成文**（见下方修正方向）。
   - **-i 被无差别丢弃**：`flags` 过滤把 `-i` 与 `-p/-l` 一并扔掉。实验实证 `-i -p g` 返回 `Get_中文/getX/getX2/get_中文`（**CI 叠加有效**），`-p g` 只返回 `getX/getX2/get_中文`（丢 `Get_中文`）。后果：lookup_ci 桥接的 ASCII 首字符分支（如查 `get_中文`、库里有 `Get_中文`）超集不含大小写变体 → CI 过滤后 0 行。这不是对现状的回归（现状该场景同样 0 行——argv 中文段损坏），但它是 r1 修正方向 a)"flags 只保留后端自有 modifier"的**背离**：-i 正是后端自有 modifier，保留即把 CI 语义带进桥。`-p` 重复无害已实证（`-p -p g` 与 `-p g` 输出一致），丢弃 -p 亦无必要。
   - 小项：`_ascii_dump` 内 `import os as _os`——模块顶 :25 已有 os，冗余（与 r1 对 P-23 的 note 同型）；dump 返回 []（子进程瞬时失败）会以 (mtime, []) 钉死到实例生命周期末——请求级寿命，影响小，注释宜说明。
3. **是否遗漏更优方案——是，合并形态本身更简且更对。** R2-10 落地后 flags 全部是后端自有常量（`-i`/`-p`/`-l`），**R2-8 的整套 flags 丢弃机制冗余**：桥分支直接 `flags + ["-p", target[0]]` 透传即可（-i 保留、-p 重复无害、-l 与 names 不同时出现无需防）。prefix 桥接建议**一律走 dump + lower 前缀过滤**（跳过首字符窄化）：首字符 ASCII/非 ASCII 两种形态的 CI 覆盖才均匀（首字符窄化版对 `Get_中文` 型大写开头混合名仍漏），且 dump 与同请求的 substring（现状本就全量）共享 `_ascii_cache`，边际成本≈0。

**内存面专项（审计点②）**：`_ascii_cache` 为实例级——实例随 `_open_tags` 每请求新建，缓存随请求结束释放：①单请求内 50 候选 × push→lookup 的 r1 乘数问题被真实解决（50 次 dump → 1 次）；②跨请求无共享——这是**正确取舍**而非缺陷：模块级 (ld, mtime) 缓存会让 readtags 档常驻 200MB 级文本（110 万行 × ~180B，Python str 头开销后 250~350MB），恰好复活 readtags 档要避免的 memory 档内存面；③并发请求各自 dump——瞬时内存 N×200MB，Ctrl+T 串行键击下 N=1，可接受；④净性能对比现状：中文查询现状 substring 本就每次全量 dump，桥后 prefix+substring 共享一次 dump，**不劣于现状、略有改善**。风险注"缓存作用有限但无害"的表述应改为"作用域=单请求内多查询共享（r1 乘数问题的解），跨请求不共享是防常驻内存的取舍"。

**修正方向（合并形态，R2-8+R2-10 一次成文）**：
```python
class _ReadtagsBackend(object):
    _ascii_cache = None   # (tags_mtime, lines)——实例级=请求级；不升级模块级（防 readtags 档常驻内存）

    def _ascii_dump(self, timeout=60):
        try:
            _mt = os.path.getmtime(self._tags)          # 模块顶 os，勿再 import
        except OSError:
            return []
        if self._ascii_cache and self._ascii_cache[0] == _mt:
            return self._ascii_cache[1]
        lines = self._run_raw(["-l"], timeout)
        self._ascii_cache = (_mt, lines)
        return lines

    @staticmethod
    def _needs_ascii_bridge(names):                     # 只看 names——flags 全是后端自有
        return any(not n.isascii() for n in names)

    def _run(self, flags, names=(), timeout=30):        # R2-10 签名
        if not self._exe:
            return []
        if self._needs_ascii_bridge(names):
            target = names[0] if names else ""
            if target and target[0].isascii():
                # flags 透传：lookup_ci 的 -i 保留（CI 叠加实证有效）；-p 重复无害（实证）
                return self._run_raw(flags + ["-p", target[0]], timeout)
            return self._ascii_dump(timeout)
        argv = [self._exe, "-s1", "-e", "-n", "-t", self._tags] + flags \
               + (["-"] + list(names) if names else [])
        ...

    def prefix(self, q, limit):
        ql = q.lower()
        out = []
        for l in (self._run(["-p"], names=(q,)) if q.isascii()
                  else self._ascii_dump(timeout=60)):   # 桥接路径一律 dump：CI 覆盖均匀 + 与 substring 共享缓存
            r = self._parse(l)
            if r and r[0].lower().startswith(ql):       # ← R2-8 声明了但没写出来的过滤
                out.append(r)
                if len(out) >= limit:
                    break
        return out
```
（ASCII 直查路径叠 lower 过滤无害：敏感命中是 CI 命中子集，只增比较不增不减结果。）

**验证补充**：r1 修正方向 d) 的"lookup_ci 精确性探针"保留；新增"prefix 探针"：`_be.prefix('中文函数', 50)` 应只含 `中文*` 名族（实证现状桥后返回全库任意符号）；`_be.lookup_ci('get_中文')` 在库含 `Get_中文` 时应命中（验证 -i 保留）。

---

### R2-9（P-10 重写：res_boot.MANIFEST "fix" 键 + 具名 _probe_codegraph 三元组）——**FAIL**

**现状核对**：MANIFEST :43-67（8 kind 无 codegraph）；probe_all :333-350——:340 `st, ver, detail = _PROBES[k]()`（try 内），:346-348 `items.append({..., "fix": m["fix"]})`（**try 外**）——r1 两个坑的机理核实无误。probe_bili :294-298 三元组惯例 `("ok","","")/("missing","","")`。消费端：res_api.py:43-52（probe_all 无外层 try，probe_all 抛错→/api/resources/status 500）；settings.js:859-867 渲染——:863 `it.ver` 仅在 **ok** 态渲染、:867 `it.detail || it.fix` 仅在**非 ok** 态渲染（`const detail = it.ok ? '' : ...`）。

**三问**：

1. **是否正确解决问题——两个崩溃坑真消除 ✓**。①`"fix"` 键入 MANIFEST → :348 `m["fix"]` KeyError 消除（且该行在 try 外会崩整个 /api/res/status 的面随之消除）；②具名函数返回三元组 → :340 解包 ValueError 消除；③注册方式 `_PROBES["codegraph"] = _probe_codegraph` 可用（不必并入 :301 字面量）；④单装链确认就绪：res_install.ORDER:36 已含 codegraph、_INSTALLERS:832、名称映射 :841 与提议 name 逐字一致；settings.js inPkg(:849) 对 codegraph 判定通过（offline_assets/MANIFEST.json 实证含 codegraph）；hard=False → preflight_gate(:426) 只拦 _HARD(:374 webview2/dotnet)，**无启动面变化** ✓。
2. **是否引入新问题——三处（前两处直接打在补丁的目标场景上）。**
   - **三元组槽位错位，missing 态显示错乱且遮蔽 fix 文案**。补丁 missing 分支 `return ("missing", "未安装（离线资源包自带，无需 npm）", "codegraph")`——按 (state, **ver**, **detail**) 契约：fix 文案进了 ver 槽、"codegraph" 进了 detail 槽。前端实证后果：非 ok 态渲染 `it.detail || it.fix` → detail="codegraph"（真值）胜出 → **MANIFEST 的 fix 指引（"安装离线资源包（或设置→外部依赖安装单装）"）永不显示**。补丁要治的病就是"错误文案成死路"，修订版在目标机器（未装 codegraph 的工作机）上把指引再次弄丢。
   - **ok 态版本两头全灭**。ok 分支 `("ok", "", "codegraph " + (_v or "已安装"))`：ver=""（:863 不渲染）+ detail 在 ok 态被 :867 的 `it.ok ? ''` 短路（**不渲染**）→ 版本串无论读到什么都不可见。惯例（probe_node:229 `("ok", _run_ver(...), "")`）是版本进 ver 槽。
   - **版本读取路径差一级 + `_os` 未定义**。路径 `dirname(_cg_exe()) + ".." + "lib" + "package.json"`：_cg_exe 返回 bundle 根的 node.exe 全路径（nav_codegraph.py:48-51），而 package.json 在 **bundle 根内** `<bundle>/lib/package.json`（res_install._ver :521-526 同款、无 `..`）。磁盘实证三种形态全 404：本机 offline_assets 形态 `offline_assets/codegraph/lib/package.json` 存在（version=1.6.0）而 `offline_assets/lib/package.json` 不存在；APPDATA 安装形态（实测 `%APPDATA%/npm/node_modules/@colbymchenry/codegraph/node_modules/@colbymchenry/codegraph-win32-x64/lib/package.json` 存在）其 `..\lib` 亦不存在；npm shim 形态两种拼法都不存在（可接受，回落"已安装"）。加上 `_os` 在 res_boot.py 全文件无定义（grep 实证）→ `_os.path.join` NameError——被 `except Exception` 吞掉 → `_v` 恒 ""。三因叠加：**版本显示功能在所有形态下 dead-on-arrival**（不崩，但永远显示不出）。
   - 小项：命名 `_probe_codegraph` 与同文件 probe_* 家族（probe_webview2…probe_bili）不一致，建议 `probe_codegraph`；`open()` 未 close（CPython 引用计数兜底，风格项）。
3. **是否遗漏更优方案——是**：res_install._ver 已是版本读取的既定惯例（同库同路径同解析），probe 应照抄而非自创 `..` 拼法；missing 态文案应交给 MANIFEST fix（probe_bili 惯例：missing → `("missing","","")`），probe 不必自带一份与 fix 键语义重复的文案。

**修正方向**：
```python
def probe_codegraph():
    """codegraph 引擎探测：bundle（资源包/npm 位）/offline_assets/which 任一可用即 ok"""
    from src import nav_codegraph as _ncg
    if not _ncg.available():
        return "missing", "", ""          # fix 文案由 MANIFEST.fix 出（probe_bili 惯例）
    v = ""
    exe = _ncg._cg_exe() or ""
    if exe:
        try:
            import json as _j
            with open(os.path.join(os.path.dirname(exe), "lib", "package.json"),
                      encoding="utf-8") as f:      # res_install._ver 同款——无 ".."
                v = _j.load(f).get("version") or ""
        except Exception:
            v = ""
    return "ok", v or "已安装", ""        # 版本进 ver 槽（settings.js:863 ok 态渲染）
```
**验证补充**：未装机器 /api/res/status 200 且 codegraph 行"✗缺失 + fix 指引可见"；已装（offline_assets 形态）显示"✓已就绪 1.6.0"。

---

### R2-10（P-18 重写：flags/names 分离上移调用点）——**PASS with notes**

**现状核对**：4 个调用点与 diff `-` 行逐字吻合——lookup :792 `self._run([name])`、lookup_ci :799 `self._run(["-i", name])`、prefix :802 `self._run(["-p", q])`、substring :807 / by_path :818 `self._run(["-l"], timeout=60)`；files :825 同款 `-l`（diff 未列，见 notes）。

**三问**：
1. **正确解决问题——是。** getopt 语义复核（vendor --help 原文）：`[-] NAME...`——"-" indicates arguments after this as NAME(s) even if they start with "-"；`-i`/`-p` 为 NAME action 的无参 modifier。行为实验（本机重建 fixture）复验 r1 全部结论：`-p - -l` → 恰 `['-l']`；`-i - -l` → `['-l']`；`-i -p - -l` → `['-l']`（尖峰注入面全封）；`-p - getX` 型 prefix 正常（本轮以 `- -l` 单 NAME 形式复验：恰返回 '-l' 行）。转义位只吃用户可控串、flags 永在 `-` 之前——P-18 两形态的反例（形态一毁 prefix / 形态二 lookup("-l") 尖峰保留）均结构性消除。
2. **新问题——无硬伤，三 notes**：
   a) **`-l` flag 位保持正确**：substring/by_path/files 的 `-l` 是 ACTION 非 name，留 flags 位（names 空 → 不加 `-`）与现状行为一致；
   b) **files()（:825）未被 diff 列出但无需改**——新签名 `names=()` 默认值使旧调用形态 `self._run(["-l"], timeout=60)` 继续成立；全仓 `_run(` 调用点穷举（:792/:799/:802/:807/:818/:825）无第六处以 name 打头传参的残留；
   c) **与 R2-8 的合并形态缺失**（同 R2-8 FAIL ②）：R2-10 尾注一句"桥按新签名"不够，两 diff 改同一函数头，必须给出合并成文（见 R2-8 修正方向）。
   另两个编辑面 note：substring/by_path 的 diff 行 `-`/`+` 完全相同（no-op 展示行，非真改动，应用时跳过）；空 names 边界（`names=("",)` 理论可达 `["-",""]` → readtags 查空名 → 0 行）不可达（nav_api:333/347 对 file/symbol/q strip 后 400、symbols :1084 空查询早退），无需防御。
3. **更优方案**：调用点分离即 r1 修正形态本身，无更优替代。
**新实证留档**：vendor 二进制 `[-]` 后**多 NAME 只返回最后一个 NAME 的匹配**（`- -l getX` → 仅 getX；`- getX -l` → 仅 '-l'）——现调用点全单 NAME 无影响，留档防止未来批量传名踩坑。
**验证**：patch-log 所列三条（`-l` 查询空结果无尖峰 / `getX` prefix 正常 / 中文桥接回归）对合并形态有效。

---

### R2-11（rebind 前置 _close_tagdb，r1 新发现①落实）——**PASS with notes**

**现状核对**：nav_index.py:236 `os.replace(ld, new_ld)`（目录整体改名）在 :240 `_invalidate_cache()`（内含 _close_tagdb）**之前**——与 R2-11 描述的行号逐字吻合，无漂移。机理成立：_TagDB 持 tags.db 连接（含 mmap 句柄）在 ld 目录内，Windows 带打开句柄改目录名必败；库被查询过则连接常驻（:882 单槽 cache / :939 orphans，P-1 落地后多槽常驻同然）。

**三问**：
1. **正确解决问题——是**。改名前 _close_tagdb() 释放本进程全部 sqlite 句柄，消除"查询过的库 rebind 必败"主面；与 P-13（delete 前关连接）构成 D-4 同族补全，措辞"同族"准确。
2. **新问题——无硬伤，三 notes**：
   a) **放置精度**：diff 注释"（rebind 目录改名前）"有歧义（函数顶 vs 分支内）。改名只发生在异库分支（:234 `if os.path.abspath(new_ld) != os.path.abspath(ld):`），同根分支仅 _write_json meta（meta.json 无常驻句柄，:239 无撞面）——**应放进该 if 分支内、:236 之前一行**；放函数顶则校验失败的 rebind 也白关全部连接（无正确性害，多槽后代价=N 库重连）。
   b) **两个未覆盖残面（低概率，失败态干净）**：①close 与 :236 replace 之间并发查询可重开连接（与 P-3/P-13 同型窄窗，无重试）；②**readtags 子进程句柄类不在 _close_tagdb 覆盖面**——readtags 档库正被 `-l` dump（可长达 60s）时子进程持 tags 句柄，改名仍败。两者失败态均干净：os.replace 是改名第一步、meta 未写，异常抛出后旧绑定完整（nav_rebind nav_api.py:181 无 try → Flask 500——现状既有行为，R2-11 未使其变差；顺手补 try/except 转 ok:false 属可选增强）。
   c) _close_tagdb 全关所有库连接（非只关该库）——与 P-13 现阶段形态一致、可接受；P-1 落地后如做细粒度 pop(ld)，rebind/delete 应同步。
3. **更优方案**：无（结构上必须先关句柄）。
**验证**：sqlite 档查询过的库 rebind 换盘成功 ✓（patch-log 已列）；建议加一条"readtags 档大库 `-l` 查询进行中 rebind → 可见失败、重试成功"的已知边界记录。

---

### R2-13（build:450 tags.tmp→tags replace 重试，r1 新发现③落实）——**PASS with notes**

**现状核对**：nav_index.py:450 `os.replace(tags_tmp, tags)` 位置逐字吻合（阶段 2 末、取消检查 :444-449 之后、tags 计数 :452 之前）。重试循环语法可行（`time`:30 已导入；OSError 覆盖 WinError 5/32）。

**三问**：
1. **正确解决问题——方向正确**。撞读者场景识别准确：并发读者=①readtags 子进程（readtags 档查询持 tags 句柄，0.2s 精查~60s `-l` dump）②_load_tags（memory 档 cache miss 全量读，小库 <200k 符号 → tags ~20MB 级、亚秒）。**build 与 reindex 本就互斥**（nav_api.py:87/:203 共用 _state["running"]）——_build_tag_db 读者类（:630 读 tags）与 build 并发不可能，diff 不需要也不应加 _close_tagdb（tags 本体无常驻进程内句柄，_TagDB 只持 tags.db）——R2-13 与 P-3 的差异点把握正确。
2. **新问题——表述与充分性两 notes**：
   a) **"窗口毫秒级"表述不准**（patch-log R2-13 括注）：readtags 档 `-l` dump（substring/by_path/files 每次触发）持 tags 句柄可到秒级（110 万行/200MB 文本），timeout 上限 60s——读者窗口与读耗时同阶，不是毫秒级。推论：3×50ms（总退避 150ms）只覆盖"短重叠"（open 瞬间/精查尾段），对持续 dump 中的读者**概率缓解而非封闭**——3 次全败 raise → build 任务可见失败（nav_api work :112 捕获 → ok:false），无静默降级、状态一致（tags_tmp 残留被下次 build 的 ctags -f 覆盖），可接受；但台账应如实写"重试降低概率，持续读者下 build 可能可见失败、重跑即可"。
   b) 与 P-3 同款复用正确，但注意 P-3 的重试体内有 _close_tagdb 而 R2-13 **不应有**（无 db 句柄可关）——R2-13 的 diff 已正确省略 ✓。
3. **更优方案**：备选=把退避拉长为 50/200/500ms 梯度（总 750ms，覆盖亚秒级 _load_tags 读）——成本一次 sleep、无副作用，修订时可顺手；不强求。
**验证**："并发 references 下重建索引零失败"应改为达标口径"零静默失败；持续 readtags 查询下允许可见失败+手动重跑"。

---

### R2-3~R2-7 落实核验（涉后端项）

- **R2-6（P-21 emoji 五处，update_server.py 属后端）——落实确认 ✓**：五处行号逐字精确无漂移——:807/:828/:850（keycap 1️⃣2️⃣3️⃣，`mn-step-t` 行）、:1006/:1025（⬇ 下载按钮）；settings.js:1682 ⚪ 在位。R2-6 的"P-21 保持（五处替换不变）"与源码现状相容；audit-b:187 豁免表勘误仍挂前端组（本轮不核）。见新发现①：settings.js 另有两处 ⬇ 不在 P-21 清单。
- **P-7 选点（D-2 meta.json replace 重试）——缺口 ✗**：r1 已裁决"**改 `_write_json` 本体**（单点覆盖全部写者 + tmp 清理天然归属；只对 os.replace 段重试）"，但 patch-log 的 P-7 正文**未回写**（仍是"调用处循环 / 或改本体——审计员裁决选点"两可形态）。核实 r1 裁决依据成立：`_write_json`（nav_index.py:76-82）写者全仓穷举 8 处——nav_index :237/:239（rebind meta）、:391（manifest）、:490/:1191（gen_files）、:543（symbols.json）、:589（build meta）、nav_api :232（reindex meta）——调用处循环版会让 build/reindex/rebind 三处口径分裂；:79 tmp 由本体创建、:80-82 **无清理**（json.dump TypeError 与 os.replace OSError 两条路径都留 tmp）。**第 3 轮修订要求**：P-7 改写为本体形态——`def _write_json(p, obj, _retries=3)`：try 包 dump+replace，except OSError 对 replace 段 3×50ms 重试（open/write 失败不重试），finally/except best-effort `os.remove(tmp)`。
- R2-3（style.css z-index）/R2-4（editor.js isNote+md）/R2-5（editor.js 护栏）/R2-7（monaco-bridge 映射）：纯前端文件，无后端作用面，移交 r2-frontend（R2-3 中 bkSel 复位引用的 `m.backend` 与后端 auto 判档 :552-553 口径一致，无需后端配合改动）。

---

## 新发现区（本轮审计过程新撞见，单列）

1. **settings.js 另有两处 ⬇ 不在 P-21 清单**：:788（`⬇ 在线安装所选` 按钮）、:1661（`⬇ 下载并校验中…` 提示行）——按"要么 SVG 要么不要"铁律属同族漏网（P-21 只收了 update_server.py 五处 + settings.js:1682 ⚪）。归前端组 r2 复核补清单。
2. **vendor readtags `[-]` 多 NAME 行为**：`- NAME1 NAME2` 实证只返回**最后一个** NAME 的匹配（`- -l getX` → 仅 getX；`- getX -l` → 仅 '-l'）——与 --help "NAME(s)" 复数表述不符。现调用点全单 NAME 无影响；任何人未来批量传名前必须先复核此行为。
3. **`_write_json` 非 replace 路径也留 tmp**：json.dump 抛 TypeError（对象不可序列化）时 tmp 同样残留——P-7 本体化的 tmp 清理应用 try/finally 包住 dump+replace 全段，而非只包 replace（比 r1 建议面略宽，成本为零）。
4. **R2-8 风险注的缓存作用域表述需更正**：原文"readtags 档实例不进 _tagdb_cache……缓存作用有限但无害"低估了其真实作用——缓存的确定价值是**单请求内多查询共享**（r1 FAIL ③的 50 候选乘数问题正是靠它解决）；跨请求不共享则是防 200MB 级常驻的正确取舍。表述不改会误导后人对缓存价值做错误增删。
5. **probe_all 缓存把异常文本一并落盘**（:343 cached[k]={"detail": str(e)[:80]}）——probe 一次异常文本在 60s TTL 内被缓存并在 state 文件持久化，属 pre-existing 观察项（R2-9 落地后 `_probe_codegraph` 的 NameError 类错误若存在就会被这样缓存——修订版已消除该输入源）。不改行为，留档。

---

## R2-12 裁决（readtags 档 prefix 大小写：维持观察 vs 升级全量桥）

**裁决：维持观察——ASCII 纯查询不升级全量桥；但"桥接路径的 lower 前缀过滤"不是可选项，它是 R2-8 的必修缺陷件（即 FAIL 修正方向中的 prefix 改写）。**

理由：

1. **混合名 CI 需求在 readtags 档已有真实兜底**：symbols() 的三档里 substring 本就是 `-l` 全量 + CI 过滤（:804-813），`appl` 查不到 `Application` 作 prefix 时会在 substring 档命中并展示（排序靠后但可见）——升级全量桥的增量收益仅是"把 substring 档已有的结果提到 prefix 档排序"，边际价值低。
2. **全量桥的代价落在最常用快路径上**：readtags 档选型场景=大库（auto 判档 ≥20 万落 sqlite，readtags 是手动选档或 db 缺失回退）。ASCII 短查询（如 `a`/`get`）现状 `-p` 二分毫秒级；全量桥后首次查询 7s 级（1.1M 行 dump）——为排序微收益把最快路径打成最慢档，不值。且 scope=file 与 substring 档的慢已有 UI 提示，prefix 并无慢档预期，属新增回归面。
3. **折中增强（可选，不强制）**：ASCII 查询补一次首字符大小写反转的 `-p` 双查合并（r1 建议 b）——2×二分成本，覆盖首字符大小写差异；不覆盖中段大小写（`APPlication` 型），价值有限，列为可选优化不作为门槛。
4. **非 ASCII 查询（含 ASCII 首字符混合名）走桥**：该路径 prefix 必须过 lower 过滤（R2-8 缺失件）；桥接形态建议 prefix 一律 dump+过滤（CI 覆盖均匀、与 substring 共享 `_ascii_cache`，边际成本≈0，见 R2-8 修正方向）。此时 R2-12 的"升级方案"实质上**只在桥接路径内被采纳**，ASCII 直查维持现状——即裁决的完整表述。

---

## 实验留存说明

全部实验在 `%TEMP%/rt_audit_r2` 搭建（UTF-8 排序 tags fixture：11 符号名，含中文/混合名/`-l` 同名注入条目），实验后已整体清理；`python -I` 直调仅调用只读函数（_parse/_run），仓库内零写入（本报告除外）。关键实证：

| 实验 | 结果 |
|---|---|
| `readtags ... 中文函数`（ACP=936） | 0 行（C-1 失明根因复验） |
| `readtags ... -i -l` | 全量 11 行（R2-8 桥前提复验） |
| `readtags ... -i -p g` | Get_中文/getX/getX2/get_中文（**-i 可叠加，CI 超集**） |
| `readtags ... -p g` | getX/getX2/get_中文（丢 Get_中文——R2-8 丢 -i 的代价实证） |
| `readtags ... -p -p g` | 同 `-p g`（重复 modifier 无害——合并形态 flags 透传可行） |
| `readtags ... -p - -l` / `-i - -l` / `-i -p - -l` | 均 `['-l']`（R2-10 转义复验） |
| `readtags ... - -l getX` / `- getX -l` | 各只返回最后一个 NAME（新发现②） |
| 直调 `_parse`+dump 模拟：lookup_ci('中文函数')+过滤 | 恰 `['中文函数']`（R2-8 ①修复成立） |
| 直调模拟：prefix('中文函数') 桥接无过滤 | 全库任意符号 `['-l','Application',…]`（**R2-8 污染实证**） |
| 直调模拟：prefix('get_中文') 桥接无过滤 / +lower 过滤 | g* 全量 / 恰 `['get_中文']`（修正方向有效） |
| offline_assets/codegraph/lib/package.json | 存在，version=1.6.0（R2-9 路径差一级实证） |
| APPDATA 嵌套 bundle `<bundle>/lib/package.json` vs `..\lib` | 存在 / 不存在（安装形态同证） |
| res_boot.py `_os` 符号 | 全文件无定义（grep 实证——NameError 必现，被 except 吞） |
| settings.js :863/:867 渲染条件 | ver 仅 ok 态渲染；detail 仅非 ok 态渲染（`it.ok ? '' : detail||fix`）——R2-9 两分支显示全灭实证 |
