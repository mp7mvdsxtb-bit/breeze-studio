'use strict';
// The selected batch is just a local bookmark; the jobs themselves remain in SQLite.
let reviewBatch=localStorage.getItem('breeze-review-batch')||'';
const reviewBox=el('div','panel');
reviewBox.innerHTML='<h2>批次复查</h2><p class="helper">提交后可在这里试听、记录问题和返工。选择历史任务的“查看批次”可恢复其他批次。</p><div class="batch-toolbar"><select id="review-filter" class="simple-input"><option value="">全部任务</option><option value="unreviewed">待试听</option><option value="raspy">沙哑</option><option value="hollow">空洞</option><option value="mispronounced">发音有误</option><option value="unnatural">不自然</option><option value="satisfied">满意</option><option value="error">失败</option></select><button id="review-refresh" class="secondary" type="button">刷新批次</button><input id="export-prefix" class="simple-input" maxlength="80" placeholder="导出文件前缀，例如产品名（可选）"><a id="review-export" class="secondary" hidden>导出本批 WAV</a></div><div id="review-list"></div>';
document.querySelector('#batch-view').append(reviewBox);
const reviewList=document.querySelector('#review-list');
async function reviewLoad(){
 if(!reviewBatch){reviewList.textContent='尚未选择批次。';return}
 try{
  const result=await request('/api/batches/'+encodeURIComponent(reviewBatch));
  const filter=document.querySelector('#review-filter').value;
  const selected=result.items.filter(j=>!filter||filter==='unreviewed'&&j.status==='complete'&&!j.subjective_feedback?.length||filter==='error'&&j.status==='error'||j.subjective_feedback?.includes(filter));
  reviewList.replaceChildren();
  reviewList.append(el('p','helper',`本批 ${result.items.length} 项，显示 ${selected.length} 项。状态需要时可手动刷新。`));
  const link=document.querySelector('#review-export');link.href='/api/export?batch_id='+encodeURIComponent(reviewBatch)+'&name_prefix='+encodeURIComponent(document.querySelector('#export-prefix').value);link.hidden=!result.items.some(j=>j.status==='complete');
  for(const job of selected){
   const card=el('div','panel');const voice=voices.find(v=>v.id===job.options.voice_id);
   card.append(el('strong','',`${job.title||job.id.slice(0,8)} · ${labels[job.status]||job.status} · ${voice?.name||names[job.options.mode]} · ${(job.audio_seconds||0).toFixed(1)} 秒`),el('p','',job.text));
   if(job.error)card.append(el('p','warning',job.error));
   if(job.status==='complete'){
    const audio=el('audio');audio.controls=true;audio.preload='none';audio.src=job.result.url;card.append(audio);
    const feedback=el('div','batch-toolbar');
    for(const [id,label] of [['satisfied','满意'],['raspy','沙哑'],['hollow','空洞'],['mispronounced','发音有误'],['unnatural','不自然']]){const l=el('label');const c=el('input');c.type='checkbox';c.value=id;c.checked=(job.subjective_feedback||[]).includes(id);l.append(c,document.createTextNode(' '+label));feedback.append(l)}
    const save=el('button','secondary','保存反馈');save.onclick=async()=>{try{await post('/api/voice-feedback/'+job.id,{labels:[...feedback.querySelectorAll('input:checked')].map(x=>x.value)});await reviewLoad();toast('反馈已保存')}catch(e){toast(e.message)}};feedback.append(save);card.append(feedback);
    const details=el('button','secondary','查看结果与单段返工');details.onclick=()=>showJob(job);card.append(details);
    const remake=el('button','secondary','整条重生成');remake.onclick=async()=>{try{const opts={...job.options,variants:1};const result=await post('/api/submit',{texts:[job.text],options:opts});toast('新任务已加入队列，原音频保留。');focusJob=result.id;await tick()}catch(e){toast(e.message)}};card.append(remake);
   }else if(['error','cancelled','interrupted'].includes(job.status)){const retry=el('button','secondary','重试 / 续作');retry.onclick=async()=>{try{await post('/api/jobs/'+job.id+'/retry',{});await reviewLoad()}catch(e){toast(e.message)}};card.append(retry)}
   reviewList.append(card);
  }
 }catch(e){reviewList.textContent=e.message}
}
document.querySelector('#review-filter').onchange=reviewLoad;document.querySelector('#review-refresh').onclick=reviewLoad;document.querySelector('#export-prefix').oninput=reviewLoad;
const submitBeforeReview=submitTexts;
submitTexts=async function(texts){const result=await submitBeforeReview(texts);if(result?.batch_id){reviewBatch=result.batch_id;localStorage.setItem('breeze-review-batch',reviewBatch);await reviewLoad()}return result};
const historyObserver=new MutationObserver(()=>{for(const card of document.querySelectorAll('#history-list .history-card')){if(card.querySelector('.open-batch'))continue;const button=el('button','secondary open-batch','查看批次');button.onclick=async()=>{try{const job=await request('/api/jobs/'+card.dataset.id);if(!job.batch_id||job.batch_id==='legacy')throw Error('旧任务没有可用的批次。');reviewBatch=job.batch_id;localStorage.setItem('breeze-review-batch',reviewBatch);setView('batch');await reviewLoad();reviewBox.scrollIntoView({behavior:'smooth'})}catch(e){toast(e.message)}};card.append(button)}});
historyObserver.observe(document.querySelector('#history-list'),{childList:true});
const projectBox=el('div','panel');
projectBox.innerHTML='<h2>本机配音项目</h2><p class="helper">保存文案、当前参数和批次入口到当前浏览器。音频与声音库仍在工作室本机保存；更换浏览器或清除浏览器数据会丢失项目草稿。</p><div class="batch-toolbar"><input id="project-name" class="simple-input" maxlength="80" placeholder="项目名称"><button id="project-save" class="secondary" type="button">保存项目</button><select id="project-select" class="simple-input"></select><button id="project-load" class="secondary" type="button">恢复项目</button><button id="project-delete" class="secondary" type="button">删除项目草稿</button></div>';
document.querySelector('#batch-view').append(projectBox);
function readProjects(){try{const data=JSON.parse(localStorage.getItem('breeze-projects')||'{}');return data&&typeof data==='object'&&!Array.isArray(data)?data:{}}catch{return {}}}
function listProjects(){const select=document.querySelector('#project-select'),selected=select.value;select.replaceChildren(new Option('选择已保存项目',''));for(const name of Object.keys(readProjects()).sort())select.add(new Option(name,name));select.value=selected}
document.querySelector('#project-save').onclick=()=>{const name=document.querySelector('#project-name').value.trim();if(!name||['__proto__','constructor','prototype'].includes(name)){toast('请填写有效的项目名称。');return}try{const projects=readProjects();if(Object.hasOwn(projects,name)&&!confirm('项目已存在，覆盖保存的草稿吗？'))return;projects[name]={text:document.querySelector('#batch-text').value,options:options(),batch_id:reviewBatch};localStorage.setItem('breeze-projects',JSON.stringify(projects));listProjects();document.querySelector('#project-select').value=name;toast('项目草稿已保存在当前浏览器。')}catch(e){toast('项目保存失败：'+e.message)}};
document.querySelector('#project-load').onclick=()=>{const name=document.querySelector('#project-select').value,p=readProjects()[name];if(!p){toast('请选择项目。');return}if(!confirm('恢复项目将替换当前页面未保存的文案和参数，继续吗？'))return;document.querySelector('#project-name').value=name;document.querySelector('#batch-text').value=p.text||'';batchCount();renderBatchItems();applyOptions(p.options||{});reviewBatch=p.batch_id||'';localStorage.setItem('breeze-review-batch',reviewBatch);reviewLoad();toast('项目已恢复，请检查声音与参数。')};
document.querySelector('#project-delete').onclick=()=>{const name=document.querySelector('#project-select').value;if(!name||!confirm('删除此项目草稿？声音和任务音频会保留。'))return;const projects=readProjects();delete projects[name];localStorage.setItem('breeze-projects',JSON.stringify(projects));listProjects();toast('项目草稿已删除。')};
listProjects();reviewLoad();
