'use strict';
// Group less frequent tools without removing their controls or changing their state.
function collapseGroup(label,nodes,after){
 const detail=document.createElement('details');detail.className='compact-group';
 const summary=document.createElement('summary');summary.textContent=label;detail.append(summary);
 after.before(detail);for(const node of nodes)if(node)detail.append(node);return detail;
}
const tools=document.querySelector('.event-tools');
const check=document.querySelector('#check-script');
const quick=document.createElement('div');quick.className='quick-actions';
quick.append(check);tools.before(quick);
const eventHelp=tools.nextElementSibling;
collapseGroup('发声事件与分段工具',[tools,eventHelp],tools);
const translation=document.querySelector('.translation-box');
collapseGroup('用中文描述声音并翻译',[translation],translation);
const presets=document.querySelector('#english-presets');
collapseGroup('选择声音与表达预设',[presets],presets);
const recipe=document.querySelector('.recipe-bar');
collapseGroup('保存和使用配音配方',[recipe],recipe);
const projectHeading=[...document.querySelectorAll('#batch-view > .panel')].find(x=>x.querySelector('#project-name'));
if(projectHeading){const group=collapseGroup('项目草稿',[projectHeading],projectHeading);group.classList.add('secondary-group')}
const reviewHeading=document.querySelector('#review-list')?.closest('.panel');
if(reviewHeading){const group=collapseGroup('批次复查',[reviewHeading],reviewHeading);group.classList.add('secondary-group');document.querySelector('#history-list').addEventListener('click',event=>{if(event.target.closest('.open-batch'))group.open=true})}
