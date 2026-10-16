# -*- coding: utf-8 -*-
"""notes_index 解析层形状验证（一次性探针）。"""
import sys
sys.path.insert(0, '.')
from src.notes_index import _note_to_blocks, _extract_links, _extract_tags, _compile_query

raw = '{"blocks": [' \
      '{"type": "header", "data": {"text": "<b>调试</b>笔记 #硬件"}},' \
      '{"type": "list", "data": {"style": "unordered", "items": [{"content": "外层", "items": [{"content": "内层 [[电机驱动]]"}]}]}},' \
      '{"type": "code", "data": {"code": "[[not_a_link]] #not_a_tag x=[[y]]"}},' \
      '{"type": "checklist", "data": {"items": [{"text": "测 #颜色 #fff #123 待办", "checked": false}]}},' \
      '{"type": "paragraph", "data": {"text": "电机 #v2 #fff current"}}' \
      ']}'
blks = _note_to_blocks(raw)
for b in blks:
    print(b['kind'], '|', b['text'][:50])
print('links =', _extract_links(blks))
print('tags  =', _extract_tags(blks))
rx, _ = _compile_query('电机', False, False)
print('search =', bool(rx.search('XX电机YY')))
