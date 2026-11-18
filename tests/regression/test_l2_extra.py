# -*- coding: utf-8 -*-
"""L2 补充链路：编辑器保存、日志回放、命令库编辑模态。

写操作只作用于 tests/regression/fixtures/ 下的样本文件，测后恢复原内容。
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from cdp_lib import Page, result          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(_HERE))
FIX = os.path.join(ROOT, "tests", "regression", "fixtures").replace(os.sep, "/")
SAMPLE = os.path.join(ROOT, "tests", "regression", "fixtures", "sample.txt")


def _read_sample():
    with open(SAMPLE, encoding="utf-8") as f:
        return f.read()


def _write_sample(text):
    with open(SAMPLE, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _wait_file_contains(marker, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if marker in _read_sample():
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def run():
    try:
        pg = Page()
    except Exception as e:
        return [result("L2X-ENV", "L2 补充环境", "L2", "P0", "SKIP", "应用未运行: %r" % e)]
    out = []
    original = _read_sample()
    try:
        pg.clear_errs()
        # ---- E1-5 编辑器保存（Ctrl+S 链路） ----
        try:
            pg.ev("(async()=>{await window.openFileSmart(%s,'auto');return 1;})()"
                  % json.dumps(FIX + "/sample.txt"), await_promise=True, timeout=60)
            ok_monaco = pg.wait_until(
                "Object.values(connections).some(c=>c.meta&&c.meta.label==='sample.txt'&&!!c.monaco)",
                timeout=15, interval=0.5)
            marker = "回归保存验证-" + str(int(time.time()))
            pg.ev("(function(){var c=Object.values(connections).find(x=>x.meta&&x.meta.label==='sample.txt');"
                  "if(!c)return 'no-conn';c.monaco.setValue(c.monaco.getValue()+'\\n%s');"
                  "return 'set';})()" % marker)
            time.sleep(0.5)
            pg.ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'s',code:'KeyS',"
                  "ctrlKey:true,bubbles:true,cancelable:true}))")
            saved = _wait_file_contains(marker, timeout=10)
            out.append(result("E1-5", "编辑器修改后 Ctrl+S 保存", "L2", "P1",
                              "PASS" if ok_monaco and saved else "FAIL",
                              "monaco=%s saved=%s" % (ok_monaco, saved)))
            # 关闭 tab
            pg.ev("(function(){var c=Object.values(connections).find(x=>x.meta&&x.meta.label==='sample.txt');"
                  "if(c)window.closeEditorTab(c.portId);return 1;})()")
            time.sleep(0.5)
        except Exception as e:
            out.append(result("E1-5", "编辑器修改后 Ctrl+S 保存", "L2", "P1", "CHECK", repr(e)))
        finally:
            _write_sample(original)      # 无论成败恢复样本
        # ---- O1-12 日志回放 ----
        try:
            pg.ev("document.querySelector('#btnLogs') && document.querySelector('#btnLogs').click()")
            time.sleep(0.8)
            has_replay = pg.ev("document.querySelectorAll('#logsList [data-replay]').length")
            if has_replay:
                pg.ev("document.querySelector('#logsList [data-replay]').click()")
                time.sleep(1.5)
                rp = pg.ev_obj(
                    "JSON.stringify({open:!!document.querySelector('#replayPanel.show'),"
                    "info:((document.querySelector('#replayInfo')||{}).textContent||'').slice(0,40),"
                    "body:((document.querySelector('#replayBody')||{}).children||[]).length})")
                pg.ev("(function(){var b=document.querySelector('#btnReplayClose');"
                      "if(b)b.click();return 1;})()")
                time.sleep(0.4)
                closed = not pg.ev("!!document.querySelector('#replayPanel.show')")
                out.append(result("O1-12", "日志回放面板（打开/信息/关闭）", "L2", "P2",
                                  "PASS" if rp.get("open") and closed else "CHECK",
                                  json.dumps(rp, ensure_ascii=False)))
            else:
                out.append(result("O1-12", "日志回放面板（打开/信息/关闭）", "L2", "P2",
                                  "SKIP", "日志列表无条目"))
        except Exception as e:
            out.append(result("O1-12", "日志回放面板（打开/信息/关闭）", "L2", "P2", "CHECK", repr(e)))
        # ---- O1-6b 命令库编辑模态 ----
        try:
            has_edit = pg.ev("document.querySelectorAll('#cmdLibrary .cmd-edit-trigger').length")
            if has_edit:
                pg.ev("document.querySelector('#cmdLibrary .cmd-edit-trigger').click()")
                time.sleep(0.6)
                em = pg.ev_obj(
                    "JSON.stringify({open:!!document.querySelector('#cmdEditModal.show'),"
                    "name:((document.querySelector('#cmdEditName')||{}).value||'').slice(0,20),"
                    "cmd:((document.querySelector('#cmdEditCmd')||{}).value||'').slice(0,20)})")
                pg.ev("(function(){var b=document.querySelector('#cmdEditClose');"
                      "if(b)b.click();return 1;})()")
                time.sleep(0.3)
                closed = not pg.ev("!!document.querySelector('#cmdEditModal.show')")
                out.append(result("O1-6b", "命令库编辑模态（打开/回填/关闭）", "L2", "P2",
                                  "PASS" if em.get("open") and closed else "CHECK",
                                  json.dumps(em, ensure_ascii=False)))
            else:
                out.append(result("O1-6b", "命令库编辑模态（打开/回填/关闭）", "L2", "P2",
                                  "SKIP", "命令库无条目"))
        except Exception as e:
            out.append(result("O1-6b", "命令库编辑模态（打开/回填/关闭）", "L2", "P2", "CHECK", repr(e)))
        errs = pg.drain_errs()
        out.append(result("L2XE", "L2 补充链路无页面异常", "L2", "P0",
                          "PASS" if not errs else "FAIL",
                          json.dumps(errs[:5], ensure_ascii=False)))
    finally:
        _write_sample(original)
        pg.close()
    return out


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
