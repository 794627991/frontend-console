v0.1 ~ v0.9 时期（串口控制台前身）（共 128 次提交，回溯自 git；里程碑节选）
· @feat(大纲): 集成 web-tree-sitter 真语法树解析——替换手写正则
· @feat(编辑器): 集成 Monaco Editor + markdown-it——GitHub 专业文本编辑器与 MD 解析器
· feat(v0.4): SSH 集成 + G 级历史数据无卡顿翻阅
· @chore(v1.0.0): 正式更名前端控制台 + web/ico 目录归位 + 十进制列头错位修复
· @chore(整理): 全部 Python 源码入 src/ + 删分支版本目录与 v0.2-legacy 分支 + 建 docs/
· @fix(hex查看器): 四问题修复——最近打开bin/打开方式选择/十进制对齐/多字节命中高亮/确认弹窗画风
· @feat(hex查看器): HxD 式「查看方式」下拉——十六进制/无符号十进制 × 8/16/32/64 位分组显示
· @fix(hex查看器): ASCII 列 0x00 同步灰色弱化（识图对照 ImHex 灰白对照）
· @feat(hex查看器): 参考 ImHex——0x00 字节灰色弱化 + Binary 16/32/64 位展示
· @fix(hex查看器): 对抗审计后续三修复——事件改全局代理/列头与数据行同构/字节范围选择检视
· @feat(hex): 数据检视对齐 ImHex 全类型 + 参考资源目录
· @fix(hex): 按截图对比修复 4 问题——虚拟滚动断裂/配色太花/列头/数据检视
· @feat(hex): 二进制文件十六进制查看/编辑——类 HxD 三栏布局，bin/hex/ihx 可开可改
· @feat(HFS): 下载记录进最近传输列表 + 每条标明 TFTP/HFS 来源
· @fix(HFS): 恢复原版布局——标题「TFTP/HFS : 8081」在左，右侧独立胶囊开关
· @fix(HFS): 按期望图合并开关——「TFTP/HFS : 8081」一行 + 单状态胶囊
· @fix(HFS): 面板开关简化——恢复原布局，TFTP 旁一个「hfs:8081 未运行」按钮
· @feat(HTTP下载): 设备经 HTTP 从 TFTP 目录拉文件——端口 8081，与 TFTP 联动