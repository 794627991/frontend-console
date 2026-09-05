# -*- coding: utf-8 -*-
"""日志行偏移索引（G 级文件随机访问）。
日志格式：工具自记录 ts\ttag\traw_line\n；外部日志：任意文本行。
索引记录每行起始字节偏移，支持 O(1) seek 到第 N 行。索引缓存到 .idx 文件。
"""
import os, re, time
from array import array
from itertools import islice

class LogIndex:
    """日志文件行偏移索引。首次扫描全文件记录每行偏移，缓存到 .idx。
    支持工具格式（ts\ttag\ttext）和外部纯文本日志。
    文件追加后按 size 变化增量续扫，避免重扫 G 级文件。"""
    def __init__(self, path):
        self.path = path
        # 索引统一放工具目录 idx/ 下（不再散落日志目录）：
        # 文件名 = <原名>.<md5(日志绝对路径)>.idx —— 拖拽不同目录同名日志
        # 不会互相覆盖，绝对路径哈希即映射关系
        import hashlib
        from src.app_state import BASE_DIR
        self.idx_dir = os.path.join(BASE_DIR, "idx")
        os.makedirs(self.idx_dir, exist_ok=True)
        key = hashlib.md5(os.path.abspath(path).encode("utf-8")).hexdigest()[:16]
        self.idx_path = os.path.join(self.idx_dir, f"{os.path.basename(path)}.{key}.idx")
        self.offsets = []  # 每行起始字节偏移
        self.total = 0
        self._loaded = False
        self._built_size = -1  # 建索引时的文件大小，用于检测追加失效
        self._built_head = None  # 建索引时的首 4KB md5：检测原地替换/轮转（追加不改变头部）
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

    def _head_hash(self, size):
        """文件首 4KB md5：检测原地替换/轮转（追加不改变头部，正常追加不误伤）。
        只哈希首 4KB——G 级文件全文哈希太慢，头部变化足够区分新旧文件。"""
        try:
            import hashlib
            with open(self.path, "rb") as f:
                return hashlib.md5(f.read(4096)).hexdigest()
        except Exception:
            return None

    def _self_check(self, cur_size, head):
        """索引与当前文件是否仍自洽：大小一致且头部哈希一致。
        大小不同是正常追加（走 _append_scan）；头部哈希不同 = 原地替换/轮转
        穿越旧尺寸，旧偏移全部作废必须全重扫（否则 _append_scan 从旧文件
        行偏移切入新文件中部，错位被 _save_cache 持久化跨重启存活）。"""
        return self._built_size == cur_size and self._built_head == head

    def build(self):
        """扫描日志文件建索引。首次 O(n)，结果缓存到 .idx 文件。
        已加载且文件未追加时直接返回；文件追加时增量续扫。"""
        cur_size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        head = self._head_hash(cur_size)
        # 已加载：头部哈希变化 = 原地替换/轮转 → 全重扫；否则按大小走快路径
        if self._loaded and self._built_head is not None and self._built_head != head:
            self._loaded = False
            self.offsets = []
            self.total = 0
            self._hits_invalidate()
        # 已加载且文件大小未变（头部也未变）→ 直接返回
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
                    if len(data) >= 40:
                        # v2 格式：<u64 total><u64 built_size><32B 指纹区><offsets...>
                        import struct
                        cached_total, cached_size = struct.unpack(">QQ", data[:16])
                        cached_head = data[16:48].rstrip(b"\n").decode("utf-8", errors="replace") or None
                        count = (len(data) - 48) // 8
                        # 校验：缓存的总行数与偏移数一致才采用
                        if count == cached_total:
                            # 指纹校验：缓存的 built_size 与当前文件大小一致时，
                            # 首部 md5 必须也一致——同尺寸原地替换（轮转穿越旧尺寸）
                            # 仅凭 mtime/大小采信会把错位偏移加载进来
                            if cached_size == cur_size and cached_head and cached_head != head:
                                pass  # 指纹不符：不采信，落到下方全重扫
                            else:
                                self.total = cached_total
                                self.offsets = list(struct.unpack(">" + "Q" * count, data[48:48 + count * 8]))
                                self.offsets.append(cur_size)  # 追加 EOF 偏移占位
                                self._loaded = True
                                self._built_size = cached_size
                                self._built_head = cached_head or head
                                if cur_size < cached_size:
                                    # 文件被截断到更小：缓存失效 → 全重扫
                                    self._loaded = False
                                    self.offsets = []
                                    self.total = 0
                                elif cur_size > self._built_size:
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
        self._loaded = True  # 此前缺失：全扫后仍 not loaded，下次 build 误走 .idx 加载分支
        self._built_size = cur_size
        self._built_head = head
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
            # 追加不改变文件头部，_built_head 保持（build 入口已校验头部一致）
            self._hits_invalidate()  # 追加引入新命中行：旧命中索引作废，下次全量 search 重建
            self._save_cache()
        except Exception:
            # 续扫异常（截断等）→ 标记未加载，下次 build 全重扫
            self._loaded = False
            self.offsets = []
            self.total = 0
            self._hits_invalidate()

    def _save_cache(self):
        """保存索引到 .idx 文件。v2 头部：<u64 total><u64 built_size><32B 指纹区
        （首 4KB md5 hex + \\n 填充）>，加载时对比指纹，同尺寸原地替换不采信。
        v1 格式（8B 头）读取时走 except 静默全重扫，自然升级 v2。"""
        try:
            import struct
            with open(self.idx_path, "wb") as f:
                f.write(struct.pack(">QQ", self.total, max(self._built_size, 0)))
                fp = (self._built_head or "")
                f.write(fp.encode("utf-8"))
                f.write(b"\n" * (32 - len(fp)))  # 32B 指纹定长区
                if self.offsets and self.total > 0:
                    f.write(struct.pack(">" + "Q" * self.total, *self.offsets[:self.total]))
        except Exception:
            pass

    def _touch_idx(self):
        """刷新 .idx 访问时间：3 天未用清理的判定依据。"""
        try: os.utime(self.idx_path, None)
        except OSError: pass



    def ts_list(self):
        """全文件扫描一遍，构建 ts 列表（毫秒，array('q')）。
        ts 非法（<=0）的行用前一个有效值填充（保证单调非降，可二分），
        供回放按时间定位行号用。结果跟随 _built_size 失效（与命中索引同策略）。
        首次调用 O(n)（顺序读，G 级文件 ~秒级），之后 O(1)。"""
        if self._ts_list is not None and self._ts_state == self._built_size:
            return self._ts_list
        # 局部快照 + 钳制（同 get_page：并发 build 不越界）
        offsets = self.offsets
        total = min(self.total, len(offsets) - 1) if offsets else 0
        ts_arr = array("q", bytes(8 * max(total, 1)))
        last_valid = 0
        with open(self.path, "rb") as f:
            for i in range(total):
                f.seek(offsets[i])
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
        # 局部快照：并发 build 重置 offsets（全量重扫先置 [0] 再补 total）时，
        # 快照可能捕获到 (旧 total, 新 offsets) 交叉状态——快照后按 offsets 实际
        # 长度钳制 total，自洽不越界（缺的行留给下次读取）。
        offsets = self.offsets
        total = min(self.total, len(offsets) - 1) if offsets else 0
        if offset >= total:
            return []
        end = min(offset + limit, total)
        res = []
        with open(self.path, "rb") as f:
            for i in range(offset, end):
                f.seek(offsets[i])
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
        # 索引命中：刷新访问时间（3 天未用清理的依据）
        self._touch_idx()
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
        # 局部快照（同 get_page：并发 build/_append_scan 异常路径清空 offsets 时，
        # 快照按 offsets 实际长度钳制，自洽不越界）
        offsets = self.offsets
        scan_total = min(self.total, len(offsets) - 1) if offsets else 0
        with open(self.path, "rb") as f:
            for i in range(start_offset, scan_total):
                f.seek(offsets[i])
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
        # 局部快照（同 get_page：并发 build 时不 IndexError）
        offsets = self.offsets
        res = []
        with open(self.path, "rb") as f:
            for i in hits[hit_start:hit_start + hit_count]:
                if i >= len(offsets):
                    break  # 快照期间文件被截断重扫：越界命中丢弃（下次搜索重建）
                f.seek(offsets[i])
                line = f.readline().decode("utf-8", errors="replace")
                parsed = self._parse_line(line)
                parsed["row"] = i
                res.append(parsed)
        return res


def cleanup_stale_idx(max_age_days=3):
    """清理 idx/ 下超过 max_age_days 天未使用的索引文件。
    在服务启动时调用一次。atime 由 _touch_idx 维护（命中即刷新），
    未命中的文件 atime 停在建档时间，到期自动删除。"""
    from src.app_state import BASE_DIR
    idx_dir = os.path.join(BASE_DIR, "idx")
    if not os.path.isdir(idx_dir):
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    try:
        for fn in os.listdir(idx_dir):
            if not fn.endswith(".idx"):
                continue
            p = os.path.join(idx_dir, fn)
            try:
                # atime 由 _touch_idx 维护；mtime 是建档时间，两者取大防误删
                st = os.stat(p)
                last_use = max(st.st_atime, st.st_mtime)
                if last_use < cutoff:
                    os.remove(p)
                    removed += 1
            except OSError:
                pass
    except OSError:
        pass
    return removed
