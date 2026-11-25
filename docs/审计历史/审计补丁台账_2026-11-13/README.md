# 内嵌浏览器（路线 A）对抗审计总纲

- **审计对象**：`git diff 6504d07^..HEAD`，即 `v4.1.0-a473`（6504d07）→ `v4.1.0-a556`（d9c8886）共 **85 个提交**。
- **功能主线**：内嵌浏览器路线 A —— 网页 tab + 工具栏地址栏 + 收藏夹 + 发给Claude + CDP 解禁（L3 地基）。
- **形态演化**：a501–a543 为 iframe + Web 代理方案；a544/a545 整体退役，**终局形态 = 每个网页 tab 一个 WebView2 浏览器控件实例**。审计以 HEAD（d9c8886）当前代码为准；退役残留（死代码/孤儿端点/半删逻辑）同样计入发现。
- **基线**：d9c8886，工作树必须保持 clean。

## 覆盖文件（净改动 14 文件 / +2075 行）

| 文件 | 改动 | 内容 |
|---|---|---|
| `src/web_tabs.py` | +484 | WebView2 多控件生命周期/导航/事件推送/Bounds 布局 |
| `web/js/web-panel.js` | +755 | 前端 tab 管理/地址栏/收藏夹/发给Claude |
| `src/main.py` | +86 | 装配、NewWindowRequested、右键、CDP |
| `src/devtools_cdp.py` | ±11 | CDP 解禁 |
| `src/web_proxy.py` | +103 | 代理时代残留 |
| `src/server.py` / `src/tray.py` | ±37/±1 | 挂接点 |
| `web/index.html` / `settings.js` / `sidebar-resize.js` / `util.js` / `style.css` | ±183 | UI/联动 |
| `tests/test_web_tabs_logic.py` / `tests/test_web_fetch.py` | +433 | 逻辑测试 |

## 方法与轮次

每轮**并行派出且仅派出 2 个子代理**：1 白盒（代码对抗审）+ 1 黑盒（隔离实例 GUI/API 实测）。
发现汇总到 `rounds/`；每轮结束后由主控输出补丁 md 到 `patches/`（**只写 md、绝不改代码**）。
下一轮审计带着上一轮全部发现与补丁，重点转向：新问题、补丁正确性推演、上轮盲区。
**终止条件**：连续一轮（白+黑）零确凿新问题 → 审计结束，输出 `SUMMARY.md` 终版台账。

## 铁律（所有轮次、所有参与者）

1. **绝对不允许直接改代码**：仓库内唯一允许写入的路径是 `docs/审计补丁台账_2026-11-13/**`。补丁只以 md 形式输出。
2. 禁止任何改变工作树/历史的 git 操作（add/commit/checkout/stash/clean）。
3. **用户实机正在运行**：`http://127.0.0.1:56278`（pid 4068）——禁止杀/重启/干扰；只允许 GET 类无破坏探测；禁止在实机上创建/销毁网页 tab。
4. 黑盒测试一律用隔离无头实例（`USERPROFILE=<临时目录>` 重定向 + `python src/server.py`，端口 8765），临时文件放系统临时目录。
5. 同一时刻最多 1 白盒 + 1 黑盒两个子代理。
6. 分级纪律：**确凿**（有代码依据或可复现）与**存疑**（推测）必须分开，不许混级。

## 文件结构

```
docs/审计补丁台账_2026-11-13/
├── README.md          # 本总纲
├── STATUS.md          # 轮次状态（兜底定时任务的依据）
├── rounds/            # 每轮白盒/黑盒报告
│   ├── round-N-whitebox.md
│   └── round-N-blackbox.md
├── patches/           # 每轮补丁（md 形式，不落盘代码）
│   └── patch-round-N.md
└── SUMMARY.md         # 终版台账
```
