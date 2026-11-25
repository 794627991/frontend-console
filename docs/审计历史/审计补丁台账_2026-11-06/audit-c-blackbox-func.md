# 对抗式黑盒功能攻击报告 C · 界面与 API（a392）

- 测试对象：http://127.0.0.1:8867（v4.1.0-a392，boot log 实证）；CDP 9223 独立 target；根库 f93dd9f2b98437bd（D:\AI\前端控制台，sqlite 档，458,264 符号）
- 视角纪律：全程黑盒——只从用户/攻击者视角打界面与 API，未读实现代码找 bug（仅环境侦察读路由签名/fixture 指纹规则/配置路径）；零文件修改（本报告除外）；根库全程只读、终态完好（backend=sqlite、tags.db 在场、四接口锚点正常）；零 git 操作；真电源计划未触碰（档位测试只走取消路径）
- 已知台账避让：R35 终版（S35-1~6/S36-1 全闭环）与 A 组（S37-1~12）已读，本报告新实锤均不与已知项同根因；黑盒撞到同源现象的单独标注

---

## 结论先行

**实锤 2 件（P2×2），已知项黑盒复现 1 件（S37-9 同源），观察项 4 条。** 主题一句话：**readtags 档对中文符号整体失明（definition/symbols 三级查询全空，跨档口径撕裂），索引面板档位确认弹窗被自身面板遮挡（z 200 vs 9999）导致切档交互不可达、下拉显示与库实际脱节**；其余攻击面——API 门卫、注入形态、并发齐轰、互斥 409、切档竞态、跳转链全链、文件内符号全链、Hover、极限文件——全部按预期防御或正确工作。

| # | 分级 | 主题 | 一句话 |
|---|---|---|---|
| C-1 | **P2** | readtags 档中文符号全灭 | 中文函数/类的 definition 与 symbols（exact/prefix/substring 三级）在 readtags 档恒空；memory/sqlite 档同查询命中 |
| C-2 | **P2** | 档位确认弹窗被索引面板遮挡 | modal z=200 < 面板 z=9999——「切换查询模式」弹窗完全不可见，取消/确认不可达，取消后下拉不回显（显示已切、库未切） |
| 复现 | — | S37-9 同源 | reindex 后 status.size 缺 tags.db 项：报 183.5MB，磁盘实占 412.6MB |

---

## 实锤详证

### C-1（P2）：readtags 档中文符号查询全灭——definition/symbols 双接口跨档口径撕裂

- **复现步骤（fixture 库，三档对照）**：
  1. 建含中文符号的 fixture（`unicode_sym.py`：`def 中文函数甲(x)` 行 2、`def 中文函数乙(x)` 行 5、`class 蓝牙配置类` 行 8；ctags 三档共用同一份 tags 文件）
  2. `POST /api/nav/reindex {backend:"readtags"}` → poll 完成（meta.backend=readtags）
  3. `GET /api/nav/definition?root=…&file=…\unicode_sym.py&symbol=中文函数甲` → **200 `candidates:[]`**
  4. `GET /api/nav/symbols?root=…&file=…&q=中文` / `q=蓝牙` / `q=甲`（单字）/ `q=函数`（中缀）→ **全部 `items:[]`**
  5. 同参数切 memory 档 → definition 命中 `unicode_sym.py:2`、symbols 命中 `蓝牙配置类`；切 sqlite 档 → 同样全命中
- **预期 vs 实际**：预期三档同一份 tags 数据同一查询口径一致；实际 readtags 档中文符号 definition/symbols **全空**，英文对照（`unique_single`/`fn_` 前缀/`REPL` 大写 substring）全部正常——失败精确隔离在"中文符号 × readtags.exe 进程查询链路"。**references 不受影响**（中文符号引用正常返回 unicode_sym.py:2,6——rg 链路）。tags 文件本身含中文名（memory/sqlite 档即从它读出），排除索引缺收录。
- **黑盒根因边界**：readtags.exe 为外部进程，查询串经 Windows 进程参数传递（CreateProcessW→ANSI argv）或 stdout 解码与 tags 的 UTF-8 不匹配；进一步定位需白盒，黑盒止步于"readtags.exe 链路对 UTF-8 查询串失明"。
- **影响面**：显式/自动落到 readtags 档的中文工程（国内工程中文函数名常见）——Ctrl+T 搜中文、F12 跳中文定义全部静默空结果，无任何错误提示。与 A 组 S37-1（memory 档 prefix 大小写）、S37-7（readtags 参数注入）均不同根因。
- **严重级**：P2（核心功能静默错误；触发需 readtags 档，大库 auto 判档下是默认档之一）
- **证据**：探针脚本与输出 `.zcode/tmp/caudit/api_attack5.py`（T1 三档对照表：def_cn/sym_cn 两项 readtags DIFF）、`api_attack6.py`（9 探针收窄：英文全过、中文全灭、references 正常）

### C-2（P2）：索引面板档位下拉的确认弹窗被面板自身遮挡（z 200 vs 9999）——确认交互不可达、取消后下拉不回显

- **复现步骤（真机 UI，CDP 真鼠标/键盘）**：
  1. 文件树根行（前端控制台）右键 → 菜单点「代码索引...」→ 索引面板打开（显示 sqlite 档、458,264 符号）
  2. 点击档位 `<select>` 聚焦，按 `r`（原生类型跳选）→ select 值变 readtags
  3. **0.5s 即时截图（i7_confirm_immediate.png）**：画面上只有索引面板，**无任何弹窗**
  4. DOM 探测：`modal show` 元素存在，内含「切换查询模式」标题与「取消」按钮，`position:fixed; z-index:200`
  5. 索引面板容器：`position:fixed; z-index:9999` —— **弹窗被面板完全覆盖**
  6. 点击弹窗「取消」按钮坐标后：select 仍显示 `readtags`；`GET /api/nav/status` 服务器 `backend=sqlite`（库未被误切——**取消路径的数据安全保持住了**，但 UI 不知道）
- **预期 vs 实际**：预期弹窗置顶可见、用户可确认/取消、取消后下拉回显原档位；实际弹窗 z=200 被面板 z=9999 盖死，用户改档后看不到任何确认提示；无论用户点什么，下拉显示新档位而库保持旧档——**显示与实际脱节**，直到重开面板（重渲染按 meta 恢复 sqlite）。
- **影响面**：ctags-mem-v2 §4.0.1 的核心交互（三档切换）在索引面板内全部经过此弹窗——sqlite↔readtags↔memory 任意方向切换的确认流程均被遮挡。用户实际能完成切档的唯一途径是点「重建」（走 reindex POST，不经弹窗），档位下拉+确认弹窗组合在当前层叠关系下不可用。
- **与已知项边界**：R35-S35-5 是"status 不下发 backend→下拉显示不跟随"（数据链，已闭环）；本条是弹窗层叠遮挡+取消回显缺失（纯 UI 交互层），A 组未触及 UI。
- **严重级**：P2（核心交互不可用/误导；数据安全侧因取消路径"静默不切"而未受损，一旦用户在被遮挡的弹窗上盲操作「确认」则行为不可预期）
- **证据**：截图 `i5_confirm_r.png`/`i7_confirm_immediate.png`/`i8_confirm_later.png`（弹窗全程不可见、select 已变 readtags）、z-chain DOM 输出（modal show z=200 vs 面板容器 z=9999）、取消后 status backend=sqlite 对照

### 已知项黑盒复现（同源，不计新实锤）

- **S37-9 同源**：projbig（110 万 tag 行）reindex readtags→sqlite 后 `status.meta.size=183,512,091`（仅 tags 项）；磁盘 lib 目录实占 `412,597,672`（tags 183.5MB + tags.db 229.1MB）——面板显示虚低 229MB。与 A 组 S37-9（reindex 只改 backend 两键不更新 meta.sizes.db）同根因，黑盒数字级复现。

---

## 通过清单（打了什么、没炸什么）

### API 层（/api/nav/*）

| 攻击 | 结果 |
|---|---|
| root 越界/逃逸（`..`、`..\..\..`、`C:\Windows\System32`、小写盘符、超长 300、NUL 设备） | **全部 400 拒绝**（归一后不在登记根内，fail-safe 方向正确） |
| root 宽松形态（`.`、文件路径当 root、带引号、尾空格、尾点、尾反斜杠） | 归一后自洽响应（has_code=false 或正确映射根库），无错数据注入 |
| definition/symbols/references 怪参（缺参/空参/不存在符号/`-l`/引号/5000 字符/SQLi 形态 `%' OR 1=1--`） | 优雅空结果（mode=not-found/empty）或 400，无 500、无注入效果、无崩溃 |
| reindex 对无索引目录 | 400「该目录没有索引库」✓ |
| reindex 怪 backend/缺 backend | 400「backend 须为 memory/readtags/sqlite」✓ |
| 10 并发 references 齐轰（同符号） | 10/10 200，wall 1.9s，结果一致（items=2） |
| 5 references + 5 poll 混合并发 | 10/10 200，poll 9ms 不被重查询阻塞 |
| **互斥 409 语义**（110 万行 sqlite 重建窗口内） | reindex#2 / build / cg_build **全部 409**「已有索引任务在运行（root）」✓（注：readtags/memory 切档仅删文件+写 meta，毫秒级完成，窗口太窄撞不到互斥属正常） |
| **查询并发下切档**（def/sym 查询循环 × 5 轮三档来回切） | 查询零错误（0 个非 200），最终四接口口径正确 |

### 三档口径一致性（9 探针 × memory/readtags/sqlite）

- definition×3（含大写查询、中文）、symbols×4（前缀/大写/中文/中缀）、references×2：**memory 与 sqlite 全项 SAME**；readtags 除中文两项 DIFF（即 C-1）外全 SAME。
- 大小写不敏感（`DUPE_FN`→dupe_fn 两候选）、substring 三级兜底（`REPL`→repl）三档行为一致 ✓

### UI 跳转链（真鼠标/键盘，CDP Input）

| 攻击点 | 结果 |
|---|---|
| F12 单候选（unique_single 调用处） | 直跳 main.c:5 定义行 ✓ |
| F12 多候选（dupe_fn：main.c:7 + extra/dupe.c:2） | 直跳排序最优候选（main.c:7）；完整候选列表由 Ctrl+T 面板承载（两行候选、带行号与 kind 标注，截图 j12r_typed.png）✓ |
| F12 无索引符号（printf） | 底部 toast「未找到定义（无索引或符号不在库内）——文件树右键可建索引」，不炸、光标不乱跳（截图 j5）✓ |
| Ctrl+Click 跳转 | 与 F12 同效（main.c:5）✓ |
| Shift+F12 引用面板（g_ref_target） | 面板「「g_ref_target」的引用 1 处（定义行已排除）」列出 main.c:16；**生成文件 gen/moc_gen.c 中的引用被黑名单正确过滤**（API references 同口径）✓（截图 j11） |
| Shift+F12 面板 Esc 取消 | closed ✓ |
| Ctrl+T 键盘链 | 打开自动聚焦（dd-input）→ 输入过滤 → Enter 跳转（main.c:7）→ Esc 关闭 → 重开 ✓ |
| Ctrl+T 面板点击落点+高亮 | 点击第二候选（extra/dupe.c:2）：**未开文件自动打开**、落点行精确（`int dupe_fn(int a) { return a * 3; }`）、wordHighlight 高亮词生效（截图 j17）✓ |
| 中文目录+空格文件名（`中文 目录\空格 文件.c`） | 双击打开 ✓、F12 空格函数直跳 line 2 ✓ |
| 键位作用域 | F12/Shift+F12/Ctrl+T 三键统一要求编辑器焦点（焦点在文件树/body 时静默无响应）——与 VSCode 惯例部分差异，归观察项 |

### Ctrl+Shift+O 文件内符号

| 攻击点 | 结果 |
|---|---|
| main.c 面板+键盘链 | 打开自动聚焦、输入 dupe、Enter 跳 main.c:7、Esc、重开 ✓ |
| 2 万行 py（big20k.py） | 打开 1.8s；fsym 输入 repl → Enter 跳 `def repl(n):`（line 1，多定义第一候选）✓ |
| 同名多定义（repl×2 @1/101） | 候选可达（Enter 取第一；列表含多候选由面板承载）✓ |
| 中文过滤（unicode_sym.py 输入"中文"） | 面板列出 `function 中文函数甲 :2`、`function 中文函数乙 :5`（截图 o4）✓——文件内符号链路不走 readtags.exe，中文完好（反证 C-1 边界） |
| 0 字节 zero.c | 打开正常、fsym 面板正常（空符号集不炸）✓ |
| 1MB 单行 onelong.c | 渲染无卡死；fsym 候选 `function one_long_fn :1`（截图 e2r）✓ |
| 二进制伪装 .c（binfake.c） | 双击弹「选择打开方式」防护对话框（二进制打开/阅读器打开/编辑器打开三分，截图 o6）——**防误开守护正确**，非缺陷 ✓ |

### Hover（真鼠标 Input.dispatchMouseEvent）

- function（unique_single：`unique_single function` + 定义 snippet + `main.c : 5`）、struct（ChipCtx：`ChipCtx struct` + typedef snippet + `main.c : 9`）、variable（g_ref_target：`g_ref_target variable` + `main.c : 11`）三类 token 悬停卡片全部正确（截图 h1/h4/h3r）✓
- 快速掠过 17 行 token（1115ms 完成）：无崩溃、无 console 错误、无残留卡片异常 ✓

### 大文件/极限（API+UI）

- 42MB/110 万行文件（readtags 档）：definition API **186ms** 命中行正确 ✓；symbols scope=file 6.5s（readtags `-l` 全扫，R35 观察项 5 已知，非回归）
- 索引面板渲染（45.8 万符号根库）：符号数/编译白名单/ELF/占用 105.6MB/sqlite 档位显示全部正确（S35-5 修复侧验证）✓

### 未执行项（诚实声明）

- **设置页 6 键录制/档位确认弹窗的"确认"路径**：设置页入口在黑盒 DOM 侦察中未定位（topbar 无设置按钮、无"设置"文本元素、齿轮类选择器 0 命中）；档位确认弹窗的「确认」路径因 C-2 遮挡不宜盲点（会真切根库档位），只验证了取消路径。fsym 落盘问题已有 A 组 S37-5 白盒实锤，未重复构造。
- **VCS 页**：入口未定位（全 DOM 无版本/变更/VCS 入口元素；文件树右键菜单无版本项）；svn 1.14.5 本机可用，若产品存在入口则具备后续测试条件。

---

## 观察项（不实锤，供跟踪）

1. **三跳转键的编辑器焦点依赖**：F12/Shift+F12/Ctrl+T 在焦点位于文件树/页面 body 时静默无响应（无提示、无 toast）。Ctrl+T 在 VSCode 是全局命令，此处行为偏窄——是否设计使然待定性。
2. **模型 URI 盘符小写**：文件树打开的文件 model URI 为 `file:///d%3A/AI/...`（小写盘符），与 tags 存储形态（大写盘符）形态不一致；当前由 normcase 兜底未显性问题，形态漂移敏感面（与 R35-S35-6 残留观察同族）。
3. **readtags 档 scope=file 全扫时延**：120 万行库 6.5s/次（R35 观察项 5 延续，UI title 提示"约0.2s/次"不含此形态）。
4. **共享服务器静默死亡 ×2**：测试期间 8867 两次进程消失（无 traceback/core、端口直接消失）。`server_restart.log`（1.3MB）实证同期另一测试组（resdfx fixture、fx_* 符号、独立 reindex、秒级数十请求）在轰同一实例——多客户端重载并发背景明确，无法归因单客户端触发；已两次重启恢复，根库数据完好。**建议**：nav 索引查询/构建为重载面（memory 档 110 万条目 dict、rg 全根扫描），共享演示环境上宜有资源护栏（归产品观察，非本轮实锤）。

---

## 方法说明

1. **通道**：CDP 9223 直连（websocket-client 1.9.2），每次测试新开独立 target（`http://127.0.0.1:8867/?r=<时间戳>`），`monacoInit()`/`.monaco-editor` 探活；鼠标/键盘一律 `Input.dispatchMouseEvent/dispatchKeyEvent`（真输入，杜绝合成事件失真——期间实证合成 click 对根头/左栏 sheet 失效）；每步 Page.captureScreenshot 留证。
2. **fixture**：三套——`.zcode/tmp/cfix/proj`（API 三档库：单/多候选、生成文件指纹、中文符号、中文+空格路径、2 万行、1MB 长行、0 字节、二进制 .c）、`.zcode/tmp/cfix/projbig`（42MB/110 万行重载库）、`_caudit_tmp/proj`（树可见 UI 库，因文件树隐藏点开头目录）。生成文件指纹按产品识别规则构造（"Generated by Cython" 头）。
3. **收尾**：断言式清理——2 个 fixture 工程目录 rmtree 后断言不存在；3 个索引库（fb52cf67add76bd2/734ddb1e16b5750c/271d5029633fe498）删前逐个读 meta.json 断言 root 指向本组 fixture 后 rmtree+断言；根库终态 backend=sqlite、tags.db 在场、四接口正常。他组现场（05bed852/resdfx）与历史孤儿库（211c/7e43/8207，R35 前残留）未触碰。测试脚本与 30+ 张截图保留于 `.zcode/tmp/caudit/` 供复核。
4. **已知项避让**：R35 终版台账与 A 组 12 实锤逐项比对；C-1 与 S37-1（memory 档 prefix 大小写）/S37-7（readtags argv 注入）按符号集与链路区分；C-2 与 S35-5（backend 数据链）按 UI 层叠 vs 数据链区分；size 现象主动标注 S37-9 同源不计新。
