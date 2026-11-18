'use strict';
const $=s=>document.querySelector(s), form=$('#search-form'), results=$('#results');
let active=null, searchAbort=null, readerAbort=null, lastResult=null;
let dark=matchMedia('(prefers-color-scheme: dark)').matches;
try{const saved=localStorage.getItem('opendot-pdf-theme');if(saved)dark=saved==='dark';}catch{}
function theme(){document.documentElement.dataset.theme=dark?'dark':'light';$('#theme').textContent=dark?'Light mode':'Dark mode';$('#theme').setAttribute('aria-pressed',String(dark));}
theme();$('#theme').onclick=()=>{dark=!dark;theme();try{localStorage.setItem('opendot-pdf-theme',dark?'dark':'light');}catch{}};
const element=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
$('#result-limit').replaceChildren(element('strong','Showing the first 500 contract pages (5,000 contracts).'),document.createTextNode(' More contracts may match your search. Narrow your keywords, year range, document type, or contract number to find more specific results.'));
function link(url,text){const a=element('a',text,'button secondary');a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
function highlighted(text){const p=element('p');let marked=false;for(const part of text.split(/(\uE000|\uE001)/)){if(part==='\uE000'){marked=true;continue;}if(part==='\uE001'){marked=false;continue;}p.append(marked?element('mark',part):document.createTextNode(part));}return p;}
function pageLabel(n){return n==null?'Text (page unavailable)':`PDF page ${n}`;}
function metadata(r){return [r.contract?`Contract ${r.contract}`:'',r.item_number?`Item ${r.item_number}`:'',r.letting_date?`Letting ${r.letting_date}`:'',r.document_type?.replaceAll('_',' ')].filter(Boolean).join(' · ');}
function pageHit(row,hit){
  const box=element('section',undefined,'page-hit'),head=element('div',undefined,'page-head');
  head.append(element('strong',`Viewer page ${hit.page}`));
  const actions=element('div',undefined,'actions');
  const read=element('button','Read page text','secondary');read.onclick=()=>openReader(row.document_id,hit.page);actions.append(read);
  if(row.source_url)actions.append(link(row.source_url+'#page='+hit.page,'Open on IDOT ↗'));
  head.append(actions);const snippet=highlighted(hit.snippet);snippet.className='snippet';box.append(head,snippet);return box;
}
function documentCard(row,searchState){
  const card=element('article',undefined,'card document'),head=element('div',undefined,'card-head'),heading=element('div',undefined,'heading-area');
  heading.append(element('h2',row.pdf_name,'filename'),element('div',metadata(row),'meta'));
  const actions=element('div',undefined,'actions document-actions');
  if(row.source_url){const a=link(row.source_url,'Open full PDF ↗');a.classList.add('full-pdf-link');actions.append(a);}
  else actions.append(element('span','IDOT link not yet verified','muted'));
  const read=element('button','Read document text','secondary');read.onclick=()=>openReader(row.document_id,null);actions.append(read);
  head.append(heading,actions);card.append(head,element('div',row.relative_pdf_path||'','path'));
  const details=element('details',undefined,'matches'),summary=element('summary','Show matching pages');
  const count=element('span',`${row.matching_passages.toLocaleString()} matching text passages`,'summary-count');summary.append(count);details.append(summary);
  const pages=element('div'),error=element('p','','error-inline'),more=element('button','Load more matching pages','load-more');error.hidden=true;more.hidden=true;
  let after=0,started=false,busy=false;
  async function load(){
   if(busy)return;busy=true;more.disabled=true;error.hidden=true;
   if(!started)more.textContent='Loading matching pages…';more.hidden=false;
   try{
    const q=new URLSearchParams({...searchState,id:row.document_id,after:String(after)});q.delete('page');
    const r=await fetch('/api/document-pages?'+q),d=await r.json();if(!r.ok)throw Error(d.error||'Unable to load matching pages.');
    for(const hit of d.pages)pages.append(pageHit(row,hit));after=d.after;started=true;more.hidden=!d.has_more;
    count.textContent=d.has_more?`${pages.children.length.toLocaleString()} matching pages loaded`:`${pages.children.length.toLocaleString()} matching pages`;
    if(!pages.children.length)pages.append(element('p','No matching pages remain. Run the search again.','muted'));
   }catch(e){error.textContent=e.message;error.hidden=false;more.hidden=false;}
   finally{busy=false;more.disabled=false;more.textContent=started?'Load more matching pages':'Retry loading matching pages';}
  }
  details.ontoggle=()=>{if(details.open&&!started)load();};more.onclick=load;
  details.append(pages,error,more);card.append(details);return card;
}
function bestMatch(m){
  const box=element('span',undefined,'contract-match'),text=element('span',undefined,'contract-snippet');
  let marked=false;
  for(const part of m.snippet.split(/(\uE000|\uE001)/)){if(part==='\uE000'){marked=true;continue;}if(part==='\uE001'){marked=false;continue;}text.append(marked?element('mark',part):document.createTextNode(part));}
  const where=[m.document_type?m.document_type.replaceAll('_',' '):'',m.page!=null?`viewer page ${m.page}`:''].filter(Boolean).join(', ');
  box.append(element('span','Best match'+(where?` (${where})`:''),'contract-match-label'),text);return box;
}
function county(c){c=(c||'').trim();if(!c)return '';if(/^various$/i.test(c))return 'Various counties';return /[,-]/.test(c)?`${c} counties`:`${c} County`;}
function cards(data){
 results.replaceChildren();const searchState={...active};
 for(const row of data.results){
  const contract=row.contract;
  if(!contract){results.append(element('p','A result has no contract number. Refine the search or contact Open DOT.','error-inline'));continue;}
  const card=element('article',undefined,'card contract-card');
  const details=element('details',undefined,'contract-details');
  const summary=element('summary');
  const heading=element('span',undefined,'contract-heading');
  heading.append(element('span','Contract','contract-kicker'),element('strong',contract,'contract-number'));
  const info=element('span',undefined,'contract-info');
  if(row.description){const desc=element('span',row.description,'contract-desc');desc.title=row.description;info.append(desc);}
  info.append(element('span',[county(row.counties),row.route||'',row.letting_date?`Letting ${row.letting_date}`:'',row.item_number?`Item ${row.item_number}`:''].filter(Boolean).join(' · '),'contract-meta'));
  if(row.match)info.append(bestMatch(row.match));
  const disclosure=element('span','Show matching PDFs','contract-disclosure');
  summary.append(heading,info,disclosure);
  const contents=element('div',undefined,'contract-contents');
  const status=element('p','Loading matching PDFs…','contract-status');
  const list=element('div',undefined,'contract-documents');
  const nav=element('div',undefined,'contract-pager');
  const previous=element('button','Previous PDFs','secondary');
  const label=element('span','','contract-page-label');
  const next=element('button','Next PDFs','secondary');
  nav.append(previous,label,next);nav.hidden=true;
  contents.append(status,list,nav);details.append(summary,contents);card.append(details);results.append(card);
  let page=1,busy=false,hasNext=false;
  async function load(n){
   if(busy)return;busy=true;previous.disabled=true;next.disabled=true;status.hidden=false;
   status.textContent='Loading matching PDFs…';
   try{
    const q=new URLSearchParams({...searchState,contract,page:String(n)});
    const response=await fetch('/api/search?'+q),data=await response.json();
    if(!response.ok)throw Error(data.error||'Unable to load this contract.');
    if(!card.isConnected)return;
    page=n;list.replaceChildren(...data.results.map(pdf=>documentCard(pdf,{...searchState,contract})));
    if(!data.results.length)list.append(element('p','No matching PDFs for this contract.','muted'));
    label.textContent=`PDF page ${page.toLocaleString()} of ${data.pdf_total_exact?'':'about '}${data.total_pages.toLocaleString()}`;
    hasNext=data.has_next;previous.disabled=page===1;next.disabled=!hasNext;
    nav.hidden=data.total_pages<=1;status.hidden=true;
   }catch(e){if(card.isConnected){status.textContent=e.message;status.classList.add('error-inline');}}
   finally{busy=false;previous.disabled=page===1;next.disabled=!hasNext;}
  }
  previous.onclick=()=>load(page-1);next.onclick=()=>load(page+1);
  details.ontoggle=()=>{disclosure.textContent=details.open?'Hide matching PDFs':'Show matching PDFs';if(details.open&&!list.children.length)load(1);};
 }
 if(!data.results.length)results.append(element('p','No contracts matched. Try fewer keywords or a wider year range.','empty'));
}
function paging(data,busy=false){$('#result-limit').hidden=busy||!(data?.total_pages>500||data?.at_limit);document.querySelectorAll('.pager').forEach(nav=>{
 nav.hidden=!data?.results.length;
 nav.querySelector('.page-label').textContent=data?`Contract page ${data.page.toLocaleString()} of ${data.contract_total_exact?'':'about '}${data.total_pages.toLocaleString()}`:'';
 nav.querySelector('[data-step="-1"]').disabled=busy||!data||data.page===1;
 nav.querySelector('[data-step="1"]').disabled=busy||!data?.has_next;
 const input=nav.querySelector('input');input.max=String(data?.max_page||1);input.value=data?.page||1;input.disabled=busy;
 nav.querySelector('[type="submit"]').disabled=busy;
});}
async function run(state,push=true,scroll=false){searchAbort?.abort();const controller=new AbortController();searchAbort=controller;active={...state};$('#error').hidden=true;$('#status').textContent='Searching…';results.setAttribute('aria-busy','true');paging(lastResult,true);if(push)history.pushState(null,'','?'+new URLSearchParams(state));try{const response=await fetch('/api/contracts?'+new URLSearchParams(state),{signal:controller.signal});const data=await response.json();if(!response.ok)throw Error(data.error||'Search failed.');if(searchAbort!==controller)return;lastResult=data;cards(data);paging(data);const total=data.matching_passages.toLocaleString()+(data.total_relation==='gte'?'+':'');$('#status').textContent=`${total} matching passages · ${data.pdf_total_exact?'':'About '}${data.matching_pdfs.toLocaleString()} PDFs · ${data.contract_total_exact?'':'About '}${data.matching_contracts.toLocaleString()} contracts · ${data.took_ms} ms`+(data.at_limit?' · Refine filters to see more results.':'');if(scroll){$('#result-section').scrollIntoView({block:'start',behavior:'smooth'});$('#result-section').focus({preventScroll:true});}}catch(e){if(e.name==='AbortError')return;results.replaceChildren();paging(null);$('#status').textContent='';$('#error').textContent=e.message;$('#error').hidden=false;}finally{if(searchAbort===controller)results.removeAttribute('aria-busy');}}
form.onsubmit=e=>{e.preventDefault();const state=Object.fromEntries(new FormData(form));state.page='1';run(state,true,true);};
$('#clear').onclick=()=>{form.reset();searchAbort?.abort();active=null;lastResult=null;results.replaceChildren();paging(null);$('#error').hidden=true;$('#status').textContent='Enter keywords or choose filters to search the archive.';history.pushState(null,'',location.pathname);$('#q').focus();};
document.querySelectorAll('[data-step]').forEach(b=>b.onclick=()=>{if(active&&lastResult)run({...active,page:String(lastResult.page+Number(b.dataset.step))},true,true);});
document.querySelectorAll('.page-jump').forEach(jump=>jump.onsubmit=e=>{e.preventDefault();if(active&&lastResult&&jump.reportValidity())run({...active,page:jump.elements.jump.value},true,true);});
async function loadStats(){try{const r=await fetch('/api/stats'),d=await r.json();if(!r.ok)throw Error();$('#archive-stat').replaceChildren(element('strong',d.searchable_pages.toLocaleString()),element('span','searchable pages'));}catch{$('#archive-stat').textContent='Searchable page count temporarily unavailable';}}
loadStats();
function restore(){const p=new URLSearchParams(location.search);form.reset();for(const [key,value]of p){const node=form.elements.namedItem(key);if(node)node.value=value;}if(p.size)run(Object.fromEntries(p),false);else $('#clear').click();}
window.onpopstate=()=>{if(location.search)restore();else{searchAbort?.abort();form.reset();results.replaceChildren();paging(null);lastResult=null;active=null;$('#error').hidden=true;$('#status').textContent='Enter keywords or choose filters to search the archive.';}};
const dialog=$('#reader');$('#close-reader').onclick=()=>dialog.close();dialog.addEventListener('close',()=>readerAbort?.abort());
async function openReader(id,page){readerAbort?.abort();const controller=new AbortController();readerAbort=controller;if(!dialog.open)dialog.showModal();$('#reader-title').textContent='Loading document…';$('#reader-text').textContent='';$('#reader-meta').textContent='';$('#reader-page').textContent='';$('#reader-error').hidden=true;$('#reader-pdf').hidden=true;$('#previous-text').disabled=true;$('#next-text').disabled=true;try{const q=new URLSearchParams({id});if(page!=null)q.set('page',page);const response=await fetch('/api/document?'+q,{signal:controller.signal});const data=await response.json();if(!response.ok)throw Error(data.error||'Unable to read document.');if(readerAbort!==controller)return;$('#reader-title').textContent=data.pdf_name;$('#reader-meta').textContent=metadata(data);$('#reader-page').textContent=pageLabel(data.page);$('#reader-text').textContent=data.text;$('#reader-text').scrollTop=0;$('#previous-text').disabled=data.previous==null;$('#next-text').disabled=data.next==null;$('#previous-text').onclick=()=>openReader(id,data.previous);$('#next-text').onclick=()=>openReader(id,data.next);if(data.source_url){$('#reader-pdf').href=data.source_url+(data.page==null?'':'#page='+data.page);$('#reader-pdf').hidden=false;}}catch(e){if(e.name==='AbortError')return;$('#reader-title').textContent='Document text';$('#reader-error').textContent=e.message;$('#reader-error').hidden=false;}}
if(location.search)restore();
