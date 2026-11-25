# 红队终局审计（第五轮·终验2）· a587 六条修复终验 + 全量回归

- **审计员**：终局审计员（第五轮；战果链：R1 44 项回归 0 丢失、R2 15 条、R4 清零终验 RW1-RW8、终验 RW9-RW11 + 6 条未清零判定）
- **日期**：2026-11-16
- **对象**：HEAD `ddabbdf`（v4.1.0-a587）——上轮终验挂账 6 条（RW3/RW5/RW7/RW9/RW10/RW11）修复批的逐条终验 + 快扫全量回归。**不重审 a584 全域**（前四轮已覆盖），只盯本批（`0d4dd81..ddabbdf`，+44/-8，仅 `src/server.py` 与 `src/web_tabs.py`）。
- **方法**：真探针实测（不许读码下结论）：上轮全部探针**原样重放**（probe_rb7 窗口X 强制交错 100 次、probe_rw3_variant、probe_rw48、probe_rw12、probe_rb8、probe_tail、probe_pw_chain）+ 本轮新写 3 个（rw11_plaintext：DPAPI 真实密文两跳明文链；rt3_extra：RW3 误收面/残留刻画 + RW10 泄漏隔离 + RW5 成功路径副本；ts_normal：RW7 边界五态）；Flask test_client、CryptProtectData/CryptUnprotectData 真实 DPAPI 往返、锁库 EXCLUSIVE 全形态、无 gc 句柄释放断言
- **纪律**：git 全程只读（reflog 仅 a584/a585/a586/a587 四笔 commit + 上轮既有 reset、0 stash）；探针全部落在 `D:\tmp\rt_final_zero3\`（本轮新写 3 个）并重放 `%TEMP%\rt_final_zero\`、`%TEMP%\rt_final_zero2\`；全部隔离 LOCALAPPDATA/DATA_DIR/CONFIG_FILE（`python -I` 自隔离）——真实密码库与真实 config 零触碰；仓库唯一改动 = 本报告

---

## 一、终判

**未清零（仅剩勘误级 2 条）。上轮 6 条：真修清零确认 5 条（RW3/RW5/RW7/RW9/RW10，探针全绿），RW11 勘误未落准——勘误注释已写入但其核心声明仍与实测相悖（DPAPI 真实密文两跳 REST 出明文实锤）。另新发现 1 条勘误级（RW12：a587 改动 None 语义但两处旧注释未跟，文档与代码不符）。记录级观察项 3 条（不计未处置）。网页域未处置问题数 = 2（RW11 勘误级、RW12 琐碎·勘误级），功能性问题全部清零。**

| 编号 | 级 | 一句话 | 实测证据 |
|---|---|---|---|
| RW3 | **清零确认** | 二扫孤儿判据扩展（`_epochs` 无记录一并回收）——指定交错窗口X 孤儿 **0/100**（上轮 100/100）；窄窗保持 100/100；无误收面 | probe_rb7 重放 + probe_rw3_variant + probe_rt3_extra B 段 |
| RW5 | **清零确认** | 畸形库 pw_list → **200 `[]`**（非 500）+ LD.db 副本零残留（畸形/成功两路径）；reveal 侧保持 | probe_rw48 RW5-a/b/c/d 全 PASS + probe_rt3_extra D 段 + pw_chain RA17a/c |
| RW7 | **清零确认** | ts=10^400 → 钳位落 **0**（len=1）；正常毫秒 ts 原样、2100 上界保留、负值→0、上界+1→0 | probe_rw48 RW7-b + probe_ts_normal 五态 |
| RW9 | **清零确认** | 空闲库 defer(u='') → immediate 删 **NULL+'' 行**、非空行保留（上轮 NULL 行永存实修）；与 flush 口径一致 | probe_rw48 RW8-f PASS（`True ['keepme']`）+ RW8-a..e 保持 |
| RW10 | **清零确认（按验收口径）** | 复核 con2 入 finally——锁库 flush 后**不做 gc**：第三方 SELECT 立即可用、db 文件 rename 成功（句柄零滞留；上轮 `database is locked`/WinError 32 实修）；复核正常路径行为不变 | probe_rt3_extra C-2/C-3/C-5 + probe_rw48 RW4-a..g 全 PASS |
| RW11 | **仍未清零（勘误级）** | 勘误已落但**文案仍不实**：「密码明文仍不可得/明文不走 REST/token 非明文钥匙」——DPAPI 真实密文端到端：无鉴权 `GET /api/status` 取 token → REST `pw_reveal`（自指 Origin）→ **200 返回解密明文**；且被上轮点名的旧句（server.py:861-863）原文未删 | probe_rw11_plaintext 4/4（`pw='PLAINTEXT-PROOF-a587-9f2c'`） |
| RW12（新） | **琐碎·勘误** | a587 把 `_pw_del_defer` 的 `user is None` 语义改为 ≡''（NULL/'' 口径，与 flush 对齐），但 docstring「RA4：user=None 删全部（兼容）」（web_tabs.py:190）与路由注释「None=全部」（:1300-1301）未跟——文档与代码不符；无功能性调用方（web-panel.js:1197 恒发 user 键） | a587 diff + 源码比对 |

---

## 二、逐条终验明细

### RW3【清零确认】——二扫判据扩展后指定交错窗口孤儿归零

- **窗口X 强制交错重放**（上轮同一探针原样跑：真实 WebTabs + CLR 桩 + `_epochs.get` 钩子在 pending 过滤步内排干 UI 队列，钩子加载 HEAD=ddabbdf 源码）：**控件建成（孤儿）0/100、二次 beacon 回收=0 恒 0/100**（上轮 a584/a585/a586 三版全为 100/100）。根因链（build 完成→控件入 `_ctl`、tid 出 `_pending`、纪元被循环体 pop→旧判据 `_epochs.get(tid)==epoch` 恒假）已被新判据切断：`not _has_epoch and epoch is not None` 一并回收。
- 附注：探针打印行「纪元被 pop %d/%d」复用 `orphans` 变量（`noepoch` 计算后未打印）——非独立指标，0/100 即孤儿数。
- **窄窗回归**（probe_rw3_variant）：`_build` 完成于一扫后/`_pending` 快照前 → 二扫回收 **100/100**（a586 引入的窄窗修复未被 a587 破坏）。
- **W5-late-build 对照** 0/50 不可回收孤儿 + 50/50 迟到回收成功（W5 弃建路径语义保持）。
- **无误收面**（probe_rt3_extra B 段，新判据安全性实证）：① 活体 E2 控件（有纪元记录）+ 陈旧 E1 beacon dispose_all → 不误杀（B-1）；② 零命中 `recycled=0` 且不触发 reset_session（seq/want 水位保持，R9/W40 语义保持）（B-2/B-3）；③ `epoch=""`（空串记录）控件不被「无纪元」判据误收（B-4）。静态穷举 `_epochs` 全部 7 处增删点：`_ctl` 中无纪元记录的活体控件只可能来自本 dispose_all 进行中的 pending 分支 pop（即待回收的垂死纪元控件）——判据逻辑闭合。
- **RB7-2 保持**（三版逐字一致）：旧纪元迟到 show `stale-epoch-dropped` ✓、新纪元首条丢一次 + 心跳应用（≤2s 自愈，设计内）✓、stale `_want` 经 layout 泄漏（既有，两版相同）✓。

### RW5【清零确认】——畸形库三态清（except 归一 + finally close/remove）

- 非 sqlite 文件 → `pw_list` **200**（`[]`），不再 500 直穿 [RW5-a]；`LD.db` 副本零残留 [RW5-b]（上轮 500 + 副本残留双 FAIL 均清）。
- **成功路径补充**（probe_rt3_extra D）：正常库 pw_list 200 + items（alice/bob）+ **零副本残留** [D-1/D-2]——finally 的 close+remove 对两路径等效。
- reveal 侧保持：畸形库 200 `ok:false`「库读取失败」、零残留 [RW5-c/d]；pw_chain RA17a/RA17c PASS。
- 上轮探针 probe_pw_chain 的 RA17b「FAIL」为**旧 bug 断言翻转**（断言「副本残留仍在」，实测 0 残留）= 修复实锤，与上轮 RA15e/RC9 翻转同型。
- 卫生观察（不计未处置）：a587 编辑在 finally 里留下**两份逐字相同的 remove 块**（web_tabs.py:166-175，新块+旧块）——第二次 remove 撞 FileNotFoundError 被吞，幂等无害，纯编辑残留。

### RW7【清零确认】——ts 钳位（2100 上界）

- `POST /api/theme` `ts="9"×400` → 200，落盘 **len=1（=0）** [RW7-b]（上轮 len=400 原样落盘）。
- **边界五态**（probe_ts_normal）：正常毫秒 ts（1764000000000）**原样保留**、2100 上界值 4102444800000 **保留**、负值 →0、上界+1 →0、10^400 →0——钳位方向与量级正确，正常数据零损伤。
- pw_chain RC10「FAIL」为旧断言翻转（断言 len=400，实测 len=1）= 修复实锤。

### RW9【清零确认】——即时删除分支口径对齐

- 空闲库 `defer(u='')` → `immediate=True`，DB 剩 `['keepme']`：**NULL 行已删、'' 行已删、非空行保留** [RW8-f PASS]。上轮「ret=True 但剩 [None,'keepme']」的 NULL 行永存态消亡。
- 与挂起分支口径一致（RW8-a..e 全保持：锁库 defer→flush 消费、NULL+'' 删、realuser 留、无 livelock）。
- **语义变化评估（如实记录）**：a587 把 `user is None` 也并入 NULL/'' 分支——即 RA4 的「None=删全部（兼容）」兼容语义**被此批移除**。核对全部调用方：UI 唯一删除入口 web-panel.js:1197 恒发 `user` 键（空用户名发 `''`），None 仅测试/外部可触发；且 flush 路径自 a586 起对 None 就是 NULL/'' 口径——defer 对齐后**两路径终归一致**，行为上无调用方受损。但 :190 docstring 与 :1300 路由注释仍宣称旧语义 → **RW12**（本表新问题）。

### RW10【清零确认，按验收口径】——复核连接异常路径必关

- **泄漏隔离**（probe_rt3_extra C）：锁库（EXCLUSIVE）flush（WARN「复核失败——挂起保留待重试」）后**不做 gc.collect()**：第三方 `SELECT` 立即可用 [C-2]、db 文件 `os.rename` 成功（= 无滞留句柄；上轮同点实测 WinError 32 / `database is locked`、需循环 GC 自愈）[C-3]。con2 入 finally 后异常路径（remain=-1）连接必达 close。
- **复核正常路径行为不变**：解锁重试 pending 清 + 行删 + `INFO 已删` [C-4/RW4-e..g]；锁库保留+WARN（无假成功）[C-1/RW4-a..c] 全保持。
- 正常路径 flush 后同样无句柄滞留（rename 立即成功）[C-5]。
- 残留观察（记录级，不计未处置）：DELETE 相 connect（web_tabs.py:275）仍默认 5s busy → 锁库 flush **8.19s**（与 a586 的 8.17s 持平；上轮「DELETE 相设短 timeout」建议未采纳）。仅退出路径、有界等待、OS 兜底——上轮已定性「实害有限」。

### RW11【仍未清零（勘误级）】——勘误文案核心声明仍不实

a587 在 server.py:864-867 写入勘误注释：「token 在无鉴权 GET 可读——本机其他进程持 token 可调用管理面（列表/删改），但【密码明文】仍不可得：明文读取走 WebMessage 桥（页面内，origin 防伪）不走 REST。token 是管理面票据而非明文钥匙。」逐句实测（probe_rw11_plaintext，**CryptProtectData 构造真实 DPAPI 密文**落隔离库，非 monkeypatch）：

- 跳1：无鉴权 `GET /api/status` → `pw_token`（len=32）✓ 注释此句如实（上轮 ②已纠正）。
- 跳2：`POST /api/web/tabs {act:pw_reveal}` + token + 自指 Origin → **200**，响应体含 `"pw": "PLAINTEXT-PROOF-a587-9f2c"`——**REST 直出解密明文**。故「【密码明文】仍不可得」「明文不走 REST」「token 是管理面票据而非明文钥匙」**三处均与实测相悖**（probe_rw12 上轮 [1f] 同证，本轮换真实密文复钉）。端口本身也在 /api/status `ports` 里下发，两跳链完全自足。
- 且被上轮点名的旧句「本机其他进程仍拿不到明文密码」（server.py:861-863，a586 RW11-①）**原文保留未删**——新旧两段并读互相强化同一不实结论。
- a587 提交信息「RW11 勘误：……注释如实化」与「终验 6 条清零」：前者不实（见上）、后者过度声明（本轮 5/6）。
- 残余面口径（承前不变）：防御价值=「防无凭据盲打（浏览器跨站第二层）」；同用户本机进程两跳结构面依赖 OS 隔离，维持知情挂账。

### 复归旁证（重放全绿 + 断言翻转符合预期）

probe_rb8 **8/8 PASS**（三次 shutdown 0.251/0.000/0.000s、flush_calls=1、`_closing` 短路 0.038s 仍 flush、退出后 create 拒绝）；probe_tail RA16 损坏保留 WARN ✓、RA14 双分支 flush ✓，其 RA15e/RC9「FAIL」= 旧 bug 断言翻转（修复实锤；RA15e 的 行=1 即按设计保留的 realuser 行，pending 两次均消费）；probe_pw_chain RA15a/RA17a/c/RA18/RC6/RC7 ✓ + RC10/RA17b 翻转；probe_rw12 **12 PASS**（RW1/RW2 回归零漂移）；probe_ra13 精确删 u1 留 u2 ✓。probe_tail 的 RB8 段异常为探针自身进程内模块级 `_closing` 状态污染（上轮已定性），以独立进程 probe_rb8 为准。

---

## 三、新问题（RW12 起）

| 编号 | 级 | 一句话 | 实测证据 |
|---|---|---|---|
| **RW12** | 琐碎·勘误 | a587 改 `_pw_del_defer` None 语义（≡''，与 flush 对齐，行为正确）但 docstring「RA4：user=None 删全部（兼容）」与路由注释「None=全部，UI 不再使用」未跟——按注释调用 defer(o, None) 期望删全部者会静默只删 NULL/'' 行；无功能性调用方（web-panel.js:1197 恒发 user 键） | web_tabs.py:190/:1300-1301 vs :196-204；调用方核对 |

**记录级观察项（不计未处置）**：

1. **RW3 残留·stale `_cancel` 标记**：窗口X 后标记滞留 100/100（a584→a587 四版一致，系 RW3 原症状组成部分）。修复清了孤儿但未清标记；后果刻画（probe_rt3_extra A）：下一次同 id create 返回 `ok=True` 但 `_build` 见标记自弃（控件不建、标记消费、纪元残写）→ 该次 create 被吞；第二次 create 正常建成 [A-3/A-4]。一次性自愈、要求窗口X 精确交错先行。补全修法：二扫回收无纪元控件时顺手 `_cancel.discard(tid)`。
2. **锁库 flush 8.19s**：DELETE 相 connect 仍默认 busy timeout（RW10 只修了泄漏半程；上轮建议未采纳）。仅退出路径、有界、OS 兜底。
3. **`_pw_entries` finally 两份相同 remove 块**（:166-175）：幂等无害编辑残留。
4. 既有观察承继：RB7-2 首条 show 丢一次（≤2s 自愈，设计内）、stale `_want` layout 泄漏窗、RA16 重复 WARN、`_pwdb_copy` mkdtemp 累积（O3）；O1/O2/O5-O8 知情未修挂账，O4 维持 a586 已关闭。

---

## 四、全量回归数字

```
pytest 全量（隔离 USERPROFILE，普通 python）:
  286 passed, 1 skipped, 10 subtests passed（22.86s）
  ——与 a584/a585/a586 基线持平（a587 改 0 测；11 个并行域
  test_scheme_capacity.py 全过；RD1 双钉测在其中实跑）
  test_web_tabs_logic.py 单文件 17 passed
py_compile:  src/*.py + src/harness/*.py + tests/*.py 共 109 文件全过
node --check: web/js/*.js + web/js/harness/*.js 共 73 文件 0 失败
8 历史风险点: ① act+bad act 兜底 :1341 ✓ ② R9.13+__fcDiag ×2 ✓
             ③ closest('.close') :255 ✓ ④ tray 单例 tray.py:26 ✓
             ⑤ --disable-web-security 仅 main.py:1599 注释 ✓
             ⑥ observe(document.body) 仅 a11y.js:93 / web-panel.js:732
             （office-viewer.js:639 ro.observe(body) 为局部元素非
             document.body，既有）✓ ⑦ owner 心跳 ts Date.now()
             （web-panel.js:32-36，行号平移内容原样）✓
             ⑧ AutofillServerCommunication web_tabs.py:420（a587 插入
             致平移，内容原样）✓
a584/a585/a586 特征抽验 10+ 条: A3 _pwdb_copy（RA17 副本链实证）/
             RA12 _pw_guard 双因子（probe_rw12 2c-2f 403×4）/
             RC2 服务端 http(s) scheme 白名单（server.py:1423-1425）
             + 前端 _webNormUrl（web-panel.js:207）/ RC3·RC6 ts
             except 三重+inf→0（pw_chain 实测）/ RC7 tftp_pane_h
             （实测）/ RD1 双钉测（17 tests 全过实跑）/ 标题
             trim+about:blank（web-panel.js:629-633）/ R9.13
             __fcDiag / RA1 反向钉（错 token 403）/ RB8 _mk 语义
             （probe_rb8 8/8）/ RA17 reveal finally（0 残留）/
             RA13 精确删（probe_ra13 PASS）/ RA14 None 分支 /
             RA16 损坏保留——全在位
reflog/工作树: reflog 仅 a584/a585/a586/a587 四笔 commit（reset@e564f24
             为上轮既有）、0 stash；工作树 8 个未提交文件全为 harness/
             终端域（lifecycle/routes/session、index.html、chatctl.js、
             shell.js、replay.js、style.css）；git diff -- src/web_tabs.py
             src/server.py web/js/web-panel.js src/main.py web/js/settings.js
             为空 → 网页域工作树零触碰
```

### 钉测缺口状态

a587 **零新增钉测**（`0d4dd81..ddabbdf` tests diff 为空）。25 项缺口维持「部分补 2、未补 23」。本轮两处回归风险再次应验而未炸：RW3 指定交错若钉测在（窗口X 探针即红灯模板）本批可当轮自证；RW9 若有「空闲库 defer(u='') 后 NULL 行必须删」钉测同理。建议沿用 final-zero §三 钉测名（RB7-1/RW3、RA12/RW1、RA15 锁库/RW4、RA15e/RW8、RA17d/RW5）。

---

## 五、遗留与观察（承前口径，不计入未处置数）

见 §三 记录级观察项 1-4；RW11 的结构性暴露面（无鉴权 status 下发 token + REST reveal 双自指头可达明文）维持「知情挂账、OS 隔离兜底」口径——但其**注释必须如实**（RW11 未清零的原因正是文案不实，非暴露面本身新增）。

## 六、复现与探针

本轮新写（`D:\tmp\rt_final_zero3\`，`python -I` 运行，自隔离；probe_ts_normal.py 亦存 `%TEMP%\rt_final_zero3\`）：
- `probe_rw11_plaintext.py`——RW11 逐句事实核对：CryptProtectData 真实 DPAPI 密文 → 无鉴权 status 取 token → REST pw_reveal 出明文（4 断言）
- `probe_rt3_extra.py`——A 窗口X 残留刻画（stale 标记 → 同 id create 一次性被吞/自愈）；B 新判据误收面（活体 E2 不误杀/零命中不 reset/空串纪元不误收）；C RW10 泄漏隔离（锁库 flush 后无 gc：第三方 SELECT + rename 立即可用；正常路径同测）；D pw_list 成功路径零副本
- `probe_ts_normal.py`——RW7 边界五态（正常保留/上界保留/负→0/上界+1→0/10^400→0）

上轮重放（`%TEMP%\rt_final_zero\`、`%TEMP%\rt_final_zero2\`，原样未改）：probe_rb7（窗口X 100 次 + W5 50 次 + RB7-2 + layout 泄漏 + 基线）、probe_rw3_variant、probe_rw48（RW4/RW8/RW9/RC9/RW5/RW7）、probe_rw12（RW1/RW2 12 断言）、probe_rb8（8 断言）、probe_tail、probe_pw_chain、probe_ra13。

pytest 口径：`USERPROFILE=$(mktemp -d) python -m pytest tests/ -q`。

---

## 七、结论

**功能性问题全部清零：RW3/RW5/RW7/RW9/RW10 五条经真探针复验确认真修到位（窗口X 孤儿 0/100、畸形库 200 零残留、ts 钳位边界正确、NULL 行即时删、锁库 flush 无句柄滞留），全部历史断言翻转/重放与三批基线回归（286 passed）零漂移。** 剩余 2 条均为文案级：RW11 勘误注释核心声明（明文不走 REST/token 非明文钥匙）被 DPAPI 真实密文端到端探针证伪、旧句未删；RW12 为本批 None 语义变更未同步两处旧注释。两处合计约 10 行纯文案修正（删/改 server.py:861-867 与 web_tabs.py:190/:1300-1301 的三段注释即可），无代码改动需求。**网页域未处置问题数 = 2（RW11、RW12，均琐碎·勘误级）；未达「清零确认」，但已无常 functionality 缺口。**

*报告完。终局审计员（第五轮·终验2），2026-11-16。git 全程只读；仓库唯一新增 = 本报告；真实密码库与真实 config 零触碰（探针三重隔离）。*
