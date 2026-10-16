# -*- coding: utf-8 -*-
"""真实 files/ 冒烟：_scan 全量解析 + 搜索链路（一次性探针）。"""
import sys, time
sys.path.insert(0, '.')
from src.notes_index import _scan, _CACHE

t0 = time.time()
cache, skipped = _scan(force=True)
took = int((time.time() - t0) * 1000)
notes = [k for k in cache if k.lower().endswith('.note')]
print('files=%d (note=%d) skipped_big=%d took=%dms' % (len(cache), len(notes), skipped, took))
# 抽样 2 个 .note 看解析形状
for k in notes[:2]:
    blks = cache[k]['blocks']
    print('---', k, 'blocks=%d links=%s tags=%s' % (len(blks), cache[k]['links'][:3], cache[k]['tags'][:5]))
    for b in blks[:3]:
        print('   ', b['kind'], '|', b['text'][:60])
# 搜索链路
from src.notes_index import _compile_query
hit_files = 0
rx, _ = _compile_query('the', False, False)
for fn, d in cache.items():
    for b in d['blocks']:
        if rx.search(b['text']):
            hit_files += 1
            break
print('search-smoke(the):', hit_files, 'files hit')
