"""Runnable real-browser acceptance harness for the pipeline panel.

Run with /opt/hermes/.venv/bin/python tests/test_pipeline_ui_browser.py.
It starts the real FastAPI app against an isolated temporary SQLite board,
then uses the installed browser-harness daemon to exercise the real page.
"""
import json, os, shutil, socket, sqlite3, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = "/opt/hermes/.venv/bin/python"
BROWSER = "/opt/data/installs/351f81cc06284494/environments/a063469458cb452a81155be546988223/venv/bin/browser-harness"
TOKEN = "isolated-viewer"


def run_browser(code):
    proc = subprocess.run([BROWSER], input=code, text=True, capture_output=True, timeout=120, cwd=ROOT)
    print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="")
    if proc.returncode:
        raise RuntimeError(f"browser-harness exit={proc.returncode}")


def main():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    server = subprocess.Popen([PY, str(ROOT / "tests/pipeline_ui_fixture_server.py"), str(port)], cwd=ROOT,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        line = server.stdout.readline().strip()
        if "ISOLATED_BOARD=" not in line:
            raise RuntimeError(f"fixture server failed to start: {line}")
        board = Path(line.split("ISOLATED_BOARD=", 1)[1].split(" PORT=", 1)[0])
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                with urllib.request.urlopen(base + "/healthz", timeout=.3): break
            except Exception: time.sleep(.05)
        else: raise RuntimeError("isolated HTTP fixture server did not become ready")
        with urllib.request.urlopen(base + "/v1/state?token=" + TOKEN) as r:
            state = json.load(r)
        assert state["pipeline_available"] is True and len(state["agents"]) == 0
        assert state["pipelines_omitted"] == 2 and len(state["pipeline"]) == 5
        print("HTTP fixture: status=200, agents=0, pipelines=5, omitted=2")

        positive = f'''\
import time
ensure_real_tab()
goto_url({base!r} + "/")
wait_for_load()
time.sleep(1)
if "hidden" in js("document.querySelector('#gate').className"):
    pass
else:
    fill_input('#tok', {TOKEN!r})
    js("document.querySelector('#gateform button').click()")
    time.sleep(1)
result = js("(() => {{const b=document.querySelector('#taskPipelineBody'),t=b.innerText;return {{rows:b.querySelectorAll('.pipeline-row').length,children:b.querySelectorAll('.pipeline-child').length,hidden:b.querySelector('.pipeline-omitted')?.innerText,subtitle:b.querySelector('.pipeline-subtitle')?.innerText,shared:b.querySelector('.pipeline-shared')?.innerText||null,blockedFirst:b.querySelector('.pipeline-child .pipeline-dot.blocked')!==null,flags:b.querySelectorAll('.pipeline-emergent').length,hostile:t.includes('Hostile <img src=x onerror=alert(1)>')&&!b.querySelector('.pipeline-title img'),wib:/WIB/.test(t),missing:t.includes('Started unavailable')}}}})()")
print("POSITIVE_DOM=" + str(result))
assert result['rows']==5 and result['children']==4 and result['hidden']=='+2 older pipelines hidden'
assert result['subtitle']=='planned 0 / added 8' and result['shared']=='also under 1'
assert result['blockedFirst'] and result['hostile'] and result['wib'] and result['flags']>=2
js("document.querySelector('#taskPipelineBody .pipeline-more').click()")
assert js("document.querySelectorAll('#taskPipelineBody .pipeline-child').length") == 8
assert 'Started unavailable' in js("document.querySelector('#taskPipelineBody').innerText")
shot = capture_screenshot()
print("SCREENSHOT=" + str(shot))
goto_url({base!r} + "/")
wait_for_load();time.sleep(1)
assert js("document.querySelectorAll('#taskPipelineBody .pipeline-child').length") == 8
print("reload persistence: 8 children; actual WIB and missing-start fallback rendered")
// Clear expansion, deny storage writes, and prove the in-memory fallback rerenders.
js("sessionStorage.removeItem('mc.pipeline.expanded.ui-root')")
goto_url({base!r} + "/")
wait_for_load();time.sleep(1)
js("Object.defineProperty(Storage.prototype,'setItem',{{configurable:true,value:function(){{throw new Error('storage denied')}}}})")
assert js("document.querySelectorAll('#taskPipelineBody .pipeline-child').length") == 4
js("document.querySelector('#taskPipelineBody .pipeline-more').click()")
assert js("document.querySelectorAll('#taskPipelineBody .pipeline-child').length") == 8
js("document.querySelector('#taskPipelineBody .pipeline-more').click()")
assert js("document.querySelectorAll('#taskPipelineBody .pipeline-child').length") == 4
js("document.querySelector('#taskPipelineBody .pipeline-more').click()")
assert js("document.querySelectorAll('#taskPipelineBody .pipeline-child').length") == 8
print("storage-denied fallback: expand/collapse/re-expand passed")
'''
        run_browser(positive)

        # Change only the disposable DB and reload through the actual HTTP route.
        con = sqlite3.connect(board); con.execute("DELETE FROM task_links"); con.execute("DELETE FROM tasks"); con.commit(); con.close()
        time.sleep(2.1)
        run_browser(f'''\
import time
ensure_real_tab();goto_url({base!r} + "/");wait_for_load();time.sleep(1)
empty=js("document.querySelector('#taskPipelineBody').innerText")
print("EMPTY_DOM=" + empty)
assert empty == "No decomposed tasks in flight."
''')
        # The request fails closed when the isolated source schema is unavailable.
        board.rename(board.with_suffix(".offline"))
        time.sleep(2.1)
        run_browser(f'''\
import time
ensure_real_tab();goto_url({base!r} + "/");wait_for_load();time.sleep(1)
failure=js("document.querySelector('#taskPipelineBody').innerText")
print("FAILURE_DOM=" + failure)
assert failure == "board unavailable"
''')
        print("UI browser acceptance: PASS (empty/failure clear rows and omitted counter)")
    finally:
        server.terminate()
        try: server.wait(timeout=4)
        except subprocess.TimeoutExpired: server.kill(); server.wait(timeout=2)


if __name__ == "__main__":
    main()
