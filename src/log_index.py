# -*- coding: utf-8 -*-
"""日志行偏移索引（G 级文件随机访问）。
日志格式：工具自记录 ts\ttag\traw_line\n；外部日志：任意文本行。
索引记录每行起始字节偏移，支持 O(1) seek 到第 N 行。索引缓存到 .idx 文件。
"""
import os, re
from array import array
from itertools import islice

class LogIndex:
    """日志文件行偏移索引。首次扫描全文件记录每行偏移，缓存到 .idx。
    支持工具格式（ts\ttag\ttext）和外部纯文本日志。
    文件追加后按 size 变化增量续扫，避免重扫 G 级文件。"""
    def __init__(self, path):
        self.path = path
        self.idx_path = path + ".idx"
        self.offsets = []  # 每行起始字节偏移
        self.total = 0
        self._loaded = False
        self._built_size = -1  # 建索引时的文件大小，用于检测追加失效
        # 命中行号索引缓存：{搜索词: array('Q') 行号}。search 全量扫描时建，
        # search_page 按命中序号 O(1) 取段。文件追加后全量重扫时会整体刷新。
        self._hits_by_q = {}
        self._hits_q_state = -1  # 建索引时的 _built_size 快照：追加后视为陈旧
        # ts 列表缓存（回放用）：array('q')，每行头部 ts（毫秒）。
        # ts<=0 的行（comment/外部纯文本/脏数据）用相邻有效值填充，保证单调非降可二分。
        # 与命中索引不同，它跟随 _built_size 一起失效（文件追加后重建）。
        self._ts_list = None
        self._ts_state = -1

    def _hits_stale(self):
        """命中索引是否已随文件变化而陈旧（需重建）。"""
        return self._hits_q_state != self._built_size

    def _hits_invalidate(self):
        self._hits_by_q.clear()
        self._hits_q_state = self._built_size

    def _parse_line(self, raw):
        """解析一行，返回 {ts, tag, text}。兼容工具格式和外部纯文本。"""
        raw = raw.rstrip("\n").rstrip("\r")
        if raw.startswith("#"):
            return {"ts": 0, "tag": "comment", "text": raw}
        parts = raw.split("\t", 2)
        if len(parts) == 3 and parts[0].isdigit():
            # 工具格式：ts\ttag\ttext
            try:
                return {"ts": int(parts[0]), "tag": parts[1], "text": parts[2]}
            except Exception:
                pass
        # 外部纯文本：整行作为 text
        return {"ts": 0, "tag": "text", "text": raw}

    def build(self):
        """扫描日志文件建索引。首次 O(n)，结果缓存到 .idx 文件。
        已加载且文件未追加时直接返回；文件追加时增量续扫。"""
        cur_size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        # 已加载且文件大小未变 → 直接返回
        if self._loaded and self._built_size == cur_size:
            return
        # 已加载但文件追加 → 增量续扫追加部分
        if self._loaded and self._built_size >= 0 and cur_size > self._built_size:
            self._append_scan(cur_size)
            return
        # 首次：尝试加载 .idx 缓存
        if not self._loaded:
            try:
                if os.path.isfile(self.idx_path) and os.path.getmtime(self.idx_path) >= os.path.getmtime(self.path):
                    with open(self.idx_path, "rb") as f:
                        data = f.read()
                    if len(data) >= 8:
                        import struct
                        cached_total = struct.unpack(">Q", data[:8])[0]
                        count = (len(data) - 8) // 8
                        # 校验：缓存的总行数与偏移数一致才采用
                        if count == cached_total:
                            self.total = cached_total
                            self.offsets = list(struct.unpack(">" + "Q" * count, data[8:8 + count * 8]))
                            self.offsets.append(cur_size)  # 追加 EOF 偏移占位
                            self._loaded = True
                            # .idx 未存文件大小，用最后一行起点作 _built_size 近似值。
                            # cur_size 必 >= 最后一行起点（该行有内容）；文件被截断时
                            # cur_size < 最后一行起点（或 ==0 且缓存非空）→ 缓存失效全重扫。
                            last_row_start = self.offsets[-2] if len(self.offsets) >= 2 else 0
                            if cur_size < last_row_start or (cur_size == 0 and cached_total > 0):
                                # 文件被截断到更小或清空，缓存失效 → 全重扫
                                self._loaded = False
                                self.offsets = []
                                self.total = 0
                            else:
                                self._built_size = last_row_start
                                if cur_size > self._built_size:
                                    self._append_scan(cur_size)
                            return
            except Exception:
                pass
        # 全文件扫描
        self.offsets = [0]
        with open(self.path, "rb") as f:
            f.seek(0)
            while True:
                line = f.readline()
                if not line:
                    break
                self.offsets.append(f.tell())
        # 末尾可能有空行偏移，去掉
        while len(self.offsets) > 1 and self.offsets[-1] == self.offsets[-2]:
            self.offsets.pop()
        self.total = len(self.offsets) - 1 if self.offsets else 0
        if self.offsets and self.offsets[-1] == 0:
            self.total = 0
        self._built_size = cur_size
        self._hits_invalidate()  # 全量重扫（首次/缓存失效/截断）：命中索引一并作废
        self._save_cache()

    def _append_scan(self, cur_size):
        """增量续扫：从上次索引末尾继续扫描追加部分。
        offsets 结构：[行0起点, 行1起点, ..., 行N-1起点, EOF]。
        pop 掉旧 EOF，从最后一行起点重读到新末尾（兼容最后一行未以 \\n 结尾）。
        追加会引入新命中行：旧的 _hits_by_q 命中索引已不完整，全部作废，
        下次全量 search 时重建（宁慢勿错）。"""
        try:
            with open(self.path, "rb") as f:
                if self.offsets:
                    self.offsets.pop()  # 弹掉旧 EOF
                if not self.offsets:
                    self.offsets = [0]  # 空文件起点
                f.seek(self.offsets[-1])  # 从最后一行起点重读
                while True:
                    line = f.readline()
                    if not line:
                        break
                    self.offsets.append(f.tell())
                while len(self.offsets) > 1 and self.offsets[-1] == self.offsets[-2]:
                    self.offsets.pop()
                self.total = len(self.offsets) - 1 if self.offsets else 0
                if self.offsets and self.offsets[-1] == 0:
                    self.total = 0
                # 截断守卫：若扫描期间文件被截断，最后一个偏移可能超文件大小，
                # 导致后续 get_page seek 到 EOF 外。检测到则丢弃缓存全重扫。
                if self.offsets and self.offsets[-1] > cur_size:
                    raise ValueError("offsets past EOF, file truncated during scan")
            self._built_size = cur_size
            self._hits_invalidate()  # 追加引入新命中行：旧命中索引作废，下次全量 search 重建
            self._save_cache()
        except Exception:
            # 续扫异常（截断等）→ 标记未加载，下次 build 全重扫
            self._loaded = False
            self.offsets = []
            self.total = 0
            self._hits_invalidate()

    def _save_cache(self):
        """保存索引到 .idx 文件。"""
        try:
            import struct
            with open(self.idx_path, "wb") as f:
                f.write(struct.pack(">Q", self.total))
                if self.offsets and self.total > 0:
                    f.write(struct.pack(">" + "Q" * self.total, *self.offsets[:self.total]))
        except Exception:
            pass

    def ts_list(self):
        """全文件扫描一遍，构建 ts 列表（毫秒，array('q')）。
        ts 非法（<=0）的行用前一个有效值填充（保证单调非降，可二分），
        供回放按时间定位行号用。结果跟随 _built_size 失效（与命中索引同策略）。
        首次调用 O(n)（顺序读，G 级文件 ~秒级），之后 O(1)。"""
        if self._ts_list is not None and self._ts_state == self._built_size:
            return self._ts_list
        ts_arr = array("q", bytes(8 * max(self.total, 1)))
        last_valid = 0
        with open(self.path, "rb") as f:
            for i in range(self.total):
                f.seek(self.offsets[i])
                line = f.readline().decode("utf-8", errors="replace")
                ts_arr[i] = self._parse_line(line).get("ts", 0) or 0
                if ts_arr[i] > 0:
                    last_valid = ts_arr[i]
                else:
                    ts_arr[i] = last_valid  # 非法行继承前一有效 ts
        self._ts_list = ts_arr
        self._ts_state = self._built_size
        return ts_arr

    def seek_ts(self, ts_ms):
        """二分定位：第一个 ts >= ts_ms 的行号。ts 列表单调非降（见 ts_list 填充）。
        用于回放按时间戳 O(log n) 跳行，不逐行扫 G 级文件。"""
        ts_arr = self.ts_list()
        lo, hi = 0, len(ts_arr)
        while lo < hi:
            mid = (lo + hi) // 2
            if ts_arr[mid] < ts_ms:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def get_page(self, offset, limit):
        """读取第 offset 行起的 limit 行（0-based）。返回 [{ts,tag,text}, ...]。"""
        if not self._loaded:
            self.build()
        if offset < 0 or offset >= self.total:
            return []
        end = min(offset + limit, self.total)
        res = []
        with open(self.path, "rb") as f:
            for i in range(offset, end):
                f.seek(self.offsets[i])
                line = f.readline()
                res.append(self._parse_line(line.decode("utf-8", errors="replace")))
        return res

    def search(self, q, limit=200, start_offset=0, count_total=True, exclude=""):
        """从 start_offset 行起搜索 q（大小写不敏感），返回命中行 + 游标。
        count_total=False 时跳过全量计数（total 返回 -1），扫到 limit 条即停——
        续载场景前端已知 total，无需每次重扫 G 级文件。
        exclude：命中行再按排除模式过滤，多个用 | 分隔（bsp.err | ^ 关键字 之类，
        每段 trim 后为空则忽略；支持正则——直接 re.search，非转义）。命中即剔除。
        全量扫描时顺带把所有命中行号收进 _hits_by_q 缓存（每命中仅 8 字节，
        200W 命中 ~16MB），此后可按命中序号区间 O(1) 取任意段，支持前端
        稀疏窗口缓存按需回载，内存可控且不设上限。"""
        if not self._loaded:
            self.build()
        if not q:
            return {"total": 0, "lines": [], "next_offset": -1, "has_more": False}
        pat = re.compile(re.escape(q), re.IGNORECASE)
        # 排除模式：| 分隔，逐段 trim；正则语法错误时该段降级为字面匹配
        ex_pats = []
        for seg in (exclude or "").split("|"):
            seg = seg.strip()
            if not seg:
                continue
            try:
                ex_pats.append(re.compile(seg, re.IGNORECASE))
            except re.error:
                ex_pats.append(re.compile(re.escape(seg), re.IGNORECASE))
        res = []
        next_offset = -1
        # total 与命中索引同源：全量时收集行号直接数长度，杜绝计数/索引错位
        collect_hits = count_total and start_offset == 0 and limit > 0
        hits = array("Q") if collect_hits else None
        total = -1  # -1 = 跳过计数（count_total=False 续载）；全量时由 len(hits) 覆盖
        with open(self.path, "rb") as f:
            for i in range(start_offset, self.total):
                f.seek(self.offsets[i])
                line = f.readline().decode("utf-8", errors="replace")
                parsed = self._parse_line(line)
                if pat.search(parsed["text"]):
                    # 排除过滤：命中任一排除模式 → 该行不算命中
                    if ex_pats and any(p.search(parsed["text"]) for p in ex_pats):
                        continue
                    if hits is not None:
                        hits.append(i)  # 全量：进索引，total 由 len(hits) 得出
                    elif count_total:
                        total += 1  # collect_hits=False 但要计数的罕见路径（limit<=0）
                    if len(res) < limit:
                        parsed["row"] = i
                        res.append(parsed)
                    else:
                        # 已满 limit，记录续搜游标。count_total=False 时直接停（不重扫全文件）
                        if next_offset < 0:
                            next_offset = i
                        if not count_total:
                            break
        if hits is not None:
            key = (q, exclude or "")  # 复合键：不同排除条件各自独立索引
            self._hits_by_q[key] = hits  # 全量命中行号索引（内存 ~8B/命中）
            total = len(hits)  # total 与索引同源，保证一致
            self._hits_q_state = self._built_size  # 索引基于当前文件状态
        has_more = next_offset >= 0
        return {"total": total, "lines": res, "next_offset": next_offset, "has_more": has_more}

    def search_page(self, q, hit_start, hit_count, exclude=""):
        """按命中序号取页：命中列表第 [hit_start, hit_start+hit_count) 条。
        依赖 search(count_total=True) 建立的 _hits_by_q 命中索引，O(1) seek。
        前端稀疏窗口缓存滚远回载时用，不重扫不重计。"""
        key = (q, exclude or "")
        hits = self._hits_by_q.get(key)
        if hits is None or self._hits_stale():
            # 命中索引未建/已随文件变化陈旧：补一次全量搜重建（limit>0 触发收集）
            if self._hits_stale():
                self._hits_invalidate()
            self.search(q, limit=1, count_total=True, exclude=exclude)
            hits = self._hits_by_q.get(key)
            if hits is None or not len(hits):
                return []
        if hit_start < 0 or hit_start >= len(hits):
            return []
        res = []
        with open(self.path, "rb") as f:
            for i in hits[hit_start:hit_start + hit_count]:
                f.seek(self.offsets[i])
                line = f.readline().decode("utf-8", errors="replace")
                parsed = self._parse_line(line)
                parsed["row"] = i
                res.append(parsed)
        return res
