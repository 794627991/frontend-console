v1.0.0 ~ v1.1.0 时期（前端控制台定名）（共 225 次提交，回溯自 git；里程碑节选）
· 版本号 1.1.0 → 2.0.0（用户定版）：入口/MCP/proxy_core/serial_cli/server/页面标题
· retry_config.json 归数据目录（DATA_DIR，可迁移）：配置跟数据走（用户定调）
· 引用右键菜单改 fixed 定位挂 body：根治菜单随滚动/定位祖先飞走（用户截图实锤）
· ask 选择卡片弹出时自动滚进视口：不再让用户翻页找（用户实锤）
· 用量统计排除「?」假模型：无模型名的请求不再计入（用户定调）
· HikLink 机器人上线通告：持久化最近活跃 session，重启后复用它推上线消息
· 计算器严查第二轮：对抗审查实锤 10 项全修
· 计算器：裸 hex 字面量支持（HEX 模式 AA 报无法识别——用户实锤）
· 五修：①托盘自愈 watchdog（30s 验活重建，用户实锤托盘消失无唤出入口）+ 单实例唤醒双通道（HTTP /api/raise_window 自唤优先 
· 合入 Claude Proxy 核心：src/proxy.py（四类平移+统一托盘段+自愈+蓝图）；tray.py 并入 Proxy 菜单段
· 计算器键盘 v5：修红框实锤的空白括号键+底行空洞+符号基线
· @fix(审查): todo 25 项全修（严重8+中等11+轻微5+运行时回归）+ 设置弹窗重构 + 笔记文案 + 灰条修复
· 移除根目录 retry_config.json：已归数据目录（DATA_DIR），仓库不再跟踪程序侧配置
· 数据目录迁移覆盖所有关键配置：根级 *.json 全量严格校验（原只迁 cmdlib.json）
· 根目录清理：gen_ext_icons.py / restart_tool.py 挪 tools/（用户要求根目录不放源码）
· .gitignore 忽略 _engine_stdio_ext/：PyInstaller 打包解包产物不入库
· 「新建笔记」升级为「新建文件」下拉：笔记 / .txt / .md / 自定义后缀（用户需求）
· 右键引用命中范围扩到思考/执行抽屉：右键组内任意位置都可引用（CDP 实测驱动）