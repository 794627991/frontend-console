# 红队回归审计 · D2 轮终验报告（第三轮全量回归）

- **审计员**：红队回归审计员 D（第二轮终验）
- **日期**：2026-11-16
- **对象**：当前 HEAD `e564f24`（v4.1.0-a584），基线 `480c07d`（a583，上轮 D 报告对象）。区间 `480c07d..HEAD` 共 **2 提交**：d7a2441（shell 终端类型）+ e564f24（红队四路修复 26 条声称全清 + 新需求「休眠保持标题」）
- **任务**：①上轮 44 项 + RD1 改名在 HEAD 逐一重验（盯修复批次相互覆盖）②a584 修复钉测完备性清单 ③git 考古（区间逐 diff 删串/覆盖钉测扫描 + 重名扫描）④全量机械验证 ⑤产出「a584 修复面钉测清单」作下轮回退对照基线
- **方法**：修复清单逐条 → `git show HEAD:<file>` 特征串定位 + 语义核对（不做存在性假阳性：RA11 即存在性核对漏掉的死代码，靠控制流核对抓出）；区间仅 2 commit，全量 `-` 行逐条人工裁决；AST 扫 tests/ 模块级重名 + test_ 函数重名 + web/js 函数重名；全程 git 只读；pytest 隔离 USERPROFILE

---

## 一、终判

**上轮 44 项 + 8 风险点：源码级修复零丢失，RD1 改名复活实测生效（套件 274→275）。**
**本轮新确凿丢失/破坏 1 条（RD2 起）**：a584 的 **RA11 修复是死代码**（`shutdown()` 的 `_pw_del_flush()` else 分支不可达）——修复形态在、逻辑无效，「_tabs=None 时挂起删除须 flush」意图未实现。另确认 **B 报告 RB6（退出期 zombie）未修**且提交信息把 RB1 的修复错标为 RB6（见 §四 O1）。

- pytest 全量（隔离 USERPROFILE）：**275 passed, 1 skipped, 10 subtests passed**（19.0s）——比上轮基线 274 **净增 1 = RD1 复活的 test_show_hide_one_semantics 实跑**。注意：`python -I` 会屏蔽用户目录 site-packages（cryptography 装在 %APPDATA%），致 test_pw_decrypt_roundtrip 假失败——pytest 须不带 `-I` 跑（上轮口径）
- `test_route_chain_complete` 单跑：**1 passed**（13 act 全可达含 pw_*+Origin 适配 + 未知 act 必报 bad act）
- RD1 钉测对单跑：`test_show_hide_one_semantics` + `test_anti_autosignin_injected` **各 1 次定义、均 PASSED**（a556 语义钉 + a557 注入钉双双复活且唯一）
- `test_web_tabs_logic.py + test_web_fetch.py`：**27 passed**（与 e564f24 提交说明一致）
- 机械验证：`py_compile` 7 文件（web_tabs/web_proxy/server/main/tray/devtools_cdp/**shell_conn 新增**）全过；`node --check` web/js/ **44 个 JS 全过**；tests/ 模块级重名 **0**（178 个模块级 def）；web/js 函数重名 0（test_subagent_chain_state 的 `test_cases`×6 为 6 个不同类的**方法**，非 RD1 模式）；reflog 干净（区间零 reset、零 stash）
- a584 钉测缺口：**26 条修复中 25 条无专属钉测**（详见 §七映射表）——下轮回退时除 RD1 外全部无红灯保护

---

## 二、上轮 44 项 + 8 风险点重验（HEAD e564f24）

**免检说明**：区间两提交未触碰 main.py / web_proxy.py / devtools_cdp.py / tray.py / style.css / settings.js（`git diff 480c07d..HEAD --stat` 实证空），其承载的 A1/A2/N1'/N2/N4'/W38/W39/风险点④⑤ 与 13 例暗色底结构性免扰动。逐一 grep 复核仍全过。

### web_tabs.py（e564f24 大改，逐签名核对）

| 项 | HEAD 位置与核对 | 判定 |
|---|---|---|
| A3 | `:279 _cancel` 集 + `_build` 弃建（`tab_id in self._cancel: discard; return`）原样 | ✅ 在 |
| A4''/W21 | `:442 err = str(e)` 先固化 + `_init_done` 回收链（_ctl/_pend_nav/_epochs pop + `__webTabDead` 推送）原样 | ✅ 在 |
| A5 | `:396 _pend_nav[tab_id] = url`（就绪前导航挂起）原样 | ✅ 在 |
| A6 | REST `_num` 收口 + show 分支 `_on/_all` isinstance 分派原样（e564f24 仅追加 epoch 实参，布尔逻辑未动） | ✅ 在 |
| A9 | `:516 url or "about:blank"`、`:596 str(a.Uri or "") or "about:blank"` 原样 | ✅ 在 |
| P1'' | `:23 _HIDE_ALL`、`:915 _want` 哨兵、`:868-888 _apply_visibility` 三分支（全隐全挂 :874 / 排他 Resume+BringToFront :880 / 只藏挂起 :883）——e564f24 **未触碰**，a575 TrySuspend 与 R9.14 推演共存完好 | ✅ 在 |
| D1 | `:25 _webPageEpoch`（前端）、dispose_all(epoch) 覆盖 `_ctl ∪ _pending`（`:961/:965 epoch is None or …== epoch`）、`:971 W40 条件 reset` 原样 | ✅ 在 |
| D2 | `:512 AreDevToolsEnabled=self._cdp`、`:1065 _detect_cdp`、`:330-348` 显式 options 四旗+条件 9223 原样 | ✅ 在 |
| W37 | `:340-348 pop→CreateAsync→finally 还原` 原样 | ✅ 在 |
| D8/W42 | `:647-648 GoBack` 唤醒/巡检、前端 `_navSrc` back/fwd/restore 对账（:566-587）、`_webRestore`（:801）、restore 消费复位（:569-570）、`_webActivePid` 复位（:832）原样 | ✅ 在 |
| 13 例 | `:728/:735 CapturePreviewAsync` 反射、`:773 len(b64)<=4MB`、失败降级 `ctl.Visible=False`（ContinueWith 异常路径）原样；RC1 只改了诊断串拼法，抓帧/推送链未动 | ✅ 在 |
| 15 例 | `:849/:858 _suspend_ctl/_resume_ctl + TrySuspendAsync` 原样；**RB5 的 `_after` 改动只改可见性终值判定（按 `_want` 意图），挂起管线本体未动** | ✅ 在 |
| ⑦ | `:41 var g=Date.now()` 原样；钉测实测过 | ✅ 在 |
| ⑧ | `:326 AutofillServerCommunication`（--disable-features 尾项）、`:481/:492 IsPasswordAutosaveEnabled/IsGeneralAutofillEnabled` 真属性 + 回读日志原样 | ✅ 在 |
| A11 | 死代码三标志仍仅注释。**口径更新**：e564f24 为 `_pw_del_lock` 重引入 `import threading`（RA5 正当用途）——上轮「threading 计数 0」判据自本轮起作废，勿据此误报 | ✅ 在（判据演进） |

### web-panel.js（e564f24 改 3 处：_webCtlVisible 加 epoch / __webTabTitle 标题保持 / 收藏点击白名单）

| 项 | HEAD 位置与核对 | 判定 |
|---|---|---|
| A8'' | `_webNavigate(url,c)`:761、`_webAct` wrap.dataset.portId:970-973、`_webReaderToggle(,,,c)`:886、`_webApplyZoom(,,,c)`:948、`_webSyncUI(c)`:959 全参数化原样 | ✅ 在 |
| N3 | sidebar.js closeConnection 正则 `/^(edit|hex|diff|bindiff|web):/ → closeEditorTab`（W22 注释完整，d7a2441 仅挪注释格式）；util.js 抽屉批量 web→closeEditorTab（:246-248）原样 | ✅ 在（双 hunk） |
| N5 | `:153-154 _webFavs` 非数组/缺 url 过滤+回写原样 | ✅ 在 |
| D3=a/W40 | `:29 web-ui-owner` 心跳、`:55 beacon owner 门`、`:227 buildWebPanelTab 非 owner 拦截`、`:401 second-ui-client` 原样 | ✅ 在 |
| 11 例 | `:452 _webReconcileVis` 单一权威推演、2s 周期（:543-548）、wrap style 观察器（回调函数 + pend 去抖 :521-526，3s 补挂 :540）原样 | ✅ 在 |
| 12 例 | `:683-687 anyOverlayOpen` 仅类名快路径（modal/ctx-menu/webFavMenu/nf-menu/**tab-overflow-list**）、R9.13 结构扫描禁用注释（:677-682）+ `__fcDiag`（:690）原样 | ✅ 在 |
| 13 例 | `:645 __webTabShot` 原样 | ✅ 在 |
| 14 例/R9.14 | `:493-496`（全隐每次真实下发）+`:513-516`（目标每次真实下发）原样——**e564f24 对 `_webCtlVisible` 的 epoch 追加与 R9.14 恒发语义正交**（只加字段不改恒发） | ✅ 在 |
| B26 | `:1088-1099 F5/Ctrl+R → activePortId 判定` 原样 | ✅ 在 |
| ③ | `:255 closest('.close')` 上溯 + stopPropagation 原样 | ✅ 在 |
| A10'' | `_webNormUrl` 黑名单（:210 注释）+ 地址栏 banner（:314/:1112）原样 | ✅ 在 |
| D7 前端 | `:1034（内网来源——内容可信度低…）` 原样 | ✅ 在 |

### server.py（d7a2441 动 connect/recent、e564f24 动 _web_favs_clean——均远离已审计段）

| 项 | HEAD 核对 | 判定 |
|---|---|---|
| D6 | `:185-186 @app.errorhandler(404)/(405)` `/api/*` JSON 原样 | ✅ 在 |
| D7 后端 | web_proxy.py 逐跳分类零改动（文件免检） | ✅ 在 |
| a567 路由误删史对照 | dispatch 13 act（create/nav/back/fwd/reload/suspend/show/dispose/dispose_all/layout/pw_list/pw_reveal/pw_del）+ bad act 兜底全在，route_chain 实测过——RA1 守卫插入**未重演** a567 式路由破坏 | ✅ 在 |

### 8 风险点终态

| # | 风险点 | 结论 |
|---|---|---|
| ① | a567 误删 4 路由 | 13 act + bad act 反向钉实测 1 passed；e564f24 在同链上加 `_pw_guard` 未破坏链 | 
| ② | R9.13 结构化扫描 | 仍真禁用（类名快路径含 tab-overflow-list，禁用注释在案） |
| ③ | `closest('.close')` | 在（:255） |
| ④ | tray.py global | 在（AST 实证：hide_to_tray:505 / _watchdog_loop:531(R9.7 注释) / quit_tray:563 各函数顶部段声明；py_compile 过） |
| ⑤ | `--disable-web-security` | 全仓 grep 仅 main.py:1599 注释；零回流 |
| ⑥ | observe(document) | `_PW_FORM_HELPER_JS` 随 a579 退役不变；现存命中（a11y.js:93 / web-panel.js:732 document.body class 观察器）为无关正当功能，非密码助手残魂 |
| ⑦ | `var g=Date.now()` | 在 + 钉测实跑 |
| ⑧ | AutofillServerCommunication | 在（:326） |

### RD1 复活核验

- `tests/test_web_tabs_logic.py:337` 定义名已改回 **`test_show_hide_one_semantics`**（docstring 带 RD1 案底注释），`:401` **`test_anti_autosignin_injected`** 唯一保留——AST 实证测试文件模块级 def 零重名
- 实跑：两测试单跑均 PASSED；全量 275 = 上轮 274 + 1（复活钉测计数入套件）——**RD1 闭环**

---

## 三、a584 修复批次逐条核对（26 条清单口径）

四路红队确凿发现合计 **24 条**（A 报 11 + B 报 8 + C 报 5）+ D 报 RD1 + 新需求 = **26**。e564f24 提交信息声称「26 确凿全清（4红+7黄+低危）」，**其逐项清单实际只列 17 项修复 + 新需求**——差额 8 项的实况见下表（提交信息数字与清单不符，按「应修全修」口径核对每条实况）。

### 密码域（A 报）

| # | 修复内容 | HEAD 核对 | 判定 |
|---|---|---|---|
| RA1 | pw_* 无 Origin 拒 | register 内 `_pw_guard`：`Origin != "http://"+rq.host → 403`，pw_list/reveal/del 三分支逐一挂接（web_tabs.py:1128-1146 等三处） | ✅ 在 |
| RA2 | 无端口/异端口 Origin 拒 | 同 `_pw_guard` 精确串比较（`http://localhost` ≠ `http://localhost:8765`）——无端口豁免对 pw 面失效 | ✅ 在 |
| RA3 | 库副本用完即删 | `_pw_entries` finally `_os.remove(db)`；pw_reveal 读后显式 remove。**残留**：`_pwdb_copy` 仍每次 `mkdtemp()`——文件删、**空目录仍无限累积**（§四 O3） | ✅ 在（部分） |
| RA4 | 按 origin+user 精确删 | `_pw_del_defer(origin, user)` 双条件 DELETE；flush 兼容旧格式字符串（isinstance list 判别） | ✅ 在 |
| RA5 | 挂起文件锁 + 原子替换 | `_pw_del_lock = threading.Lock()` 全程持锁 + `tmp + os.replace`（web_tabs.py:185-210） | ✅ 在 |
| RA6 | 损坏告警 + 重建 | json.load 失败 → `lst=[]` + `_log("WARN", "pw_pending_del.json 损坏，已重建")` | ✅ 在 |
| RA7 | 畸形库 try/except + 不再 500 | pw_reveal：`try: connect/execute/close except → {"ok":False,"err":"库读取失败：%r"}`。**残留**：返回 200 非 400（提交说明称 400，口径差 §四 O6）；`_pw_entries` 异常路径连接泄漏仍在（A 报 RA7 列两处，只修一处） | ✅ 在（部分） |
| RA8 | 多条取最新 | `ORDER BY date_created DESC LIMIT 1` | ✅ 在 |
| RA9 | reveal 二次认证/审计 | 提交未列、代码无——**未修**（A 报低危） | ❌ 未修（未声明） |
| RA10 | pw mgr fetch 绕过 owner 门 | `_webPwMgr`(:1125) 仍自带 fetch 无 `__webUiIsOwner`——**未修**（同源第二 UI 仍可操作 pw 面） | ❌ 未修（未声明） |
| RA11 | `_tabs=None` 退出也 flush | `shutdown()` 首行 `if _tabs is None: return` 未动，`else: _pw_del_flush()` 在 try 内不可达——**死代码，意图未实现** | ❌ **RD2 死代码** |

### 并发域（B 报）

| # | 修复内容 | HEAD 核对 | 判定 |
|---|---|---|---|
| RB1 | flush 期 create 5s 钉死 | `flush_on_exit` 置 `self._closing = True`（:1008）+ create `if self._env is None and self._closing: return {"ok":False,"err":"正在退出"}`（:376-379）——实害（每线程 5s 白等）已消 | ✅ 在（提交信息挂名 RB6） |
| RB2 | dispose_all 自清 _cancel | `reset_session` 删 `_cancel.clear()`，RB2 案底注释在案（:1030-1032）；`_build` 消费自清原样 | ✅ 在 |
| RB3 | show sq 门非原子 | 未列未修（B 报 P3，现实概率极低） | ❌ 未修（未声明） |
| RB4 | show 带纪元 | `show(..., epoch=None)`：`epoch != _want_epoch → _want_epoch=epoch; _want_seq=0`（:905-907）；REST 透传 `str(d.get("epoch"))or None`；前端 `_webCtlVisible` 恒带 `epoch: _webPageEpoch`（:439）；`reset_session` 连纪元清（:1026）。误重置由 2s 推演恒发自愈（设计内） | ✅ 在 |
| RB5 | suspend 迟到回调按意图 | `_after`：`w = self._want; if w is not None and w[0]==tab_id and w[1]: Visible=True else False`（:755-763） | ✅ 在 |
| RB6 | 退出期 zombie（_build 撞 env=None） | **未修**：`_wire` 对 `EnsureCoreWebView2Async(self._env)` 同步抛仍只 `_log("ERROR","_wire: %r")`（:529-530），`_build` 已先 `Controls.Add + _ctl[tab_id]=ctl` → zombie 滞留路径原样。RB1 的 `_closing` 快速失败只挡**新** create，in-flight create 窗口（B 实测 50/50）依旧。提交信息将 RB1 修复错标为 RB6 | ❌ 未修（标签混淆 §四 O1） |
| RB-JS1 | 推演 `_a` 空值旁路 | 未列未修（纵深缺口非现行 bug） | ❌ 未修（未声明） |
| RB-JS2 | 推演无节流上限 | 未列未修 | ❌ 未修（未声明） |

### 注入域（C 报）

| # | 修复内容 | HEAD 核对 | 判定 |
|---|---|---|---|
| RC1 | diag 整句 json.dumps | 两处 push 均 `"console.warn(%s)" % json.dumps('[web-tabs] suspend: ' + ";".join(diag))`（:786-788/:815-817）——单引号语境消除 | ✅ 在 |
| RC2 | file:// 全链封堵 | 服务端：`_web_favs_clean` 加 `url.startswith(("http://","https://"))` 白名单（server.py:1413-1416）；前端：收藏点击 `/^https?:\/\//i.test(f.url)` 否则 banner 拒（web-panel.js:1294-1297）。**残余旁路**：REST create/nav 后端仍零 scheme 校验；本地 localStorage 恢复栈过滤器仍只挡 about:blank（:74-76）——C 报列的 4 入口修 2 个（§四 O2） | ✅ 在（部分） |
| RC3 | ts 类型防护 | `try: int(it.get("ts") or 0) except (TypeError, ValueError): ts = 0` | ✅ 在 |
| RC4 | lone surrogate 截断挂起文件 | 未列。**间接消除主损害**：RA5 原子写后 json.dump 抛 UnicodeEncodeError 时原文件不再被截断（写 .tmp 失败、os.replace 未达）；该条删除仍写不进（WARN 可见） | ⚠️ 间接缓解 |
| RC5 | cleaner 口径归一 | 未做（大写 scheme 仍拒）；RC2 白名单下仅成垃圾拒收，无注入面 | ❌ 未修（未声明） |

### 回归域（D 报）+ 新需求

| # | 内容 | HEAD 核对 | 判定 |
|---|---|---|---|
| RD1 | a556 钉测改名复活 | 见 §二 RD1 节 | ✅ 闭环 |
| 新需求 | 休眠保持网页标题 | `__webTabTitle`：`t=String(title\|\|'').trim(); if (c && t && t!=='about:blank' && t!=='about:blank') _webSetLabel(c, title)`——空/about:blank 标题不再刷掉真名。**疵点**：`t !== 'about:blank'` 重复写两次（冗余条件，功能无损，§四 O4） | ✅ 在（带疵点） |

### shell 提交（d7a2441）与审计修复面交叉

- `_SINGLE_KINDS` 保持 `{harness,bitcalc,proxy,vcs}`（A7 完好；shell 未加入，符合多开设计）
- api_connect shell 分支：shell 白名单（SHELLS）+ cwd isdir + 占位锁外 spawn——结构与 ssh/claude 分支同构，不触及 web_tabs/审计段
- api_recent 白名单扩 telnet/shell——纯扩展
- terminal-core.js：wheel→PgUp/PgDn 与「打字跳底」保持 claude-only（:364/:390 kind==='claude' 原样），shell 只并排除串口工具栏/全屏 overlay/尺寸同步——claude 特性零扰动
- sidebar.js closeConnection 的 W22 转发正则原样保留（注释重排）

---

## 四、本轮新发现清单

### RD2【修复无效｜死代码】RA11：`shutdown()` 的挂起删除 flush 分支不可达

- **位置**：`src/web_tabs.py:1214-1226`
- **实况**：
  ```python
  def shutdown(grace_ms=1200):
      # RA11（红队）：即使 _tabs 未装配（env 失败），挂起删除也须执行
      global _tabs
      if _tabs is None:
          return                     # ← 早退
      try:
          if _tabs is not None:
              _tabs.flush_on_exit(grace_ms)
          else:
              _pw_del_flush()        # ← 死代码：上面已 return，永不达
  ```
- **后果**：RA1 场景（`_tabs=None` 的会话退出）挂起删除依旧永不 flush，与修复前行为完全一致。且 `test_shutdown_none_safe`（:479）只断言「_tabs=None 不抛」、不断言 flush 被调——**该死代码零红灯**。main.py 亦无 `_pw_del_flush` 直调兜底（grep 实证仅 `_wt.shutdown()`）
- **修法建议**：`if _tabs is None:` 分支内改 `return` 为 `_pw_del_flush(); return`（try 包裹），或删 try 内 if/else 恢复直调并前置 flush。配套钉测见 §七

### 观察项（如实记录，非 RD 级）

- **O1**：提交信息把 RB1 的修复（`_closing` 快速失败，治「5s 钉死线程」）标注为「RB6」。B 报 RB6（zombie：in-flight create 的 `_build` 撞 `_env=None`）本体未修——`_wire` 未加 B 建议的「`_env is None` 走 `_rm` 回收」。台账如按提交信息销 B-RB6 会错销
- **O2**：RC2 修了 C 报 4 入口中的 2 个（服务端收藏写入清洗、前端收藏点击）。残余：① REST `create/nav` 对 url 仍零 scheme 校验（本机进程可直 POST file:// ——与 RA1 同信任域，但 A 报 RA1 修后 pw 面有守卫而导航面没有）；② 本地 localStorage 恢复栈过滤器（web-panel.js:74-76）仍只挡 `about:blank`，修复前已中招的 file:// 恢复项可经 `_webNavigate` 直达（服务端 session 种子有 `_web_session_clean` 白名单，本地 localStorage 段无）
- **O3**：RA3 残留——`_pwdb_copy` 仍每次 `mkdtemp()`，`_pw_entries`/pw_reveal 只删 `LD.db` 文件不删目录：%TEMP% 空目录仍随每次点击线性累积（敏感文件本体已删，隐私面已闭，属资源泄漏残留）
- **O4**：`__webTabTitle` 的 `t !== 'about:blank' && t !== 'about:blank'` 同一条件写两遍——疑为想写两种空白变体的笔误，功能无损（等效单次判断）
- **O5**：`_want_epoch` 未在 `__init__` 初始化（`show` 用 `getattr(self, "_want_epoch", None)` 兜底、`reset_session` 落值）——功能正确，风格疵点
- **O6**：RA7 提交说明称「500→400」，实现实际返回 200 + `ok:false`（不再裸 500 的核心目的达成，状态码口径与说明不符）
- **O7**：`test_route_chain_complete` docstring 仍称「10 个 act」（实际 13，a583 起）——文档滞后
- **O8**：提交信息「26 确凿全清（4红+7黄+低危）」与逐项清单（17 项修复+新需求）不符；未修未声明的 6 项：RA9、RA10、RB3、RB-JS1、RB-JS2、RC5（均为报告定级低危/纵深项，建议在台账 STATUS 注明「知情未修」防后续审计重复立牌）

---

## 五、git 考古（480c07d..HEAD 全量）

**区间仅 2 commit，`-` 行全量逐条裁决（两向：删修复特征串 / 覆盖钉测定义）**：

| commit | 删除内容 | 定性 |
|---|---|---|
| e564f24 | `self._cancel.clear()` | **RB2 修复本体**（有意移除缺陷机制，注释在案） |
| e564f24 | `def test_anti_autosignin_injected`（:337 dup）+ a556 docstring | **RD1 修复本体**（改名复活，非覆盖） |
| e564f24 | `ctl.Visible = False`（suspend `_after`） | RB5 修复本体（改按意图判定） |
| e564f24 | `"console.warn('[web-tabs] suspend: %s')" % json.dumps(...)` ×2 | RC1 修复本体（单引号语境消除） |
| e564f24 | 旧 `_pw_del_defer`（无锁非原子）+ 旧 flush 循环（全 origin 删）+ pw_reveal 裸 query | RA4/RA5/RA6/RA7/RA8 修复本体 |
| e564f24 | `if (c && title) _webSetLabel(c, title);` | 新需求替换（真标题写入语义保留于新分支内） |
| e564f24 | `if (f) buildWebPanelTab(f.url, …)` | RC2 修复本体（加白名单分支） |
| e564f24 | `_tabs.flush_on_exit(grace_ms)`（直调形式） | 改 if/else——**RA11 死代码产生点（RD2）** |
| d7a2441 | api_recent 白名单两行 / descText 三元 / RECENT_ICON/TYPE_NAME / closeConnection def 行 + D-3 注释行 / terminal-core claude 判定 6 处 | 全部为**扩展重写**（shell 并入），W22/D-3 语义经 HEAD 核对完整保留 |

- **「覆盖钉测定义」扫描**：e564f24 对 tests 仅 2 处改动（RD1 改名 + route_chain 加 Origin 头）——零覆盖、零同名 shadow。AST 实证 tests/ 178 个模块级 def 零重名；`test_` 前缀函数跨作用域唯一命中仅 `test_cases`×6（6 个不同类的**方法**，非 shadow 模式）
- **「回归再引入」反向**：区间 `+` 行无 `--disable-web-security` 实参、无 `var g=0`、无 `_SINGLE_KINDS` 含 'web'、无 `bool(d.get("on", True))` 回流
- **reflog**：区间零 reset、零 stash、零弹跳（上轮 a567 型事故未重演）

**上轮教训专项核对（任务点名）**：
- a575 TrySuspend 与 R9.14 推演共存：`_apply_visibility` 三分支未被 e564f24 触碰；RB5 `_after` 的 Visible=True 与 `_want` 意图、前端恒发推演方向一致——共存完好，`test_hidden_tab_suspends_pipeline`/`test_hide_all_suspends_everything` 实跑过
- 密码管理器路由与 a567 路由误删史对照：`_pw_guard` 以**函数内定义 + act 分支内调用**方式插入，未采用会引发整链重写的结构；route_chain 反向钉（bad act 必报）实测过——RA1 修法未重演 a567

---

## 六、机械验证数字（复现口径）

```
py_compile:  web_tabs web_proxy server main tray devtools_cdp shell_conn → 全过（7 文件）
node --check: web/js/*.js → 44 文件全过（含新五件套 web-panel/util/sidebar/settings/sidebar-resize + terminal-core）
pytest 全量:  USERPROFILE=$(mktemp -d) python -m pytest tests/ -q
              → 275 passed, 1 skipped, 10 subtests passed (19.0s)
              （上轮基线 274 + RD1 复活 1 = 275，自洽）
              ⚠ python -I 跑 pytest 会因屏蔽用户 site-packages（cryptography）
              致 test_pw_decrypt_roundtrip 假失败——回归口径须不带 -I
route_chain:  单跑 1 passed（13 act + bad act 反向钉）
RD1 钉测对:   test_show_hide_one_semantics / test_anti_autosignin_injected 单跑各 PASSED，定义各唯一
tests 重名:   AST 模块级 def 178 个，零重名；test_ 函数零模块级重名
web/js 重名:  函数名扫描零重名
风险点 grep:  ⑤ 仅注释命中 / ④ 三函数顶部段 global / ⑥ 仅无关正当功能 / ⑦⑧ 特征串在位
reflog:       区间零 reset / 零 stash
工作树:       仅 4 份审计报告 untracked，零 M 项（a584 已全部入库）
```

---

## 七、a584 修复面钉测清单（26 条 → 现有钉测映射 · 下轮回退对照基线）

**现状**：26 条中**仅 RD1 有钉测**（它本身就是测试修复）；`test_route_chain_complete` 携带 RA1 的正向适配（带 Origin 必 200），但**无负向 403 断言**。除 RD1 外 25 条回退/覆盖时**套件零红灯**。

| # | 修复 | 现有钉测 | 无钉测者 → 建议钉测名（pytest 可测口径） |
|---|---|---|---|
| RA1 | pw 无 Origin 403 | —（route_chain 仅正向适配） | `test_pw_guard_requires_matching_origin`：test_client 无 Origin → 403；`Origin: http://evil:9` → 403 |
| RA2 | pw 无端口/异端口 Origin 403 | — | 并入上测：`Origin: http://localhost`（缺端口）vs Host localhost:PORT → 403 |
| RA3 | 库副本用完即删 | — | `test_pw_entries_removes_copy`：stub _pwdb_copy 指向临时文件，调用后文件不存在 |
| RA4 | 按 origin+user 精确删 | — | `test_pw_del_scoped_to_user`：临时库两 user 同 origin，删其一 rows_left=1 |
| RA5 | 挂起文件锁 + 原子替换 | — | `test_pw_del_defer_concurrent_no_loss`：双线程各删 10 条 → pending 20 条全在（上轮 B 探针口径）；断言最终文件为合法 JSON（原子性） |
| RA6 | 损坏挂起文件告警重建 | — | `test_pw_pending_corrupt_rebuilds`：写入 `{"corrupt` → defer 后 pending 为合法 JSON 且含新条目、日志含 WARN |
| RA7 | 畸形库不 500 | — | `test_pw_reveal_malformed_db_graceful`：非 sqlite 文件 → 200 且 ok:false（改 400 后同步断言状态码） |
| RA8 | 多条取最新 | — | `test_pw_reveal_latest_by_date`：两条同 origin+user → 返回 date_created 最新 |
| RA9 | （未修）二次认证/审计 | — | 修复时补 `test_pw_reveal_audit_logged` |
| RA10 | （未修）owner 门 | — | 修复时补 `test_web_pw_mgr_gated_by_owner` |
| RA11 | `_tabs=None` 也 flush | —（`test_shutdown_none_safe` 只钉不抛） | `test_shutdown_none_flushes_pending`：_tabs=None + 造 pending 文件 → shutdown 后 pending 文件消失（**先修 RD2 再补**；顺带把 none_safe 改名为 flush 语义） |
| RB1 | 退出期 create 快速失败 | —（`test_env_failed_fast_return` 只钉 _env_failed 路） | `test_create_fast_fail_while_closing`：`_env=None; _closing=True` → create 即返 err 且 <0.5s |
| RB2 | dispose_all 不清 _cancel | — | `test_reset_session_preserves_cancel`：`_cancel.add('a')` → reset_session → `'a' in _cancel` 仍真；配套 `_build` 消费 discard 已有 create_dedup 测试邻近可借力 |
| RB3 | （未修）sq 门原子 | — | 修复时补 |
| RB4 | epoch 纪元重置水位 | —（route_chain 传 epoch:"" 走旧路） | `test_show_epoch_resets_seq_watermark`：show(sq=50, epoch=E1) → show(sq=1, epoch=E2) 不被丢（无 epoch 重置时 sq=1 ≤ 50 会被丢）；旧纪元迟到 sq 自愈行为另钉 |
| RB5 | suspend 迟到回调按意图 | — | `test_suspend_callback_respects_intent`：`_want=('t',True)` 时触发 `_after` 等价路径 → Visible 保持 True；`_want=None` → False |
| RB6 | （未修）zombie | — | 修复时补 `test_wire_env_none_recycles` |
| RB-JS1/2 | （未修） | — | 前端侧，修复时补 node 断言或源码断言 |
| RC1 | diag 整句 json.dumps | — | `test_suspend_diag_no_quote_escape`：源码断言无 `"console.warn('[` 形态、diag 含 `'` payload 时拼出的脚本 json.loads 往返无损 |
| RC2 | favs scheme 白名单 | — | `test_web_favs_clean_scheme_whitelist`：POST /api/theme 带 `file:///x` 收藏 → GET 回读无 file 项（Flask test_client 同 p11 口径）；前端消费端属 JS，源码断言 `/^https?:\/\//i.test` 在位 |
| RC3 | ts 类型防护 | — | 并入上测：`{"url":"http://a/","ts":"abc"}` → 200 且 ts==0（非 500） |
| RC4 | （间接缓解） | — | 修复时补 `test_pw_del_defer_lone_surrogate_keeps_prior` |
| RC5 | （未修） | — | 修复时补 |
| RD1 | 钉测本身复活 | **test_show_hide_one_semantics（:337）+ 全量计数 275** | 已有——防再犯：CI 加模块级重名 AST 扫描（一行成本，上轮 D 报建议） |
| 新需求 | 休眠保持标题 | — | 前端侧：源码断言 `__webTabTitle` 含 trim + about:blank 忽略分支（或 node DOM 桩单测 `_webSetLabel` 未被空标题调用） |

**建议钉测补齐优先序**（回退风险 × 实现成本）：RA1/RA2（安全门，最易被「重构」无声拆掉）> RB4/RB2/RB5（并发三修，逻辑微妙最易被误简化）> RA11/RB1（退出链，RD2 修复后立即补）> RA3-RA8（密码文件链）> RC1/RC2/RC3 > 其余。

---

## 八、结论与建议

1. **上轮 44 项 + 8 风险点在 HEAD 完好；RD1 闭环（275 计数实证）**。a584 修复批次与本轮区间考古零意外覆盖——a570-a583 修复未被 a584 破坏（含任务点名：a575/R9.14 共存、pw 路由 vs a567 误删史、epoch 与 route_chain 对照）。
2. **唯一行动项 RD2**：`web_tabs.py:1214-1226` shutdown 死代码——`_tabs is None` 早退分支内补 `_pw_del_flush()`（try 包裹），并把 `test_shutdown_none_safe` 升级为 flush 语义钉测（§七 RA11 行）。一行修复 + 一钉测。
3. **台账口径勘误建议**：①B-RB1/RB6 标签混淆（提交信息把 RB1 修复标为 RB6；RB6 本体未修）；②「26 全清」实为 17 修 + 1 间接缓解 + 1 新需求，RA9/RA10/RB3/RB-JS1/RB-JS2/RC5 六项未修未声明——建议 STATUS 注明「知情未修」；③RA7 状态码口径（200 非 400）；④RC2 剩余两入口。
4. **钉测缺口是当前最大回退风险**：26 条中 25 条无钉测。上轮 RD1（同名覆盖静默死亡）+ 本轮 RD2（死代码零红灯）同型——**「修复无钉测 = 下次静默回退」**。§七清单已给出 25 个建议钉测名与优先序，供主控择批补齐。
5. 遗留观察项照旧：W41（设计内竞态）、R9.13 结构化扫描重建待定位误判源；本轮新增 O1-O8 观察项随台账。

*报告完。审计员 D，2026-11-16（D2 轮终验）。git 全程只读；仓库唯一新增 = 本报告；pytest 全程隔离 USERPROFILE。*
