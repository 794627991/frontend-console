# 补丁 · 第 4 轮（提案，未应用）

> 生成：2026-11-13（R4 收尾）。依据：`rounds/round-4-whitebox.md`（W28–W30）+ `rounds/round-4-blackbox.md`（B16–B19）。
> 性质：**纯提案 md，未修改任何代码文件**。本轮特征：白盒确凿收敛（13→7→7→**3**，全 P3）；黑盒 4 条全部为 N3/N5/N1' 的请求级验收基线补形。叠装一致性（白盒 R4 评审核验）：**三份补丁 hunk 零冲突、语义零作废**。

---

## 一、确定性补丁

### N4'（修 W30/P3）——fetch_text 错误分支保全 HTTP 状态码

N4 的 `_hint` 映射表不含 `HTTPError`：目标 404/403/500 → 「取页失败：HTTPError」，比基线 `str(e)` 更不可诊断。在通用分支**之前**加专门分支（N1' 的重定向 HTTPError 已在循环内消费，此处只接非重定向）：

```diff
--- a/src/web_proxy.py（替换 patch-round-3 N4 的 except 块）
@@
-    except Exception as e:
-        # R3 审计 B12：内部异常原文不外露（非 ASCII 主机的 latin-1 编码
-        # 异常等直出到响应体）——常见失败给可读文案，其余只给类型名
+    except urllib.request.HTTPError as he:
+        # R4 审计 W30：非重定向 HTTPError 必须带状态码——404/403/500 的
+        # 可诊断性不能低于基线 str(e) 形态
+        return jsonify({"ok": False,
+                        "err": "取页失败：目标返回 HTTP %s" % getattr(he, "status", "?")})
+    except Exception as e:
+        # R3 审计 B12：内部异常原文不外露（非 ASCII 主机的 latin-1 编码
+        # 异常等直出到响应体）——常见失败给可读文案，其余只给类型名
         _kind = type(e).__name__
```

---

## 二、设计项登记

### D8（W28 + W29，P3）——「前端 `_nav` 栈 vs 后端原生历史」双轨失步

R1-R3 只审过双轨的**归属语义**（B1/B7/A8 族，已收敛）；R4 首次触及**内容语义**，产出两形态：

- **W28**：`__webTabUrl`（web-panel.js:314-327）的栈规则只为「用户导航」设计，却同样作用于后退/前进的 SourceChanged——跨站 back = push（栈膨胀 `[A,B,C,B]`、50 帽加速淘汰真实历史），同站 back = 原地覆盖（前进项暂失、再前进自愈）。消费点全部读栈顶**恰好保持正确**，危害限于簿记失真。
- **W29**：休眠/阅读模式写入的 about:blank 原生历史项——唤醒/退出阅读用 `Navigate(url)` 新开条目，原生历史成 `[…, B, about:blank, B']`；用户按 ◀ 落白屏，而 a556 的 about:blank 事件过滤使前端永不知情（地址栏停在 B'、◀ 仍可按）。再按一次 ◀ 或 ▶ 可走出。

**修复方向**（白盒 R4 给出，需与 D 栈同批实现）：
1. 导航来源区分：`_webCtl back/fwd` 时前端打标志消费下一条 SourceChanged（或后端在事件里带导航类型），后退/前进对栈做 pop/`idx--` 而非 push/覆盖；
2. 内部导航不进历史：休眠/阅读的 about:blank 与唤醒的 Navigate 改「Navigate 后 GoBack 剔除」或后端为内部导航打「可回退剔除」标记；唤醒优先 `GoBack/GoForward` 回真实条目。

**风险注记**：本项涉及导航语义重写，必须保护 A8'/B10 已收敛的 tab 归属语义与 a556 的 about:blank 过滤——**不建议单独热修**，与 D 栈（W3/W4/W8/D1''）同批实现、同批桌面验证（手册 #5/#10 关联）。

---

## 三、验收基线与记录（不打补丁）

| 项 | 内容 |
|---|---|
| **B16（P1）** | **N3 验收基线（请求级）**：侧栏 ✕ 关网页 tab = `POST /api/disconnect {"port_id":"web:1"}` 必败噪音 + **dispose REST 缺失**；resize 时幽灵监听发 `{"act":"layout","x":0,"y":0,"w":0,"h":0,"tab":"web-1"}` 与存活 tab 同帧并发。N3 应用后的回归断言：dispose 出现、噪音消失、幽灵 layout 归零 |
| **B17（P2）** | N3 细化：每关一个**激活态**网页 tab 永久累积一个幽灵（resize 反复重发）；**后台态关闭有 `display:none` 守卫不发幽灵**；「存活控件缩 50×50」桌面后果存疑（无头不可达）→ 手册 #11 |
| **B18（P3）** | **N5 验收基线（7 格）**：缺 url 元素 tooltip 泄露 `"undefined"`、数字 url 污染导航栈——N5 的 `typeof x.url === 'string'` 过滤恰好同时覆盖；尾斜杠=独立收藏（精确串去重，cosmetic 维持）；100 条上限保最新 |
| **B19（P2）** | **N1' 验收基线**：重定向环 12 跳 0.098s 优雅失败（基线无挂死）；Location 空格/百分号/相对路径全通；**302→跨主机自签 https 取页成功 = CERT_NONE 跨主机链路实锤**——N1' 应用后此格必须翻转为失败 |
| **N3 时序** | N3 第二 hunk（util.js 抽屉分支）在 **A7（W9 修复）落地前不可达**（B15：web 根本不进抽屉）——应用顺序：先 A7 后 N3-2；第一 hunk（sidebar.js）即时可达 |
| N1' 观察 | 跳数×超时放大上限 6×15s=90s worker 占用——本地单用户可接受，记录 |
| 叠装一致性 | 白盒 R4 全量对账：patch-round-1/2/3 **hunk 零冲突**（web-panel.js 七补丁行段对账）、**语义零作废**（A4/A8/A10 修订链、N1→N1'、A2+N2 串行、epoch 后缀下游兼容） |

## 四、建议新增测试（增量）

20. N4'：404/500 目标 → 断言 err 含状态码；302 目标 → 断言不被误报为 HTTPError。
21. D8（实现后）：跨站 back 栈形态 `[A,B,C]` 不膨胀；休眠唤醒后 ◀ 不落 about:blank。

## 五、收敛状态（R5 入口）

- 白盒静态产出率：13→7→7→**3**（全 P3）；patch-round-3 五条补丁全对抗通过；三份叠装零冲突。
- 白盒 R5 候选（静态可达）：`_webSleep/_webWake` 状态机角落、`_webFavMenu` 其余分支、`main.py _patched_ready` 交互面（右键×preventDefault、load_html）、双轨历史近邻形态、D3 会话语义静态推演。
- 桌面-only（进验证手册，双通道均不可达）：per-monitor DPI/`Form` 原点假设、a551×HWND 叠放矩阵、休眠真机全链、`_ensure_env`/`install` 二次装配（tray/watchdog 主窗重建）、target=_blank 真实流。
