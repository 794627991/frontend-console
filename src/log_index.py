# -*- coding: utf-8 -*-
"""日志行偏移索引（G 级文件随机访问）。
日志格式：工具自记录 ts\ttag\traw_line\n；外部日志：任意文本行。
索引记录每行起始字节偏移，支持 O(1) seek 到第 N 行。索引缓存到 .idx 文件。
"""
import os, re

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
        self._save_cache()

    def _append_scan(self, cur_size):
        """增量续扫：从上次索引末尾继续扫描追加部分。
        offsets 结构：[行0起点, 行1起点, ..., 行N-1起点, EOF]。
        pop 掉旧 EOF，从最后一行起点重读到新末尾（兼容最后一行未以 \\n 结尾）。"""
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
            self._save_cache()
        except Exception:
            # 续扫异常（截断等）→ 标记未加载，下次 build 全重扫
            self._loaded = False
            self.offsets = []
            self.total = 0

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

    def search(self, q, limit=200, start_offset=0):
        """从 start_offset 行起搜索 q（大小写不敏感），返回命中行 + 游标。"""
        if not self._loaded:
            self.build()
        if not q:
            return {"total": 0, "lines": [], "next_offset": -1, "has_more": False}
        pat = re.compile(re.escape(q), re.IGNORECASE)
        res = []
        total = 0
        next_offset = -1
        with open(self.path, "rb") as f:
            for i in range(start_offset, self.total):
                f.seek(self.offsets[i])
                line = f.readline().decode("utf-8", errors="replace")
                parsed = self._parse_line(line)
                if pat.search(parsed["text"]):
                    total += 1
                    if len(res) < limit:
                        parsed["row"] = i
                        res.append(parsed)
                    else:
                        # 已满 limit，记录续搜游标，但继续统计 total 以给前端准确计数
                        if next_offset < 0:
                            next_offset = i
        has_more = next_offset >= 0
        return {"total": total, "lines": res, "next_offset": next_offset, "has_more": has_more}
