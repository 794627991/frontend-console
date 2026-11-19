# -*- coding: utf-8 -*-
"""Lanz 额度后台线程（a672，自 proxy.py 平移）。

与代理转发零耦合：它只做「登录 SSO → 定时拉额度/负载 → 写共享状态槽」。
emit 直写 src.lanzi.state，前端从 /api/lanzi/status 读走。

防登录风暴的三道闸（历史实锤累积，勿删）：
  1. 锁定识别 _is_lockout_msg：SSO 锁号后每次重试都会重置锁定计时，
     命中即停登等用户手动操作
  2. 被踢熔断 _push_relogin：30 分钟内第 3 次重登成功 = 会话被另一处
     登录互踢，停登 30 分钟
  3. 跨进程标记 state.save_marks：进程重启循环也压到每冷却期一次登录
"""
import logging
import threading
import time

from src.lanzi import config, state
from src.lanzi import quota

log = logging.getLogger("claude_proxy")

# 模型负载刷新间隔（秒）：额度 600s 级变化，负载 20s 级。a672 搬移时
# 常量留在 api.py，worker 内层循环引用它 → 运行期 NameError 被外层
# except 吞掉，形成无等待的崩溃紧循环（每轮两次真实 API 往返）。
LOAD_TTL = 20.0

# a459（审计遗留）：裸 "locked" 会命中 "unlocked"——SSO 解锁成功的提示若拼进
# 异常文案，会被误判成锁定而停登（与 a452 修掉的「警示语误判」同族）。
# locked 的判定挪到 _is_lockout_msg 里先剥 unlocked 再测。
_LOCKOUT_KEYS = ("too many attempts", "error limit")


def _is_lockout_msg(msg):
    """a454/a456：登录失败文案是否是「SSO 账号被锁」而非普通会话失效。

    锁定后每再试一次都会重置 SSO 的锁定计时（用户实锤：1 小时仍未解开，
    因为 600s 一次的退避重登一直在续期）。所以必须在文案层识别出来，
    一旦命中就停登，等用户手动触发。

    a452（审计 P0：判据闭合成环）：原实现里的「锁定」二字是子串匹配，而
    `quota._classify_nonjson` 的**密码错误**文案自带警示语「注意：
    连续错误会锁定 SSO 账号」——警示语被当成锁定事实，用户密码输错一次
    就永久停登，改对密码也不自愈。所以不能匹配裸「锁定」，必须匹配
    _classify_nonjson **优先级1 那条确定结论**的特征词。

    同理「会话失效 + 重定向」（优先级4）本身是「可能锁定也可能凭据失效」
    的不确定结论，不该当确定锁定处理：它只作为**一次性的**停登理由（避免
    反复撞锁），且 refresh_now / force_relogin / 换凭据都能立刻解除。
    """
    m = str(msg or "").lower()
    # 英文：锁定页/接口返回的原始错误（lanz_quota 会拼进各异常文案）
    if any(k in m for k in _LOCKOUT_KEYS):
        return True
    # a459：先剥 unlocked 再测 locked，防止「账号已解锁」被当锁定停登
    if "locked" in m.replace("unlocked", ""):
        return True
    if "too many" in m and "attempt" in m:
        return True
    # 中文：只认 _classify_nonjson 优先级1 的确定结论。不要匹配裸「锁定」——
    # 密码错误文案里的「会锁定 SSO 账号」是警示语，不是事实。
    if "已被 sso 锁定" in m:
        return True
    # a452（审计）：优先级3 —— 服务端登录页 `<div id="msg">` 若给出中文提示
    # （如「您的账号已被锁定」），_classify_nonjson 不命中英文关键词就落到
    # 「登录失败…服务端提示: …」。必须认带「已」的确定措辞，仍不得恢复裸
    # 「锁定」。注意不能匹配「账号已锁定」——优先级4 兜底文案「可能账号
    # 已锁定或凭据失效」含该子串，那是**不确定**结论，误判成确定锁定就是
    # 上一轮刚修掉的 P0（假锁定卡死一整夜）。
    if "已被锁定" in m:
        return True
    return "尝试次数超限" in m or "次数超限" in m


def _epoch_changed(w, cred, cred_now, cur_epoch):
    """内层负载循环的「换代」判据：凭据变了、或两个 epoch 计数任一变了。

    a452（审计）：`cur_epoch` 是 `(cur_cred_epoch, cred_epoch)` **二元组**，
    原来这里写成 `getattr(self, "_cur_cred_epoch", 0) != cur_epoch`——int 与
    tuple 恒不等 → 内层每轮必 break，600s 的全量刷新被退化成 20s 一次。
    抽成独立函数是为了让测试**直接调真实判据**，而不是在测试里复刻表达式。
    """
    return (cred_now != cred
            or cur_epoch[0] != getattr(w, "_cur_cred_epoch", 0)
            or cur_epoch[1] != w._cred_epoch)


class LanzQuotaWorker:
    """额度查询 daemon 线程。emit(kind,payload) 直写模块级缓存
    _quota_state（前端轮询 /api/proxy/status 读走），无 tkinter。"""

    REFRESH_INTERVAL = 600
    LOGIN_RETRY_WAIT = 60

    def __init__(self, emit):
        self._emit = emit
        self._cred = None
        self._auto = config.get_quota_auto()   # 自动刷新(10min)：拉额度
        self._auto_relogin = config.get_auto_relogin()   # a448：自动重登（独立）
        self._login_failed = False
        self._login_err = ""
        self._locked = False                 # a454：SSO 锁定 → 停登等手动
        self._cred_epoch = 0                 # a452：凭据提交计数（同值重提也能唤醒）
        self._refresh_req = False            # a452：手动刷新请求（唤醒后必须拉一次全量）
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def submit_credentials(self, user, pwd):
        with self._lock:
            self._cred = (user, pwd)
            # a452（审计 P2）：只比较凭据值时，用户把**同一组**账号密码再提交
            # 一次无法跳出锁定停登循环（元组相等），界面一直停在锁定态。用
            # epoch 给「提交动作」本身发信号。
            self._cred_epoch += 1
            # a452（审计 P1）：换账号/改密码要清掉上一个账号的锁定态，
            # 否则账号 A 被锁的 _locked/_login_err 会传给账号 B。
            self._locked = False
            self._login_err = ""
        self._wake.set()

    def clear_credentials(self):
        with self._lock:
            self._cred = None
            self._login_failed = False
            self._locked = False      # a452：登出必须清锁定态
            self._login_err = ""
            self._cred_epoch += 1
        self._wake.set()

    def refresh_now(self):
        """手动刷新。a454：同时解除锁定停登——用户手动点了就是要再试一次，
        这是解锁后唯一的主动出口（自动重登已被锁定拦住）。
        a452（审计 P1：点刷新对额度无效）：原实现只 _wake.set()，而内层循环
        醒来先判 `now - last_full >= 600` 未到期就跳过，手动刷新等于没刷。
        加一次性标志，内层消费后必拉一次全量。"""
        with self._lock:
            if self._cred is None:
                return False
            self._locked = False
            self._refresh_req = True
        self._wake.set()
        return True

    def force_relogin(self):
        """强制重登：丢旧 client（连旧 session cookie 一起），下轮循环换新
        client 全新登录。多天不用后 session 过期且 _ensure_login 的单次
        重试救不回来时用（用户实测场景）。代理链路零触碰——只动额度查询。
        a454：同样解除锁定停登（这是用户说的「我登一次就好了」的出口）。"""
        with self._lock:
            if self._cred is None:
                return False
            self._login_failed = False
            self._locked = False
        self._cur_cred_epoch = (getattr(self, "_cur_cred_epoch", 0) + 1)
        self._wake.set()
        return True

    def set_auto(self, on):
        """自动刷新开关：只管「每 10 分钟拉额度」。a454 落 config.json，
        否则控制台一重启就又开回来（用户实锤：关了也没用）。
        a448：**不再**在这里解除锁定——刷新与重登是两件事，锁定停登只由
        set_auto_relogin(True)/手动刷新/强制重登解除。"""
        with self._lock:
            self._auto = bool(on)
        config.set_quota_auto(bool(on))
        if on:
            self._wake.set()   # 开启时唤醒，避免卡在 wait(None)

    def set_auto_relogin(self, on):
        """a448：自动重登独立开关（用户令：不许复用「自动刷新」开关）。
        开启＝登录失败时按退避自动重登；关闭＝只等用户手动刷新/强制重登。
        默认开启（config.json 缺省即 True）。"""
        with self._lock:
            self._auto_relogin = bool(on)
            if on:
                self._locked = False   # 重新允许自动重登＝解除停登
        config.set_auto_relogin(bool(on))
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    @staticmethod
    def _push_relogin(stamps, ts, window=1800, limit=3):
        """a559：重登滑窗维护（纯函数，tests 直测）。

        返回 (new_stamps, tripped)。窗口内第 limit 次重登 → tripped
        （会话被另一处登录反复互踢——每次重登都是真实 SSO 登录，
        次数失控即锁号，视同锁定停登）。"""
        new = [t for t in stamps if ts - t < window] + [ts]
        return ([], True) if len(new) >= limit else (new, False)

    def _locked_wait(self, cred, epoch_of_cred):
        """a454/a559/a561：锁定/熔断停登等待。

        手动解锁（清 _locked）/换凭据/换代唤醒；熔断带冷却时间戳的，
        冷却到期（30 分钟）自动恢复——进程重启型风暴的跨进程熔断不能
        只靠手动。"""
        while not self._stop.is_set():
            with self._lock:
                if not self._locked or self._cred != cred:
                    return
                if self._cred_epoch != epoch_of_cred:
                    return
                trip = getattr(self, "_trip_ts", 0.0)
            if trip and time.time() - trip >= 1800:
                with self._lock:
                    self._locked = False
                    self._trip_ts = 0.0
                state.save_marks([], 0.0)
                log.info("SSO 熔断冷却到期，自动恢复")
                return
            self._wake.wait(5)
            self._wake.clear()

    def _run(self):
        client = None
        cur_cred = object()
        cur_epoch = 0
        epoch_of_cred = 0
        fail_n = 0
        cur_done = 0.0          # a559：最近一次已见的登录成功时刻
        # a559：30 分钟滑窗内的重登成功时刻（被踢熔断）；
        # a561 F5：初值改从盘上跨进程标记恢复，熔断冷却期内直接停登
        login_ok_ts, trip_ts = state.load_marks()
        self._trip_ts = trip_ts
        if trip_ts and time.time() - trip_ts < 1800:
            with self._lock:
                self._locked = True
                self._login_err = (
                    "SSO 登录过频熔断冷却中（至 %s）——近期有登录风暴或"
                    "进程重启循环；冷却到期自动恢复，或手动刷新提前解锁"
                    % time.strftime("%H:%M", time.localtime(trip_ts + 1800)))
            self._emit("login_locked", self._login_err)
            # epoch_of_cred=0（初始值）：等冷却到期/手动解锁/凭据提交
            self._locked_wait(None, 0)
        while not self._stop.is_set():
            try:
                with self._lock:
                    cred, auto = self._cred, self._auto
                    auto_relogin = self._auto_relogin
                if cred is None:
                    self._wake.wait(5)
                    self._wake.clear()
                    continue
                # a452：凭据「提交动作」也算换代信号——用户把同一组账号密码
                # 再提交一次时 cred 元组相等，只比值得不到任何变化，会卡在
                # 锁定停登循环里出不来。把 _cred_epoch 并入 epoch。
                with self._lock:
                    epoch = (getattr(self, "_cur_cred_epoch", 0),
                             self._cred_epoch)
                if cred != cur_cred or epoch != cur_epoch:
                    # 换凭据或 force_relogin（epoch++）：换新 client 丢旧 session
                    client = quota.LanzClient(*cred)
                    cur_cred = cred
                    cur_epoch = epoch
                    # a452（审计实锤：cur_epoch 是元组，下面却拿 int 比，
                    # 恒不等 → 内层每轮必 break，600s 全量刷新退化成 20s）。
                    # 复用同一份快照，不要二次读共享字段。
                    epoch_of_cred = epoch[1]
                    fail_n = 0
                    # a561 审计 F4：换账号不背旧账号的滑窗/熔断
                    login_ok_ts = []
                    self._trip_ts = 0.0
                    state.save_marks([], 0.0)
                if not self._ensure_login(client, cred):
                    self._clear_loads("登录失败，模型负载暂不可用")
                    with self._lock:
                        locked = self._locked
                        locked_err = self._login_err
                    if locked:
                        # a454（用户实锤：1 小时都没解锁）：锁定期间**不再
                        # 自动重登**。每次尝试都会重置 SSO 的锁定计时，600s
                        # 一次的退避重登等于让锁定永久续期。停在这里，只等
                        # 用户手动刷新/强制重登（它们会清 _locked）或换凭据。
                        self._emit("login_locked", locked_err)
                        self._locked_wait(cred, epoch_of_cred)
                        continue
                    # a446：SSO 连续失败会锁号（实测 "Too many attempts"）。
                    # 固定 60s 重试等于持续敲锁定账号，改指数退避 60→120→
                    # 300→600s 封顶；成功一次即归零。
                    fail_n += 1
                    wait = min(self.LOGIN_RETRY_WAIT * (2 ** min(fail_n - 1, 4)), 600)
                    # a448：是否自动重登看**独立开关** _auto_relogin，
                    # 与「自动刷新(拉额度)」解耦（用户令：不许混为一谈）
                    if not auto_relogin:
                        self._wake.wait(None)
                    else:
                        self._wake.wait(wait)
                    self._wake.clear()
                    continue
                fail_n = 0
                # a559 铁律（用户令：在线就不许反复登录）：新登录成功时刻
                # 变化才计数——30 分钟内第 3 次「重新登录成功」= 会话被
                # 另一处登录反复互踢（每次都是真实 SSO 登录，次数失控即
                # 锁号）。视同锁定停登，等用户确认单一登录处后手动刷新。
                done_ts = getattr(self, "_login_done_ts", 0.0)
                if done_ts != cur_done:
                    prev_done = cur_done
                    cur_done = done_ts
                    # a561 审计 F2：仅「距上次登录 <15 分钟」的重登计为被踢
                    # 嫌疑——自然过期型重登（会话存活长）不计数，服务端会话
                    # TTL ≥15 分钟时永不误熔断
                    if prev_done and done_ts - prev_done < 900:
                        login_ok_ts, tripped = self._push_relogin(login_ok_ts,
                                                                  done_ts)
                        state.save_marks(login_ok_ts, 0.0)
                        if tripped:
                            self._trip_ts = time.time()
                            state.save_marks([], self._trip_ts)   # F5：落盘跨进程
                            with self._lock:
                                self._locked = True
                                self._login_err = (
                                    "检测到 SSO 会话被反复踢（30 分钟内第 3 次"
                                    "重登成功——另一台机器/实例在用同一账号？）。"
                                    "已停止自动重登（30 分钟后自动恢复，或手动"
                                    "点刷新提前解锁；若服务端会话有效期本就短，"
                                    "也会触发本保护）")
                            login_ok_ts = []
                            self._emit("login_locked", self._login_err)
                            self._locked_wait(cred, epoch_of_cred)
                            continue
                # a446（严重回归修复）：负载查询必须复用**这一个** client。
                # 原先 _get_model_loads 自己 new LanzClient 并每 20s 登录一次，
                # 同一 SSO 账号两个会话互相踢——worker 刚登录就被踢回 SSO
                # 登录页，表现为「一直登录失败」，还会触发风控锁号。
                # a446（严重回归修复）：负载查询必须复用**这一个** client。
                # 原先 _get_model_loads 自己 new LanzClient 并每 20s 登录一次，
                # 同一 SSO 账号两个会话互相踢——worker 刚登录就被踢回 SSO
                # 登录页，表现为「一直登录失败」，还会触发风控锁号。
                # a446：负载 20s 级变化，额度 600s 级。切三段等待，负载每
                # LOAD_TTL 走一次 _fetch_loads（同一 client，零新登录）。
                self._cur_client = client
                last_full = 0.0
                while not self._stop.is_set():
                    now = time.time()
                    # a452（审计 P1：点刷新对额度无效）：手动刷新请求必须
                    # 立即拉一次全量，不能被下面 600s 的到期判定吃掉。
                    with self._lock:
                        force_full = self._refresh_req
                        self._refresh_req = False
                    if force_full or now - last_full >= (self.REFRESH_INTERVAL if auto else 1e9):
                        last_full = time.time()
                        if not self._fetch_all(client, cred):
                            break        # a452：会话过期 → 回外层走 _ensure_login
                    if not self._fetch_loads(client):
                        break            # 会话失效 → 回外层按 60s 退避重登
                    self._wake.clear()
                    if self._stop.is_set():
                        break
                    # 自动刷新关掉时：只等 wake（手动刷新），负载也不自动拉
                    self._wake.wait(LOAD_TTL if auto else None)
                    with self._lock:
                        cred_now, auto_now = self._cred, self._auto
                    # a452：cur_epoch 是 (cur_cred_epoch, cred_epoch) 二元组，
                    # 必须逐项比。原来 `int != tuple` 恒真，内层每轮都 break。
                    if _epoch_changed(self, cred, cred_now, cur_epoch):
                        break            # 凭据/重登变了 → 回外层重建 client
                    auto = auto_now
            except Exception:
                log.exception("LanzQuotaWorker _run 循环异常，继续运行")

    def _fetch_loads(self, client):
        """拉模型负载（a446）：复用 worker 的 client，绝不另建会话。

        返回 True=继续；False=会话失效——**不在负载通道里自己重登**。账号
        一旦被 SSO 风控锁定，20s 一次的重登会持续加重锁定，交给外层
        _ensure_login 按 60s 退避重登。
        """
        try:
            loads = client.get_model_loads()
        except quota.LanzSessionExpired:
            self._set_loads_err("会话过期，等待重新登录")
            return False
        except quota.LanzError as e:
            self._set_loads_err("负载查询失败: %s" % e)
            return True
        except Exception as e:
            log.warning("模型负载查询异常: %s", e)
            self._set_loads_err("负载查询异常: %s" % e)
            return True
        state.set_loads(loads)
        return True

    def _set_loads_err(self, msg):
        state.set_loads_err(msg)

    def _clear_loads(self, msg):
        state.clear_loads(msg)

    def _cred_changed(self, cred):
        with self._lock:
            return self._cred != cred

    def _ensure_login(self, client, cred):
        if client.logged_in:
            return True
        self._emit("login_start", None)
        try:
            client.login()
            if self._cred_changed(cred):
                return False
            with self._lock:
                self._login_failed = False
                self._login_err = ""
                self._locked = False      # a454：登录成功即解除锁定停登
                self._login_done_ts = time.time()   # a559：新登录时刻（被踢熔断判据）
            self._emit("login_ok", cred[0])
            return True
        except quota.LanzAuthError as e:
            msg = str(e)
            with self._lock:
                # a452（审计）：旧账号的 login() 在途时用户提交了新账号，
                # 这里若照写 _locked/_login_err，会把旧账号的锁定态喂给新
                # 账号（界面闪一次误导性的「账号已被 SSO 锁定」）。持锁区
                # 内只能直接比字段——_cred_changed 会重新 acquire 死锁。
                if self._cred == cred:
                    self._login_failed = True
                    self._login_err = msg
                    # a454（用户实锤：1 小时不解锁——锁定期间每 600s 仍自动
                    # 登一次，每次尝试都把 SSO 锁定计时重置，等于永久续期）。
                    # 识别到锁定文案就**停登**，不再定时重试，等用户手动点
                    # 刷新/重登。
                    if _is_lockout_msg(msg):
                        self._locked = True
            if not self._cred_changed(cred):
                self._emit("login_err", msg)
            return False
        except quota.LanzNetworkError as e:
            # a452（审计 P1）：锁定文案不只从 LanzAuthError 出来——_fetch_text
            # 在 HTTP 401/403/500 时把响应体拼进 LanzNetworkError，锁定页的
            # "Too many attempts" 会走这条。只认 LanzAuthError 就漏判，外层
            # 按 60→600s 退避持续重登，把 SSO 锁定反复续期。
            msg = "网络错误（需内网/VPN）: %s" % e
            with self._lock:
                self._login_failed = True
                if _is_lockout_msg(msg):
                    self._locked = True
                    self._login_err = msg
            if not self._cred_changed(cred):
                self._emit("login_err", msg)
            return False
        except quota.LanzError as e:
            # a452：同理，_request 在 code!=2001/3001 时抛的通用 LanzError
            # 也可能带锁定文案（"API 返回错误 code=… msg=Too many attempts"）。
            msg = "登录失败: %s" % e
            with self._lock:
                self._login_failed = True
                if _is_lockout_msg(msg):
                    self._locked = True
                    self._login_err = msg
            if not self._cred_changed(cred):
                self._emit("login_err", msg)
            return False

    def _fetch_all(self, client, cred=None):
        """拉额度全量。返回 True=继续，False=会话已过期，调用方须回外层重登。

        a452：原 `for attempt in (1, 2)` 的重试只服务于「会话过期 → force
        重登 → 再取一次」这一条（唯一 continue 的路径，已删）。现在会话
        过期直接返回 False，循环只跑一轮。

        a452（审计）：原来这里只 emit 不返回状态，内层靠紧随的
        _fetch_loads 也报 3001 才 break。若 dashboard 走 /v1/ai-resource 已
        过期、而 models 走 /v1/openai/models 仍 2001（两条网关路径），内层
        永不回外层 → 额度面板永久「会话过期，等待重新登录」直到手动重登。
        会话过期必须以返回值显式传递。
        """
        try:
            dash = client.get_dashboard()
            budget = None
            try:
                budget = client.get_budget_overview()
            except quota.LanzError:
                pass
            if cred is not None and self._cred_changed(cred):
                return True
            self._emit("data", {"dashboard": dash, "budget": budget,
                                "ts": time.time()})
            return True
        except quota.LanzSessionExpired:
            # a452（审计 P1）：这里原有 `client.login(force=True)` 私有重登，
            # 绕过了 _ensure_login 的锁定识别、_auto_relogin 开关和锁定停登
            # ——自动重登关着照样重登、账号已锁照样再敲一次把锁定计时续期。
            # 刷新路径不允许自带重登：如实报会话过期，交给外层 _run 统一
            # 走 _ensure_login（那里才认锁定与开关）。
            if cred is None or not self._cred_changed(cred):
                self._emit("fetch_err", "会话过期，等待重新登录")
            return False
        except quota.LanzNetworkError as e:
            if cred is None or not self._cred_changed(cred):
                self._emit("fetch_err", "网络错误: %s" % e)
            return True
        except quota.LanzError as e:
            if cred is None or not self._cred_changed(cred):
                self._emit("fetch_err", "查询失败: %s" % e)
            return True