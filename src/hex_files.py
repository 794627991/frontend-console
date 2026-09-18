# -*- coding: utf-8 -*-
"""二进制文件十六进制查看/编辑 API（Flask Blueprint）。

bin/hex/ihx 等二进制文件以前只能走阅读器（文本形式乱码）。现在：
- /api/hex/meta：大小 + Intel HEX 标记（.hex/.ihx 是 ASCII 文本但语义是二进制镜像）
- /api/hex/read：分块读原始字节（base64）——大文件窗口式加载，不整读进内存
- /api/hex/save：整文件字节写回（base64）
安全：仅绝对路径 + 已存在文件；不做站内 files/ 名映射（二进制不在笔记白名单）。
"""
import os, base64, difflib   # v2.3.3：difflib 提到模块级——_bin_diff 用了但只在
                             # 隔壁函数 import 过（运行时 NameError 潜雷，Cython 抓出）
from flask import Blueprint, request, jsonify

hex_bp = Blueprint("hexfiles", __name__)

# 十六进制查看常用二进制后缀（不在文本白名单的都允许——is_text 探测已分流）
READ_CHUNK = 512 * 1024   # 单次读取上限 512KB（大文件分块窗口加载）

def _real_path(path):
    p = os.path.abspath((path or "").strip().strip('"').strip("'"))
    if not os.path.isfile(p):
        return None
    return p

@hex_bp.route("/api/hex/meta", methods=["POST"])
def hex_meta():
    """文件元信息：大小 + 是否 Intel HEX（.hex/.ihx 文本格式但内容是二进制镜像）。"""
    data = request.get_json(force=True, silent=True) or {}
    p = _real_path(data.get("path"))
    if not p:
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    low = p.lower()
    is_ihex = low.endswith((".hex", ".ihx"))
    try:
        size = os.path.getsize(p)
    except OSError as e:
        return jsonify({"ok": False, "err": str(e)}), 400
    return jsonify({"ok": True, "path": p, "size": size, "ihex": is_ihex})

@hex_bp.route("/api/hex/read", methods=["POST"])
def hex_read():
    """分块读字节。body: {path, offset, length} → {data: base64, size, offset}"""
    data = request.get_json(force=True, silent=True) or {}
    p = _real_path(data.get("path"))
    if not p:
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    try:
        offset = max(0, int(data.get("offset") or 0))
        length = min(int(data.get("length") or READ_CHUNK), READ_CHUNK)
        size = os.path.getsize(p)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "err": "参数无效"}), 400
    if offset >= size:
        return jsonify({"ok": True, "data": "", "size": size, "offset": offset})
    length = min(length, size - offset)
    with open(p, "rb") as f:
        f.seek(offset)
        chunk = f.read(length)
    return jsonify({"ok": True, "data": base64.b64encode(chunk).decode("ascii"),
                    "size": size, "offset": offset})

@hex_bp.route("/api/hex/save", methods=["POST"])
def hex_save():
    """整文件写回（查看器内存中已有完整镜像，尺寸通常受 READ_CHUNK 窗口约束）。
    body: {path, data: base64}。原子替换：写 .part 再 os.replace。"""
    data = request.get_json(force=True, silent=True) or {}
    p = _real_path(data.get("path"))
    if not p:
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    try:
        raw = base64.b64decode(data.get("data") or "")
    except Exception:
        return jsonify({"ok": False, "err": "base64 无效"}), 400
    # 双保险：二进制镜像长度与磁盘文件不一致一律拒绝——前端读块缺失时曾把
    # 大文件截断成 512KB 写回，os.replace 无备份直接毁文件。
    # Intel HEX 例外：写回的是 hex 文本（解析后镜像长度 ≠ 原文本长度），跳过校验
    if not p.lower().endswith((".hex", ".ihx")):
        try:
            if len(raw) != os.path.getsize(p):
                return jsonify({"ok": False, "err":
                    f"长度不一致：镜像 {len(raw)} 字节 != 文件 {os.path.getsize(p)} 字节，拒绝写回"}), 400
        except OSError as e:
            return jsonify({"ok": False, "err": str(e)}), 400
    tmp = p + ".hexpart"
    try:
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, p)
    except OSError as e:
        try: os.remove(tmp)
        except OSError: pass
        return jsonify({"ok": False, "err": str(e)}), 400
    return jsonify({"ok": True, "size": len(raw)})


# ---- 二进制对比（hex diff，v2 重构）----
# 用户需求：100MB 内固件对比是常态（v1 的 8MB 上限+不等长粗粒度不可用）。
# 调研（GitHub）：HDiffPatch(2091★)/xdelta(1342★) 走差分压缩不回显差异块；
# vbindiff(559★) 是显示层。核心思路一致——分块哈希锚定+局部细化，自建实现。
# 算法（全部实测标定）：
# - 等长文件（固件烧录对比主场景）：逐字节 + 差异区间合并（隔 64B 内并块），
#   1MB 0.06s / 100MB ~8s，字节级精确。大差异块（>1KB）再做移位探测
#   （B 块头 256B 在 A 块内 find）识别块内错位插入——纯 SequenceMatcher
#   对错位段会 O(n²) 爆炸（实测 300KB 段 84s）。
# - 不等长文件：公共前后缀锚定 O(n)，中间段按熵分流：
#   高熵（随机/代码段）→ SequenceMatcher 直比（实测随机 8MB 1.4s，插删
#   字节级定位）；低熵（0x00/0xFF 大段填充——SM 会卡死，实测 512KB 全零
#   110s+ 跑不完）→ 256B 块哈希 LCS 锚定（块哈希全等=字节全等，零误差）。
DIFF_LIMIT = 128 * 1024 * 1024   # 单文件上限 128MB（前端不再整读大文件，可放宽）
DIFF_CTX = 64                    # 相邻差异间隔 ≤ 此值并成一块
DIFF_RESCAN = 1024               # 等长路大差异块阈值：超过则做移位探测
DIFF_PROBE = 256                 # 移位探测用的段头样本长度
ENTROPY_MIN = 16                  # 采样字节种类 < 16 判为低熵（填充数据）

def _low_entropy(data):
    """采样探测低熵数据（0x00/0xFF 大段填充）——SequenceMatcher 在这类
    数据上 O(n²) 卡死（实测 512KB 全零 110s+），必须分流到块哈希锚定。"""
    if not data:
        return True
    step = max(1, len(data) // 4096)
    return len(set(data[::step])) < ENTROPY_MIN

def _seq_scan(la, lb, oa, ob, out, ctx=DIFF_CTX):
    """等长两序列逐字节比，差异区间合并，追加 (replace, a0,a1, b0,b1) 到 out。"""
    k = 0
    L = min(len(la), len(lb))
    while k < L:
        if la[k] != lb[k]:
            s = e = k
            while k < L and (la[k] != lb[k] or k - e <= ctx):
                if la[k] != lb[k]:
                    e = k
                k += 1
            out.append(("replace", oa + s, oa + e + 1, ob + s, ob + e + 1))
        else:
            k += 1

def _shift_align(seg_a, seg_b, s0, out):
    """等长文件的大差异块内错位对齐：B 块头样本在 A 块内 find 定位移位量。
    命中 → 一侧 insert/delete + 移位后等长比；未命中 → 整块 replace。"""
    hit_ab = seg_a.find(seg_b[:DIFF_PROBE])   # B 头在 A 中位置
    hit_ba = seg_b.find(seg_a[:DIFF_PROBE])   # A 头在 B 中位置
    def align_count(shift, long_s, short_s):
        # long_s[shift:] ↔ short_s[0:] 的 4096 采样匹配数（择优依据）
        if shift <= 0:
            return 0
        L = min(len(long_s) - shift, len(short_s))
        if L <= 0:
            return 0
        cnt = 0
        for p in range(0, min(L, 4096), 16):
            if long_s[shift + p] == short_s[p]:
                cnt += 1
        return cnt
    c_ab = align_count(hit_ab, seg_a, seg_b)
    c_ba = align_count(hit_ba, seg_b, seg_a)
    if hit_ab > 0 and c_ab > c_ba and c_ab > 0:
        # A[hit_ab:] ↔ B[0:]：B 侧先多 hit_ab 字节
        out.append(("insert", s0, s0, s0, s0 + hit_ab))
        _seq_scan(seg_a[hit_ab:], seg_b, s0 + hit_ab, s0, out)
        return True
    if hit_ba > 0 and c_ba > c_ab and c_ba > 0:
        out.append(("delete", s0, s0 + hit_ba, s0, s0))
        _seq_scan(seg_a, seg_b[hit_ba:], s0, s0 + hit_ba, out)
        return True
    return False

def _align_count(shift, long_s, short_s):
    """long_s[shift:] ↔ short_s[0:] 的采样匹配数（移位方向择优依据）。"""
    if shift <= 0:
        return 0
    L = min(len(long_s) - shift, len(short_s))
    if L <= 0:
        return 0
    cnt = 0
    for p in range(0, min(L, 4096), 16):
        if long_s[shift + p] == short_s[p]:
            cnt += 1
    return cnt

def _shift_align_general(ra, rb, a0, b0, out):
    """大差异区的移位对齐（不等长通用版，等长路 _shift_align 的扩展）：
    B 头样本在 A 中 find（B 侧领先 = A 有插入）或反之，命中 → 前段
    insert/delete + 等长段逐字节扫描 + 尾部残余 insert/delete。
    适用场景：唯一块锚定在纯重复填充区无锚可用（30MB 全 0x00 找不到
    唯一块），但插入点后内容全同——头样本 find 一次定位。返回是否命中。"""
    probe = min(DIFF_PROBE, len(ra), len(rb))
    if probe < 16:
        return False
    hit_ab = ra.find(rb[:probe])   # B 头在 A 中 → A 侧先多 hit_ab 字节
    hit_ba = rb.find(ra[:probe])   # A 头在 B 中 → B 侧先多 hit_ba 字节
    c_ab = _align_count(hit_ab, ra, rb)
    c_ba = _align_count(hit_ba, rb, ra)
    # 择优：采样匹配数要多于乱碰水平（probe/16 个采样点，过半才算真对齐）
    need = probe // 32
    if hit_ab > 0 and c_ab >= need and c_ab >= c_ba:
        out.append(("delete", a0, a0 + hit_ab, b0, b0))
        L = min(len(ra) - hit_ab, len(rb))
        _seq_scan(ra[hit_ab:hit_ab + L], rb[:L], a0 + hit_ab, b0, out)
        if len(rb) > L:   # B 尾多
            out.append(("insert", a0 + hit_ab + L, a0 + hit_ab + L,
                        b0 + L, b0 + len(rb)))
        elif len(ra) - hit_ab > L:   # A 尾多
            out.append(("delete", a0 + hit_ab + L, a0 + len(ra),
                        b0 + L, b0 + len(rb)))
        return True
    if hit_ba > 0 and c_ba >= need and c_ba > c_ab:
        out.append(("insert", a0, a0, b0, b0 + hit_ba))
        L = min(len(ra), len(rb) - hit_ba)
        _seq_scan(ra[:L], rb[hit_ba:hit_ba + L], a0, b0 + hit_ba, out)
        if len(ra) > L:
            out.append(("delete", a0 + L, a0 + len(ra), b0 + hit_ba + L, b0 + len(rb)))
        elif len(rb) - hit_ba > L:
            out.append(("insert", a0 + L, a0 + L, b0 + hit_ba + L, b0 + len(rb)))
        return True
    return False

def _refine_region(ra, rb, a0, b0, out):
    """块锚定后的单个差异小区（a0/b0 为区在原文件的绝对起点）字节级精修：
    小且高熵 → 字节 SequenceMatcher（插删字节级定位）；大区 → 先移位对齐
    （纯重复区唯一锚失效时仍能精确定位插入点），对不齐才整区 replace。"""
    la, lb = len(ra), len(rb)
    if la > 256 * 1024 or lb > 256 * 1024:
        if _shift_align_general(ra, rb, a0, b0, out):
            return
        out.append(("replace", a0, a0 + la, b0, b0 + lb))
        return
    if _low_entropy(ra) or _low_entropy(rb):
        out.append(("replace", a0, a0 + la, b0, b0 + lb))
        return
    sm = difflib.SequenceMatcher(a=ra, b=rb, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        out.append((op, a0 + i1, a0 + i2, b0 + j1, b0 + j2))

def _bin_diff_blocks(a, b):
    """字节级差异块 [(op, a_start, a_end, b_start, b_end)]（end 不含，equal 不返回）。"""
    import difflib, hashlib
    n, m = len(a), len(b)
    out = []
    if n == m:
        k = 0
        while k < n:
            if a[k] != b[k]:
                s = e = k
                while k < n and (a[k] != b[k] or k - e <= DIFF_CTX):
                    if a[k] != b[k]:
                        e = k
                    k += 1
                seg_a, seg_b = a[s:e + 1], b[s:e + 1]
                if (e + 1 - s > DIFF_RESCAN and not _low_entropy(seg_a)
                        and not _low_entropy(seg_b)):
                    if not _shift_align(seg_a, seg_b, s, out):
                        out.append(("replace", s, e + 1, s, e + 1))
                else:
                    out.append(("replace", s, e + 1, s, e + 1))
            else:
                k += 1
        return out
    # 不等长：公共前后缀锚定
    p = 0
    while p < min(n, m) and a[p] == b[p]:
        p += 1
    s = 0
    while s < min(n, m) - p and a[n - 1 - s] == b[m - 1 - s]:
        s += 1
    if p >= n:
        out.append(("insert", n, n, p, m))
        return out
    if p >= m:
        out.append(("delete", p, n, m, m))
        return out
    ca, cb = a[p:n - s], b[p:m - s]
    # 中间段统一走块哈希 LCS 锚定（blake2b 全等=字节全等），不再按熵分流
    # 直比——高熵直比在"两侧极不均衡"的中间段上（实测 70MB vs 30MB）
    # SequenceMatcher 无界跑不完。改为 patience 式【唯一块锚定】。
    # 教训（第二次）：块哈希列表直接喂 SequenceMatcher 在大段重复填充上
    # 仍 O(n²)——8 万个相同 0x00 块哈希，autojunk=False 又关掉启发式逃生门，
    # 100MB 档实测 5 分钟跑不完。patience diff 思路：只用【两文件都唯一】
    # 的块哈希做锚点（重复块无锚定价值，只会烧 CPU），锚点序 LIS 即 LCS，
    # 锚点间小区域字节级精修——对低熵/重复数据天然免疫。
    BS = 256
    ha = [hashlib.blake2b(ca[i:i + BS], digest_size=8).digest()
          for i in range(0, len(ca), BS)]
    hb = [hashlib.blake2b(cb[i:i + BS], digest_size=8).digest()
          for i in range(0, len(cb), BS)]
    from collections import Counter
    cnt_a, cnt_b = Counter(ha), Counter(hb)
    pos_b = {}
    for j, h in enumerate(hb):
        if cnt_b[h] == 1 and cnt_a.get(h) == 1:
            pos_b[h] = j
    # 候选锚点（按 A 序）：A 唯一 ∩ B 唯一 → (i, pos_b) 对
    seq = [(i, pos_b[ha[i]]) for i in range(len(ha))
           if cnt_a[ha[i]] == 1 and ha[i] in pos_b]
    # LIS（O(k log k)，patience 排堆回溯）：B 序最长递增子序列 = LCS
    import bisect
    tails, tidx, prev = [], [], []
    for k, (i, j) in enumerate(seq):
        t = bisect.bisect_left(tails, j)
        prev.append(tidx[t - 1] if t > 0 else -1)
        if t == len(tails): tails.append(j); tidx.append(k)
        else: tails[t] = j; tidx[t] = k
    lis = []
    k = tidx[-1] if tidx else -1
    while k >= 0:
        lis.append(seq[k]); k = prev[k]
    lis.reverse()
    # 锚点连成等长段：相邻锚点之间即差异区，逐区精修
    anchors = [(-1, -1)] + lis + [(len(ha), len(hb))]
    for (ai, aj), (bi, bj) in zip(anchors, anchors[1:]):
        i1, i2 = ai + 1, bi      # 差异区（块索引，不含锚点）
        j1, j2 = aj + 1, bj
        if i1 >= i2 and j1 >= j2:
            continue
        ra = ca[i1 * BS:min(i2 * BS, len(ca))]
        rb = cb[j1 * BS:min(j2 * BS, len(cb))]
        _refine_region(ra, rb, p + i1 * BS, p + j1 * BS, out)
    return out

# ============================================================
# 流畅度隔离（项目第一守则）：diff 计算是纯 Python 重 CPU（100MB ~8s），
# 放 Flask 主进程会持 GIL 卡死全局（弹窗 3s/日志库 10s 的元凶，用户两次
# 严厉投诉）。线程没用——GIL 照样锁主进程，必须独立【进程】。
# _DIFF_POOL 懒创建：不点对比就永远不存在（拼积木——不用不占资源）。
# ============================================================
import atexit
from concurrent.futures import ProcessPoolExecutor

_DIFF_POOL = None
_DIFF_POOL_LOCK = __import__("threading").Lock()

def _diff_worker(pa, pb):
    """子进程入口：读文件 + 跑 diff（全部在独立进程，主进程零 CPU 占用）。"""
    with open(pa, "rb") as f: ba = f.read()
    with open(pb, "rb") as f: bb = f.read()
    return [{"op": op, "a_start": i1, "a_end": i2, "b_start": j1, "b_end": j2}
            for op, i1, i2, j1, j2 in _bin_diff_blocks(ba, bb)]

def _diff_pool():
    global _DIFF_POOL
    if _DIFF_POOL is None:
        with _DIFF_POOL_LOCK:
            if _DIFF_POOL is None:
                _DIFF_POOL = ProcessPoolExecutor(max_workers=1)
    return _DIFF_POOL

def _diff_pool_shutdown():
    global _DIFF_POOL
    if _DIFF_POOL is not None:
        _DIFF_POOL.shutdown(wait=False)
        _DIFF_POOL = None

atexit.register(_diff_pool_shutdown)

@hex_bp.route("/api/bin/diff", methods=["POST"])
def bin_diff():
    """字节级对比两份二进制文件。body: {a, b} → 差异块列表（offset 相对 A/B 各自）。
    返回 blocks: [{op, a_start, a_end, b_start, b_end}]（end 不含），equal 段不返回。
    计算全程在独立子进程跑（首守则：对比再重也不许卡主进程 UI）。"""
    data = request.get_json(force=True, silent=True) or {}
    pa, pb = _real_path(data.get("a")), _real_path(data.get("b"))
    if not pa or not pb:
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    try:
        sa, sb = os.path.getsize(pa), os.path.getsize(pb)
        if sa > DIFF_LIMIT or sb > DIFF_LIMIT:
            return jsonify({"ok": False, "err":
                f"文件过大（上限 128MB）：A {sa/1048576:.1f}MB B {sb/1048576:.1f}MB"}), 400
    except OSError as e:
        return jsonify({"ok": False, "err": str(e)}), 400
    # 子进程跑 diff（100MB 也要 ~8s，主进程这期间照常服务弹窗/日志库）
    try:
        blocks = _diff_pool().submit(_diff_worker, pa, pb).result()
    except Exception as e:
        return jsonify({"ok": False, "err": f"对比失败：{e}"}), 500
    return jsonify({"ok": True, "a": pa, "b": pb,
                    "a_size": sa, "b_size": sb, "blocks": blocks,
                    "diff_count": len(blocks)})
