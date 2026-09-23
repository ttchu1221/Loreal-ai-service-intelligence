# ruff: noqa: E501  # 内嵌比赛版 workspace HTML/CSS/JS 保持单文件可交付。
from __future__ import annotations


def competition_workspace_html() -> str:
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>欧莱雅 AI 客服助手比赛版</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
background:#f6f2f3;color:#251d20}.top{height:64px;background:#191416;color:#fff;display:flex;align-items:center;
padding:0 22px;gap:18px}.brand{font:700 18px Georgia,serif}.mode{padding:7px 11px;border:1px solid #8d7d83;
border-radius:999px;font-size:12px}.sim{margin-left:auto;color:#f0b2c7;font-size:12px}.grid{height:calc(100vh - 64px);
display:grid;grid-template-columns:280px minmax(420px,1fr) 390px}.left,.right{background:#fff;overflow:auto}
.left{border-right:1px solid #ddd4d7}.right{border-left:1px solid #ddd4d7;padding:16px}.section{padding:18px;
border-bottom:1px solid #eee6e8}.section h2{font-size:16px;margin:0 0 8px}.demo{width:100%;text-align:left;
border:1px solid #dfd3d7;background:#fff;border-radius:10px;padding:12px;margin:6px 0;cursor:pointer}.demo:hover{border-color:#ac1748}
.queue{padding:10px}.queue button{width:100%;text-align:left;border:0;border-bottom:1px solid #eee6e8;background:#fff;
padding:12px;cursor:pointer}.center{display:grid;grid-template-rows:auto 1fr auto;min-height:0}.head{padding:18px 22px;
background:#fff;border-bottom:1px solid #ddd4d7}.head h1{font-size:20px;margin:0}.meta{font-size:12px;color:#75686d;margin-top:5px}
.chat{padding:20px;overflow:auto}.bubble{max-width:76%;background:#fff;border:1px solid #e5dadd;border-radius:14px;
padding:12px;margin:9px 0;white-space:pre-wrap}.bubble.agent{margin-left:auto;background:#ae1648;color:#fff;border:0}
.composer{background:#fff;border-top:1px solid #ddd4d7;padding:14px;display:flex;gap:9px}.composer textarea{flex:1;
min-height:70px;border:1px solid #d8ced1;border-radius:12px;padding:12px;resize:vertical}.primary,.secondary{border:0;
border-radius:10px;padding:0 16px;cursor:pointer}.primary{background:#ae1648;color:#fff}.secondary{background:#ede5e7}
.card{border:1px solid #e2d7da;border-radius:12px;padding:13px;margin-bottom:12px}.card h3{font-size:14px;margin:0 0 9px}
.card pre{font:12px/1.55 ui-monospace,SFMono-Regular,monospace;white-space:pre-wrap;margin:0;color:#594b50}
.actions{display:flex;gap:7px;margin-top:10px;flex-wrap:wrap}.actions button{border:1px solid #d9cbd0;background:#fff;
border-radius:8px;padding:7px 10px;cursor:pointer}.empty{padding:30px;color:#817278;text-align:center}.error{color:#a3113e}
@media(max-width:980px){.grid{grid-template-columns:220px 1fr}.right{grid-column:1/-1;border-left:0;border-top:1px solid #ddd4d7}}
</style></head><body><header class="top"><div class="brand">L'ORÉAL AI 客服助手</div>
<div class="mode" id="mode">尚未加载会话</div><div class="sim">SIMULATED 比赛演示</div></header>
<main class="grid"><aside class="left"><div class="section"><h2>主演示场景</h2>
<div class="meta">模式：AUTO_REPLY / AGENT_ASSIST / HUMAN_REQUIRED</div>
<button class="demo" onclick="seed('auto')">TC01 · 产品资料自动回复</button>
<button class="demo" onclick="seed('refund')">TC06 · 重复进线退款进度</button>
<button class="demo" onclick="seed('risk')">TC08 · 当前不适强制人工</button></div>
<div class="section"><h2>会话队列</h2><div class="meta">风险优先，同级按创建时间</div></div>
<div class="queue" id="queue"><div class="empty">点击上方场景创建 Mock 会话</div></div></aside>
<section class="center"><div class="head"><h1 id="title">请选择会话</h1><div class="meta" id="meta">数据接口未接入时使用明确标识的 Mock</div></div>
<div class="chat" id="chat"><div class="empty">这里显示截至当前消息的原始聊天</div></div>
<div class="composer"><textarea id="draft" placeholder="AI 草稿采用后仅填入这里，不会自动发送"></textarea>
<button class="secondary" id="claim" onclick="claim()">接管</button><button class="primary" id="send" onclick="send()">人工发送</button></div></section>
<aside class="right"><div class="card"><h3>① 服务轨迹</h3><pre id="trajectory">尚未加载</pre></div>
<div class="card"><h3>② 共情理解</h3><pre id="empathy">尚未加载</pre></div>
<div class="card"><h3>③ AI 建议</h3><pre id="suggestion">尚未加载</pre><div class="actions">
<button onclick="adopt()">采用到编辑框</button><button onclick="reject()">拒绝建议</button></div></div>
<div class="card"><h3>④ 风险跟踪</h3><pre id="risk">尚未加载</pre></div>
<div class="error" id="error"></div></aside></main><script>
let current=null;const $=id=>document.getElementById(id);async function api(path,options={}){const response=await fetch(path,options);
const body=await response.json().catch(()=>({detail:`HTTP ${response.status}`}));if(!response.ok)throw new Error(body.detail||JSON.stringify(body));return body;}
const now='2026-09-21T08:00:00Z',later='2026-10-21T08:00:00Z';function base(kind){const id=`demo-${kind}-${Date.now()}`;
const data={snapshot_id:`snapshot-${id}`,case_id:`case-${id}`,conversation_id:id,issue_id:`issue-${id}`,
customer_id:'demo-customer',current_message_id:`message-${id}`,cutoff_message_seq:1,current_message:'这款产品的规格是什么？',
chat_history:[],scene_major:'普通咨询',scene_minor:'W01',scene_source:'demo',products:[{product_id:'product-1',sku:'SKU-1',
name:'演示面霜',source_id:'demo-catalog',observed_at:now,valid_until:later}],knowledge_evidence:[{evidence_id:'KB-DEMO-1',
source:'demo-knowledge',excerpt:'演示面霜规格为 50ml。',product_id:'product-1',scope:'product-specification',version:'v1',
observed_at:now,valid_until:later,valid:true}],context_version:'demo-v1',captured_at:now};if(kind==='refund')Object.assign(data,
{current_message:'上次说会跟进退款，现在还是没有结果',scene_major:'售后处理',scene_minor:'refund_progress',products:[],
knowledge_evidence:[],tickets:[{ticket_id:'ticket-1',owner_customer_id:'demo-customer',category:'refund',status:'processing',
summary:'客服承诺继续跟进退款进度',source_id:'demo-ticket',observed_at:now,valid_until:later}],orders:[{order_id:'order-1',
owner_customer_id:'demo-customer',status:'refund_pending',source_id:'demo-order',observed_at:now,valid_until:later}]});
if(kind==='risk')Object.assign(data,{current_message:'使用后持续泛红和刺痛',scene_major:'风险服务',scene_minor:'adverse_reaction',
products:[],knowledge_evidence:[]});data.chat_history=[{message_id:data.current_message_id,message_seq:1,role:'consumer',content:data.current_message,
created_at:now}];return data;}async function seed(kind){try{const created=await api('/v1/competition/sessions/analyze',{method:'POST',headers:{'content-type':'application/json'},
body:JSON.stringify(base(kind))});await load();await select(created.conversation_id);}catch(e){showError(e)}}async function load(){try{const sessions=await api('/v1/competition/sessions');
const queue=$('queue');queue.replaceChildren();sessions.forEach(s=>{const b=document.createElement('button');b.textContent=`${s.decision.risk_level==='high'?'⚠ ':''}${s.snapshot.current_message}`;
b.onclick=()=>select(s.conversation_id);queue.append(b)});if(!current&&sessions[0])await select(sessions[0].conversation_id);}catch(e){showError(e)}}
async function select(id){try{current=await api(`/v1/competition/sessions/${id}`);render();}catch(e){showError(e)}}function render(){const s=current,d=s.decision;
$('mode').textContent=`${d.service_mode} · ${d.mode_reason}`;$('title').textContent=s.snapshot.current_message;$('meta').textContent=
`会话 ${s.conversation_id} · 处理人 ${s.takeover.assigned_agent_id||'未认领'} · ${s.takeover.takeover_locked?'人工锁定':'未锁定'}`;
const chat=$('chat');chat.replaceChildren();s.snapshot.chat_history.forEach(m=>{const b=document.createElement('div');b.className=`bubble ${m.role==='agent'?'agent':''}`;
b.textContent=`${m.role==='consumer'?'消费者':'客服'} · ${m.created_at}\n${m.content}`;chat.append(b)});s.messages.forEach(m=>{const b=document.createElement('div');
b.className='bubble agent';b.textContent=`客服 · ${m.status} · ${m.channel}\n${m.body}`;chat.append(b)});$('trajectory').textContent=d.service_trajectory.map(x=>
`${x.occurred_at} · ${x.title}\n${x.detail}`).join('\\n\\n')||'无历史轨迹';$('empathy').textContent=`诉求：${d.intent}\n情绪：${d.emotion}\n情绪依据：${d.emotion_evidence.join('、')||'无'}\n紧迫度：${d.urgency}\n风险：${d.risk_type||'无'}\n已知：${d.known_facts.join('；')||'无'}\n未知：${d.missing_information.join('；')||'无'}`;
$('suggestion').textContent=`草稿：${d.reply_text||'强制人工状态不生成消费者回复'}\n补问：${d.follow_up_question||'无'}\n下一步：${d.next_action}\n依据：${d.evidence.map(x=>x.evidence_id).join('、')||'无'}`;
$('risk').textContent=s.risk?`记录：${s.risk.risk_record_id}\n状态：${s.risk.status}\n处理人：${s.risk.assigned_agent_id||'未认领'}\n触发原话：${s.risk.trigger_quote}\n关闭依据：${s.risk.close_basis||'无'}`:'当前无本地风险记录';
$('draft').value='';$('error').textContent='';}function adopt(){if(!current?.decision.reply_text)return;$('draft').value=current.decision.reply_text;}
async function reject(){if(!current)return;try{await api(`/v1/competition/sessions/${current.conversation_id}/suggestion-feedback`,{method:'POST',
headers:{'content-type':'application/json'},body:JSON.stringify({decision_id:current.decision.decision_id,decision:'rejected',actor_id:'demo-agent',
rejection_reason:'other'})});$('draft').value='';}catch(e){showError(e)}}async function claim(){if(!current)return;try{await api(`/v1/competition/sessions/${current.conversation_id}/takeover`,
{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({agent_id:'demo-agent',idempotency_key:`claim-${current.conversation_id}`})});
await select(current.conversation_id);}catch(e){showError(e)}}async function send(){if(!current||!$('draft').value.trim())return;try{const d=current.decision;
await api(`/v1/competition/sessions/${current.conversation_id}/messages`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(
{decision_id:d.decision_id,based_on_message_id:d.current_message_id,body:$('draft').value,idempotency_key:`manual-${Date.now()}`,actor:'agent',
simulate_result:'sent'})});await select(current.conversation_id);}catch(e){showError(e)}}function showError(e){$('error').textContent=e.message}load();
</script></body></html>"""
