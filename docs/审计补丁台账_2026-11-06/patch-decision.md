# 补丁应用决策书（patch-decision）

- 依据：doc/patch-apply-backend.md（16 件干跑）+ doc/patch-apply-frontend.md（12 件干跑）——两路均在 %TEMP% 副本上真实应用+语法验证+行为对照，源码零改动（SHA256 前后一致）
- 干跑结论：**28 件补丁值得应用，但不能照 patch-log 台账直接落码**——只有 11 件逐字节可用，其余需按干跑报告的合成终版/修正写法执行

---

## 一、总裁决：分四批应用

### 立即批（19 个单元，风险低收益高）

| 补丁 | 修什么 | 落码要点 |
|---|---|---|
| P-7 | meta.json 并发写失败+tmp 残留 | 台账逐字节可用 |
| P-3 | 重建静默降级 readtags+110MB tmp | 台账逐字节可用 |
| P-8 | 网络盘真删文件被吞 | 台账逐字节可用 |
| P-17 | 面板尺寸失真（存量库差 ~105MB） | 台账逐字节可用；**落码后对现有库做一次 reindex 回填** |
| P-19 | %/# 目录过滤静默失效 | 台账逐字节可用 |
| P-20 | docstring 误导 | 台账逐字节可用 |
| R2-13 | build tags replace 无重试 | 台账逐字节可用 |
| R2-11 | rebind 带句柄改名必败 | 按现状缩进落码 |
| P-2 | memory 档 prefix 大小写 | diff 8 空格→现状 12，按现状缩进 |
| P-9 | fsym 改键不落盘 | diff 0 缩进→现状 8，按现状缩进 |
| P-15 | 垃圾 root 启动真任务 | **不要按台账上下文**（误中 cg_delete）——在 build/reindex/delete 三端点 root 赋值后加 isabs 判断，置于空值判断后 |
| P-12 | fsym 过滤词被覆盖 | 按干跑报告重建版 |
| P-14 族 | 关 tab 误弹重读失败 | R3-4+R4-F2 双护栏按重建版 |
| P-16 | fsym 跳转不入历史 | Enter 分支 diff 需按 onclick 推导补 |
| P-24 | Ruby 显示错位 | 台账可用 |
| P-25 | hover 围栏（≥4 反引号） | 按 R7-2 形态（R3-1 原文对不上） |
| R4-F1 | 档位下拉第 4 失步出口 | 台账可用；**与 R7-1 同一改动只执行一次** |
| R2-3+P-5 | 弹窗遮挡+四出口复位 | CSS z 10001 + nav.js 复位；**两文件必须同批** |
| R2-3 附带+P-21 | emoji 清零五处 | settings.js:788/:1661 删 ⬇ + :1682 dotOff + update_server keycap/⬇ |

### 谨慎批（4 组，需带修正落码）

| 补丁 | 干跑发现的问题 | 修正 |
|---|---|---|
| **P-1（P1 级）** | 泄漏真根治（400 交替 +800 句柄→+4）但**锁内 close 卡全库 534ms** | close 移到锁外（干跑已实测 1-2ms）——用 patch-apply-backend.md 附录的修正合成版 |
| **P-18+P-4+R6-2（一组）** | ①硬依赖：P-4 先于 P-18 直接失败；R6-2 先于 P-4 静默丢②台账终版缺 `ql = q.lower()` 行（漏掉=中文前缀全 NameError）③两件单独落码 lookup_ci 运行时 TypeError | 用 patch-apply-backend.md 附录合成终版，**严格按 P-18→P-4→R6-2 序同批落码** |
| **P-10** | 注册行在终版链只以上下文出现过（漏掉=codegraph 恒 unknown） | 用干跑合成版（含 `_PROBES["codegraph"]` 注册行+契约注释改 (state, ver, detail)） |
| **P-22+P-11** | P-22：已记忆 makefile 的文件下拉显示空白；P-11/R2-4：c.meta 无判空（缺 meta 的 conn 会中断配色广播） | P-22 落码时顺手加"记忆值不在选项则回退自动"；R2-4 加 `c && c.meta &&` 判空 |

### 暂缓批（2 件，先修台账再落）

| 补丁 | 问题 |
|---|---|
| **P-23** | 台账版 `import shutil as _sh_which` 后当函数调——TypeError 被吞=补丁无效且部分机器回归。改 `from shutil import which as _sh_which` 一个词后干跑实测生效 |
| **P-13** | 台账只有 nav_index 层 diff，缺 api 层——外部锁文件时 delete 从静默 ok 变 500 HTML。需按 r1 建议补 api 层捕获（干跑实测补后返回 {ok:false}+重试删净） |

### 不执行清单（重复/已被取代）

- R7-1（=R4-F1 同一改动，重复执行会双插入且 node --check 查不出）
- P-5b 原段（R2-3 已覆盖）、P-21 原 settings 段（R3-5 已覆盖）
- R2-1/R3-1 原文（R7-2 形态取代）、R2-2 原文 closeHexTab 行（已删）

## 二、落码操作规范（干跑教训汇总）

1. **不要从 patch-log 台账直接 git apply**——28 件中仅 11 件逐字节可用。落码蓝本：
   - 后端：doc/patch-apply-backend.md 附录合成终版（%TEMP%\patch_apply_be\work\ 有完整应用后副本参照）
   - 前端：doc/patch-apply-frontend.md 附录统一 diff（已对真实仓库 `git apply --check` 通过）
2. **缩进必须按现状归位**（P-2/P-9/R2-11/P-13 四件照抄必 IndentationError）
3. **P-18→P-4→R6-2 严格此序**；R4-F1/R7-1 只执行一次
4. **落码后动作**：对现有 4 个库做一次 reindex（回填 P-17 尺寸）；readtags 档中文查询抽测（P-4 验证）
5. **回归锚点**：scope=file 213 条 / definition line=566 / references 3 条——落码前后必跑
6. **文档勘误**：⬇（U+2B07）Emoji_Presentation 实为 No（V8+canvas 双证）——audit-b:187 原豁免判定是对的，patch-log 中 R2-6/R3-6 相关勘误需反向更正；删 ⬇ 本身无害照落

## 三、干跑新发现的存量问题（不属于本批补丁，留档）

1. P-26 的四类 tab 侧栏本就分流 closeEditorTab——真正落 closeConnection 的 office/bitcalc 拦不到（office 的 pdf.js 资源泄漏面未覆盖）
2. .md tab 的 .ed-scroll 被 Monaco 完全覆盖，P-11 的 isMd 分支无可见效果（无害但无意义）
3. 存量 4 库 sizes 失真共 ~105MB（P-17 落码+reindex 即愈）
