'use strict';
function askVoiceName(title,initial){
 return new Promise(resolve=>{
  const dialog=document.createElement('dialog');dialog.className='voice-name-dialog';
  const form=document.createElement('form');form.method='dialog';
  const heading=document.createElement('h2');heading.textContent=title;
  const label=document.createElement('label');label.htmlFor='voice-name-input';label.textContent='声音名称';
  const input=document.createElement('input');input.id='voice-name-input';input.className='simple-input';input.maxLength=80;input.required=true;input.value=initial;
  const hint=document.createElement('p');hint.className='helper';hint.textContent='最多 80 个字符，方便以后在声音库中查找。';
  const actions=document.createElement('div');actions.className='voice-name-actions';
  const cancel=document.createElement('button');cancel.type='button';cancel.className='secondary';cancel.textContent='取消';cancel.onclick=()=>dialog.close();
  const save=document.createElement('button');save.type='submit';save.className='primary';save.textContent='保存';
  actions.append(cancel,save);form.append(heading,label,input,hint,actions);dialog.append(form);document.body.append(dialog);
  let result=null;form.addEventListener('submit',event=>{event.preventDefault();const name=input.value.trim();if(!name){input.setCustomValidity('请输入声音名称。');input.reportValidity();return}result=name;dialog.close()});
  input.addEventListener('input',()=>input.setCustomValidity(''));dialog.addEventListener('close',()=>{dialog.remove();resolve(result)},{once:true});
  dialog.showModal();input.focus();input.select();
 });
}
