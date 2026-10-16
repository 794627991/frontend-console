# -*- coding: utf-8 -*-
"""事中闸恢复验证（v3.5.314）：新语义四例 + 注入函数冒烟。"""
import sys
sys.path.insert(0, '.')
from src.harness.roles import audit_gate_check

# ① 新语义核心：未审计 + 累计超线 + 未派 designer → 拦
b, m = audit_gate_check(200, reviewed=False, designed=False, design_fired=False)
assert b and 'designer' in m, 'case1 FAIL'
print('case1 OK: 未审计+超线+未派designer → 拦')
# ② v3.5.313 豁免：审计链已建立（reviewer 在场）→ 不拦（回修类）
b, _ = audit_gate_check(200, reviewed=True, designed=False, design_fired=False)
assert not b, 'case2 FAIL'
print('case2 OK: reviewed 在场 → 不拦')
# ③ 一次性：designFired 后不再咬
b, _ = audit_gate_check(300, reviewed=False, designed=False, design_fired=True)
assert not b, 'case3 FAIL'
print('case3 OK: designFired → 不再拦')
# ④ 未派 designer 但未超线
b, _ = audit_gate_check(100, reviewed=False, designed=False, design_fired=False)
assert not b, 'case4 FAIL'
print('case4 OK: 未超线 → 不拦')
# ⑤ 注入函数：settings 临时文件生成 + hooks 结构
from src.harness.audit import _audit_hook_settings_path
import json, os
p = _audit_hook_settings_path()
assert p and os.path.isfile(p), 'settings 生成失败'
cfg = json.load(open(p, encoding='utf-8'))
hook = cfg['hooks']['PreToolUse'][0]
assert hook['matcher'] == 'Edit|Write|MultiEdit|NotebookEdit'
assert '--audit-hook' in hook['hooks'][0]['command']
os.remove(p)
print('injection OK: settings 文件生成 + matcher/命令正确')
print('ALL PASS')
