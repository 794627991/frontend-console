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
  - 工具窗口不可见（最小化 / 被完全遮挡）时 Chromium 不派发输入、不出帧：
    输入与截图会挂到超时——后端已前置检查，直接报「窗口不可见」。最小化再
    还原后浏览器**不一定**把页面重新判为可见（干净窗口的对照实验里时好时坏，
    环境现象）——用户点一下工具窗口即可，不是缺陷。
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
