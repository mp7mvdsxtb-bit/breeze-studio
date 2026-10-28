'use strict';
// Follow the standard keyboard pattern for the existing mode tabs.
const modeTabs=[...document.querySelectorAll('.mode-tab')];
document.querySelector('.mode-tabs').addEventListener('keydown',event=>{
 if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
 const index=modeTabs.indexOf(document.activeElement);if(index<0)return;
 const next=event.key==='Home'?0:event.key==='End'?modeTabs.length-1:
  (index+(event.key==='ArrowRight'?1:-1)+modeTabs.length)%modeTabs.length;
 event.preventDefault();modeTabs[next].click();modeTabs[next].focus();
});
function syncNavigation(){
 for(const button of document.querySelectorAll('.nav-item')){
  if(button.classList.contains('selected'))button.setAttribute('aria-current','page');
  else button.removeAttribute('aria-current');
 }
}
document.querySelectorAll('.nav-item').forEach(button=>button.addEventListener('click',syncNavigation));
// Some navigation is triggered by links inside the interface, not sidebar clicks.
new MutationObserver(syncNavigation).observe(document.querySelector('.sidebar'),{subtree:true,attributes:true,attributeFilter:['class']});
syncNavigation();
