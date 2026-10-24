"""Local-only chat interface for an existing OpenAI-compatible model endpoint."""
import json, urllib.request, urllib.error, urllib.parse, http.server, pathlib, argparse

HTML = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>模型測試對話</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f7f7f5;color:#202321;font:15px/1.6 system-ui,"Microsoft JhengHei",sans-serif}main{max-width:960px;margin:auto;padding:24px}header{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #ddd;padding-bottom:16px}h1{font-size:22px;margin:0}.muted{font-size:13px;color:#69716c}button,input,select,textarea{font:inherit;border:1px solid #ccc;border-radius:6px;padding:9px;background:white;color:inherit}button{cursor:pointer}button:disabled{opacity:.5;cursor:default}.primary{background:#205b46;color:white;border-color:#205b46}details{margin:18px 0;border:1px solid #ddd;background:white;padding:12px}summary{cursor:pointer;font-weight:600}.settings{display:grid;grid-template-columns:2fr 1fr;gap:12px;padding-top:12px}label{display:block;font-size:13px}input,select{width:100%}.actions{display:flex;gap:8px;margin-top:12px;align-items:center;flex-wrap:wrap}#status{padding:9px 0;font-size:13px;color:#7a4e16}#messages{min-height:240px;max-height:55vh;overflow:auto;border:1px solid #ddd;background:white;border-radius:6px;padding:18px}.message{margin:0 0 24px}.role{font-size:12px;font-weight:700;color:#4c6659;margin-bottom:5px}.body{white-space:pre-wrap;overflow-wrap:anywhere}.reason{font-size:13px;color:#626762;white-space:pre-wrap}textarea{width:100%;min-height:110px;resize:vertical;margin-top:16px}.composer{display:flex;justify-content:space-between;align-items:center;gap:12px}.error{color:#b13636!important}#empty{color:#707671} @media(max-width:600px){main{padding:14px}.settings{grid-template-columns:1fr}header{align-items:flex-start;gap:10px}#messages{max-height:48vh}}#form{border:2px dashed transparent;border-radius:8px;padding:8px;margin-top:12px}#form.dragover{border-color:#205b46;background:#edf6f0}#imagePreview{display:block;max-width:240px;max-height:160px;margin:10px 0;border-radius:6px}#imagePreview[hidden]{display:none}</style>
<main><header><div><h1>模型測試對話</h1><div class="muted">自行提問 · 對話僅留在此分頁</div></div><button id="clear" type="button">清空對話</button></header>
<details open><summary>模型連線設定</summary><div class="settings"><label>連線方式<select id="provider"><option value="official">小米官方 API</option><option value="local">八卡自架（SSH 轉發）</option></select></label><label>API 位址<input id="base" value="https://api.xiaomimimo.com/v1" readonly spellcheck="false"></label><label>模型 ID<input id="model" value="mimo-v2.6-pro" spellcheck="false"></label><label>API Key（需要時填；不儲存）<input id="key" type="password" autocomplete="off"></label><label>單次最大輸出 tokens<input id="limit" type="number" min="128" max="32768" value="4096"></label></div><div class="actions"><button id="check" type="button">檢查連線</button><label><input id="thinking" type="checkbox" checked style="width:auto"> 啟用模型思考（端點須支援）</label><span class="muted">連線檢查不送出問題</span></div></details>
<div id="status" role="status" aria-live="polite">已選小米官方 API。請貼入完整 API Key 後檢查連線；尚未呼叫模型。</div><section id="messages" aria-label="對話紀錄"><div id="empty">在下方輸入你自己的問題。連接運行中的模型後即可送出。</div></section>
<form id="form"><label for="prompt" class="muted">你的問題</label><textarea id="prompt" placeholder="輸入問題，或按 Ctrl＋V 貼上圖片；也可拖曳圖片到這裡…"></textarea><div class="muted">支援 Ctrl／⌘＋V 貼上圖片，或將圖片檔拖曳到此處；每次一張。</div><img id="imagePreview" alt="待送出圖片預覽" hidden><div class="actions"><label>圖片（PNG／JPEG／WebP，單張最多2MB）<input id="image" type="file" accept="image/png,image/jpeg,image/webp"></label><button id="removeImage" type="button">移除圖片</button><span id="imageName" class="muted" role="status"></span></div><div class="composer"><span class="muted">Ctrl／⌘ + Enter 送出</span><button class="primary" id="send">送出問題</button></div></form></main>
<script>const $=id=>document.getElementById(id);let history=[],busy=false,imageData=null,imageLoading=false,imageVersion=0;function status(s,error=false){$('status').textContent=s;$('status').className=error?'error':''}function busySet(b){busy=b;['send','check','clear','provider','base','model','key','limit','image','removeImage','thinking'].forEach(id=>$(id).disabled=b)}function add(role,text,reason){$('empty')?.remove();let wrap=document.createElement('article');wrap.className='message';let title=document.createElement('div');title.className='role';title.textContent=role;wrap.append(title);if(reason){let det=document.createElement('details'),sum=document.createElement('summary'),pre=document.createElement('div');sum.textContent='模型回傳的推理欄位';pre.className='reason';pre.textContent=reason;det.append(sum,pre);wrap.append(det)}let body=document.createElement('div');body.className='body';body.textContent=text;wrap.append(body);$('messages').append(wrap);$('messages').scrollTop=$('messages').scrollHeight;return wrap}
function config(){return{base:$('base').value.trim(),key:$('key').value.trim()}}$('provider').onchange=()=>{let official=$('provider').value==='official';$('base').value=official?'https://api.xiaomimimo.com/v1':'http://127.0.0.1:30000/v1';$('base').readOnly=official;$('model').value=official?'mimo-v2.6-pro':'XiaomiMiMo/MiMo-V2.6-Pro-MOPD';history=[];status('已切換連線；新問題不會帶入先前模型的對話。')};async function api(path,data){let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...config(),...data})});let d=await r.json();if(!r.ok)throw Error(d.error||'連線失敗');return d}
$('check').onclick=async()=>{busySet(true);status('檢查模型端點…');try{let d=await api('/models',{});let ids=(d.data||[]).map(x=>x.id);if(!ids.length)throw Error('端點沒有回傳可用模型');if(!ids.includes($('model').value))$('model').value=ids[0];status('已連線：'+ids.join('、'))}catch(e){status(e.message,true)}finally{busySet(false)}};
$('form').onsubmit=async e=>{e.preventDefault();if(busy)return;if(imageLoading){status('圖片讀取中，請稍候再送出。',true);return}let text=$('prompt').value.trim();if(!text&&!imageData){status('請輸入問題或選擇一張圖片。',true);return}let content=imageData?[...(text?[{type:'text',text}]:[]),{type:'image_url',image_url:{url:imageData}}]:text;let next=[...history,{role:'user',content}];let user=add('你',text+(imageData?' [已附圖片]':''));busySet(true);status('等待模型回答…');let start=performance.now();try{let d=await api('/chat',{request:{model:$('model').value.trim(),messages:next,max_tokens:Number($('limit').value),temperature:1,top_p:.95,stream:false,chat_template_kwargs:{enable_thinking:$('thinking').checked}}});let c=d.choices?.[0],m=c?.message;if(!m)throw Error('模型沒有回傳回答');let answer=m.content||'';add('模型',answer||'模型未回傳最終回答；可增加輸出上限後重試。',m.reasoning_content||m.reasoning);if(answer){history=[...next,{role:'assistant',content:answer,...(m.reasoning_content?{reasoning_content:m.reasoning_content}:{})}];$('prompt').value='';clearImage()}else user.remove();let tokens=d.usage?.total_tokens;status('完成 · '+((performance.now()-start)/1000).toFixed(1)+' 秒'+(tokens?' · '+tokens+' tokens':'')+(c.finish_reason==='length'?' · 已達輸出上限':''))}catch(e){user.remove();status('未送達或未完成：'+e.message,true)}finally{busySet(false)}};
function clearImage(){imageVersion++;imageLoading=false;imageData=null;$('image').value='';$('imageName').textContent='';$('imagePreview').hidden=true;$('imagePreview').removeAttribute('src')}
async function acceptImage(f){if(busy)return;if(!f)return;if(!['image/png','image/jpeg','image/webp'].includes(f.type)||f.size>2*1024*1024){status('請選PNG、JPEG或WebP，單張不超過2MB。',true);return}let version=++imageVersion;imageLoading=true;status('讀取圖片…');try{let data=await new Promise((resolve,reject)=>{let reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(f)});if(version!==imageVersion)return;imageData=data;$('imageName').textContent=(f.name||'貼上的圖片')+' · 可只傳圖片，文字可留空';$('imagePreview').src=data;$('imagePreview').hidden=false;status('圖片已就緒，按「送出問題」傳送。')}catch(e){if(version===imageVersion){clearImage();status('圖片讀取失敗。',true)}}finally{if(version===imageVersion)imageLoading=false}}
$('removeImage').onclick=clearImage;$('image').onchange=()=>{let f=$('image').files[0];if(f)acceptImage(f)};
document.addEventListener('paste',e=>{let item=Array.from(e.clipboardData?.items||[]).find(i=>i.kind==='file'&&i.type.startsWith('image/'));if(!item)return;e.preventDefault();if(!busy)acceptImage(item.getAsFile())});
document.addEventListener('dragover',e=>{if(!Array.from(e.dataTransfer?.types||[]).includes('Files'))return;e.preventDefault();if(!busy)$('form').classList.add('dragover')});
document.addEventListener('dragleave',e=>{if(!e.relatedTarget)$('form').classList.remove('dragover')});
document.addEventListener('drop',e=>{let files=Array.from(e.dataTransfer?.files||[]);if(!files.length)return;e.preventDefault();$('form').classList.remove('dragover');if(busy)return;if(files.length!==1){status('一次請拖曳一張圖片。',true);return}acceptImage(files[0])});
$('clear').onclick=()=>{history=[];clearImage();$('messages').replaceChildren();let empty=document.createElement('div');empty.id='empty';empty.textContent='對話已清空。';$('messages').append(empty);status('對話已清空。')};$('prompt').onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();$('form').requestSubmit()}};
</script></html>'''

OFFICIAL_HOST = 'api.xiaomimimo.com'
# Per-process only: survives a page refresh, never written to disk or returned.
OFFICIAL_SESSION = {'key': ''}

def endpoint(base, suffix):
    p=urllib.parse.urlsplit(base)
    if p.username or p.password or p.query or p.fragment:
        raise ValueError('API 位址不可包含帳密、查詢參數或片段。')
    local=p.scheme in ('http','https') and p.hostname in ('127.0.0.1','localhost','::1')
    official=p.scheme=='https' and p.hostname==OFFICIAL_HOST and p.port in (None,443)
    if not (local or official):
        raise ValueError('僅允許本機模型或小米官方 https://api.xiaomimimo.com/v1。')
    if p.path.rstrip('/') not in ('','/v1'):
        raise ValueError('API 路徑必須是 /v1。')
    if local and p.port==8765:
        raise ValueError('API 不能指向對話頁本身。')
    return urllib.parse.urlunsplit((p.scheme,p.netloc,'/v1/'+suffix,'',''))

def adapt_request(request, official):
    req=dict(request)
    limit=req.get('max_tokens')
    if type(limit) is not int or not 128<=limit<=32768:
        raise ValueError('輸出 tokens 請設為128至32768。')
    req['stream']=False
    if official:
        if req.get('model')!='mimo-v2.6-pro':
            raise ValueError('官方測試請使用模型 ID mimo-v2.6-pro。')
        req['max_completion_tokens']=req.pop('max_tokens')
        thinking=req.pop('chat_template_kwargs',{}).get('enable_thinking',True)
        req['thinking']={'type':'enabled' if thinking else 'disabled'}
    return req

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url,code,'Redirect refused',headers,fp)

OPENER=urllib.request.build_opener(NoRedirect())

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def reply(self,status,data,kind='application/json; charset=utf-8'):
        body=data.encode() if isinstance(data,str) else json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path in ('/','/index.html'):
            page=HTML
            if OFFICIAL_SESSION['key']:
                page=page.replace('已選小米官方 API。請貼入完整 API Key 後檢查連線；尚未呼叫模型。','官方金鑰已在本機服務記憶體中；API Key 可留空。重啟服務後需重新設定。')
            return self.reply(200,page,'text/html; charset=utf-8')
        self.reply(404,{'error':'Not found'})
    def do_POST(self):
        if self.path not in ('/models','/chat'): return self.reply(404,{'error':'Not found'})
        origin=self.headers.get('Origin')
        if origin and origin not in ('http://127.0.0.1:8765','http://localhost:8765'): return self.reply(403,{'error':'Origin not allowed'})
        if self.headers.get('Content-Type','').split(';')[0]!='application/json': return self.reply(415,{'error':'JSON required'})
        try:
            size=int(self.headers.get('Content-Length',0))
            if size<1 or size>12_000_000: raise ValueError('Invalid request size')
            d=json.loads(self.rfile.read(size));url=endpoint(d.get('base',''), 'models' if self.path=='/models' else 'chat/completions')
            headers={'Content-Type':'application/json'}
            official=urllib.parse.urlsplit(url).hostname==OFFICIAL_HOST
            key=d.get('key','').strip()
            if official and not key: key=OFFICIAL_SESSION['key']
            if official and (not key or '*' in key):
                raise ValueError('請貼入完整的官方 API Key；星號遮罩不是可用金鑰。')
            if key: headers['api-key' if official else 'Authorization']=key if official else 'Bearer '+key
            body=None
            if self.path=='/chat':
                req=adapt_request(d['request'],official);body=json.dumps(req).encode()
            with OPENER.open(urllib.request.Request(url,data=body,headers=headers),timeout=600) as r:
                payload=json.load(r)
            if official: OFFICIAL_SESSION['key']=key
            self.reply(200,payload)
        except urllib.error.HTTPError as e:
            message='模型 API 拒絕請求。'
            try:
                detail=json.loads(e.read(32768));err=detail.get('error',detail)
                message=err.get('message',message) if isinstance(err,dict) else str(err)
            except (ValueError,TypeError): pass
            if isinstance(d,dict) and d.get('key'): message=message.replace(d['key'],'[已隱藏金鑰]')
            if OFFICIAL_SESSION['key']: message=message.replace(OFFICIAL_SESSION['key'],'[已隱藏金鑰]')
            self.reply(502,{'error':f'API HTTP {e.code}：{message}'})
        except (ConnectionError,urllib.error.URLError,TimeoutError) as e:
            self.reply(502,{'error':'無法連接模型 API。請確認網路、API 位址；自架模型另須啟動模型與SSH轉發。'})
        except (ValueError,KeyError,TypeError) as e: self.reply(400,{'error':str(e)})

if __name__=='__main__':
    print('Chat UI: http://127.0.0.1:8765 (no GPU or model started)',flush=True)
    http.server.ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
