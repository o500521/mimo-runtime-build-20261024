"""Free cloud CPU transport tests. MOCK model; no weights, GPU or paid APIs."""
import base64
import http.server
import json
import os
import pathlib
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import urllib.request
from unittest.mock import patch

import chat_local
import chat_ui_gateway
import runtime_session as session
from gpu_smoke import validate_devices
from playwright.sync_api import sync_playwright, expect

PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
state = {'requests': [], 'fail': False}
checks = []


def passed(name):
    checks.append(name)
    print('PASS:', name, flush=True)


class MockModel(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if state['fail']: return self.reply(503, {'error': {'message': 'MOCK unavailable'}})
        if self.path == '/v1/models': return self.reply(200, {'data': [{'id': 'mimo-2.6-pro'}], 'mock': True})
        return self.reply(404, {'error': 'MOCK route not found'})
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        state['requests'].append({'payload': payload, 'auth': self.headers.get('Authorization'),
                                  'api_key': self.headers.get('api-key')})
        content = payload['messages'][-1]['content']
        image = isinstance(content, list) and any(x.get('type') == 'image_url' for x in content)
        self.reply(200, {'choices': [{'message': {'role': 'assistant', 'content': 'MOCK ONLY IMAGE' if image else 'MOCK ONLY TEXT',
                    'reasoning_content': 'MOCK transport check; no inference.'}, 'finish_reason': 'stop'}], 'usage': {'total_tokens': 1}})


class ThreadedHTTP(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(handler, port):
    server = ThreadedHTTP(('127.0.0.1', port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def request_json(path, data, origin='http://127.0.0.1:8766'):
    req = urllib.request.Request('http://127.0.0.1:8766'+path, data=json.dumps(data).encode(),
            headers={'Content-Type': 'application/json', 'Origin': origin})
    with urllib.request.urlopen(req, timeout=5) as response: return json.load(response)


def main():
    # No credentials or network routes to any real model/API are available in this test.
    original_endpoint = chat_local.endpoint
    def loopback_only(base, suffix):
        result = original_endpoint(base, suffix)
        if not result.startswith('http://127.0.0.1:'):
            raise ValueError('CI blocks every non-loopback upstream')
        return result
    chat_local.endpoint = loopback_only
    chat_local.OFFICIAL_SESSION['key'] = 'DUMMY_MEMORY_KEY_NOT_A_REAL_CREDENTIAL'
    model = serve(MockModel, 30000)
    backend = serve(chat_local.Handler, 8765)
    gateway = serve(chat_ui_gateway.Handler, 8766)
    try:
        assert session.wait_ready('http://127.0.0.1:30000', 2) == ['mimo-2.6-pro']
        passed('readiness recognizes the configured served model ID')
        calls=[]
        def fake_docker(cmd, **kwargs):
            calls.append(cmd); return subprocess.CompletedProcess(cmd, 0)
        assert session.start_model(fake_docker, timeout=2) == ['mimo-2.6-pro']
        assert calls[0] == session.launch_command()
        assert '--detach' in calls[0] and '127.0.0.1' in calls[0][calls[0].index('HOST=127.0.0.1')]
        passed('start command -> readiness -> served model; Docker invocation simulated')
        state['fail']=True; calls=[]
        try:
            session.start_model(fake_docker, timeout=.15)
            raise AssertionError('Expected readiness timeout')
        except TimeoutError: pass
        assert calls[-1][:2]==['docker','stop'] and calls[-2][:2]==['docker','logs']
        passed('readiness timeout captures logs, stops model, and does not silently extend runtime')
        state['fail']=False
        blocked=subprocess.run([sys.executable, str(pathlib.Path(session.__file__)), 'start'], capture_output=True, text=True)
        assert blocked.returncode==2 and 'explicit approval required' in blocked.stderr
        passed('start refuses to execute without explicit approval')
        assert not session.budget_estimate(1_000_000, 16.72, 10)['fits_current_credit']
        assert session.budget_estimate(500_000_000, 16.72, 40)['fits_current_credit']
        passed('budget gate rejects insufficient current credit; estimates are explicitly non-guarantees')
        blocked_download=subprocess.run([sys.executable,session.__file__,'download','--approved','--provider-spend-cap-confirmed','--measured-mbps','8','--hourly-usd','16.72','--remaining-usd','10'],capture_output=True,text=True)
        assert blocked_download.returncode==3 and 'false' in blocked_download.stdout
        passed('insufficient allowance blocks full checkpoint download before executing the downloader')
        hardware=[dict(name='NVIDIA RTX PRO 6000 Blackwell',capability=[12,0],memory_bytes=96_000_000_000) for _ in range(8)]
        validate_devices(hardware)
        for altered in [hardware[:7],[{**d,'memory_bytes':48_000_000_000} for d in hardware],[{**d,'capability':[9,0]} for d in hardware]]:
            try:validate_devices(altered);raise AssertionError('Invalid hardware accepted')
            except ValueError:pass
        passed('hardware gate rejects wrong GPU count, insufficient VRAM or wrong architecture; mock device metadata only')
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp); (root/'model.safetensors.index.json').write_text(json.dumps({'weight_map':{'x':'part.safetensors'}}))
            try: session.validate_checkpoint(root); raise AssertionError('Missing shard accepted')
            except ValueError: pass
            (root/'part.safetensors').write_bytes(b'x'*1024)
            assert session.validate_checkpoint(root)==1
        passed('missing or incomplete checkpoint prevents model start')
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page()
            page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(('http://127.0.0.1:', 'data:')) else route.abort())
            page.goto('http://127.0.0.1:8766/'); page.wait_for_load_state('networkidle')
            page.locator('#provider').select_option('local'); page.locator('#check').click()
            expect(page.locator('#status')).to_contain_text('已連線：mimo-2.6-pro')
            assert page.locator('#model').input_value()=='mimo-2.6-pro'
            passed('actual chat gateway/backend discover and select served model ID')
            page.locator('#prompt').fill('Benign text transport test'); page.locator('#send').click()
            expect(page.locator('#messages')).to_contain_text('MOCK ONLY TEXT')
            assert state['requests'][-1]['payload']['messages'][-1]['content']=='Benign text transport test'
            assert state['requests'][-1]['auth'] is None and state['requests'][-1]['api_key'] is None
            assert state['requests'][-1]['payload']['stream'] is False
            passed('text, reasoning display and local request format; official RAM key is not forwarded')
            page.locator('#clear').click()
            page.locator('#image').set_input_files({'name':'test.png','mimeType':'image/png','buffer':base64.b64decode(PNG)})
            expect(page.locator('#imageName')).to_contain_text('可只傳圖片')
            page.locator('#send').click(); expect(page.locator('#messages')).to_contain_text('MOCK ONLY IMAGE')
            content=state['requests'][-1]['payload']['messages'][-1]['content']
            assert len(content)==1 and content[0]['type']=='image_url'
            assert content[0]['image_url']['url'].startswith('data:image/png;base64,')
            passed('image-only submission crosses actual UI -> gateway -> backend -> mock model')
            for event in ['paste','drop']:
                page.locator('#clear').click()
                page.evaluate('''({event,b64})=>{const bytes=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));const dt=new DataTransfer();dt.items.add(new File([bytes],'test.png',{type:'image/png'}));const e=event==='paste'?new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}):new DragEvent('drop',{dataTransfer:dt,bubbles:true,cancelable:true});document.dispatchEvent(e);}''', {'event':event,'b64':PNG})
                expect(page.locator('#imageName')).to_contain_text('可只傳圖片')
                page.locator('#send').click(); expect(page.locator('#messages')).to_contain_text('MOCK ONLY IMAGE')
                passed(event+' image -> preview -> image-only send')
            page.locator('#clear').click(); before=len(state['requests']); page.locator('#send').click()
            expect(page.locator('#status')).to_contain_text('請輸入問題或選擇一張圖片')
            assert len(state['requests'])==before
            passed('empty submit does not call model')
            page.locator('#image').set_input_files({'name':'bad.txt','mimeType':'text/plain','buffer':b'not image'})
            expect(page.locator('#status')).to_contain_text('單張不超過2MB')
            assert len(state['requests'])==before
            passed('unsupported image type is blocked before network transmission')
            page.locator('#image').set_input_files({'name':'too-big.png','mimeType':'image/png','buffer':b'x'*(2*1024*1024+1)})
            expect(page.locator('#status')).to_contain_text('單張不超過2MB')
            assert len(state['requests'])==before
            passed('oversized image is blocked before network transmission')
            state['fail']=True; page.locator('#check').click()
            expect(page.locator('#status')).to_contain_text('API HTTP 503')
            state['fail']=False; page.locator('#check').click()
            expect(page.locator('#status')).to_contain_text('已連線')
            passed('upstream failure is visible and recovery/reconnect succeeds')
            try:
                request_json('/models',{'base':'http://127.0.0.1:30000/v1','key':''},'https://example.invalid')
                raise AssertionError('Foreign origin accepted')
            except urllib.error.HTTPError as error: assert error.code==403
            passed('foreign-origin browser requests are rejected')
            page.screenshot(path='integration-proof.png', full_page=True)
            browser.close()
        result={'passed':len(checks),'checks':checks,'mock_only':True,'gpu_rented':False,
                'model_weights_loaded':False,'paid_api_called':False,'real_ssh_verified':False}
        pathlib.Path('integration-results.json').write_text(json.dumps(result,indent=2))
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f: print('## MOCK transport integration checks',json.dumps(result,indent=2),file=f)
        print(json.dumps(result,indent=2))
    finally:
        for server in [gateway,backend,model]: server.shutdown(); server.server_close()


if __name__=='__main__': main()
