# 红队终局审计（第五轮·终验）· a586 修复验证 + 全量回归

- **审计员**：终局审计员（第五轮；战果链：R1 44 项回归 0 丢失、R2 15 条、R4 清零终验 RW1-RW8）
- **日期**：2026-11-16
- **对象**：HEAD `0d4dd81`（v4.1.0-a586）——上轮 RW1-RW8 修复批的逐条终验 + 全量回归
- **方法**：探针实测（不许读码下结论）：上轮全部探针原样重放 + 本轮新写 3 个（RW1/RW2 端到端、RW3 覆盖窗口刻画、RW4/RW8/RC9/RW5/RW7 合探针）；Flask test_client 40+ 断言、真实 WebTabs+CLR 桩强制交错 100 次矩阵（含 a584/a585/a586 三版对照）、锁库/畸形库/lone-surrogate/os.replace 失败全形态
- **纪律**：仓库零改动（本报告除外）；git 只读（reflog 仅 a584/a585/a586 三笔、0 stash）；探针全部落在 `%TEMP%\rt_final_zero2\`（本轮新写）与 `%TEMP%\rt_final_zero\`（上轮重放）；全部隔离 LOCALAPPDATA/DATA_DIR/CONFIG_FILE——真实密码库零触碰

---

## 一、终判

**未清零。上轮 RW1-RW8：真修确认 5 条（RW1/RW2/RW4/RW6=RC9/RW8），仍未清零 3 条（RW3 部分改善但指定交错仍 100/100、RW5 未处置、RW7 未处置）；RB7-2/RB8 复归确认保持。另新发现 3 条（RW9 中、RW10 低、RW11 琐碎·勘误）。网页域未处置问题数 = 6（RW3/RW5/RW7 + RW9/RW10/RW11），终验不通过。**

| 编号 | 级 | 一句话 | 实测证据 |
|---|---|---|---|
| RW1 | **清零确认** | token 经 /api/status 下发，前端取用链端到端通 | probe_rw12 [1a-1f] 全 PASS |
| RW2 | **清零确认**（按验收口径） | GET /api/theme 不含 pw_token；guard 四向负例全 403 | probe_rw12 [2a-2f] 全 PASS；残余面→RW11 |
| RW3 | **仍未清零（部分改善）** | 双扫对指定交错仍 no-op：窗口X 100/100 孤儿（a584/a585/a586 三版全同）；新覆盖「_pending 快照前完成」窄窗（0/100→100/100） | probe_rb7 重放 + probe_rw3_variant 三版对照 |
| RW4 | **清零确认** | 锁库 flush：pending 保留、行未删、WARN「复核失败——挂起保留待重试」；解锁重试成功 | probe_rw48 RW4-a..g 全 PASS；耗时 14.65s→8.17s |
| RW5 | **仍未清零** | 畸形库 pw_list 裸 **500**（a586 未触碰 `_pw_entries`）+ LD.db 副本残留（句柄锁至循环 GC）；reveal 侧保持已修 | probe_rw48 RW5-a/b FAIL、c/d 的 c PASS；probe_pw_chain RA17d 同证 |
| RW6（RC9） | **清零确认** | 挂起写失败 .tmp 不残留（surrogate 编码崩 + os.replace 失败两形态） | probe_rw48 RC9-a/c PASS |
| RW7（RC10） | **仍未清零** | ts 无钳位：400 位巨整数原样落 config.json（len=400） | probe_rw48 RW7-b FAIL；probe_pw_chain RC10 同证 |
| RW8 | **清零确认**（按验收口径） | 空串 user defer→pending→flush 全链通：pending 消费、NULL+'' 行删、非空行保留、无 livelock | probe_rw48 RW8-a..e 全 PASS；即时路径残留→RW9 |
| RB7-2 | **清零保持** | 旧纪元迟到 show 丢弃（stale-epoch-dropped）；新纪元首条自丢一次+下条心跳应用（≤2s 自愈窗，与 a585 逐字同） | probe_rb7 RB7-2 段三版一致 |
| RB8 | **清零保持** | 三次 shutdown 0.223/0.000/0.000s、flush_calls=1；_closing 短路不睡但仍 flush；退出后 create 拒绝 | probe_rb8 8/8 PASS |

---

## 二、逐条终验明细

### RW1【清零确认】——token 通道迁移端到端通

- `GET /api/status` 含 `pw_token` 键且 **== 模块级 PW_TOKEN**（len=32，同链一致）[1a/1b]。
- `pw_list` 无 token → **403** [1c]；用 **/api/status 下发的 token** + 同源自指 Origin → **200** + items（alice/bob）[1d/1e]；`pw_reveal` 同链 200 [1f]——UI boot 的真实取用链 HTTP 层全通。
- 前端接线静态复核：web-panel.js:1123 `__fcPwToken` ← :1150-1152 `fetch('/api/status')` 取 `j.pw_token` → :1157 请求头 `X-FC-Token`。三段齐备（a585 已布，a586 服务端补齐）。
- 观察回归护栏：pw 路由前置的 get_tabs() 未装配短路（200「控件管理器未装配」）在 guard 之前——探针须 `wt._tabs` 装配后才能测到 guard（首轮探针假阴性已排除）；另有更前置的无鉴权 Origin 检查（403 forbidden origin）先于二者。

### RW2【清零确认，按验收口径】——theme 暴露通道关闭

- `GET /api/theme` 响应**不含 pw_token** [2a]，全响应文本亦无 token 值 [2b]。
- guard 四向负例全 403：错 token [2c]、自指 Origin 无 token [2d]、对 token 无 Origin [2e]、对 token 异源 Origin [2f]。
- **残余面（如实记录，并入 RW11）**：token 现由无鉴权 `GET /api/status` 下发——本机进程两跳（GET /api/status → pw_list/pw_reveal 双自指头）的结构性等价面仍在（探针 [观察] 行实测 token 可取）。防御价值维持上轮口径：「防无凭据盲打（浏览器跨站第二层）」，对同用户本机进程依赖 OS 隔离。a586 注释「本机其他进程仍拿不到明文密码」**与实测不符**（[1f] 即 status token → reveal 200 出明文链）。

### RW3【仍未清零】——双扫对指定交错仍 no-op（第三轮修复尝试）

上轮强制交错探针**原样重放**（真实 WebTabs + CLR 桩 + `_epochs.get` 钩子在 dispose_all 过滤步内排干 UI 队列；钩子加载的是 HEAD=a586 的 `src/web_tabs.py`，工作树网页域零触碰）：

| 指标 | a584 | a585 | **a586** |
|---|---|---|---|
| 窗口X 控件建成（孤儿） | 100/100 | 100/100 | **100/100** |
| 纪元被 pop | 100/100 | 100/100 | 100/100 |
| 滞留 cancel 标记 | 100/100 | 100/100 | 100/100 |
| 二次 beacon 回收=0 | 100/100 | 100/100 | **100/100** |
| W5-late-build 孤儿 | 50/50 | 50/50 | 50/50（既有 W5 窗口，非本批引入） |

根因（探针时序逐步验证）：钩子排水发生在 **pending 过滤步的 `_epochs.get` 内**——`_build` 在此刻完成（控件入 `_ctl`、finally 把 tid 移出 `_pending`、纪元**未** pop，因 `_cancel` 标记尚未写入）→ 过滤步返回 True → **循环体随后 `_cancel.add` + `_epochs.pop`** → 二扫的 `_epochs.get(tid)==epoch` 判 None≠E1 → 跳过 → 孤儿+滞留标记+纪元已 pop，二次 beacon 永不回收。**即：在修复自己声称的窗口（「第一扫与 _pending 取消之间完成的 _build」）内，二扫的纪元判据被同一循环体的 pop 污染而恒假。**

修复确有实效的窄窗（公平刻画，probe_rw3_variant，诱饵控件使排水落在一扫内）：`_build` 在「一扫之后、`_pending` 快照之前」完成时——build finally 先把 tid 移出 `_pending`，pending 循环不接管、不 pop 纪元 → **二扫回收 100/100（a585/a584 均 0/100）**。真实并发三态：A 完成于快照前→二扫收（新修✓）；B 完成于快照后/过滤中→cancel+pop 在 build 后→二扫盲（**本轮 100/100 实锤**，且此态真实可达——create 先于 pagehide 排队，UI 线程随时可插队）；C cancel 先写→build 自弃（a584 W5✓）。

**结论：RW3 部分改善、指定验收场景未清零。B2 轮即给出的有效修法（弃建/回收判据改纪元归属校验，而非 `_cancel` 成员+pop）仍是最小正解；当前结构下任何「扫后再验纪元」的修法都会被 pop 毒化。**

### RW4【清零确认】——复核失败保留挂起（假成功关闭）

锁库场景（EXCLUSIVE 持锁 + flush）实测：pending 文件**保留** [4a]、行未删（locker 视角=1）[4b]、日志 **`WARN pw_del_flush: 复核失败——挂起保留待重试`**（无 INFO 假成功）[4c]；解锁后重试：pending 清 [4e]、行删 [4f]、`INFO pw_del_flush: 1 条已删` [4g]。

- 耗时 8.17s（上轮 14.65s）：复核相 connect 已 `timeout=0.3`，但 **DELETE 相 connect 仍默认 5s busy**——退出路径延迟放大收敛一半，未到「设短 timeout」的建议值（并入 RW10）。
- 新卫生问题（并入 RW10）：复核异常路径 `con2.close()` 仍在 try 内未达 → 连接经 traceback 环引用滞留至**循环 GC**；泄漏窗内第三方连接 SELECT 实测 `database is locked`（probe_pw_chain RA15b 段 crash 实锤）、`os.remove(Login Data)` 实测 WinError 32；`gc.collect()` 后自愈。仅退出路径调用、进程退出 OS 兜底——实害有限。

### RW5【仍未清零】——pw_list 畸形库裸 500 + 副本残留（未处置）

非 sqlite 文件 → `pw_list` **500**（traceback：`sqlite3.DatabaseError: file is not a database` 于 `_pw_entries` :151 直穿 Flask）+ `LD.db` 副本残留（con 未 close → finally 的 remove 撞句柄锁被吞）[RW5-a/b FAIL]。`_pw_entries`（try/finally 无 except、close 在 try 内）与 a585 逐字相同——**a586 未触碰**。reveal 侧保持已修：畸形库 200 `ok:false`「库读取失败」、干净基线 0 副本残留 [RW5-c PASS；RW5-d 的 1 残留即 pw_list 泄漏的同一份，非 reveal 新增]。

### RW6/RC9【清零确认】——挂起 .tmp 原子写失败清理

两形态实测均 0 残留：lone surrogate → `json.dump` UnicodeEncodeError 中断 → except `os.remove(tmp)` → 无 `.tmp` [RC9-a]；monkeypatch `os.replace` 抛 OSError → 同样无 `.tmp` [RC9-c]；主挂起文件不受半截污染（合法 JSON 或不存在）[RC9-b]。

### RW7/RC10【仍未清零】——ts 无钳位（未处置）

`POST /api/theme` `web_favs[].ts="9"×400` → 200，config.json 落盘 `len(ts)=400` 原样 [RW7-b FAIL]；`_web_favs_clean` 的 `int()` 仅除 500（TypeError/ValueError/OverflowError→0），无位数/量级钳制——与 a585 逐字相同，a586 未触碰。方向安全（100 条上限）但与「钳位」声明不符，勘误级维持挂账。

### RW8【清零确认，按验收口径】——空串 user livelock 关闭

锁库 defer(u='') → 挂起落盘（immediate=False）[8a]；解锁后 flush：**pending 消费**（`1 条已删`，不再 WARN 滞留）[8b]、**NULL 行删** [8c]、**'' 行删** [8d]、**非空 realuser 行保留**（复核与 DELETE 同口径后不误删）[8e]。上轮 probe_tail 的 RA15e 反向钉（断言「永久滞留」旧 bug）重放翻转——两次 flush 均 consumed，确证 livelock 死亡。

**残留（新发现 RW9）**：库空闲时的**即时删除分支**（`_pw_del_defer` 直删相）未同步 RW8 口径——仍按 `username_value=''` 精确匹配 → NULL 行不删 [RW8-f FAIL：ret=True 但剩 `[None,'keepme']`]。后果：无用户名站点的条目（pw_list 显示 user=''）在库空闲时「点了删不掉」（NULL 行永存、列表复现）；仅锁库退出链被修正。**a586 半修。**

### RB7-2【清零保持】/ RB8【清零保持】

- RB7-2（probe_rb7 三版一致）：旧纪元迟到 show → `{"stale-epoch-dropped": true}` 意图丢弃 ✓；新纪元自己的首条 show 被丢一次（`_want_epoch` 已被迟到 E1 翻走）→ 下一条心跳（E2, sq=7）应用、Visible 终态正确 ✓（≤2s 恒发自愈，上轮已挂设计内观察）；stale `_want` 经 layout 泄漏窗两版相同（既有）。a586 未触碰 show/epoch 代码，语义零漂移。
- RB8（probe_rb8 8/8）：三次 shutdown（grace=200ms）0.223/0.000/0.000s、flush_calls=1；`_closing=True` 并发短路 0.024s 不睡但仍 flush；shutdown 后 `_tabs=None`、REST create「控件管理器未装配」。

### 真修回归旁证（probe_tail/probe_pw_chain/干净进程复验）

RA13 精确删 u1 留 u2 ✓、RA14 `_tabs=None` 分支 flush（0.018s 清账）✓、RA16 损坏 pending WARN+保留 ✓、RA18 defer 失败句柄立释 ✓、RC6/RC7 inf 落 0 不 500 ✓、RD1 双钉测唯一定义且实跑 ✓。probe_tail 的 RB8 段异常为本进程内早先 shutdown 的模块级 `_closing` 状态污染（探针自身），以独立进程 probe_rb8 为准。

---

## 三、新问题（RW9 起）

| 编号 | 级 | 一句话 | 实测证据 |
|---|---|---|---|
| **RW9** | 中 | RW8 半修：`_pw_del_defer` 即时删除分支未同步「''≡NULL」口径——库空闲时空用户名条目删除无效（NULL 行永存、pw_list 反复复现）；挂起链已通、即时链错位 | probe_rw48 RW8-f：defer(u='') 返回 True（立即生效）但 DB 剩 `[None,'keepme']` |
| **RW10** | 低 | 复核 `con2` 异常路径不 close（close 在 try 内）→ 锁库 flush 后连接经 traceback 环滞留至循环 GC：泄漏窗内第三方 SELECT `database is locked`（probe_pw_chain crash 实锤）、`os.remove` WinError 32（gc.collect 后自愈）；同函数 DELETE 相 connect 仍默认 5s busy → 锁库 flush 8.17s（14.65s 改善半程，退出延迟未达「短 timeout」建议） | probe_rw48 RW4-d + 泄漏隔离脚本 + probe_pw_chain RA15b |
| **RW11** | 琐碎·勘误 | a586 声明三处与实测不符：①注释「本机其他进程仍拿不到明文密码」——status token → pw_reveal 双自指头 200 出明文（probe_rw12 [1f] 即反例）；②token 结构性暴露面由 /api/theme **平移**到 /api/status（同为无鉴权 GET），非消除；③「前端 fetch 同步改」实为 a585 已布（a586 前端仅 ：631 标题条件去重一行） | probe_rw12 [1f]/[观察] 行 + a586 diff |

另：a586 顺带修复了上轮观察项 O4（`__webTabTitle` 重复 `about:blank` 条件）——观察项清单 -1。

---

## 四、全量回归数字（a584→a585→a586 三批总回归）

```
pytest 全量（隔离 USERPROFILE，普通 python）:
  286 passed, 1 skipped, 10 subtests passed (19.33s)
  ——与 a584/a585 基线持平（a586 改 0 测；含 11 个并行域
  test_scheme_capacity.py 全过；RD1 双钉测在其中实跑）
  test_web_tabs_logic.py 单文件 17 passed + 10 subtests
  （= a586 提交信息「pytest 27 passed」的出处，口径吻合）
py_compile:  src/*.py 58 文件 + src/harness/*.py 全过
node --check: web/js/*.js + web/js/harness/*.js 共 73 文件全过
重名扫描:    py AST 109 文件模块级 def/class 零重名；web/js 顶层
             function 零重名（utf-8-sig BOM 修正后）
8 历史风险点: ① 13 act+bad act 兜底 :1310 ✓ ② R9.13+__fcDiag ×2 ✓
             ③ closest('.close') :255 ✓ ④ tray 单例（tray.py:26，
             D2 裁决承继）✓ ⑤ --disable-web-security 仅 main.py:1599
             注释 ✓ ⑥ observe(document.body) 仅 a11y.js:93/
             web-panel.js:732 ✓ ⑦ owner 心跳 ts: Date.now() :41 ✓
             ⑧ AutofillServerCommunication :396 ✓（a586 插行使行号
             平移，内容原样）
a584/a585 特征抽验 14 条: A3 _pwdb_copy / RA12 _pw_guard 双因子 /
             RC2 前端 _webNormUrl 拦截+服务端 scheme 白名单 /
             RC3·RC6 ts except 三重+inf→0（探针复测）/ RC7 tftp_pane_h
             （探针复测）/ RD1 双钉测 / 标题保持 trim+about:blank
             （a586 触碰行，语义保持）/ R9.13 __fcDiag / RA1 反向钉
             （route_chain 错 token 403）/ RB8 _mk wt._tabs=t 语义 /
             RA17 reveal finally close+remove（干净基线 0 残留）/
             RA13 精确删 / RA14 None 分支 / RA16 损坏保留——全在位
reflog/工作树: reflog 仅 a584/a585/a586 三笔 commit（此前 reset@e564f24
             为上轮既有），0 stash；工作树 8 个改动文件全为 harness/
             终端域（lifecycle/routes/session、index.html、chatctl.js、
             shell.js、replay.js、style.css）——git diff -- src/web_tabs.py
             src/server.py web/js/web-panel.js src/main.py web/js/settings.js
             为空 → 网页域工作树零触碰，与本轮审计对象无交集
```

### 钉测缺口状态（承接 final-zero §三）

a586 **零新增钉测**（`e564f24..0d4dd81` tests diff 仅 a585 的 route_chain 双因子+反向钉与 RB8 `_mk` 语义）。25 项缺口维持「部分补 2、未补 23」。**回归风险再次应验**：RW3 指定交错若有钉测（钩子排水+二次 dispose_all recycled≥1 红灯）本批当轮即红；RW9 即时分支若有「空闲库 defer(u='') 后 NULL 行必须删」钉测亦当轮即红。建议钉测名沿用 final-zero §三表（RB7-1/RW3、RA12/RW1、RA15 锁库/RW4、RA15e/RW8、RA17d/RW5）。

---

## 五、遗留与观察（承前口径，不计入未处置数）

- RB7-2 每次刷新/换纪元首条 show 恒丢一次（≤2s 自愈，设计内）；stale `_want` 经 layout 泄漏窗（两版相同）。
- RB7-2 双活窗口结构性不可达（`_webCtl` owner 门）——维持上轮结论。
- RA16 损坏 pending 保留 → 每次退出重复 WARN（无害）。
- RA13 `user=None=全删` 兼容语义保留（UI 不触发；与 RW11 威胁面并读）。
- 锁库 flush 8.17s 退出延迟（RW10 内记账）；`_pwdb_copy` 每次调用 mkdtemp 空目录累积（O3 既有）。
- O1/O2/O3/O5/O6/O7/O8 维持「知情未修/观察」挂账；**O4 已由 a586 关闭**。

## 六、复现与探针

本轮新写（`%TEMP%\rt_final_zero2\`，`python -I` 运行，自隔离）：
- `probe_rw12.py`——RW1/RW2 全断言（status 含 token==PW_TOKEN、theme 无 token、无/错/缺 Origin/异源 403、status-token→list/reveal 200）
- `probe_rw3_variant.py [cur|a585|a584]`——RW3 二扫覆盖窗口刻画（诱饵控件使排水落一扫内；三版对照 100/100 vs 0/100 vs 0/100）
- `probe_rw48.py`——RW4 锁库（保留+WARN+重试成功+耗时）、RW8 全链（锁库 defer→flush 消费/NULL 删/非空留 + 空闲库即时分支 RW8-f）、RC9（surrogate+os.replace 两形态 .tmp 清理）、RW5（pw_list 500+残留 vs reveal 干净）、RW7（400 位 ts 落盘）
- 泄漏隔离脚本（会话内联）——con2 泄漏 + `gc.collect()` 自愈实证

上轮重放（`%TEMP%\rt_final_zero\`，原样未改）：
- `probe_rb7.py a585`（加载 HEAD=a586）——窗口X/W5/RB7-2/layout 泄漏/基线全段
- `probe_rb8.py`——RB8 8 断言
- `probe_tail.py` / `probe_pw_chain.py`——RA13-RA18/RC6/RC7/RC10 旁证（其 RA15e/RC9「FAIL」为旧 bug 断言翻转=修复实锤）

pytest 口径：`USERPROFILE=$(mktemp -d) python -m pytest tests/ -q`（不带 -I）。

---

## 七、结论

**不满足清零标准。** a586 批次把上轮 8 条中的 5 条真修到位（RW1/RW2/RW4/RW6/RW8，探针全绿），RB7-2/RB8 复归无漂移；但 RW3 的双扫在其自述窗口内仍被 pending 循环的纪元 pop 毒化（100/100 孤儿，仅窄窗生效），RW5/RW7 两条未进入批次（原样滞留）；修复自身引入 1 条半修残留（RW9 即时分支口径错位）、1 条卫生级连接滞留（RW10）与 1 条声明勘误（RW11）。**网页域未处置问题数 = 6（RW3/RW5/RW7 + RW9/RW10/RW11）。**

最小收尾路径：① RW3 采纳纪元归属判据（`_epochs.get(tid) != 创建时 epoch` 即弃建/回收，pending 循环不再 pop 纪元或 pop 改标记位）+ 钉测；② RW5 `_pw_entries` 三段式（except 归一 + close/remove 入 finally）；③ RW7 ts 钳位（`min(int_v, 8640000000000000)` 级）；④ RW9 即时分支删语句与 flush 对齐（`IS NULL OR =''`）；⑤ RW10 con2.close 入 finally + DELETE 相 connect `timeout=0.3`。五处合计约 20 行，均有当轮即红的钉测写法。

*报告完。终局审计员（第五轮），2026-11-16。git 全程只读；仓库唯一新增 = 本报告；真实密码库与真实 config 零触碰（探针三重隔离）。*
