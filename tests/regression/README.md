# tests/regression —— 模块化回归测试（统一路径）

**所有测试脚本、样本数据、运行产物都集中在本目录**（文档见本目录 `docs/`（说明书）与 `artifacts/`（运行产物））。

```
tests/regression/
├── run_all.py               # 统一入口（L0/L1/L2/L3 编排 + 报告）
├── cdp_lib.py               # CDP 公共库（连接/求值/轮询/异常/截图）
├── boot_probe.py            # 冷启动探针（headless Chrome，零依赖应用）
├── ast_checks.mjs           # AST 静态检查（espree + eslint-scope）
├── test_l0_static.py        # L0 静态门禁（挂载/动态取用/存取器/模块清单）
├── test_l1_boot.py          # L1 启动自检（冷启动/可达性/存取器往返/包装链）
├── test_l2_harness.py       # L2 Harness（切换/空会话/展开/工具卡/R1 竞态）
├── test_l2_panels.py        # L2 面板（日志/命令库/文件树/设置/代理/R3）
├── test_l2_files.py         # L2 文件链路（Monaco/Hex/Diff/终端/R2）
├── test_l3_harness.py       # L3 真实 CLI（H1-H7，按组执行，耗额度）
├── fixtures/                # 样本数据（小文件，随仓库）
│   ├── sample.txt / sample.md
│   ├── sample.hex            # Intel HEX（校验和必须正确，否则 hex 打开静默失败）
│   └── diff_a.txt / diff_b.txt
└── artifacts/               # 运行产物（截图等，不入库；保留 .gitkeep）
```

## 运行

```bat
python tests/regression/run_all.py --layers L0,L1,L2
python tests/regression/run_all.py --layers L3 --groups H1,H3,H4
python tools/install_regression_hooks.py     rem 提交即回归（L0 / L0-L2）
```

## 产物策略

- **小产物**（结果表、断言详情）：写入 `artifacts/测试报告.md`，随仓库留档。
- **中间产物**（截图、临时日志）：落 `tests/regression/artifacts/<时间戳>/`，**不入库**（`.gitignore`）。
- **大产物**（大文件/长日志/Office 样本等 >100KB）：不提交，用例明细里写明**构造方法**（如「用任意 `.docx` 文件放到 fixtures」），运行前手工准备。
- fixtures 只放可复现的最小样本（当前全部 <5KB）。
