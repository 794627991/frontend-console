# AGENTS.md —— 本工程 AI 会话约束与速览

<!-- 权限铁律（2026-11-23 用户设定，任何会话必须遵守） -->

## 权限铁律

### 绝对禁止
- **打包/构建**：不执行 `打包.bat` / `打包_debug.bat` / `python src/build.py` /
  PyInstaller / electron-builder / `npm install` 等任何构建、安装链。
  AI 只改代码；构建验证一律由用户本人执行，有问题用户会反馈。
- **git push**：任何形式的推送一律禁止，也不碰 remote 配置。
- **批量纳入**：永久禁用 `git add .` / `git add -A` / `git commit -a`；
  即使获准提交，也只逐文件点名。
- **提交他人改动**：仓库存在并行会话改动的可能——不属于本会话的改动一律
  不碰；同文件混入他人改动时报用户裁定。
- **未证明隔离生效，不得运行任何会写盘/删盘的验证**（2026-11-23 事故
  铁律）。起因：AI 跑卸载器实验，以为 `set APPDATA=沙箱` 就能引开 NSIS
  的 `$APPDATA`——实测它走 Windows 已知文件夹接口，**不读环境变量**，
  重定向从第一次起就没生效；同时用的「数据指纹」函数有 bug、永远返回
  一致。两道防护同时失效却都信了，结果删掉了用户真实的锚点配置。
  规则：
  1. 先弄清被测代码**实际**从哪读路径。本项目已知事实：`APP_DIR`/默认
     数据目录 = 被导入的 `app_state.py` 所在的项目根，**不读环境变量**
     （要隔离就把 `src` 拷进沙箱再从那里导入）；NSIS 的 `$APPDATA`、
     `$INSTDIR` 不读环境变量。
  2. 隔离是否生效，要由**被测进程自己**报告它看到的路径来证明，不能看
     启动器/包装脚本里的变量。自检不通过立即中止。
  3. 「数据没变」的结论必须来自**先自检过会变化**的比对函数（拿两个已知
     不同的东西比一次，确认它报不同）。
  4. 「没出事」≠「被挡住」。结果异常时先排除最坏可能（确实动了真实
     数据），不要先归因于测试脚手架。
  5. 运行前后对真实用户目录做指纹，出现差异必须查清来源再继续。

### 需用户明确指示才做
- git commit（走下方 aNNN 提交协议）
- 版本号变更（`src/version.py` 等版本语义文件）
- 删除 / 整体重写既有文件（常规改代码除外）

### 可自主做
- 读代码、搜索、分析、只读诊断（`git status|log|diff`、tasklist、
  curl 探活、`py_compile` 语法检查）
- 修改源码修复问题——改动只留工作区，绝不顺手提交
- 验证性启动应用、清理自己拉起的进程（先说明）；重打包前需关闭运行中
  实例这类操作只提醒用户，不代杀，除非用户明确让做

### 禁止操作用户窗口（2026-11-25 用户令，事故级）
**绝对禁止 `SetWindowPos(HWND_TOPMOST)`、`ShowWindow(SW_MAXIMIZE)` 等任何
改变用户窗口层级/尺寸/焦点状态的 Win32 调用。**

起因：AI 为了「让 Chromium 判定页面可见、好截图」反复给自己和工具窗口设
TOPMOST + 最大化，事后有的撤销了、有的没撤——用户被置顶窗口压在下面，
「点开什么都不显示」，连别的软件都看不了，只能强行中断会话。

规则：
1. **不得置顶**。需要窗口可见时只提醒用户「请把工具窗口点到前面」（或
   `SetForegroundWindow` 单次聚焦后立即失效，也不做层级的永久改动）。
2. **不得最大化/改尺寸**。窗口几何归用户。
3. 因调试确实必须临时改窗口状态时（极少数）：改完**必须**在同一个工具调用
   序列里撤销，并在回复里明说「已撤销」——不能留到下一轮。
4. 判断「窗口是否可见」用 `document.visibilityState` 读，**不要**靠改窗口
   状态去试探。不可见就如实报告「需要你点一下工具窗口」，让用户决定。

## aNNN 提交协议（获准提交时逐条执行）
1. `git log --oneline` 查最近提交，取最大 aNNN → 新号 = 最大 + 1
2. `git status` + `git diff` 逐文件核对，确认每处改动确属本会话所为
3. 逐个点名 `git add <自己的文件>`，其余一律不动
4. 提交信息沿用项目格式：`v4.1.0-aNNN 中文摘要`（结论开头风格）
5. 提交即止、不 push，把提交号报给用户

<!-- 语言铁律（2026-11-03 用户设定，同 ~/.claude/CLAUDE.md） -->

## 语言铁律
- 思考过程和回复全部用中文；代码、命令、专有名词可保留英文原文。

<!-- UI 禁 emoji 铁律（2026-11-05 用户设定，同 ~/.claude/CLAUDE.md） -->

## UI 禁 emoji 铁律
- 前端控制台**渲染到界面的文本**绝对禁止彩色 emoji（⚠❌✅🟢 等）。
- 图标一律用 ICO16 SVG 图标库（`web/js/icons.js`，如 ICO16.robot/search/trash）；
  不适合图标的用纯文字。
- 边界：✓ ✗ ⟳ ▾ 等单色文本字形是工程既有风格，允许；代码注释不受限。

## CodeGraph
- 仓库根有 `.codegraph/` 时，优先用 `codegraph explore "<符号/问题>"`
  （或 MCP `codegraph_explore`），先于 grep/find。

## 技能指路（动手前先读对应 skill）

**改了 `web/` 下任何代码（js/css/html），要在真实界面验证效果时——先读
`serial-console-pro` skill 的「验证前端控制台的界面改动」一节。**

那节的核心是铁律与流程：**永远不允许直接操作工具本体，所有 CDP 操作只走
AI 浏览器**；工具界面本身就是 `http://127.0.0.1:<port>/` 网页，用
`browser_navigate` 打开它；`devtools_*` 的 `target` 参数已删除；改完代码先
`location.reload()` 再验证（不重载时 window 上还是旧函数，结论全不成立）；
合成事件测不了 OS 拖放；裸连 CDP 的禁令。不读会重走 2026-11-26 踩过的坑
（AI 拿 `target="app"` 执行 `location.reload()` 重载了用户的工具窗口）。

**为什么写在那里而不是这里**：方法是通用的（任何项目的会话都可能要验证
前端），本工程只是触发场景之一；而 skill 只在命中时加载，不占每个会话的
常驻上下文。

其它常用 skill：`code-review`（评审改动）、`doc-coauthoring`（写设计文档）、
`data-analysis`（分析数据）、`find-skills`（找有没有现成的）。
技能仓库入口是工具内的「技能仓库」按钮（设置里的 `skills.sh` 集成），
装的技能落在 `~/.claude/skills/`，所有项目的会话共享。

<!-- 工程速览（形态与入口，帮助新会话快速对齐） -->

## 工程速览
- **P4（2026-11-22 用户拍板）**：Electron 壳是唯一入口——单实例锁/文件
  关联/窗口语义全归壳；后端 exe 只是 sidecar，由壳以 `--headless` 拉起。
- **状态布局（用户令 2026-11-23 最终版，不再改——不要加兼容）**：
  - **config.json 永远在 `工具目录\data\config.json`**（源码=项目根\data；
    安装版=exe 旁\data；隔离态=`FC_STATE_DIR\data`）。它是「数据迁到了哪」
    的唯一记录者，所以自己不跟着数据走。不从任何别处读/搬；**没有指针文件、
    不看历史位置、不做兼容**。没有它就空配置起步。
  - **数据目录 = config 里记的 `data_dir`（若那个目录存在），否则
    `工具目录\data`**。实现就三步：`_anchor_dir()`（锚点）→
    `_selfheal_cfg()`（读 config + 自愈）→ `_resolve_data_dir()`。
  - **config 的备份与本体在一起**：`config.json.bak`（每次保存滚动留底）+
    `工具目录\data\data_backup\config.json`（cred_mirror 镜像）。坏了按
    `.bak` → 镜像 的顺序自动恢复并落盘；都救不了就以空配置起步，坏件留证
    （`.bad-<时间>`）。`_selfheal_cfg()` / `_mirror_config()`。
  - **数据迁移功能保留**（设置里改数据目录，`server._do_data_dir_migrate`）：
    用户数据全量拷到新目录，config 的 `data_dir` 改成新目录；config 本体与
    备份**不随迁**。旧目录就是工具目录 data 时（第一次迁移）**逐项删、config
    相关一律留着**，绝不整个 rmtree。
  - `%APPDATA%\frontend-console-shell\backend\`（锚点，`st.HOME_DIR`）只放
    `endpoint.json`（服务发现，每轮重写）与崩溃取证日志。壳的缓存在
    `%APPDATA%\前端控制台\`。
  - 新代码一律用 `st.TOOL_DATA_DIR`（config 的家）/ `st.CONFIG_FILE` /
    `st.DATA_DIR`（数据目录）/ `st.HOME_DIR`（锚点），禁止自己拼路径。
- **测试自隔离**（`app_state._fc_test_isolation`，导入期最先执行）：
  以 `python tests/xxx.py` 或 pytest 运行时，app_state 自动把 `FC_STATE_DIR`
  指到临时目录——锚点、默认数据目录、旧目录、config 全部落沙箱
  （`FC_STATE_DIR` 一个开关管全部路径）。正常运行零影响。
  **边界（受控实验的实话）**：测试文件**自己不导入 app_state**、却用
  `python -c` 起子进程时，子进程认不出测试身份，会碰真实的 `%APPDATA%`。
  这类测试必须**在文件顶部显式 `os.environ["FC_TEST_CHILD"] = "1"`**
  （见 `tests/test_harness_version.py`）。隔离是否成立不能靠机制推定，
  要由子进程自报路径来验证。
- 源码开发：根目录 `run.bat`（唯一启动入口；Electron 运行时三级兜底）
- 调试包（2026-11-24 用户令，旧 zip 形态退役）：`打包_debug.bat` 出
  **安装包** `dist\electron_setup_debug\前端控制台调试版-Setup-*.exe`，
  与正式版同一 electron-builder NSIS 流程（配置 `electron/electron-builder.debug.json`，
  顶层扁平无 `build` 包裹）；唯一区别=后端 `_internal\src\` 是明文 .py
  （正式版是 Cython pyd）。data 保全、安装/升级/卸载行为与正式版逐字节一致。
  旧 `dist\前端控制台_debug\electron-shell`+`ico`+`前端控制台_debug-v*.zip`
  构建时自动清理（残留会让后端直启分支误拉旧壳）。调试包不进 releases。
- 正式发布：Setup.exe（electron-builder）；调试包不进 releases 分发流
- **重打包前必须先关掉运行中的调试包实例**（PyInstaller 要删重建 dist 目录）
- **安装包数据保障 + 过程显示（2026-11-23 用户令，经对抗审计修订）**：
  `electron/build/installer.nsh` 定制 NSIS——升级/卸载一律保留真实数据目录
  `$INSTDIR\resources\backend\data`（Setup 形态后端 _app_dir=resources\backend；
  customRemoveFiles 接管内置 RMDir /r：顶层跳过 resources，backend 下只保
  data\）；交互卸载弹「是否保留用户数据」（静默/升级默认保留；选清除时连
  两处 userData：frontend-console-shell 锚点 + 前端控制台壳目录一起删）；
  安装/卸载过程详情强开（隐藏 section 抢跑 `SetDetailsView show`——官方
  ShowInstDetails 属性被模板后置覆盖，实测后写胜，只能走运行时指令）。
  **该文件必须保持 UTF-8 带 BOM**（手工 makensis 对无 BOM 中文 .nsh 报
  Bad text encoding；electron-builder 流程两者皆可，BOM 防手工踩坑）；
  `Var fcKeepUserData` 必须包在 `!ifdef BUILD_UNINSTALLER` 里（否则安装器趟
  warning 6001 × -WX 构建失败）。
- **AI 浏览器（2026-11-24 用户需求 + 四项拍板）**：AI 用 CDP 操作网页时，页面
  显示在 AI 会话右侧分屏，用户看着 AI 操作（此前 `devtools_*` 默认操作的是
  工具自己的界面）。实现三处：后端 `src/ai_browser.py`（路由 `/api/ai_browser/*`；
  MCP 的 `browser_*` 与 `devtools_*` 默认目标）、前端 `web/js/harness/ai-browser.js`
  （分屏伪 tab + 挂 body 的常驻舞台）、壳 `electron/main.js` 的「AI 浏览器」段
  （视图标识交接）。拍板：会话右侧分屏 / `devtools_*` 默认=AI 浏览器、显式
  `target=app` 才操作工具自身界面 / 光标 + 点击涟漪 + 状态条 / AI 操作时自动
  展开、收起后仍可后台运行和截图。总开关 `ai_browser_enabled`（缺省开）。
  **实测硬约束（端到端踩出来的，别再踩）**：
  - 分区名 `persist:fc-ai-browser` 在前端 / 壳 `will-attach-webview` / 后端三处
    对齐；壳凭它认出视图并取消密码填充 guest-preload。
  - 网页视图的 CDP targetId 由壳用 `webContents.debugger` 精确映射后 POST
    `/api/ai_browser/attach` 登记——**不取 `/json/list` 第一个 webview**（多个
    视图时有歧义）。`getWebContentsId()` / `getURL()` 必须等 `dom-ready` 才能调。
  - **别用 CDP Page 域的导航类命令**（`Page.reload` / `Page.navigateToHistoryEntry`）：
    guest 的框架挂在宿主页面的框架树上，实测会把整个前端控制台界面一起重载。
    后退 / 前进 / 重载一律在网页内 `history.*` / `location.reload()`。
  - **后台 / 最小化 / 失焦可用（2026-11-25 用户令，仿照 zcode）**：AI 浏览器
    不再因为「窗口看不见」就拒绝操作。三层配合：
      1. 壳启动期 `appendSwitch` 关掉 `disable-backgrounding-occluded-windows`
         + `disable-renderer-backgrounding`，**外加
        `--disable-features=CalculateNativeWinOcclusion`**——Windows 的原生
        遮挡计算会在窗口被别的软件盖住时判定 occluded → webContents 转
        hidden → 停帧停输入，这正是「用户看别的软件、AI 点不动」的真凶。
        `disable-features` 同名开关只能 append 一次（后写覆盖先写），将来别处
        要用必须合并成逗号列表。
      2. 壳 `will-attach-webview` 里**只对 AI 浏览器视图**
        （`if (aibrPending)`）设 `backgroundThrottling = false`。
        **故意不开全局 `disable-background-timer-throttling`**：受控实验实测
        （guest 里跑 100ms 定时器，最小化后数 3 秒的 tick 数）——
        · 两开关全关：30 次（正常）、visibilityState=visible
        · **只关 guest 节流：30 次（正常）、visibilityState=visible** ←采用
        · 只开全局开关：30 次（正常）、visibilityState=**hidden**
        · 两者都不关：**3 次（被节流）**、hidden   ←对照组，证明测量有效
        全局开关会把工具自己主界面 2s/5s/10s/30s 的轮询在最小化时也全速跑；
        只关 guest 这一条效果更好（连 visibilityState 都保持 visible）。
        **注意 electron.d.ts 对 backgroundThrottling 的描述**（「同窗口里只要有
        一个 webContents 关了，整窗的帧合成都不再节流」）容易误读成「主界面也会
        全速」——实测**不会**：同一窗口里主界面的 setInterval 仍只有 3 次/3s、
        rAF 0 次，只有 guest 是 30 次/3s。别因为那句描述就把这个设置撤掉，先复测。
      3. 后端 `ai_browser.py` 的 `_wake_visible` / `_check_visible`：hidden 时
        先 `Emulation.setFocusEmulationEnabled` + `Page.setWebLifecycleState
        ('active')` + `Emulation.setVisibleSize` 唤醒，**仍 hidden 也不拒绝**，
        照常下发输入/截图，只在返回文案里如实提示风险。
    **最小化**：Windows 层语义会让 Chromium 判 hidden，但第 2 层（guest 关节流）
    实测能把 `visibilityState` 保持为 **visible**——真实最小化 + 连续 5 次点击全部
    送达（15~17ms），25 秒深冻结后点击仍是 1ms。所以第 3 层是**兜底**（页面被
    遮挡、被冻结、或读不到状态时才真正用上），不是常态路径。只保证「能操作」，
    用户此时看不到画面——与 zcode 无头模式同款行为，用户已接受。
    **受控实验的实测数字（真实最小化 + WebView guest，别再凭猜测写兜底）**：
    - 未唤醒的 hidden 页 `Page.captureScreenshot` 会**挂到超时**（8 秒都不回）
    - 先 `Emulation.setFocusEmulationEnabled` + `Page.setWebLifecycleState
      ('active')`，再普通 `captureScreenshot` → **66~86 ms 出图，尺寸正常**
    - 同一状态下 `fromSurface:false` **反而挂死**（别把它当成银弹；只能最后兜底）
    - `Input.dispatchKeyEvent` / 页面内 `canvas.toDataURL` 在 hidden 下本来就通
    - `Page.printToPDF` 在 Electron 的 guest 上**不存在**（`wasn't found`）
    - 慢页（40 万次 canvas 填充）首次截图 654 ms；导航中截图 51~67 ms
    因此后端截图逻辑：`_check_visible` 在读不到状态时会先唤醒一次（见下），
    截图自身在**未唤醒过**时补一次唤醒链，然后试真帧（整页 8s / 普通视口 3s）；
    失败才强制视口重截，最后退离屏（**不带 clip**，否则得到底部大片空白的废图）。
    三条都失败才报错，报错里列出每一步的原因。
    **每张截图最多跑一遍唤醒链**：跑两遍最坏多 80s（8 条 CDP 命令 × 10s 默认
    超时），叠加截图兜底与排队会烧穿 MCP 侧 100s 的 HTTP 超时
    （`_AIBR_HTTP_SLACK`），AI 那边先超时、后端还在傻跑。
    `_check_visible` 的三种情况：读到 visible → 不动手、不提示；读到 hidden →
    唤醒，唤醒后重读仍是 hidden 才提示；**读失败**（页面导航中/忙/超时）→ 照跑
    唤醒链并如实说「没读到可见性」（**不**谎称窗口不可见）。旧实现读失败就静默
    早退、一条唤醒命令都不发，页面正忙时反而毫无提示——已修，有回归测试。
    旧描述（「不可见就直接报错挡住」）已废弃。
    **审查 a699 时的复测更正（2026-11-25，隔离环境，Electron 45.4.1 / Chromium 156）**——
    上面「先唤醒再普通 captureScreenshot → 66~86ms 出图」在复测里**一次都没出现**，别照它推：
      - 最小化后页面活着（eval 2~4ms、rAF 照常、点击送达），但**帧呈现不出来**。唤醒链三步
        都不产生帧（5 种组合后立刻截图全部 6 秒无回应）；真帧那一步 5 次观测 5 次 3 秒超时，
        全靠 `setDeviceMetricsOverride` 兜底，而且**点过页面之后兜底也失效**：最小化 30 秒后
        「点击 → 截图」三条路全挂、共 31 秒（2/2）。
      - 修法在壳（`aibrRegister`）：AI 浏览器 guest **挂载即常驻 `beginFrameSubscription`**
        （按 id 只挂一次——did-attach-webview 对同一个 guest 会触发不止一次），之后最小化时
        截图 50~170ms；崩溃两次、舞台回收后重建、还原后再最小化都复测通过。
      - 订阅**必须在那次隐藏之前就在**：藏下去之后才挂约三成活（约 60 轮统计），所以不能
        跟着最小化状态挂 / 摘。代价实测：被控页 570x342、约 62 帧/秒动画时主进程 +2~4%
        单核，静止页面为 0；`incrementCapturerCount` 在这个版本已不存在。
      - **已知限制（没找到解法）**：窗口不可见期间 guest 一旦导航，截图就挂到窗口可见一次
        为止（还原后再最小化即恢复，页面不是白屏）。重挂订阅 8 次仍 0 帧、壳侧
        `capturePage` 直接 UnknownVizError、改订宿主页一样挂——别重复试。
      - 做这类实验的教训：窗口被真人还原会污染结论（一张挂了 28 秒的截图就是这样「成功」
        的），下结论前先核对截图前窗口仍是 hidden；「订阅收到几帧」在隐藏态导航之后不再是
        可靠的活 / 死判据，以产品截图的耗时为准。
  - 面板收起用近乎透明的后台态（`opacity: .001`），**不能 `display:none`**
    （实测此时截图挂死不返回）。面板被整个移除（关 tab / 切会话清场 / 被逐出）
    时 ResizeObserver **不报告**——必须另盯分屏 body 的子节点增删，否则网页层
    会以不透明、吃鼠标的前台态盖住窗格。
  - CDP 会话：`send(timeout=N)` 的 N 现在对齐单次等待（原先被建连超时 3s 封顶，
    截图 / 导航的 15~20s 名存实亡）；`wait_event` / `collect` 返回后必须恢复
    socket 超时。`Input.dispatchKeyEvent` 的 modifiers 位：Alt=1、Ctrl=2、Meta=4、
    Shift=8（Alt 曾误写成 4）。
  - 壳：`will-attach-webview` 凭分区名认出视图、紧随其后的 `did-attach-webview`
    认领进集合（**挂载即登记**，弹窗改道从这一刻起生效）；attach 只认登记过的
    视图；后端没明确回 `ok` 就算登记失败（不能默认成功，否则徽标谎报「已连接」）。
    后端 attach 只认现存的 `type=webview` target。
  - AI 自动展开**不是用户动作**：`_subShow(tid, false)`，不许把会话记成「想让
    分屏开着」（a638：否则用户亲手关掉的分屏切回会话时会自己弹出来）。
  - **下载中心（2026-11-24 用户令；起因：工具内 AI 点「下载资源包」后照页面文案
    说「浏览器下载列表可见」，而壳里根本没有下载列表；用户自己在网页标签页里下载
    更是点了保存就没下文）**——独立模块 `src/downloads.py`（蓝图
    `/api/downloads/{report,list,config,forget,open}`），**AI 浏览器与普通网页
    标签页的下载共用**：
    · 不弹保存框，直接存进下载目录；顶栏右侧「下载」钮（`web/js/downloads.js`）
      是浮层面板：进度条 / 完成 / 打开 / 所在文件夹 / 取消 / 移除记录；面板没开着
      时下载结束弹横幅。AI 用 `browser_downloads` 拿真实路径。
    · 下载目录（用户令：默认跟随数据目录，可手动另行指定）= `st.download_dir()`：
      config 的 `download_dir` 非空就用它，否则 `数据目录\download`。默认那个跟
      数据目录走：迁移时随「全部子目录」一起迁、卸载时随 data 整目录保留。**别放
      工具目录下**——卸载器会连它一起删，而且 `APP_DIR` 不认隔离开关（测试会写进
      真实目录）。配置接口 `_check_custom_dir` 拒绝：相对路径 / 磁盘根 / 数据目录、
      工具目录、锚点、用户主目录本身 / 系统目录 / 建不出或写不进的位置。
    · 壳：两个分区的 session 都挂 `will-download`（`DL_SOURCES`：AI 浏览器与网页
      标签页 `persist:webtabs`）；目录**只认**下载中心 `GET /api/downloads/config`
      给的、且 `usable` 才接管（壳不自算；否则退回弹保存框）。后端地址一有就取
      一次、每笔下载结束后重取、30s 轮询兜底、界面改了配置经 IPC `fc:dl-refresh`
      立刻重取。`setSavePath`（同名加 `(n)` 不覆盖；文件名清洗：去路径分隔符 /
      尾随的点 / 保留设备名）→ 每个阶段 POST `/api/downloads/report`。工具自己的
      主界面用默认 session，不在接管之列（导出 / 另存为照旧）。
    · **Electron 的 `updated` 事件带的 state 是 `'progressing'`，不是文档写的
      `'in_progress'`**——按后者过滤会把进度帧全吃掉，面板上的进度条从头到尾是
      0（2026-11-24 端到端旁听实锤；此前的单测是直接往接口灌进度，绕过了壳这段，
      一直没发现）。「还没结束」以 `dlItems` 为准。
      `test_shell_takeover_reports_progress_whatever_the_event_state_word_is` 用 Node
      真执行壳的 `dlTakeOver`，并按实测的那个词去触发事件（做过反向验证：改回
      旧写法它会红）。
    · 硬约束：**「完成」后端必须自己到磁盘核实**文件在下载目录里才给路径（AI 会
      照着它去读文件）；只有 AI 浏览器来源的下载才推 `ai_browser_op`（状态条）——
      普通网页的下载若推，`op()` 开头会把分屏给展开。SSE `kind="download"` 由
      `sense.js` 转给 `window.DL`，不进感知流。`open` 只认下载目录本身与它第一层
      现存的条目。记录只在内存。HTTP 头里的文件名优先于 `<a download>`（写测试页
      别两个都给）。下载落盘后调 `data_hygiene.invalidate_usage_cache()`。
    **删除入口（2026-11-24 用户令）**：统一在 设置→数据目录→「可清理项」里，且
    **只在那里**删，且**只对默认目录开放**——用户手动指定的下载目录工具只往里存、
    不提供清理（`download_dir_is_default()`：那里面可能有用户自己的文件）。
    `downloads` 是 `_CLEANABLE` 的一员，但与串口日志同款：后台
    不删、`policy` 不删、AI 不删（`browser_downloads` 只读），只认用户的手动
    「按天数（7/30/90）」或「全部清空」。只碰下载目录**第一层**的普通文件
    （`_download_files`：进行中的 `*.crdownload`、子文件夹、符号链接都不动）；
    占用与清理共用这一份口径（统计多少 = 能删多少）。想删别的只能用户自己去
    文件夹。**删法是移入系统回收站**（`_dl_recycle`，与文件树删除同一实现）：
    下载的是用户的文件，删错能找回；回收站不可用或失败就**不删**，绝不退回
    `_try_rm`。只有本地固定硬盘才有回收站（`_dl_recyclable`）——网络位置 / U 盘
    上的删除是永久的，界面据 `targets.downloads.trash` 如实警告、成功提示不说成
    「释放」。静态守卫：`test_no_code_deletes_downloads_outside_manual_clean`
    （照串口日志「后台永不删除」的写法；另钉下载分支不走 `_try_rm`）。
  - **对抗审计第二轮后的约束（a693）**：监听线程的退避必须能被 `_wake` 打断；
    `_observeSlot()` 幂等（建舞台 / 面板已存在 / 面板新建三条路径都调）；回收
    计时只在三处重置（转前台 / 转后台 / AI 的每步操作），`_sync` 末尾不许无条件
    续命；壳认领 guest 首选分区判据 `aibrIsAiGuest`，`aibrPending` 只做兜底
    （两个 webview 的挂载事件会交错）；操作锁排队有上限（`_OP_QUEUE_WAIT`），超了
    快速失败；MCP 侧的等待必须夹限（HTTP 超时是按它算的）。
  - **铁律·操作工具界面的唯一合法通道（2026-11-26 用户令，最终版）**：
    **永远不允许直接操作工具本体。任何 CDP 操作都必须用 AI 浏览器完成。**

    **不得裸连 CDP**：禁止 `find_page_target` / `find_cdp` / `CdpSession` /
    `Runtime.evaluate` 等一切直连 9222 的脚本手段。`src/devtools_cdp.py` 的
    调用方白名单**只放行 `src.ai_browser`**，随手写的脚本第一次调用就报
    「禁止裸连 CDP」。唯一例外是 `tests/` 里跑在隔离 CDP 口（`FC_CDP_PORT`）
    上的契约测试——那是契约测试，不是拿 CDP 当遥控器操作真实工具。

    **`devtools_*(target="app")` 已删除**（2026-11-26 用户令）。它曾直连工具
    本体的 CDP，等于 AI 能 eval / reload / 派发事件直接改用户界面——实锤：AI
    用它执行 `location.reload()` 重载了用户的工具窗口。那不是诊断，是操作本体。
    现在 `devtools_*` 五个工具都只是 `browser_*` 的同义词，`target` 参数整个移除。

    **想操作工具界面？它就是网页**：`http://127.0.0.1:<后端端口>/`。
    `browser_navigate` 打开它，之后全程 `browser_*`。端口从
    `GET /api/ai/mcp_info` 的 `backend_url` 或锚点 `endpoint.json` 取，
    **不要记忆**（每次启动会变）。

    改完前端代码必须 `location.reload()` 再验证——不重载时 window 上还是旧
    函数，任何结论都不成立。合成事件测不了 OS 拖放，拖拽类改动请用户实际拖一次。

  - **铁律·禁止改用户窗口状态（2026-11-25 用户令，事故级）**：见上文「禁止
    操作用户窗口」——不得 `SetWindowPos(HWND_TOPMOST)`、不得最大化/改尺寸。
    调试要窗口可见就**请用户点一下**，不许自己去置顶。
  - 验证：单测 `tests/test_ai_browser.py`（含三端契约字面量）；端到端走隔离
    环境（独立 CDP 口 `FC_CDP_PORT` + 独立 userData + `FC_STATE_DIR`，壳的
    三段代码从真实 main.js 切出），**不得连真实壳的 9222**。会写盘的场景（下载）
    前必须有隔离闸门：后端自报的各路径、接口给出的目录、**壳自己报的**它实际
    拿到的目录三处都在沙箱内才触发；比对函数先拿已知在内 / 已知在外的各比一次
    （「在沙箱内」= 是根或在根之下；别拿「数组非空」当判定，那是恒真的假明细）。
    实验窗口被遮挡时浏览器暂停 rAF、点击被拒，会整批出环境性失败——先看编排
    打印的「宿主可见性」观察行再下结论。脚手架要可重复运行：上一轮若在「改下载
    目录」之后异常中断，沙箱 config 里会留着自定义目录，闸门会（正确地）拦下——
    只有确认那个目录也在沙箱内时才替它恢复默认；同名文件的残留会让下一轮的下载
    带序号（同名不覆盖），场景开头先清。
- 惯例：用户拍板/用户令的历史一律写进对应代码的注释；提交号 aNNN 递增
