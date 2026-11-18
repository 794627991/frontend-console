# 模块化回归测试（js-modularization 分支）

本目录是「harness/前端模块化改动」的饱和式回归测试存档。

## 目录

| 文件 | 用途 |
|---|---|
| `测试计划.md` | 分层、判据、环境、执行策略、额度预算 |
| `用例明细.md` | 约 100 条用例全表（ID / 前置 / 操作 / 断言 / 层 / 脚本映射） |
| `测试报告.md` | 每次执行的结果留档（PASS/FAIL/SKIP + 证据） |
| `../../tests/regression/` | 可执行测试脚本（L0 静态 / L1 启动 / L2 CDP / L3 真实 CLI） |

## 快速执行

```bat
rem 全量（跳过 L3 真实 CLI）
python tests\regression\run_all.py --layers L0,L1,L2

rem 单层
python tests\regression\run_all.py --layers L1

rem L3（真实消耗 Claude CLI 额度）
python tests\regression\run_all.py --layers L3 --groups H1,H3,H4

rem 结果自动追加到 docs\modularization-regression\测试报告.md
```

前置条件：前端控制台应用正在运行（主 UI CDP 端口 9222 常开）。L0 静态层不需要应用；
M05 需要 `tools/js-tooling` 下 `npm install`（eslint/espree）；headless 模式需要 Chrome/Edge。

## 结构治理工具（a654）

```bat
python tools/check_graph.py                  rem 依赖图门禁（M09 同源）
python tools/check_graph.py --update-baseline rem 结构变更后刷新趋势基线
python tests/regression/run_all.py --smoke   rem 真机冒烟（用户发起制，1 条额度）
python tests/regression/render_audit.py      rem 渲染路径测绘（1 条额度）
python tools/split_css_subsystems.py --dry-run rem CSS 子系统分类预演
python tests/regression/style_snapshot.py    rem 样式快照/页内对比（--save/--diff）
```

## 提交即回归（推荐一次性启用）

```bat
python tools/install_regression_hooks.py
rem 之后：每次 commit 自动跑 L0；每次 push 自动跑 L0/L1/L2
rem 卸载：python tools/install_regression_hooks.py --remove
```

## 背景

本次模块化把 69 个文件转为 ES module（harness 25 个）。子类风险：

1. **动态取用漏挂**：`_g('name')` 字符串引用，eslint 看不见（已修 24 个）；
2. **业务逻辑判据失效**：如工作头 `:scope >` 查不到时间线内正文（已修）；
3. **加载顺序**：module 全 defer，classic→module 调用链；
4. **严格模式/顶层 this**：sloppy 隐式全局在 module 中抛错；
5. **共享可变态**：let/var 走 defineProperty 存取器，读写语义。

用例设计针对以上五类 + 全功能面主路径/边界/竞态。
