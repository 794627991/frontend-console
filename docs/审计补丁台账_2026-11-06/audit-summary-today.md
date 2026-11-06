# 今日全量代码审计汇总（audit-summary-today）

- 审计对象：`git diff 8251c58..HEAD`（33 提交 / 36 文件 / +1873−314，a372→a392 主线 + 并行修复线）
- 审计方式：四路并行——A 白盒后端 / B 白盒前端 / C 黑盒功能攻击 / D 黑盒健壮性（并发/资源/长跑）
- 四份分报告：`doc/audit-a-backend.md`（S37-1~12）、`doc/audit-b-frontend.md`（S-B1~9）、`doc/audit-c-blackbox-func.md`（C-1~2）、`doc/audit-d-resilience.md`（D-1~5）
- 关联台账：R28-R35 对抗审查（全部闭环）`.zcode/tmp/audit_round3*.md`
- 补丁台账：`doc/patch-log.md`（全部 28 件的文档形式补丁提案，待审计循环）

---

## 一、实锤汇总（28 件，去重后）

| # | 级 | 主题 | 组/编号 | 位置 |
|---|---|---|---|---|
| 1 | **P1** | _tagdb_orphans 单槽缓存孤儿连接无界泄漏——多库交替查询每次 +2 句柄/+0.35MB，满载 60s 服务器进程静默死亡（两次复现，无 Traceback/无自动重启） | D-1 | nav_index.py:905-936 |
| 2 | P2 | memory 档 prefix 大小写敏感回归——小库混合名前缀命中丢失（R35-1 只修了 sqlite 档） | S37-1 | nav_index.py:845-848 |
| 3 | P2 | build 阶段 4 sqlite 无前置 _close_tagdb——重建"成功"却静默降级 readtags + tags.db.tmp 残留（a392 只修了 reindex） | S37-2 | nav_api.py:103-105 + nav_index.py:555-671 |
| 4 | P2 | readtags 档中文符号全灭（definition/symbols 三级恒空；memory/sqlite 同查询命中——readtags.exe 链路 UTF-8 失明） | C-1 | nav_index.py readtags 链路 |
| 5 | P2 | 档位确认弹窗被索引面板遮挡（modal z=200 < 面板 z=9999）——切档核心交互不可达、下拉显示与库实际脱节 | C-2 | nav.js:877 + web/index.html z-chain |
| 6 | P3 | db 操作窗口期 TOCTOU：reindex/build 进行中并发查询重开连接——a392 前置关连接只封起始时刻（黑盒量化：25 次切档撞 2 次 WinError 5/32） | S37-3/D-同源 | nav_api.py:214-228 |
| 7 | P3 | reindex 末步 meta.json replace 撞并发读者（list_libs 每次读全库 meta）——9.5% 失败率 + tmp 残留 | D-2 | nav_api.py:232 + nav_index.py:1037 |
| 8 | P3 | 网络盘 `!`（missing）无条件隐藏——真实删除文件在 SVN 面板消失、symlink_hidden 虚计（假阴性比假阳性更危险） | S37-4 | vcs.py:396-399 |
| 9 | P3 | nav_keys POST 白名单漏 fsym 且整字典覆盖——设置页 fsym 改键永不落盘、刷新静默还原 | S37-5 | server.py:1476/1505 |
| 10 | P3 | codegraph 未注册 res_boot.MANIFEST——外部依赖面板无此项，错误文案指向死路 | S37-6 | res_boot.py:43-66 |
| 11 | P3 | 档位下拉「确认取消」两连坏：下拉不回弹（显示已切、库未切）+ _renderState 重渲染写进脱离 DOM 死节点 | S-B1 | nav.js:877/:818 |
| 12 | P3 | md-pv 预览配色泄漏到全部编辑器形态 .ed-scroll——代码/文本 tab 背景被染色、新旧 tab 不一致 | S-B2 | editor.js:1885 + style.css:5229 |
| 13 | P3 | ed-lang 下拉 Makefile 死选项（vendored Monaco 无 makefile 语言注册）——选了=无高亮与纯文本不可区分 | S-B3 | editor.js:140 + monaco-bridge.js:22 |
| 14 | P3 | fsym 面板首拉期间输入的过滤词被全量结果覆盖（时序竞态：input 对空 _full 过滤，resolve 无条件全量 render） | S-B4 | nav.js:396-419 |
| 15 | P3 | 前端 tab 开/关慢泄漏（真实关闭路径 closeEditorTab 已 dispose 仍 +5.8MB/10 次线性不回落） | D-3 | editor.js closeEditorTab 链 |
| 16 | P3 | /api/nav/delete 对锁定文件 rmtree(ignore_errors) 静默失败仍 ok:true——45MB tags.db 永久残留且不可再删 | D-4 | nav_index.py:202-207 |
| 17 | P4 | readtags 后端参数注入——`-` 开头查询被当 ACTION（-l 全库列举进内存+CPU 尖峰） | S37-7 | nav_index.py:763 |
| 18 | P4 | _svn_symlink_paths sqlite URI 未编码——`%`/`#` 目录名下过滤静默失效（SMB 误报回涌无日志） | S37-8 | vcs.py:184 |
| 19 | P4 | reindex 不更新 meta.sizes.db——面板尺寸双方向失真（虚高 95MB+/虚低 1.2GB） | S37-9 | nav_api.py:229-233 |
| 20 | P4 | _register_codegraph_mcp docstring 与实现矛盾（自愈覆盖语义/双前提未同步，用户自定义条目被静默重置无提示） | S37-10 | claude_default.py:353-358 |
| 21 | P4 | update_server emoji 铁律残留（⬇×2 + keycap 1️⃣2️⃣3️⃣×3） | S37-11 | update_server.py:807-1025 |
| 22 | P4 | npm root -g 探测 Windows 恒失败（list 形态不解析 .cmd 且无 npm.exe）——自定义前缀兜底死分支 | S37-12 | build.py:288/341 |
| 23 | P4 | shebang ruby 探测结果下拉无选项——显示「自动」实际 ruby 高亮（显示错位） | S-B5 | monaco-bridge.js:56 |
| 24 | P4 | 分发服务「未运行」残留 ⚪ 彩色 emoji（a373 漏改，运行侧已换 SVG） | S-B6 | settings.js:1682 |
| 25 | P4 | _edJumpFresh 无 tab 存活护栏——跳转窗口内关 tab → disposed editor setValue 抛错误弹「重读失败」 | S-B7 | editor.js:1236-1251 |
| 26 | P4 | hover 四反引号围栏对 ≥4 连反引号行仍可闭合（CommonMark 闭合栏 ≥ 开栏长度） | S-B8 | nav.js:633-636 |
| 27 | P4 | fsym 面板跳转不入导航历史（与 Ctrl+T 行为不一致，VSCode 计入） | S-B9 | nav.js:380/416 |
| 28 | P4 | _guard 放行类型混淆 root（root=123/{} /True 经 abspath 以 CWD 解析落回登记根）→ 垃圾 build 任务真实启动 | D-5 | nav_api.py:75-83 |

**分级统计**：P1×1 / P2×5 / P3×10 / P4×12。

---

## 二、主题聚类（修复面协同）

1. **_tagdb 连接生命周期族**（#1 D-1 P1 + #3 S37-2 + #6 S37-3 + #7 D-2 + #16 D-4）：单槽缓存+孤儿列表是根因。推荐结构性修复——**缓存改按 ld 键的多槽 dict（每库常驻一连接）+ 删孤儿路径 + _close_tagdb 保留给 delete/重建**；一并消除 #1 泄漏、#3 窗口期重开、#16 删除锁死三个面；#7 meta.json replace 加 2-3 次短退避重试；#3 加 _build_tag_db 失败重试。
2. **readtags 档健壮性族**（#4 C-1 + #17 S37-7）：中文符号失明（C-1 根因需白盒定位：CreateProcessW 参数编码/`-e` 输出解码）+ argv 注入（`-` 转义）。
3. **档位下拉交互族**（#5 C-2 + #11 S-B1 + #19 S37-9）：弹窗 z-index 提升到 10000+、取消分支改 bkSel.value 复位（替代失效的 _renderState）、reindex 补 sizes.db。
4. **memory 档口径族**（#2 S37-1）：prefix 加 lower（一行）。
5. **前端泄漏/竞态族**（#15 D-3 + #14 S-B4 + #25 S-B7）：D-3 需 heap snapshot 白盒定位（补丁先给防御性一行：closeConnection 对 edit:* 转发 closeEditorTab）。
6. **配置/注册完整性族**（#9 S37-5 + #10 S37-6 + #23 S-B5）：三处白名单/清单补项，各一行到三行。
7. **文案/展示族**（#21 S37-11 + #24 S-B6 + #13 S-B3 + #20 S37-10）：emoji 三处+docstring+Makefile 选项。
8. **防护加固族**（#8 S37-4 + #18 S37-8 + #22 S37-12 + #26 S-B8 + #27 S-B9 + #28 D-5）：各一行到三行的防御性修复。

---

## 三、存疑区（四组合计 29 条，不计实锤）

- A 组存疑 9 条（清场锁定残留窗/_open_tags 降级无尺寸守卫/Hover 摘要整读/codegraph 复制无进度/os.stat junction 面/LIKE 子串误匹配/noqa. 笔误/双检返回他 key db/scan_max 补扫阻塞）
- B 组存疑 10 条（fsym 分支缺 return/navJumpTo 死分支/matchKey metaKey/_normPath UNC 大小写/lang-override 无上限/_hoverCache 全清/proxy-panel 前导空格/bit-calc 尾冒号/_edJumpFresh stat 往返/_tvScrollToPath 并发 tick）
- D 组观察 4 条（tags 缺失时 references 域过滤失效/损坏 db 回退档 1.3-2.8s/满载双峰延迟指纹/环境历史残留）
- C 组观察 4 条（跳转键焦点依赖/model URI 盘符小写/readtags scope=file 时延/共享服务器静默死亡×2 归因）

详见各分组报告。观察项不进补丁循环，修复实锤时顺带可低成本收口的已在 patch-log 标注。

---

## 四、通过清单（打了什么没炸什么——要点）

- **无 P0**；无 XSS/SQL 注入/命令注入（readtags flag 注入除外，无 shell）；根库全程只读零污染（四组纪律遵守）
- 并发 6200+ 请求零串线/零半写读取/零空结果误报；任务槽互斥守住；异常注入全优雅
- 磁盘破坏四态全 200 优雅降级（S35-4 修复黑盒成立）；单库内存压力与 4 分钟长跑平稳
- UI 跳转全链（F12/Ctrl+Click/Shift+F12 生成文件过滤/中文+空格路径）、Ctrl+Shift+O 全项、Hover 三类 token、vendor cpp/shell 补丁、fcpk-plus 主题、导航历史栈——全部真机通过
- R28-R35 已闭环实锤在四组复验面零回归

## 五、方法学说明

- A/B 白盒逐提交归因+全文精读；C/D 黑盒真机攻击（fixture 自建自清、根库只读、断言式清理）
- 环境事件：C/D 两组并发压测同一 8867 致服务器三次更替（两组各自重启），两组压测结论存在交叉污染可能——D-1 的最小化实验（单变量四段证据链）不受影响；C 组的"切档并发零错误"在干扰期测得，置信度打折
- 本汇总与 patch-log.md 为纯文档，未修改任何工具源码

## 六、修复优先级建议

1. **立即**（P1）：#1 多槽缓存重构（治本，连带收口 #3/#16 部分）
2. **高**（P2）：#2/#3（切档正确性）、#4（中文工程 readtags 不可用）、#5（档位交互不可达）
3. **中**（P3）：#6-#16 按"用户可见面"排序——#8/#9/#11/#14 先（数据丢失/静默错误类）
4. **低**（P4）：#17-#28 顺手批处理
