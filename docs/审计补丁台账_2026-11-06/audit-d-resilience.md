# 对抗式审计报告 D · 健壮性/并发/资源组（黑盒）

- 对象：8867 真机（a392 已加载）+ CDP 9223 前端，攻击矩阵 7 项（并发轰击 / 切档中途 / 磁盘资源 / 内存压力 / 长跑 / 异常注入 / 前端资源）
- 基准台账：`.zcode/tmp/audit_round35.md`（S35-1~6、S36-1 已闭环）+ `doc/audit-a-backend.md`（S37-1~12）。本报告全部为黑盒**新发现**；与已知项同根因的标注"同源"并只做量化补充。
- 纪律：根库（f93dd9f2b98437bd，用户共享数据区）全程只读查询；破坏性测试仅对自建 fixture 库（`.zcode/tmp/resdfx/proj`，21.7 万符号 sqlite 库）与其数据目录副本；fixture 已全清（见方法与清理节）。

---

## 结论先行

**实锤 5 件（P1×1 + P3×3 + P4×1）+ 同源量化 1 件 + 观察项 4 条。**

主题一句话：**三档后端的"单槽连接缓存"在多工程交替查询下无界泄漏 sqlite 连接——句柄与内存线性爬升，满载约 50-60 秒服务器进程静默死亡（无 Traceback、无 WER 事件、无自动重启）；两条独立文件级 TOCTOU（meta.json replace 撞并发读者）让 reindex 偶发失败并残留 tmp；前端 tab 开/关存在每次数百 KB 的慢泄漏。**

| # | 分级 | 主题 | 一句话证据 |
|---|---|---|---|
| D-1 | **P1** | `_tagdb_orphans` 单槽缓存孤儿连接无界泄漏：多库交替查询每次换库泄漏 ~2 句柄 + 0.35MB priv；满载混合负载下句柄 249→2698、WS 66→505MB 线性爬升后**服务器进程静默死亡**（两次独立复现，其一有完整看门狗轨迹） | 最小化实验四段证据链（本报告 §D-1） |
| D-2 | **P3** | reindex 末步 `os.replace(meta.json.*.tmp → meta.json)` 撞并发读者（`list_libs()` 每次 definition 都读全部 meta.json）→ WinError 5 任务失败 + `meta.json.<tid>.tmp` 残留——S37-3 的 TOCTOU 同族但资源与修法不同 | 25 次三档循环撞 2 次（9.5%），残留 2 个 374B tmp |
| D-3 | **P3** | 前端 tab 开/关慢泄漏：走产品真实关闭路径 `closeEditorTab`（dispose monaco+model）后，强制 GC 堆仍每 10 次开/关 +5.8MB 线性不回落（小文件 +2.7MB/10 次） | GC 甄别实验（本报告 §D-3） |
| D-4 | **P3** | `/api/nav/delete` 对被锁文件 `rmtree(ignore_errors=True)` 静默失败仍返回 ok:true——45MB tags.db 永久残留且不可再删（meta 已删 → 无代码路径再触发 `_close_tagdb` 解锁） | 删除后返回 ok:true 但目录残留，手动删报 WinError 32 |
| D-5 | **P4** | `_guard` 对类型混淆/相对形态 root 放行：`root=123`/`{}`/`True` 经 `str()`+abspath（以服务器 CWD 解析）落回登记根内 → build 任务真实启动（对不存在目录快速失败，未落库） | 5 种垃圾 root 中 4 种返回 200 ok:true |
| 同源 | — | S37-3（db 窗口 TOCTOU）黑盒量化：3 查询线程下 25 次切档失败 4 次（tags.db replace WinError 5 ×1、remove WinError 32 ×1）；a392 前置 `_close_tagdb` 只封起始时刻的结论在真机成立 | 不计新实锤 |

---

## 实锤详证

### D-1（P1）：单槽缓存孤儿连接无界泄漏 → 满载服务器进程静默死亡

- **位置**：`src/nav_index.py:905-936`（`_get_tagdb` 每次换 key 把旧连接挂 `_tagdb_orphans`）+ `:942-955`（`_close_tagdb` 是**唯一**回收点，仅 reindex work 开头 / build / rebind 经 `_invalidate_cache` 触达）。纯查询路径上没有任何回收。
- **机制**：`_tagdb_cache` 是单槽（key+db 各一份）。两个库 A/B 交替查询时，每次切到另一库必然 key 失配 → 建**新** `_TagDB`（新 sqlite 连接：文件句柄 + 256MB mmap + 最大 64MB page cache）→ 旧连接进 `_tagdb_orphans`。库里挂着引用，永不 GC。多工程用户（本机 tree_roots 实配 4 个根）在两个已索引工程间交替 F12/Ctrl+T 即持续泄漏。
- **攻击序列**：①攻击1（22 线程混合端点 60s，definition 同时打 fixture+根库）；②攻击1v3 仪表化分级（P0 2 线程 10s → P1 6 线程 30s → P2 20 线程 60s）+ 独立看门狗进程 1s 采样。
- **现象（两次进程死亡）**：
  - 死亡 A（PID 35244，全新实例）：看门狗时间线 `.zcode/tmp/resdfx/timeline.tsv`——0-40s（P0+P1）poll 2-23ms 全 200，但**自 P1 起（多库交替开始）资源线性爬升**：handles 727(20s)→1231(25s)→1594(30s)→1887(36s)→2337(40s)→2698(45s)，WS 66→505MB（+15MB/s）；P2 满载后最后一次 OK 在 48.3s，51.3s 起连接失败，**60.5s 确认 PROC GONE、端口死亡**。全程无 5xx、无 Traceback、无 Windows Error Reporting 事件（Application 日志 3 小时内 0 条 Id 1000/1001）。
  - 死亡 B（PID 36320，已运行 3.5h 的实例）：22 线程轰击 ~3s 后客户端全部 ConnectionReset（每次 ~2034ms）随后 ConnectionRefused；服务端日志（server_a392.log）把这些在途请求的 200 全部压在 **01:21:06 同一秒**落盘（≈9 分钟后统一完成）——先冻结后死亡；进程终告消失（procinfo None），由外部在 01:24:30 重启。
- **最小化实锤（controlled experiment，`.zcode/tmp/resdfx/scripts/attack_leak.py`）**：
  | 实验 | 句柄 | priv | 结论 |
  |---|---|---|---|
  | 双库交替 200 次 | 264→668（**+404**） | 58→128MB（+70MB） | 泄漏 ≈2 句柄 + 0.35MB / 次跨库查询 |
  | 交替后空闲 5s | 664（不回收） | 118.7MB | 无自愈路径 |
  | **对照：单库 200 次** | 664→670（+6，噪声） | +10MB 瞬态回落 | 单库不泄漏——变量锁定"换库" |
  | 一次 reindex（memory） | 668→**252** | 128→65MB | `_close_tagdb` 全量回收孤儿——泄漏物身份证实 |
- **影响面**：多工程交替使用的开发者数小时内句柄/内存爬升；脚本化/重度并发场景（CI、多面板齐发）约 1 分钟内服务死亡且**无任何日志线索、无自动重启**（run.bat 不守护）——用户表现为"工具凭空消失"。这也解释了共享测试环境下 8867 一日内多次换 PID。
- **与已知项边界**：S35-3 闭环的是"并发 close/双建/换库杀在途"三个并发正确性缺陷（a391 修复复验 PASS，本轮 P0-P2 低并发下零 ProgrammingError，佐证修复有效）；audit-a S37-3 是"窗口期重开连接撞文件操作"（同源见下）；**orphan 列表本身作为纯查询路径上唯一生命周期终点的设计缺口**未在任何台账出现。
- **最小修方向**：①`_get_tagdb` 缓存改按 ld 键的多槽 dict（每库一个常驻连接，并发查询本就经 `_TagDB._lock` 串行，多槽安全）——删掉孤儿路径；或②保守修：`_tagdb_orphans` 加上限（如 >8 时锁内关最旧），并让 `_open_tags` 在**查询路径**的空闲时机（如每 N 次查询）顺带回收；无论哪种，`close()` 应拿 `self._lock`（R35 遗留观察项一并收口）。

### D-2（P3）：reindex 末步写 meta.json 撞并发读者——任务失败 + tmp 残留

- **位置**：`src/nav_api.py:232`（reindex work 收尾 `_write_json(meta.json)` → `os.replace`）↔ `src/nav_index.py:1037-1049 find_lib_for → list_libs()`（**每次 definition 都 `_read_json` 全部库的 meta.json**）+ `_load_json_cached`。CPython `open()` 的共享模式不含 FILE_SHARE_DELETE，`os.replace` 需要对目标取 DELETE 访问 → 读者在窗口内即 WinError 5。
- **攻击序列**：攻击2——3 个查询线程（def×2 + scope=file×1，fixture 单库）+ 1 个 reindex 线程做 25 次三档循环（sqlite/readtags/memory）。
- **现象**：25 次中失败 4 次（15.6%——其中 2 次即本条）：
  - `sqlite` 档 2 次：tags.db 重建+replace **已全部完成**（5s 白做）后，`meta.json.28308.tmp → meta.json` 与 `meta.json.32168.tmp → meta.json` 各报 **[WinError 5] 拒绝访问**；
  - 残留：两个 `meta.json.<tid>.tmp`（374B，内容完整）留在库目录——`_write_json` 失败路径无清理，按线程 ID 命名，长期累积；
  - 任务槽终态 ok=False（meta 未写=档位未切换，用户重试通常成功）。
- **同源说明**：与 audit-a S37-3（reindex 窗口内查询重开 db 连接撞 remove/replace）同属"reindex 写盘窗口 vs 并发读者"TOCTOU 族；但资源是 **meta.json 而非 tags.db**，S37-3 建议的"replace 失败重试 + `_db_busy` 让 `_get_tagdb` 让路"修不到本条（读者是普通文件读）。故按新实锤报。
- **影响面**：多库共存 + 用户边查边切档的常态操作下 reindex 约一成概率"切档失败"（且已白付一次 sqlite 重建 5s+）；残留 tmp 污染库目录（stale 空间计入 sizes 展示口径外）。
- **最小修方向**：`_write_json` 的 `os.replace` 包 2-3 次短退避重试（每次间隔 20-50ms，读者 open→json.load 毫秒级）；或 reindex 收尾前对同 ld 短暂持 `_cache_lock` 之外再无必要——重试已够；tmp 失败路径 finally 清理。

### D-3（P3）：前端 tab 开/关慢泄漏（真实关闭路径下仍不回落）

- **位置**：编辑器 tab 关闭链 `closeEditorTab → _edCloseNow`（editor.js:1427，已 dispose editor/monaco/model/监听器）之后仍有保留物；黑盒无法定位具体对象（需白盒 heap snapshot）。
- **攻击序列**（CDP 9223 独立 target，`attack7.py` + `attack7b.py`）：
  1. 50 次 `openFileSmart(nav_index.py / server.py)` + 关闭，每 10 次采样 `performance.memory`：usedJSHeap 28→75→107→137→160→198MB 单调爬升；
  2. **GC 甄别**：`HeapProfiler.collectGarbage` 后重跑 5 轮×10 次开/关——baseline 23.7MB → +38.0 → +69.1 → +100.5 → +131.4 → +162.7MB（**每 10 次 +31MB，GC 后不回落**）；
  3. 修正关闭路径重跑（`closeEditorTab`，即 UI 侧栏分发 sidebar.js:229-235 的真实编辑器路径）：仍线性 +5.8MB/10 次（50 次 +33.5MB）；
  4. 小文件（README.md）×30：+8.1MB（+2.7MB/10 次）——保留量随开关次数而非文件大小线性。
- **对照 PASS**：tab/connections 数每次关闭后精确回归 baseline（DOM 无泄漏）；log-viewer 39.6MB×5 开/关 total=500000 每次重建、堆 215→194MB 自然回落（**日志查看器路径无泄漏**）；全程 0 个 JS 异常。
- **影响面**：重度切换文件的会话（1 天 ~1000 次开/关 ≈ 270-580MB 驻留）；长跑工具进程（pywebview 常驻）内存缓涨，与 D-1 服务器侧叠加放大观感。
- **附带 API 足枪观察**：`closeConnection(edit:*)` 直调（绕过 `_edCloseNow`）泄漏 5 倍（3.1MB/次）——终端 tab 关闭钮走的就是 closeConnection（terminal-core.js:76），当前按 kind 分发没踩到；外部脚本/扩展若直调 closeConnection 关编辑器 tab 会放大 5 倍。
- **最小修方向**：白盒做一次 heap snapshot diff（50 次开关前后 retained size 排序）定位保留者（首要嫌疑：monaco standalone editor 的 per-editor theme/styling cache 与 standaloneCodeEditor 端 worker 代理）；`_edCloseNow` 补 dispose。另建议 `closeConnection` 对 `edit:*` 前缀直接转发 `closeEditorTab`（一行防御）。

### D-4（P3）：`/api/nav/delete` 对锁定文件静默失败返回 ok:true——45MB 残留且不可再删

- **位置**：`src/nav_index.py:202-207 delete_lib`（`shutil.rmtree(ld, ignore_errors=True)` 恒 True）+ `nav_api.py:145-167`（删除后无残留核验）。被锁根因：fixture 库曾被查询（sqlite 档），`_tagdb_cache` 持有 tags.db 连接；删除先删 meta.json 成功 → **库从 `list_libs` 消失 → `find_lib_for` 不再命中 → `_open_tags`/`_get_tagdb` 永不执行 → 缓存连接无任何路径释放**。
- **攻击序列**：攻击1-5 使 fixture 库处于 sqlite 档且被查询 → `POST /api/nav/delete {root}` → 返回 `{"ok": true}`。
- **现象**：meta.json/manifest/tags/symbols 全部删除，**tags.db（44.9MB）残留**；手动 rmtree 报 [WinError 32]；`/api/nav/reindex` 因"没有索引库" 400、`status` 显示未索引——UI 视角库已不存在，磁盘视角 45MB 死数据 + 死连接，直到重启服务器（或对同 root 重新 build 触发 `_invalidate_cache`，本轮即用此法自清成功）。
- **影响面**：用户"删除索引"后空间不释放且无任何提示；残留目录名是 md5（用户无从下手）；与 S35-2 时代"删除被连接挡死"的表现不同（那次报错可重试，本次**静默成功**）。
- **最小修方向**：`delete_lib` 前 `nav_index._close_tagdb()`（与 reindex work 对齐，一行）；`rmtree` 改 `ignore_errors=False` 并对失败回 "部分删除失败" 而非 ok:true；`has_lib=False` 的删除路径（孤儿清理）同样先关连接。

### D-5（P4）：`_guard` 放行类型混淆/CWD 相对 root——垃圾 build 任务真实启动

- **位置**：`src/nav_api.py:75-83`（`root = str(d.get("root") or "").strip()` → `_guard(root)`）；`src/file_tree.py:73-81 _under_roots`（`os.path.abspath(相对形态)` 以**服务器 CWD**（=D:\AI\前端控制台）解析）。
- **攻击序列**（攻击6）：`POST /api/nav/build` body root 依次为 `null/123/{"a":1}/["x"]/true`。
- **现象**：`null` → 400（or 短路）；`123`→"123"、`{"a": 1}`、`["x"]`、`True` → **全部 200 ok:true**——abspath("123")="D:\AI\前端控制台\123" 落在登记根内，守卫放行，build 线程真实启动（对不存在目录阶段 1 快速失败，未写库——`/api/nav/libs` 复核无新增）。同口径 reindex 亦放行。
- **影响面**：API 直调方（脚本/集成）的语义错误不会被拒绝而是**静默启动一个对奇怪路径的索引任务**（失败于任务槽 err 里，UI 无从关联）；无路径逃逸（abspath 钉在 CWD 子树），无落盘污染。
- **最小修方向**：`build/reindex/delete` 入口校验 `os.path.isabs(root) and os.path.isdir(root)`（各一行）；或 `_guard` 拒绝非绝对路径形态。

### 同源量化（不计新实锤）

- **S37-3（db 窗口 TOCTOU）黑盒成立并量化**：攻击2 的 25 次切档中 2 次失败于 db 文件本身——sqlite 档 `os.replace(tags.db.tmp → tags.db)` WinError 5 ×1、readtags 档 `os.remove(tags.db)` WinError 32 ×1（3 查询线程的轻负载下即 8%）。a392 前置 `_close_tagdb` 只封起始时刻、窗口期查询重开连接即撞——与 audit-a 推演一致。修复方向即 S37-3 原文（replace 短重试 / `_db_busy` 让 `_get_tagdb` 返回 None 走兜底）。
- **S35-4（损坏 db 回退）黑盒复核 PASS**、**S36-1/substring 口径**、**S37-9（sizes 失真）**见下"通过清单/观察项"。

---

## 观察项（非实锤，供跟踪）

1. **tags 缺失时 references 域过滤静默失效**（tags-missing 态实测 17→18 条）：`_be.files()` 返回空集 → `if tags_set and ...` 假 → rg 结果不再按索引域过滤，域外文件（如 README.md）回涌。无崩溃、量级小，但"引用数"在降级路径上轻微失真（nav_index.py:1163-1166、:1239）。
2. **损坏 db 回退 readtags 档的性能形态**：db-garbage/zero 态四接口全 200 无 500（S35-4 修复黑盒成立），但 scope=file/symbols/references 走 `-l` 全扫实测 1.3-2.8s/次（fixture 42MB；600 万行库外推两位数秒）——UI 提示只在档位 title，降级瞬间无提示。
3. **攻击1 客户端可复现的延迟形态**：满载下 poll p50 26ms 而 status/def 全端点 p95≈2040ms 呈"双峰"（第一峰=正常服务，第二峰=连接在 2s 左右被重置）——可作为"服务进入冻结/死亡前兆"的黑盒指纹。
4. **环境残留（非本轮产物）**：根库目录内历史 corrupt.db（1 字节，R35 测试遗留，惰性）；DATA_DIR/nav 内 r35v2fx/r35v2fx2/r35v2fx3 三个不可达旧 fixture 库（meta 在、根已删，空间 ~30KB）；`.zcode/tmp` 下 cfix/projbig 等前轮 fixture 目录仍在（其库已在数据区删除）。均未触碰。

---

## 通过清单（攻击后无实锤区）

- **四接口锚点回归**（R34/R35 口径第四轮连绿）：scope=file server.py **213**；definition `_load_tags` **line=566**；fixture def/scf/sym/ref 全通。
- **数据完整性（并发 6200+ 请求）**：攻击1v3/攻击2/攻击5 累计 ~8000 请求，definition 空结果 0（根库 `_open_tags` 627 次 not-found 为 ctags 未收录该符号，tags 文件直读证实，API 行为正确——第一轮误报已撤销）、跨库串线 0、半写 db 读取 0；sqlite `os.replace` 原子性在 21 次切档中无一被读到中间态。
- **任务槽互斥**：10 并发 build（1 ok + 9×409）、10 并发 build+reindex 混合（1 ok + 9×409）、reindex 运行中再发 → 409 且文案正确；poll/状态在 4 分钟 21 次切档下无一错乱。
- **异常注入全优雅**：非 JSON/空字节/半截 JSON/数组/字符串 body → 400；1MB root → 400（abspath 未崩）；100KB query/URL → HTTP 414（Werkzeug 层拦截，无 500）；limit=99999/abc/-5 → 100/50/10 钳制正确；backend 大小写+空格归一接受、非法值 400；登记根外/无库目录 → 400。
- **磁盘破坏四态全 200**：tags.db 垃圾字节 / 零字节（探测失败 → readtags 回退，无 500、无 fd 泄漏——句柄 250 稳定）/ tags 缺失（全接口优雅空）/ meta 垃圾（status 未索引、全接口优雅降级，恢复 meta 后 mtime 失效自动换档）/ mtime 倒挂（无 mtime 排序逻辑，行为无差异）。
- **内存压力（单库）**：600 次 definition/scope=file/symbols 前后 handles +2（254→250）、priv 回落——进程侧无无界增长（前缀查询 132ms/次 = 已知 substring LIKE 全扫口径，不另立）。
- **长跑 4 分钟 mixed（1 req/s 随机端点 + 每 10s 切档）**：187 请求全 200、21 次切档 0 失败、错误尾 0；句柄 252-256 平稳，WS 197-290MB 振荡（memory 档 dict 装卸）后回落——**单库+周期回收的长跑形态稳定**。
- **前端 log-viewer 大文件**：39.6MB/50 万行 ×5 开/关，索引每次完成，DOM/tab 回归，堆自然回落，零异常。
- **Windows 映射保护正行为记录**：`open(tags.db,"wb")`（截断语义）在服务器持有 mmap 时报 EINVAL（ERROR_USER_MAPPED_FILE 映射），`r+b` 可写——磁盘损坏注入改用原位覆写完成。

---

## 压力数据表

**表 1：攻击1v3 看门狗时间线摘录（死亡 A，PID 35244 全新实例）**

| 相对时刻 | 阶段 | poll 探针 | 服务器 handles | WS | 线程 |
|---|---|---|---|---|---|
| 0-15s | P0/P1 前 | 2-23ms OK | 249-257 | 66-67MB | 6-7 |
| 20s | P1（6 线程多库交替） | OK | 727 | 149MB | 11 |
| 25s | P1 | OK | 1231 | 238MB | 12 |
| 30s | P1 | OK | 1594 | 310MB | 12 |
| 36s | P1 | OK | 1887 | 362MB | 11 |
| 40s | P1 | OK | 2337 | 438MB | 12 |
| 45s | P2 开始 | OK | 2698 | 505MB | 11 |
| 48.3s | P2 | 最后 OK | — | — | — |
| 51.3s | P2 | FAIL（URLError） | — | — | — |
| 60.5s | — | **PROC GONE / 端口死** | — | — | — |

**表 2：最小化泄漏实验（attack_leak.py，PID 15760）**

| 步骤 | 请求形态 | handles | priv MB |
|---|---|---|---|
| 基线（预热后） | — | 264 | 58.0 |
| A：双库交替 ×200 | definition A/B 交替 | **668（+404）** | **128.2（+70）** |
| A：空闲 5s | — | 664 | 118.7 |
| B：对照单库 ×200 | definition 仅 fixture | 670（+6） | 128.6 |
| B：空闲 5s | — | 666 | 118.9 |
| C：reindex memory 一次 | 回收动作 | **252（-412）** | **65.4（-63）** |

**表 3：长跑 4 分钟采样摘录（attack5.py，单库 + 每 10s 切档）**

| 时刻 | WS | priv | handles | 备注 |
|---|---|---|---|---|
| 15s | 197MB | 190MB | 254 | sqlite 档 |
| 94s | 290MB | 277MB | 252 | memory 档 dict 峰 |
| 143s | 231MB | 221MB | 256 | readtags 档回落 |
| 237s | 228MB | 213MB | 254 | 收尾 |

codes：def 53 / scf 38 / symw 26 / refs 20 / status 27 / poll 23 全 200；切档 21 次（sqlite×6 / readtags×10 / memory×5）失败 0。

**表 4：攻击2 切档中途统计（attack2.py，3 查询线程 + 25 次三档循环，约 4 分钟）**

| 指标 | 值 |
|---|---|
| definition 成功 / 空 / 串线 / 错误 | 4279 / 0 / 0 / 0 |
| scope=file 成功 / 错误 | 2075 / 1 |
| reindex 成功 / 失败 | 21 / 4 |
| 失败构成 | meta.json replace WinError 5 ×2（D-2）；tags.db replace WinError 5 ×1、remove WinError 32 ×1（S37-3 同源） |
| tmp 残留 | tags.db.tmp 在建期出现/被下轮清理；meta.json.28308.tmp、meta.json.32168.tmp 终态残留 |

**表 5：前端 tab 开关 GC 甄别（attack7b.py，CDP HeapProfiler.collectGarbage）**

| 轮次（每轮 10 次开/关） | GC 后 usedJSHeap | 相对 baseline |
|---|---|---|
| baseline | 23.7MB | — |
| 1 | 34.2MB | +10.5MB |
| 2 | 40.5MB | +16.8MB |
| 3 | 46.1MB | +22.4MB |
| 4 | 51.5MB | +27.8MB |
| 5 | 57.2MB | +33.5MB |

（对照：错误路径 `closeConnection` 直调 edit tab = 3.1MB/10 次，5 倍泄漏；log-viewer 39.6MB×5 开关 = 回落，无泄漏。）

---

## 方法与清理说明

1. **fixture**：`.zcode/tmp/resdfx/proj`（350 .c + 40 .h，217,615 符号，经 `/api/nav/build` 建为 05bed852e01cbf89 库）；生成器与全部攻击脚本留存于 `.zcode/tmp/resdfx/scripts/`（gen_fixture.py / step_anchor / attack1 / attack1v3 / attack_leak / attack2-7 / watchdog.py / timeline.tsv）。
2. **根库纪律**：f93dd9f2b98437bd 全程只读查询；tags.db（110,833,664B）/tags（110,759,685B）/meta.json 与基线逐字节一致（backend=sqlite，sizes 无变化）；终态锚点全绿（def 566 / scf 213）。历史 corrupt.db 残留未触碰。
3. **清理**：fixture 库经 build(memory)→delete 两步彻底删除（第一步 delete 因 D-4 静默残留 tags.db，借 build 收尾 `_invalidate_cache` 解锁后二次删除成功，目录已不存在）；nav 数据区现存 4 库全部为历史/根库，无孤儿目录；大日志 resdfx_big.log 已删；自建 CDP target（resdfx_* ×4）已全部关闭，用户既有页面未触碰；fixture 源码目录已删（保留脚本与 timeline 证据）。
4. **环境事件记录**：测试期间 8867 服务器进程三次更替——36320（R35 验证期遗留实例，于攻击1 轰击中冻结 ~9 分钟后死亡）、35244（01:24:30 由并行审计组拉起，于攻击1v3 满载中死亡，全程看门狗记录）、15760（01:35:03 拉起，存活至今，终态 ws 250MB / handles 254 / threads 6）。两次死亡均发生在我的满载攻击窗口内，其中一次资源轨迹完整；并行审计组（caudit 系列）的活动与重启动作已如实记录于归因说明。无 WER 崩溃事件、无服务端 Traceback。
5. **归因诚实性声明**：死亡 B（36320）存在并行活动混杂（另一组测试/重启），其"冻结 9 分钟 + 回放 + 死亡"的完整机制无法纯黑盒定论；死亡 A（35244）从 66MB/249 句柄健康基线开始、资源爬升与死亡全程单变量记录（期间无其他已知负载），是 D-1 的主要证据。最小化实验（表 2）在独立窗口以 4 倍余量复核了泄漏因果。

---

*报告完 · D 组（健壮性/并发/资源）· 实锤 5（P1×1 / P3×3 / P4×1）+ 同源量化 1 + 观察项 4*
