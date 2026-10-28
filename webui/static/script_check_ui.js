'use strict';
async function showScriptCheck(field,box){
 const original=field.value;box.hidden=false;box.replaceChildren();
 try{
  const result=await post('/api/script-check',{text:original});
  if(field.value!==original){box.textContent='文案已变化，请重新检查。';return}
  if(!result.issues.length&&!result.suggestions.length){box.textContent='没有发现需要提示的读法或格式问题。';return}
  for(const issue of result.issues)box.append(el('p','warning',issue));
  for(const item of result.suggestions){const row=el('div','panel');row.append(el('p','',item.original+' → '+item.replacement),el('small','',item.reason));const apply=el('button','secondary','采用这条读法');apply.type='button';apply.onclick=()=>{if(field.value!==original){box.textContent='文案已变化，请重新检查。';return}const chars=Array.from(original);chars.splice(item.start,item.end-item.start,...Array.from(item.replacement));const proposed=chars.join('');if(field.maxLength>0&&proposed.length>field.maxLength){box.textContent='修改后超过长度上限，请先精简文案。';return}field.value=proposed;field.dispatchEvent(new Event('input',{bubbles:true}));showScriptCheck(field,box)};row.append(apply);box.append(row)}
 }catch(e){box.textContent=e.message}
}
function renderBatchItems(){
 const list=document.querySelector('#batch-items');list.replaceChildren();const read=()=>document.querySelector('#batch-text').value.split(/^\s*---\s*$/m);const texts=read();if(texts.length===1&&!texts[0].trim())return;
 texts.forEach((text,index)=>{const card=el('div','panel');card.dataset.batchIndex=index;card.append(el('strong','',`第 ${index+1} 条`));const field=el('textarea','simple-input');field.rows=3;field.value=text.trim();card.append(field);field.oninput=()=>{const values=read();values[index]=field.value;document.querySelector('#batch-text').value=values.join('\n---\n');batchCount()};
 const tools=el('div','batch-toolbar');const check=el('button','secondary','检查英文');check.type='button';const output=el('div','segment-preview');output.hidden=true;check.onclick=()=>showScriptCheck(field,output);tools.append(check);
 const sample=el('button','secondary','试听这一条');sample.type='button';sample.onclick=async()=>{sample.disabled=true;try{await submitTexts([field.value]);toast('样片已加入队列，可在任务与历史中试听。')}catch(e){toast(e.message)}finally{sample.disabled=false}};tools.append(sample);
 const remove=el('button','secondary','删除这一条');remove.type='button';remove.onclick=()=>{const values=read();values.splice(index,1);document.querySelector('#batch-text').value=values.join('\n---\n');batchCount();renderBatchItems()};tools.append(remove);card.append(tools,output);list.append(card)})
}
