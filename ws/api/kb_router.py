"""知识库管理：接口 + 自带页面。

为什么页面由后端直接吐 HTML，而不是做进 Next.js：
前端镜像要 `npm ci` 才能重建，这台机器连不上 npm；而运维页不需要 React。
一个 HTMLResponse 就能上线，还顺手绕开了「运营令牌不能下发到浏览器」的问题 ——
令牌由使用者在页面里填、存 sessionStorage，只随请求头发给后端。

⚠️ 已知边界：`重建索引` 是从语料文件重新灌库的，所以页面上「删除」只是
临时下线一条知识；下次重建会把它带回来。要永久删除必须改语料文件。
这条限制写在页面顶部的提示条里，不让运营误以为是永久删除。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from ws.api.handoff_router import require_operator
from ws.knowledge import reindex, store

router = APIRouter(prefix="/api/kb", tags=["知识库"])


@router.get("/stats")
async def stats(_: str = Depends(require_operator)):
    return {"code": 0, "data": await store.admin_stats()}


@router.get("/chunks")
async def chunks(limit: int = Query(default=20, ge=1, le=200),
                 offset: int = Query(default=0, ge=0),
                 q: str = Query(default=""),
                 _: str = Depends(require_operator)):
    return {"code": 0, "data": await store.admin_list(limit, offset, q.strip())}


@router.post("/reindex")
async def reindex_now(_: str = Depends(require_operator)):
    result = await reindex.ensure_index(force=True)
    return {"code": 0, "data": {
        "reindexed": result.reindexed,
        "chunks": result.chunks,
        "backend": result.embedding_backend,
        "reason": result.reason,
    }}


@router.delete("/chunks/{doc_id}")
async def delete_chunk(doc_id: str, _: str = Depends(require_operator)):
    deleted = await store.admin_delete(doc_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="知识不存在")
    return {"code": 0, "data": {"deleted": deleted}}


@router.get("/ui", response_class=HTMLResponse)
async def ui() -> str:
    return KB_UI_HTML


KB_UI_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>知识库管理</title>
<style>
 body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;margin:24px;color:#1f2328}
 h1{font-size:18px;margin:0 0 12px}
 .bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
 input,button{font-size:14px;padding:6px 10px;border:1px solid #d0d7de;border-radius:6px;background:#fff}
 button{cursor:pointer}
 button.primary{background:#1f6feb;color:#fff;border-color:#1f6feb}
 button.danger{color:#cf222e;border-color:#cf222e}
 .note{background:#fff8c5;border:1px solid #eac54f;border-radius:6px;padding:10px;font-size:13px;margin-bottom:12px}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{border-bottom:1px solid #eaeef2;padding:8px;text-align:left;vertical-align:top}
 th{background:#f6f8fa;font-weight:600}
 .muted{color:#656d76}
 #msg{margin-left:8px;font-size:13px}
</style></head><body>
<h1>知识库管理</h1>
<div class="note">「重建索引」会从语料文件重新灌库，所以这里的<b>删除只是临时下线</b>，重建后会恢复。要永久删除请改语料文件。</div>
<div class="bar">
  <input id="token" type="password" placeholder="运营令牌（X-Operator-Token）" size="34">
  <button class="primary" onclick="saveToken()">保存令牌</button>
  <input id="q" placeholder="搜索标题/内容/doc_id" size="22">
  <button onclick="load(0)">搜索</button>
  <button onclick="doReindex()">重建索引</button>
  <span id="msg" class="muted"></span>
</div>
<div class="bar muted" id="stats"></div>
<table><thead><tr><th>doc_id</th><th>类型</th><th>标题</th><th>来源</th><th>内容预览</th><th></th></tr></thead>
<tbody id="rows"></tbody></table>
<div class="bar"><button onclick="load(prev)">上一页</button><button onclick="load(next)">下一页</button></div>
<script>
let offset=0, total=0; const size=20;
const tok=()=>localStorage.getItem('kb_token')||'';
const msg=(t)=>{document.getElementById('msg').textContent=t||''};
function saveToken(){localStorage.setItem('kb_token',document.getElementById('token').value.trim());msg('令牌已保存');load(0)}
async function api(path,opts){
  const r=await fetch(path,{...(opts||{}),headers:{'X-Operator-Token':tok(),'Content-Type':'application/json',...(opts&&opts.headers||{})}});
  const body=await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(body.detail||('HTTP '+r.status));
  return body;
}
async function load(start){
  offset=Math.max(0,start);
  try{
    const q=encodeURIComponent(document.getElementById('q').value.trim());
    const {data}=await api('/api/kb/chunks?limit='+size+'&offset='+offset+'&q='+q);
    total=data.total;
    document.getElementById('rows').innerHTML=data.items.map(it=>`<tr>
      <td>${esc(it.doc_id)}</td><td>${esc(it.kind)}</td><td>${esc(it.title)}</td>
      <td class="muted">${esc(it.source)}</td><td class="muted">${esc(it.preview)}</td>
      <td><button class="danger" onclick="del('${esc(it.doc_id)}')">删除</button></td></tr>`).join('')
      || '<tr><td colspan="6" class="muted">没有数据（先保存令牌？）</td></tr>';
    document.getElementById('stats').textContent='共 '+total+' 条，当前显示 '+(offset+1)+'-'+Math.min(offset+size,total);
    msg('');
  }catch(e){msg('加载失败：'+e.message)}
}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function prev(){return Math.max(0,offset-size)} function next(){return offset+size}
async function del(id){
  if(!confirm('确认临时下线 '+id+' ？')) return;
  try{await api('/api/kb/chunks/'+encodeURIComponent(id),{method:'DELETE'});msg('已删除 '+id);load(offset)}
  catch(e){msg('删除失败：'+e.message)}
}
async function doReindex(){
  msg('重建中，可能需要几十秒…');
  try{const {data}=await api('/api/kb/reindex',{method:'POST'});
    msg('完成：'+(data.reindexed?'已重建':'无需重建')+'，共 '+data.chunks+' 条');load(0)}
  catch(e){msg('重建失败：'+e.message)}
}
document.getElementById('token').value=tok();
if(tok()) load(0);
</script></body></html>
"""
