# -*- coding: utf-8 -*-
"""全审修复验证：F1 链路级（OutputData 包装原样）+ S2/S3 畸形注入复测。"""
import sys, json
sys.path.insert(0, '.')
from src.notes_index import _blocks_to_md, _note_to_blocks, _snippet

# F1：前端 conn.editor.save() 返回的是 OutputData 包装对象（{blocks,time,version}）
wrap = {"time": 1, "version": "2.24.3", "blocks": [
    {"type": "header", "data": {"text": "标题", "level": 2}},
    {"type": "paragraph", "data": {"text": "正文内容必须出现在导出里"}}]}
md = _blocks_to_md(wrap)
assert '正文内容必须出现在导出里' in md and '## 标题' in md, 'F1 修复失败: %r' % md
print('F1-OK: 包装对象解包，导出非空（%d 字）' % len(md))
# 兼容：裸 list 依旧工作
assert '正文' in _blocks_to_md(wrap['blocks'])
print('F1-OK2: 裸 list 兼容')

# S2：data 非字典的坏块
bad = '{"blocks":[{"type":"paragraph","data":"oops"},{"type":"paragraph","data":{"text":"存活"}}]}'
blks = _note_to_blocks(bad)
assert any('存活' in b['text'] for b in blks), 'S2 修复失败'
print('S2-OK: 坏块跳过好块存活（%d 块）' % len(blks))

# S3：三条 500 路径
md2 = _blocks_to_md([{"type": "header", "data": {"text": "x", "level": "abc"}},
                     {"type": "list", "data": {"style": "ordered", "meta": "oops", "items": [{"content": "a"}]}},
                     {"type": "table", "data": {"content": ["not_a_row", 42]}}])
print('S3-OK: 畸形字段降级不炸（%d 字）' % len(md2))

# G1：快照类型
from src.notes_index import _scan
snap, sk = _scan()
assert isinstance(snap, dict)
print('G1-OK: _scan 返回快照')

# L1：截窗平移
long_text = 'x' * 150 + '命中词' + 'y' * 100
sn, marks = _snippet(long_text, [[150, 153]])
assert sn.startswith('…') and sn[marks[0][0]:marks[0][1]] == '命中词', (sn[:20], marks)
print('L1-OK: 前缀省略号下高亮坐标对齐')
print('ALL PASS')
