# -*- coding: utf-8 -*-
"""_blocks_to_md 映射表验证（designer 方案第 4 步冒烟）。"""
import sys, json
sys.path.insert(0, '.')
from src.notes_index import _blocks_to_md

raw = json.dumps({"blocks": [
    {"type": "header", "data": {"text": "<b>调试</b>笔记", "level": 2}},
    {"type": "paragraph", "data": {"text": "电机 <mark class=\"cdx-marker\">驱动电流</mark> 参考 <code class=\"inline-code\">TIM1</code> <a href=\"https://x.y\">手册</a> [[电机驱动]] #硬件"}},
    {"type": "list", "data": {"style": "unordered", "items": [
        {"content": "外层甲", "items": [{"content": "内层乙"}]},
        {"content": "外层丙"}]}},
    {"type": "list", "data": {"style": "ordered", "meta": {"start": 3}, "items": [{"content": "步骤一"}, {"content": "步骤二"}]}},
    {"type": "checklist", "data": {"items": [
        {"text": "已办", "checked": True}, {"text": "待办", "checked": False}]}},
    {"type": "quote", "data": {"text": "引用第一行\n第二行", "caption": "出处"}},
    {"type": "code", "data": {"code": "int main(){}\n```nested"}},
    {"type": "table", "data": {"withHeadings": True, "content": [["寄存器", "值"], ["CR1", "0x1|2"]]}},
    {"type": "image", "data": {"file": {"url": "/api/ed/img/img_1.png"}, "caption": "接线图"}},
    {"type": "delimiter", "data": {}},
]})
print(_blocks_to_md(json.loads(raw)["blocks"]))
