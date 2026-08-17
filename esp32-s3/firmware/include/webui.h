#pragma once
static const char WEBUI_HTML[] PROGMEM = R"HTML(
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>AlisBoard</title>
<link rel="icon" href="/favicon.ico" type="image/x-icon"/>
<style>
:root{--bg:#0f172a;--card:#1e293b;--line:#334155;--t:#e2e8f0;--m:#94a3b8;--ok:#34d399;--bad:#f87171;--acc:#2dd4bf}
*{box-sizing:border-box}body{margin:0;font-family:Segoe UI,Tahoma,sans-serif;background:var(--bg);color:var(--t)}
header{padding:16px 20px;border-bottom:1px solid var(--line)}
h1{margin:0;font-size:20px}h2{margin:0 0 10px;font-size:13px;color:var(--m);letter-spacing:.04em;text-transform:uppercase}
.wrap{max-width:880px;margin:0 auto;padding:16px 20px 40px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:0 0 12px}
.row{display:flex;justify-content:space-between;gap:10px;padding:4px 0;font-size:14px}
.k{color:var(--m)}.ok{color:var(--ok)}.bad{color:var(--bad)}
label{display:block;color:var(--m);font-size:12px;margin:8px 0 4px}
input{width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:#0f172a;color:var(--t)}
button{margin:8px 8px 0 0;padding:8px 14px;border-radius:8px;border:0;background:var(--acc);color:#042f2e;font-weight:700;cursor:pointer}
button.ghost{background:#0f172a;color:var(--t);border:1px solid var(--line)}
.log-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:8px}
.log-head h2{margin:0}
.logbox{display:block;white-space:pre-wrap;word-break:break-word;font:12px/1.45 Consolas,monospace;height:300px;overflow-y:scroll;overflow-x:auto;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:#0b1220;color:var(--t);user-select:text;-webkit-user-select:text}
</style>
</head>
<body>
<header><h1>AlisBoard</h1><div class="k" id="ver"></div></header>
<div class="wrap">
<div class="card"><h2>Status</h2>
<div class="row"><span class="k">USB / Helper</span><span id="s_helper">…</span></div>
<div class="row"><span class="k">Windows user</span><span id="s_user">…</span></div>
<div class="row"><span class="k">SQL Server</span><span id="s_sql">…</span></div>
<div class="row"><span class="k">Wi-Fi</span><span id="s_wifi">…</span></div>
<div class="row"><span class="k">API</span><span id="s_api">…</span></div>
<div class="row"><span class="k">Last SQL ID</span><span id="s_last">…</span></div>
</div>
<div class="card"><h2>SQL Server</h2>
<label>Server / Instance</label><input id="sql_server"/>
<label>Database</label><input id="sql_db"/>
<label>Authentication</label><input value="Windows Authentication" disabled/>
<button onclick="saveSql()">Save SQL</button>
<button class="ghost" onclick="testSql()">Test SQL</button>
</div>
<div class="card"><h2>Wi-Fi (API path)</h2>
<label>SSID</label><input id="wifi_ssid"/>
<label>Password</label><input id="wifi_pass" type="password"/>
<button onclick="saveWifi()">Connect</button>
</div>
<div class="card"><h2>API</h2>
<label>Endpoint</label><input id="api_url"/>
<label>Token</label><input id="api_token" type="password"/>
<label>Helper URL</label><input id="helper_url"/>
<button onclick="saveApi()">Save API</button>
<button class="ghost" onclick="testApi()">Test API</button>
</div>
<div class="card"><div class="log-head"><h2>Logs</h2><button class="ghost" onclick="copyLogs()">Copy logs</button></div>
<div class="logbox" id="logs">loading…</div>
<button class="ghost" onclick="clearLogs()">Clear</button>
<button class="ghost" onclick="reboot()">Restart ESP</button>
</div>
</div>
<script>
async function j(u,opt){const r=await fetch(u,opt);return r.json()}
function setLogs(t){var el=document.getElementById('logs');var stick=el.scrollTop+el.clientHeight>=el.scrollHeight-12;el.textContent=t||'';if(stick)el.scrollTop=el.scrollHeight;}
function copyLogs(){var t=document.getElementById('logs').textContent||'';if(window.clipboard&&window.clipboard.writeText){window.clipboard.writeText(t);return;}
var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();try{document.execCommand('copy');}catch(e){}document.body.removeChild(ta);}
function paint(s){
  document.getElementById('ver').textContent='firmware '+ (s.firmware||'');
  const h=s.helper||{};
  document.getElementById('s_helper').className=h.ok?'ok':'bad';
  document.getElementById('s_helper').textContent=h.ok?'Running':'Not found';
  document.getElementById('s_user').textContent=h.windows_user||'—';
  document.getElementById('s_sql').className=h.sql_connected?'ok':'bad';
  document.getElementById('s_sql').textContent=h.sql_connected?(h.database||'Connected'):(h.error||'Not connected');
  document.getElementById('s_wifi').className=s.wifi_ok?'ok':'bad';
  document.getElementById('s_wifi').textContent=s.wifi_ok?(s.wifi_ip+' · '+s.wifi_ssid):'Not set';
  document.getElementById('s_api').className=s.api_ok?'ok':'bad';
  document.getElementById('s_api').textContent=s.api_ok?'Online':(s.api_detail||'Unknown');
  document.getElementById('s_last').textContent=s.last_id;
  document.getElementById('sql_server').value=s.sql_server||'';
  document.getElementById('sql_db').value=s.sql_database||'';
  document.getElementById('wifi_ssid').value=s.wifi_ssid||'';
  document.getElementById('api_url').value=s.api_url||'';
  document.getElementById('helper_url').value=s.helper_url||'';
  setLogs((s.logs||[]).join('\n'));
}
async function tick(){try{paint(await j('/api/status'))}catch(e){setLogs(String(e))}}
async function saveSql(){await j('/api/sql',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({server:sql_server.value,database:sql_db.value})});tick()}
async function testSql(){const r=await j('/api/test-sql',{method:'POST'});alert(JSON.stringify(r,null,2));tick()}
async function saveWifi(){await j('/api/wifi',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:wifi_ssid.value,password:wifi_pass.value})});tick()}
async function saveApi(){await j('/api/api',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:api_url.value,token:api_token.value,helper_url:helper_url.value})});tick()}
async function testApi(){const r=await j('/api/test-api',{method:'POST'});alert(JSON.stringify(r,null,2));tick()}
async function clearLogs(){await j('/api/logs/clear',{method:'POST'});tick()}
async function reboot(){await j('/api/restart',{method:'POST'});}
tick();setInterval(tick,3000);
</script>
</body></html>
)HTML";
