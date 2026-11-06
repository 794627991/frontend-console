# 对抗式代码审计报告 A · 后端组（白盒）

- 对象：`git diff 8251c58..HEAD`（33 提交，a372→a392）的全部后端 Python 改动，重点六文件：nav_index.py / nav_api.py / vcs.py / res_install.py / build.py / claude_default.py，另覆盖 server.py / nav_codegraph.py / update_server.py / harness/* / deps_bootstrap.py / res_boot.py（未改但被本范围改动牵连）。
- 基准台账：`.zcode/tmp/audit_round35.md`（S35-1~6、S36-1 已闭环；遗留观察项 10 条已逐项避让，本报告全部为**新发现**，无已知项改名重报）。
- 纪律遵守：全程只读（git/工作区/配置零触碰）；只读直调仅 `_MemBackend.prefix`（内存构造对象，未触盘）、`readtags --help`、`where npm`、`offline_assets/codegraph/node.exe --liftoff-only` 冒烟（无文件写入）；真 `~/.claude.json`、用户索引库、真电源计划未读写。

---

## 结论先行

**实锤 12 件（P2×2 + P3×4 + P4×6），存疑 9 条。** 主题一句话：**a390 三档后端的配套债没有清完——memory 档前缀匹配回归、build/reindex 的 db 文件操作与连接生命周期仍有两处竞态缺口；a386 codegraph 内置只铺了安装器没接面板；vcs 网络盘过滤把真实丢失文件一并隐藏。**

| # | 分级 | 主题 | 位置 |
|---|---|---|---|
| S37-1 | **P2** | memory 档 `prefix` 大小写敏感回归（q 传入前已被 lower，混合名跌出前缀族）——R35-1 修复只补了 sqlite 档与 exact 族 | nav_index.py:845-848 ↔ :1091 |
| S37-2 | **P2** | build 阶段 4 sqlite 分支无前置 `_close_tagdb`：`os.replace` 撞本进程在用连接 → 整库重建"成功"却**静默降级 readtags** + tags.db.tmp 残留 | nav_index.py:555-567/671；nav_api.py:103-105 |
| S37-3 | **P3** | reindex/build 的 db 操作窗口内并发查询线程重开旧连接（TOCTOU）——a392 前置关连接只封了"起始时刻"，没封窗口期 | nav_api.py:214→228；nav_index.py:905-936 |
| S37-4 | **P3** | 网络盘过滤把**所有** `!`（missing）无条件隐藏并计入 symlink_hidden——真实删除的文件在 SVN 面板消失；`~` 分支为死代码 | vcs.py:396-399 |
| S37-5 | **P3** | nav_keys POST 只收 5 键、整字典覆盖保存——设置页六键中的 **fsym 改键永不落盘**，刷新即静默回默认 | server.py:1476/1505-1509 ↔ settings.js:151/258 |
| S37-6 | **P3** | codegraph 未注册进 res_boot.MANIFEST——外部依赖面板无此项不可装，而错误文案正是"设置→外部依赖安装"（死路） | res_boot.py:43-66 × res_install.py:35 |
| S37-7 | **P4** | readtags 后端把用户查询裸传 argv——`-` 开头查询被当 ACTION/OPTIONS（q=`-l` 触发全库列举拉内存） | nav_index.py:763/792/802 |
| S37-8 | **P4** | `_svn_symlink_paths` sqlite URI 未做路径编码——目录名含 `%`/`#` 时连接失败 → 符号链接过滤静默失效 | vcs.py:184 |
| S37-9 | **P4** | reindex 只改 backend 两键不更新 meta.sizes.db——status 尺寸双方向失真 | nav_api.py:229-233 |
| S37-10 | **P4** | `_register_codegraph_mcp` docstring 与实现矛盾（"幂等只补缺不覆盖" vs R34-2 自愈覆盖；"npm 全局可执行"前提 vs bundle 直启） | claude_default.py:353-358 ↔ :379-387 |
| S37-11 | **P4** | update_server emoji 清零残留：⬇ 按钮文案 ×2 + keycap 1️⃣2️⃣3️⃣（R35 扫描只扫新增行故漏） | update_server.py:807/828/850/1006/1025 |
| S37-12 | **P4** | `npm root -g` 探测 Windows 恒 FileNotFoundError（CreateProcess 不解析 .cmd，npm 无 npm.exe）——自定义 npm 前缀兜底为死分支 | build.py:288（:341 claude 段存量同款） |

---

## 实锤详证

### S37-1（P2）：memory 档 `prefix` 大小写敏感回归——小库（<20 万符号默认档）混合大小写前缀命中丢失

- **位置**：`src/nav_index.py:845-848`（`_MemBackend.prefix`），调用点 `:1091`（`_be.prefix(qlow, limit * 2)`）。
- **证据链**：
  1. `symbols()` 把查询统一小写后传入：`qlow = (q or "").strip().lower()`（:1063）→ `_be.prefix(qlow, ...)`（:1091）。
  2. `_MemBackend.prefix` 实现 `if k.startswith(q)`——k 是**原形态**符号名，q 是**已小写**查询：任何含大写字母的符号名恒 False。
  3. 对照 pre-a390 原实现（`git show 8251c58:src/nav_index.py` 的 symbols()）：`nl = name.lower(); elif nl.startswith(qlow): prefix.append(name)`——**双小写、不敏感**。a390 换档时 memory 档 prefix 写成了敏感比较，a391 的 S35-1 修复只改了 sqlite 档 prefix（范围式 lower）与 exact 族（lookup_ci），memory/readtags 两档 prefix 未动；R35 终版台账只记了"readtags 档 prefix 精确性差异（-p 无不敏感形态）"——**memory 档不在已知清单内**。
  4. 运行时探针（只读直调，内存构造 dict）：`prefix('appl')` → `[]`（库里有 'Application'）；`prefix('foo')` → 只有 'foobar_ui'，'FooBar' 丢失。
- **影响面**：memory 档是 <20 万符号库的默认档（绝大多数工程）。饱和场景（小写前缀族 ≥ limit*2）时 `substr` 被跳过（:1092-1093）→ 混合大小写名**完全消失**——与 R35-1 的 'Application' 零结果同型，只是换了档位；不饱和时跌到 substring 三级（结果顺序本就不按分级排，主要伤饱和与 `[:limit*2]` 截断）。
- **复现**：静态推演 + 上述只读探针即可；真机可用任一 <20 万符号库 Ctrl+T 输大写前缀（如 `App`）对照小写前缀（`app`）。
- **最小修**：`if k.lower().startswith(q):`（一行，与 substring 档口径对齐）。

### S37-2（P2）：build 阶段 4 sqlite 分支无前置 `_close_tagdb`——重建"成功"却静默降级 readtags + 110MB 级 tmp 残留

- **位置**：`src/nav_index.py:555-567`（阶段 4 sqlite 分支与失败回退）、`:671`（`os.replace(tmp, db_path)`）、`:594`（`_invalidate_cache()` 在**最后**才调）；`src/nav_api.py:103-105`（nav_build work() 直接 `nav_index.build(...)`，**无** `_close_tagdb`——a392 只给 reindex work() 前置了，:214）。
- **证据链（纯静态推演即可复现）**：
  1. 用户查询过该库（sqlite 档正常使用状态）→ `_tagdb_cache` 常驻持有 tags.db 连接（256MB mmap）。
  2. 用户点"重建索引"（backend=sqlite/auto 大库）→ build() 阶段 1-3 不动缓存 → 阶段 4 `_build_tag_db` 写 tags.db.tmp 成功 → 末步 `os.replace(tmp, db_path)`：Windows 上旧 tags.db 被本进程打开（无 share-delete）→ **WinError 5**。
  3. 异常被 `except Exception` 捕获 → say"tags.db 构建失败——回退 readtags 模式"→ `_bk_user="readtags"` → 补删 `os.remove(db_path)` 同样失败（有 `try OSError: pass` 静默）→ **meta.backend=readtags 落盘，build 整体 ok=True**。
  4. 后果：用户显式要 sqlite（或 auto 大库判档）→ 拿到 readtags（查询 ~0.2s/次 vs 0~4ms），建好的 tags.db.tmp（45.8 万行 95MB、600 万行 ~1.2GB）残留；磁盘上旧 tags.db 也在（与 meta 口径分裂，sizes.db 记的还是旧库大小）。
  5. 第二次重建才可自愈（降级后 meta=readtags，查询走 readtags 不再持 db 连接）——但用户不知道要重建第二次。
- **与已知项边界**：R35 只报过 reindex 端点（S35-2，a392 已闭环）与 build 的 **memory/readtags 分支 remove**（"不崩但 db 残留"观察项）；**build 的 sqlite 分支 os.replace 失败 → 静默降级**这条链未在任何台账出现，且 nav_build work() 至今没接 a392 的前置修复。
- **最小修**：nav_api.nav_build 的 work() 开头（或 build() 进入阶段 4 前）加 `nav_index._close_tagdb()`——与 reindex 对齐，一行。

### S37-3（P3）：reindex/build 的 db 操作窗口内并发查询重开连接（TOCTOU）——a392 前置修复的并发盲区

- **位置**：`src/nav_api.py:214`（`_close_tagdb` 只清一次）→ `:221-224`（sqlite 重建，`_build_tag_db` 内部 45.8 万行 ~3s / 600 万行 ~40s）→ 末步 `os.replace`；`:228`（remove）。重开入口 `src/nav_index.py:905-936`（`_get_tagdb` 无任何"防重开"守卫）。
- **证据链**：a392 的前置 `_close_tagdb()` 只保证**起始时刻**无连接。窗口期内（reindex sqlite 重建全程 / reindex readtags 的 remove 前毫秒级 / build 阶段 4 全程）任何查询线程走 `_open_tags` → meta 仍是 sqlite → `_get_tagdb` 重开旧 tags.db 并入缓存 → 末步 remove/replace 再次 WinError 32/5。
  - reindex 后果：任务 err（meta 未写，可重试，重试通常成功——与 S35-2 时代的永久失败不同）+ tags.db.tmp 残留（R35 复验就撞过一次 110MB 残留）。
  - build 后果：叠加 S37-2 的静默降级链。
  - R35 终版真机重演是"无并发查询"场景，本竞态未覆盖。
- **复现**：静态推演成立（线程交错点明确：`_close_tagdb` 与 `os.remove`/`os.replace` 之间无互斥）；真机可在 reindex sqlite 期间连续 F12 撞窗口尾部的 replace。
- **最小修**：①`os.replace(tmp, db_path)` 失败时短暂重试 2-3 次（每次前再 `_close_tagdb()`）；或②结构性：模块级 `_db_busy` 集合，build/reindex 操作某 ld 期间 `_get_tagdb` 对该 ld 返回 None（查询自然落 readtags/memory 兜底，正确性无损）。

### S37-4（P3）：网络盘过滤把所有 `!` 无条件隐藏——真实删除文件在 SVN 面板消失，symlink_hidden 计数虚高

- **位置**：`src/vcs.py:396-399`：
  ```python
  if f["st"] in ("!", "~"):        # !（missing）误报；~ 未入映射表防御
      sym_hidden += 1
      continue
  ```
- **证据链**：
  1. 该分支**不查 sym 清单**（`_svn_symlink_paths` 的结果 `sym`/`sym_low` 只在 M 分支 :400 使用）。
  2. svn status 的 `!`（missing）语义 = "受控文件在磁盘上丢失"——**用户手工删除的真实文件在网络盘上同样报 `!`** → 被当成符号链接误报隐藏，面板看不到该改动，且 `symlink_hidden` 计数虚高（前端提示"已隐藏 N 条"把真删文件也算进去）。
  3. `~` 分支为死代码：状态映射表（:329-333）只有 modified/added/deleted/unversioned/conflicted/replaced/missing/none，`obstructed` 在解析阶段即被 `if not st: continue` 丢弃——`f["st"]=="~"` 永不出现；注释"~ 未入映射表防御"自相矛盾（防御一个到不了的分支，反而漏防真实的 `!`）。
- **影响面**：网络盘（SMB/UNC）SVN 工作副本的变更面板——真实删除/丢失文件静默消失（假阴性），比过滤前的误报（假阳性）更危险：用户以为"没有改动"。
- **复现**：静态推演成立；网络盘上 `del 真实文件`（非 svn rm）→ 刷新变更面板 → 该文件不出现且 symlink_hidden+1。
- **最小修**：`!`/`~` 仅当 `f["rel"] in sym or f["rel"].lower() in sym_low` 才隐藏，否则保留；顺带删死分支或补 obstructed 映射。

### S37-5（P3）：nav_keys POST 只收 5 键、整字典覆盖——fsym 改键永不落盘

- **位置**：`src/server.py:1476`（`_NK_KINDS = ("def", "ref", "sym", "back", "fwd")`——无 fsym）、`:1505-1509`（`len(set(...)) != len(_NK_KINDS)` 冲突检查 + `_save_config({**_load_config(), "nav_keys": _nk_out})` **整字典替换**）；GET 默认 `:1381-1387` 却含 `"fsym": "ctrl+shift+o"`。前端 `web/js/settings.js:151`（DEF 六键）、`:160`（`_ORDER = ['def','ref','sym','fsym','back','fwd']`）、`:256-259`（POST 全量 `{nav_keys: keys}` + banner 全键宣称"已生效（fsym 曾漏）"）。
- **证据链**：
  1. 设置页快捷键卡片有 fsym 录制框，用户改 fsym → 保存 POST 六键。
  2. 后端循环只收 5 键 → `_nk_out` 无 fsym → `_save_config` 用五键字典**整体覆盖** config.nav_keys → fsym 从配置中消失（连 GET 默认值都救不回：config 已有 nav_keys，`cfg.get("nav_keys", 默认)` 不再走默认）。
  3. 前端 `NJ.applyKeys(keys)` 热应用当次生效、banner 宣称全键已生效；**刷新后** nav.js `applyKeys` 缺键回退硬编码默认 `ctrl+shift+o` → 用户改的 fsym 静默还原。
  4. 附带：fsym 与其他键的冲突检测在后端永不生效（值根本进不了 `_nk_out`）——仅剩前端 syncSave 兜底。
- **与已知项边界**：R33-4 修的是 banner 漏拼 fsym（前端显示层）；server.py 保存白名单漏 fsym 未报过。
- **复现**：设置页把"文件内符号"改为 F4 → 保存（banner 成功）→ 刷新页面 → Ctrl+Shift+O 仍生效、F4 无效；config 文件里 nav_keys 无 fsym 键。
- **最小修**：`_NK_KINDS = ("def", "ref", "sym", "fsym", "back", "fwd")`（一行；GET/POST/前端三方口径即齐）。

### S37-6（P3）：codegraph 未注册进 res_boot.MANIFEST——外部依赖面板死路，与 a386 的 installer/错误文案脱节

- **位置**：`src/res_boot.py:43-66`（MANIFEST 8 kind：webview2/dotnet/node/git/claude/pydeps/onlyoffice/bili，**无 codegraph**；该文件本范围未改）；对照 `src/res_install.py:35`（ORDER 已加 "codegraph"）、`:510-575`（_install_codegraph）、`:829/:838/:841`（_INSTALLERS/_INSTALL_LABEL 已注册）；`src/res_api.py:46-49`（面板数据源 = `probe_all` + `MANIFEST`）；`src/nav_codegraph.py:87-88`（错误文案"codegraph 未安装（**设置→外部依赖安装**，或重装资源包）"）。
- **证据链**：
  1. a386 给 res_install 铺了完整安装能力，但 res_boot.MANIFEST 没加条目 → `probe_all` 不探测、面板不显示、单装入口不存在。
  2. 用户工作机（a386 的原始实锤场景：无 npm、面板报未安装）按错误文案打开"设置→外部依赖"→ **没有 codegraph 这一项** → 死路（只剩"重装资源包"整包路径）。
  3. claude_default.py:358 docstring"未装时静默跳过（**弹层有安装提示**）"——弹层来自 MANIFEST，提示同样落空。
  4. 在线安装通道（res_install.py:1046 起）无 codegraph 分支 → 该 kind 静默进 skipped，连一句 say 都没有（bili/onlyoffice 有显式跳过文案）。
  5. 只有"完整离线包安装"（kinds=None → 全 ORDER）才会装 codegraph——增量/单装/面板全不可达。
- **复现**：静态推演成立；未装 codegraph 的机器打开设置→外部依赖 → 无 codegraph 条目。
- **最小修**：res_boot.MANIFEST 加 `{"kind": "codegraph", "name": "Claude 代码图引擎", "hard": False, ...}` + `_PROBES["codegraph"] = lambda: ("ok","") if nav_codegraph.available() else ("missing","")`（两行）。

### S37-7（P4）：readtags 后端参数注入——`-` 开头查询被当 ACTION/OPTIONS

- **位置**：`src/nav_index.py:763`（`argv = [self._exe, "-s1", "-e", "-n", "-t", self._tags] + args`），`args` 直接来自用户查询：lookup `:792`（`self._run([name])`）、lookup_ci `:799`（`["-i", name]`）、prefix `:802`（`["-p", q]`）。
- **证据**：`readtags --help` 实证（本机 vendor/ctags）：`-l | --list` 是 ACTION（全量列举）、`-i` 是 icase 开关，且 help 明确提供转义形态 `[-] NAME...（"-" indicates arguments after this as NAME(s) even if they start with -）`——即后端没有使用官方转义。
- **影响面**：仅 readtags 档。Ctrl+T 查询框输入 `-l` → argv 尾部变成 ACTION → 全库 1.2GB stdout 进内存 + CPU 尖峰（30s 超时兜底杀进程，结果仍为空）；`-i/-p/-e/-n/-D` 等改变语义/报错，均静默空结果。sqlite/memory 档不受影响。无命令注入风险（list 形态、无 shell）。
- **复现**：静态推演成立（readtags getopt 行为）；readtags 档库 Ctrl+T 输 `-l` 可实测内存/延迟尖峰。
- **最小修**：位置参数前插转义 `"-"`（按 help 的 `[-] NAME` 形态），或对 q 以 `-` 开头时拒绝/加前缀。

### S37-8（P4）：`_svn_symlink_paths` sqlite URI 未编码——`%`/`#` 目录名下过滤静默失效

- **位置**：`src/vcs.py:184`：`sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True, timeout=3)`。
- **证据链**：wc 路径来自用户工程目录（登记根内任意目录）。Windows 允许目录名含 `%` 与 `#`（`?` 不允许）。`D:\AI\50%off\...` → URI 解析把 `%of` 当百分号转义序列 → 打开错误路径；`D:\AI\issue#1\...` → `#` 起 fragment 截断路径 → 连接失败 → `except Exception: return set()` → 网络盘符号链接过滤**静默全关**（SMB 误报回涌，且无任何日志）。对照 `_TagDB`（nav_index.py:682）同形态但路径受控（DATA_DIR/md5），无此暴露面。
- **复现**：静态推演成立；网络盘上建含 `%` 的目录做 wc → 误报不过滤。
- **最小修**：`pathlib.Path(db).as_uri()` 或 `urllib.parse.quote(db.replace("\\","/"))`。

### S37-9（P4）：reindex 不更新 meta.sizes.db——status 尺寸双方向失真

- **位置**：`src/nav_api.py:229-233`（reindex work 只写 `backend/backend_auto` 两键）；`src/nav_index.py:175`（status `size = sum(sizes.values())`）。
- **证据链**：sqlite→readtabs 切档：tags.db 已删但 meta.sizes 仍带旧 `db` 项 → 面板显示库尺寸虚高 ~95MB+；readtags→sqlite 切档：新建 tags.db 但 sizes 无 `db` 键 → 虚低（600 万行库差 ~1.2GB）。build() 每次全量重写 sizes 无此问题。
- **复现**：静态推演成立；reindex 后读 status.size 与磁盘实际对比。
- **最小修**：reindex 成功后按 backend 现状补/删 `meta["sizes"]["db"]`。

### S37-10（P4）：`_register_codegraph_mcp` docstring 与实现矛盾

- **位置**：`src/claude_default.py:353-358`（docstring："前提：npm 全局 codegraph 可执行……幂等只补缺不覆盖"）↔ `:379-387`（实现：`_stale` 即**覆盖更新**——R34-2 的自愈语义，且 argv 来自 bundle 直启不再依赖 npm）。
- **证据**：diff 直读——R34-2 修复改掉了"只补缺"行为（这正是其闭环实锤），但 docstring 未同步；"npm 全局可执行"前提也已被 a386 bundle 直启取代。行为本身无缺陷（R34 复验闭环），问题在注释误导后人 + 覆盖语义会把用户对 codegraph 条目的自定义（如 env、换端口 args）每次 provision 静默打回——docstring 的旧契约承诺会让人误以为安全。
- **最小修**：docstring 两句改写（自愈覆盖语义 + bundle/npm 双前提），并提示用户自定义条目会被重置。

### S37-11（P4）：update_server emoji 清零残留

- **位置**：`src/update_server.py:807/828/850`（说明书 `1️⃣2️⃣3️⃣` keycap 序列，U+0031+U+FE0F+U+20E3）、`:1006/:1025`（下载按钮 `⬇` U+2B07）。
- **证据**：程序化扫描（本报告审计方法节）——本范围 a373 提交清理了该文件十余处 emoji（🎨📦📖✨🔩📄🤖👥👁🛡🚀💡📅🧰），但这五处漏网；R35 的"新增行 emoji 扫描"只扫 + 行，这些是上下文行故未报。keycap 与 ⬇ 属 emoji 呈现（铁律"要么 SVG 要么不要"），非 ✓/✗ 类文本符号。
- **最小修**：`⬇` 删或换 SVG；keycap 三处换 `<b>1.</b>` 类文本样式。

### S37-12（P4）：`npm root -g` 探测在 Windows 恒失败——自定义 npm 前缀兜底死分支

- **位置**：`src/build.py:288`（a386 新增 `_refresh_offline_codegraph`）；`:341`（`_refresh_offline_claude` 存量同款，作对照）。
- **证据**：`subprocess.check_output(["npm", "root", "-g"], ...)`——list 形态走 CreateProcess，不解析 `.cmd`（PATHEXT 是 cmd.exe 的机制），且 npm 发行物无 `npm.exe`（本机 `where npm` 实证：仅 `C:\Program Files\nodejs\npm` 与 `npm.cmd`）→ FileNotFoundError → `except Exception: pass`。注释宣称的"npm 前缀自定义过的机器"兜底**从未生效过**；codegraph 段原样复制了该死分支。后果轻（APPDATA 默认位候选通常够用），但该候选永远只查默认位，与注释承诺不符。
- **复现**：静态推演成立（CreateProcess 语义 + npm.exe 不存在）；或临时把自定义 npm 前缀装上包后跑打包，观察从不命中。
- **最小修**：`["npm.cmd", "root", "-g"]`（Windows）或 shutil.which("npm") 取全路径。

---

## 存疑区（不实锤，供跟踪）

1. **_install_codegraph 失败清场的锁定文件残留窗**（res_install.py:544-555）：`_sh2.rmtree(dst, ignore_errors=True)` 遇被锁文件会静默留下残缺 dst → 幂等检查读残缺 lib/package.json 可能再次误判"已是最新"（R34-3R 想封死的形态在"rename 成功后、rmtree 期间文件被占用"的窄窗内仍可复活）；且 `os.replace(bak, dst)` 失败被 `except OSError: pass` 吞掉、无 say（claude 段同场景有"回滚失败"提示）——静默丢旧版。
2. **_open_tags 降级链无尺寸守卫**（nav_index.py:885-902）：显式 readtags/sqlite 档的大库，在 readtags.exe 缺失（被杀软隔离/损坏）时静默落 `_MemBackend` → 600 万行 tags 全量 dict ≈ 8GB → OOM/卡死。auto 判档规则不适用于显式档的回退路径。
3. **definition Hover 摘要整读**（nav_index.py:1369-1388）：`_need = max(line)+2` 逐行读——tags 行号失效（超 EOF）时读到底，32MB 级生成文件整份进内存，注释"大文件不整读"承诺被击穿（正常行号不触发）。
4. **codegraph 250MB 复制无进度回调**（res_install.py:838 `_PROGRESSIVE = {_install_claude}` 不含 codegraph）：`_install_codegraph` 内的 prog 接线（:547/:548-550）是死代码；UI 只能"不确定进度"。与 _INSTALL_LABEL 注释自洽，疑为有意，记观察。
5. **build.py codegraph 归档 walk 的 os.stat 异常面**（build.py:519-521）：`os.stat(os.path.join(r, d)).st_file_attributes` 遇断链目录符号链接抛 FileNotFoundError → 打包崩（bili/claude 段同款存量写法）；且 os.stat 跟随 junction → 指向外部大目录的 junction 不带 reparse 标志 → 过滤失效 → 归档膨胀（npm bundle 正常形态无断链，触发面窄）。
6. **`LIKE '%svn:special%'` 子串误匹配**（vcs.py:186-188）：svn 只保留 `svn:` 前缀属性名，`foo:svn:specialx` 类自定义属性合法且会被命中 → 该文件 M 在网络盘被误隐藏。极窄。
7. **`import elftools  # noqa. F401`**（nav_index.py:501，a390 把 `noqa: ` 写成 `noqa. `）：静态检查指令失效（微）。
8. **_get_tagdb 双检第二分支可返回他 key 的 db**（nav_index.py:929-931）：key 在建连期间被第三方换掉时，返回的是新 key 的连接（瞬态跨版本读，同库不同 mtime，影响可忽略）。
9. **a372 scan_max 重置的一次性补扫阻塞**（nav_index.py:1172-1193）：所有旧库首次 references 触发同步 rg 全树补扫（timeout 300s）——设计如此（"升级即生效"），代价是首个 Shift+F12 可能长时间挂起，建议前端给提示。

---

## 无问题声明区（核对过、无实锤）

- **SQL 注入**：nav_index.py `_TagDB` 全部查询、`_build_tag_db`、vcs.py `_svn_symlink_paths` 均为字面 SQL + `?` 参数化，无字符串拼接用户输入。
- **命令注入**：全范围 subprocess 均 list 形态、无 shell=True、无 str 拼接（rg/ctags/readtags/robocopy/node）；唯 readtags 位置参数 flag 注入另报（S37-7）。
- **并发缓存**：`_tags_cache/_symbols_cache/_manifest_cache/_meta_cache_for_backend/_tagdb_cache/_tagdb_orphans` 读写全部持 `_cache_lock`；`_write_json` 线程唯一 tmp + `os.replace` 原子；`_file_sym_cache/_tags_files_cache` 已退役为死声明（无写入点，无泄漏）。
- **vcs 结构判定**：`_is_git_wc`（.git 文件看 gitdir: 前缀 / 目录看 HEAD+objects）与 `_is_svn_wc`（wc.db）对 git worktree/submodule 与 svn 1.7+ 形态正确；svn 1.6 纯目录工作副本不再识别为注释声明的设计收窄。`_is_network_drive` UNC 直判 True + GetDriveTypeW(4) 与 R34-1 复验口径一致。
- **a386 直启链真机冒烟**：`offline_assets/codegraph/node.exe` v24.16.0 接受 `--liftoff-only --disable-warning=ExperimentalWarning`，`lib/dist/bin/codegraph.js` 在场且与 `_cg_argv` 三个候选路径一一对应（res_install 安装位 / npm 嵌套位 / offline_assets）。
- **res_install 主路径**：`_install_codegraph` 幂等（版本比对）/ bak 还原 / 无 bak 清场的主干与 claude B4 同款语义成立（残留窗见存疑 1）；ORDER/_INSTALLERS/_INSTALL_LABEL/离线 kinds 四处注册一致；`prog` 缺省安全（不在 _PROGRESSIVE 时不传回调）。
- **server.py nav_keys 方向键守卫**：方向键仅限 back/fwd + 必须带修饰；`_HK_RE` 对 `arrowleft`/`alt+arrowleft` 形态放行核对无误（不会误杀默认 alt+←/→）；五键互异检查兼容存量三键配置（GET 默认合并）。
- **harness/v4feed、v4hub、deps_bootstrap 的去 emoji**：三处 ✅ 前缀移除为纯文案，tests/test_v4feed.py 两处断言同步，无行为变化（v4feed 剩余 ✅×3 均在注释内，不渲染）。

---

## 审计方法说明

1. **范围确定**：`git diff 8251c58..HEAD --stat`（14 个 py 文件，+937/-141）+ `git log --oneline`（33 提交）逐条对应；六重点文件逐提交 `git show <hash> -- <file>` 归因（a372 32M 扫描、a383 hover/全键、a386 codegraph 内置、a388/389 R34 修复、a390 三档后端、a391/a392 R35 修复），其余文件全量 diff 粗扫 + 牵连文件（res_boot.py、res_api.py、web/js/nav.js、settings.js）交叉核对数据链。
2. **现状全文**：nav_index.py 1401 行全读；vcs.py 相关段（_wc_root/_svn_changes/_is_*/_svn_symlink_paths）全读；nav_api.py 关键函数全读。
3. **已知项避让**：R35 终版台账（S35-1~6/S36-1）+ 观察项 10 条逐项比对——S37-1 与"readtags prefix 差异"按档位/位置区分；S37-2 与"build remove 分支 db 残留"按分支/后果链区分；S37-3 与 S35-2 按"起始时刻 vs 窗口期"区分；其余（substring LIKE 全扫、by_path 小写盘符、_close_tagdb 锁外窄窗、假进度、code_files 语义等）未触碰。
4. **只读验证**：`_MemBackend.prefix` 内存 fixture 直调（未触盘）；`readtags --help` 参数面；`where npm` + `ls $APPDATA/npm/npm.exe`；`offline_assets/codegraph/node.exe --liftoff-only` 冒烟；Python 程序化 emoji 扫描（12 个后端文件）。全程零写盘（本报告除外）、git 零触碰、真 ~/.claude.json 与用户索引库未读写。
5. **定级口径**：P2=核心功能静默错误/用户可见回归且难自愈；P3=功能缺口/可自愈竞态/明确的数据失真；P4=一致性/健壮性/死代码级。
