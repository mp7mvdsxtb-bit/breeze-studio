'use strict';
function renderVoiceLibrary(){
 const list=document.querySelector('#voice-library-list');list.replaceChildren();
 const query=(document.querySelector('#voice-search').value||'').trim().toLowerCase();
 const category=document.querySelector('#voice-category-filter');const current=category.value;
 const categories=[...new Set(voices.map(v=>v.category||'').filter(Boolean))].sort();
 category.replaceChildren(new Option('全部分类',''),...categories.map(x=>new Option(x,x)));category.value=categories.includes(current)?current:'';
 const favoriteOnly=document.querySelector('#voice-favorites-only').checked;
 const shown=voices.filter(v=>(!favoriteOnly||v.favorite)&&(!category.value||v.category===category.value)&&[v.name,v.transcript,v.category,v.notes,v.style_description].some(x=>(x||'').toLowerCase().includes(query)));
 if(!shown.length){list.append(el('p','history-blank',voices.length?'没有匹配的声音。':'尚未保存参考声音。上传短音频，或把满意的生成结果存为音色参考。'));return}
 for(const v of shown){
  const card=el('article','panel voice-card');card.dataset.voiceId=v.id;card.append(el('h3','',v.name),el('p','',v.transcript));
  const audio=el('audio');audio.controls=true;audio.preload='none';audio.src=v.url;card.append(audio);
  if(v.blocked)card.append(el('p','warning','已排除：不再复用这个音色'));
  const tools=el('div','batch-toolbar');
  const rename=el('button','secondary','修改名称');rename.type='button';rename.onclick=async()=>{const name=await askVoiceName('修改声音名称',v.name);if(name===null||name===v.name)return;rename.disabled=true;try{await request('/api/voices/'+v.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});await loadVoices();toast('声音名称已更新。')}catch(e){toast(e.message);rename.disabled=false}};tools.append(rename);
  for(const next of ['clone','direction']){const b=el('button','secondary',next==='clone'?'使用声音克隆':'使用声音指导');b.type='button';b.disabled=!!v.blocked;b.onclick=()=>{setMode(next);document.querySelector('#voice-select').value=v.id;voiceSelection();setView('create')};tools.append(b)}
  const fav=el('button','secondary',v.favorite?'★ 已收藏':'☆ 收藏');fav.type='button';fav.onclick=async()=>{try{await request('/api/voices/'+v.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({favorite:!v.favorite})});await loadVoices()}catch(e){toast(e.message)}};tools.append(fav);
  const def=el('button','secondary',config.default_voice_id===v.id?'取消默认':'设为默认');def.type='button';def.disabled=!!v.blocked;def.onclick=async()=>{try{const id=config.default_voice_id===v.id?'':v.id;await request('/api/default-voice',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({voice_id:id})});config.default_voice_id=id;if(id){setMode('clone');document.querySelector('#voice-select').value=id;voiceSelection()}renderVoiceLibrary();toast(id?'已设置并选用默认声音。':'已取消默认声音。')}catch(e){toast(e.message)}};tools.append(def);
  const remove=el('button','secondary','删除声音');remove.type='button';remove.dataset.deleteVoice=v.id;remove.onclick=async()=>{if(!window.confirm('确定删除声音「'+v.name+'」及其参考音频？已生成的配音会保留。'))return;remove.disabled=true;audio.pause();try{await request('/api/voices/'+v.id,{method:'DELETE'});if(config.default_voice_id===v.id)config.default_voice_id='';await loadVoices();toast('声音已删除，已生成的配音保留。')}catch(e){toast(e.message);remove.disabled=false}};tools.append(remove);card.append(tools);
  const details=el('details','advanced');details.append(el('summary','','声音档案 · 编辑分类、备注与参数'));
  const fields={};for(const [key,label,max] of [['name','名称',80],['category','分类（例如美式女声）',50],['style_description','风格描述',1000],['notes','备注',500]]){const wrapper=el('label','field-label',label);const input=el(key==='style_description'||key==='notes'?'textarea':'input','simple-input');input.maxLength=max;input.value=v[key]||'';if(input.tagName==='TEXTAREA')input.rows=2;wrapper.append(input);details.append(wrapper);fields[key]=input}
  const save=el('button','secondary','保存档案');save.type='button';save.onclick=async()=>{try{const payload=Object.fromEntries(Object.entries(fields).map(([k,x])=>[k,x.value]));await request('/api/voices/'+v.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});await loadVoices();toast('声音档案已保存。')}catch(e){toast(e.message)}};details.append(save);
  const remember=el('button','secondary','保存当前生成参数');remember.type='button';remember.onclick=async()=>{try{await request('/api/voices/'+v.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({recommended_options:options()})});await loadVoices();toast('已保存当前生成参数到声音档案。')}catch(e){toast(e.message)}};details.append(remember);
  if(v.recommended_options){const use=el('button','secondary','应用保存的参数');use.type='button';use.disabled=!!v.blocked;use.onclick=()=>{let saved={...v.recommended_options};if(saved.mode==='design')saved.mode='direction';if(saved.mode==='direction'&&!saved.instruction)saved.instruction=config.defaults.instruction;applyOptions({...saved,voice_id:v.id});setView('create');toast('已应用声音档案的参数，可继续调整。')};details.append(use)}
  card.append(details);list.append(card)
 }
}
