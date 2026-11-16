#!/usr/bin/env python3
"""Grouped local preview for the existing reviewed Open Bulletins dataset."""
import argparse
from pathlib import Path
import search_core as core
import hashlib
from urllib.parse import urlsplit
OFFICIAL_URLS = {}


def bulletin_key(value):
    value=str(value).strip()
    if re.fullmatch(r'\d+',value): return ('IDOT',(int(value),))
    if re.fullmatch(r'\d{2}-\d+',value): return ('ISTHA',tuple(map(int,value.split('-'))))
    raise ValueError('Use a PTB number such as 205 or a PSB number such as 24-1.')


def search_options(agency, year_from, year_to, number_from, number_to, sort):
    if sort not in ('relevance','year_asc','year_desc','number_asc','number_desc'):
        raise ValueError('Unknown sort order')
    years=[]
    for value in (year_from,year_to):
        if value in ('',None): years.append(None)
        elif re.fullmatch(r'\d{4}',str(value)): years.append(int(value))
        else: raise ValueError('Enter a four-digit year.')
    if all(v is not None for v in years) and years[0]>years[1]:
        raise ValueError('Year From must be no greater than Year To.')
    numbers=[bulletin_key(v) if v else None for v in (number_from,number_to)]
    kinds={v[0] for v in numbers if v}
    if len(kinds)>1: raise ValueError('Use the same agency format for both bulletin bounds.')
    if kinds:
        kind=next(iter(kinds))
        if agency not in ('all',kind): raise ValueError('Bulletin range conflicts with the selected source.')
        agency=kind
    if all(numbers) and numbers[0][1]>numbers[1][1]:
        raise ValueError('Bulletin From must be no greater than Bulletin To.')
    return agency,years,numbers


def grouped_search(conn, query, agency='all', page=1, page_size=10, year_from='', year_to='', number_from='', number_to='', sort='relevance'):
    agency,years,numbers=search_options(agency,year_from,year_to,number_from,number_to,sort)
    match = core.tokenize_query(query)
    groups = {}
    if match:
        where = 'pages_fts MATCH ?'
        params = [match]
        if agency in ('IDOT', 'ISTHA'):
            where += ' AND f.agency=?'
            params.append(agency)
        rows = conn.execute('''SELECT f.doc_id, f.agency, f.bulletin_number,
            f.file_name, f.relative_path, p.page,
            snippet(pages_fts,1,'HITSTART','HITEND','...',24) AS snippet,
            bm25(pages_fts,0.0,1.0,2.0) AS score
            FROM pages_fts JOIN pages p ON p.page_id=pages_fts.page_id
            JOIN files f ON f.doc_id=p.doc_id WHERE ''' + where +
            ' ORDER BY score, f.agency, f.bulletin_number, f.doc_id, p.page', params)
        for row in rows:
            h = dict(row)
            year_match=re.search(r'(?:^|/)((?:19|20)\d{2})/',h['relative_path'])
            year=int(year_match.group(1)) if year_match else None
            if years[0] is not None and (year is None or year<years[0]): continue
            if years[1] is not None and (year is None or year>years[1]): continue
            try: num=bulletin_key(h['bulletin_number'])[1]
            except ValueError: num=None
            if numbers[0] and (num is None or num<numbers[0][1]): continue
            if numbers[1] and (num is None or num>numbers[1][1]): continue
            key = (h['agency'], h['bulletin_number'] or h['doc_id'])
            g = groups.setdefault(key, {'agency':h['agency'],
                'bulletin_number':h['bulletin_number'], 'year':year, 'number_key':num, 'files':{}, 'page_count':0})
            f = g['files'].setdefault(h['doc_id'], {'doc_id':h['doc_id'],
                'file_name':h['file_name'], 'official_url':OFFICIAL_URLS.get(h['doc_id'], ''), 'pages':[]})
            f['pages'].append({'page':h['page'], 'snippet':h['snippet']})
            g['page_count'] += 1
    result = list(groups.values())
    for g in result:
        g['files'] = sorted(g['files'].values(), key=lambda f:f['file_name'].casefold())
        for f in g['files']:
            f['pages'].sort(key=lambda p:p['page'])
    if sort.startswith('year_'):
        known=[g for g in result if g['year'] is not None]
        unknown=[g for g in result if g['year'] is None]
        result=sorted(known,key=lambda g:(g['year'],g['agency'],g['number_key'] or ()),reverse=sort.endswith('desc'))+unknown
    elif sort.startswith('number_'):
        # Separate agency sequences; PTB 205 and PSB 24-1 are not comparable numbers.
        result=[g for a in ('IDOT','ISTHA') for g in
                sorted([g for g in result if g['agency']==a and g['number_key'] is not None],
                       key=lambda g:g['number_key'],reverse=sort.endswith('desc'))]+[g for g in result if g['number_key'] is None]
    page_count = max(1, (len(result)+page_size-1)//page_size)
    page = min(max(1,page), page_count)
    return {'groups':result[(page-1)*page_size:page*page_size],
        'total_bulletins':len(result),
        'idot_bulletins':sum(g['agency']=='IDOT' for g in result),
        'istha_bulletins':sum(g['agency']=='ISTHA' for g in result), 'total_files':sum(len(g['files']) for g in result),
        'total_pages':sum(g['page_count'] for g in result),
        'page':page, 'page_count':page_count, 'backend':'local'}


HTML = core.PAGE_HTML.replace('Search Illinois Transportation Engineering Opportunities', 'Search historical IDOT and Illinois Tollway bulletins').replace('Always consult the original PDF and official agency notices.', 'Always consult the original PDF and official agency notices. Open Bulletins is an independent archive and is not affiliated with or endorsed by IDOT or the Illinois Tollway.')
start = HTML.index('<label>Work phase')
end = HTML.index('</label>',start)+len('</label>')
HTML = HTML[:start]+HTML[end:]
HTML = HTML.replace('Original, revised, and addendum PDFs may appear independently.',
    'Matching originals, revisions, and addenda are grouped by bulletin.')
HTML = HTML.replace('</style>', '''summary{cursor:pointer;padding:12px 0;color:#135385}
summary:focus-visible,a:focus-visible,button:focus-visible{outline:3px solid #d79814}
.bulletin{padding:18px 0;border-bottom:1px solid #dbe1e9}.bulletin h2{margin:0}
.file{margin:8px 0}.file summary{font-weight:600;overflow-wrap:anywhere}
.pages{padding-left:18px}.pager{display:flex;flex-wrap:wrap;gap:14px;align-items:center;margin:0 0 20px}.page-jump{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0}.page-jump label{display:flex;align-items:center;gap:8px}.page-jump input{width:90px;min-width:0;padding:9px}.pager:focus{outline:none}
button:disabled{opacity:.5;cursor:default}</style>''')
HTML = HTML.replace('</form>', '''<div class="filters">
<label>Year from<input id="year_from" type="number" min="1900" max="2099" placeholder="e.g. 2010"></label>
<label>Year to<input id="year_to" type="number" min="1900" max="2099" placeholder="e.g. 2026"></label>
<label>Bulletin from<input id="number_from" placeholder="e.g. 200 or 23-1"></label>
<label>Bulletin to<input id="number_to" placeholder="e.g. 220 or 25-2"></label>
<label>Sort by<select id="sort"><option value="relevance">Relevance</option>
<option value="year_asc">Year — oldest first</option><option value="year_desc">Year — newest first</option>
<option value="number_asc">Bulletin number — ascending</option><option value="number_desc">Bulletin number — descending</option></select></label>
</div><p class="muted" style="font-size:.85em">Ranges include both endpoints; leave blank for no limit. A plain bulletin number selects IDOT; a number such as 24-1 selects ISTHA. Number sorting lists IDOT first, then ISTHA. Press Search to apply.</p></form>''')
HTML = HTML[:HTML.index('<script>')] + '''<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const highlighted=s=>esc(s||'').replaceAll('HITSTART','<mark>').replaceAll('HITEND','</mark>');
let activeQuery='',activeAgency='all',activeFilters={},requestId=0;
async function search(page=1,scroll=false){
 const id=++requestId,root=document.querySelector('#results'),status=document.querySelector('#status');
 root.style.display='block';root.innerHTML='';status.textContent='Searching...';
 try{
  const params=new URLSearchParams({q:activeQuery,agency:activeAgency,...activeFilters,page});
  const res=await fetch('/api/search?'+params),v=await res.json();
  if(id!==requestId)return;
  if(!res.ok)throw Error(v.error||res.statusText);
  status.textContent=`${v.total_bulletins} bulletins · ${v.idot_bulletins} IDOT bulletins · ${v.istha_bulletins} ISTHA bulletins · ${v.total_files} matching PDFs · ${v.total_pages} matching pages`;
  root.innerHTML=v.groups.length?v.groups.map(g=>`<article class="bulletin">
   <h2>${esc(g.agency==='IDOT'?'PTB':'PSB')} ${esc(g.bulletin_number||'Unnumbered')}</h2>
   <div class="meta">${esc(g.agency==='IDOT'?'IDOT':'Illinois Tollway')} · ${g.year??'Year unknown'} · ${g.files.length} matching PDFs · ${g.page_count} matching pages</div>
   ${g.files.map(f=>`<details class="file" open>
    <summary>${esc(f.file_name)} · ${f.pages.length} matching pages</summary>
    <div class="pages">${f.pages.map(p=>`<div class="result"><a href="${esc(f.official_url ? f.official_url.split('#')[0] : '/pdf/'+encodeURIComponent(f.doc_id))}#page=${p.page}" target="_blank" rel="noopener">PDF page ${p.page}${f.official_url?' · Agency PDF':' · Archive copy'}</a><div class="snippet">${highlighted(p.snippet)}</div></div>`).join('')}</div>
   </details>`).join('')}</article>`).join(''):'<p>No matches. Try fewer or different terms.</p>';
  if(v.groups.length){
   const nav=document.createElement('nav');nav.className='pager';nav.setAttribute('aria-label','Search results pagination');nav.tabIndex=-1;
   nav.innerHTML=`<button type="button" id="prev" ${v.page===1?'disabled':''}>Previous</button><span>Page ${v.page} of ${v.page_count}</span><button type="button" id="next" ${v.page===v.page_count?'disabled':''}>Next</button><form class="page-jump"><label for="jump-page">Go to page</label><input id="jump-page" name="page" type="number" min="1" max="${v.page_count}" step="1" value="${v.page}" required aria-label="Result page number"><button type="submit">Go</button></form>`;
   root.prepend(nav);
   nav.querySelector('#prev').onclick=()=>search(v.page-1,true);
   nav.querySelector('#next').onclick=()=>search(v.page+1,true);
   nav.querySelector('.page-jump').onsubmit=e=>{
    e.preventDefault();const input=nav.querySelector('#jump-page');
    if(!input.reportValidity())return;
    const target=Number(input.value);
    if(Number.isInteger(target)&&target>=1&&target<=v.page_count)search(target,true);
   };
   if(scroll){document.querySelector('#status').scrollIntoView({block:'start',behavior:'smooth'});nav.focus({preventScroll:true});}
  }
 }catch(err){if(id===requestId){status.textContent='Search error';root.textContent=err.message;}}
}
document.querySelector('#form').onsubmit=e=>{e.preventDefault();activeQuery=document.querySelector('#q').value.trim();activeAgency=document.querySelector('#agency').value;activeFilters=Object.fromEntries(['year_from','year_to','number_from','number_to','sort'].map(id=>[id,document.getElementById(id).value.trim()]));if(activeQuery)search();};
</script></body></html>'''


# Open Bulletins theme v1: presentation only.
HTML = HTML.replace("<head>", "<head>" + "<script>\n(()=>{let theme;try{theme=localStorage.getItem('open-bulletins-theme');}catch(e){}\nif(theme!=='light'&&theme!=='dark')theme=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';\ndocument.documentElement.dataset.theme=theme;})();\n</script>", 1)
HTML = HTML.replace("</style>", '\n/* Open Bulletins theme */\n:root{color-scheme:light;--bg:#f5f7fa;--surface:#fff;--text:#1d2835;--muted:#596778;--border:#c7d0dc;--link:#135385;--button:#1b527d;--button-text:#fff;--mark:#fff2a8;--mark-text:#302600;--focus:#986500}\n:root[data-theme="dark"]{color-scheme:dark;--bg:#101722;--surface:#192433;--text:#e7edf5;--muted:#b0bfd0;--border:#495b70;--link:#8bc9ff;--button:#a4d4ff;--button-text:#102338;--mark:#715613;--mark-text:#fff4c2;--focus:#ffd36a}\n:root,body{background:var(--bg);color:var(--text)}\n.panel{background:var(--surface);border-color:var(--border)}\n.muted,.meta{color:var(--muted)}\ninput,select{background:var(--surface);color:var(--text);border-color:var(--border)}\ninput::placeholder{color:var(--muted);opacity:1}\nbutton{background:var(--button);color:var(--button-text)}\na,.result a,summary{color:var(--link)}\n.result,.bulletin{border-color:var(--border)}\nmark{background:var(--mark);color:var(--mark-text)}\na:hover{text-decoration:underline}\ninput:focus-visible,select:focus-visible,summary:focus-visible,a:focus-visible,button:focus-visible{outline:3px solid var(--focus);outline-offset:3px}\n.page-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}\n.page-heading h1{margin:0}\n.theme-toggle{border:1px solid var(--border);background:var(--surface);color:var(--text);min-height:44px;white-space:nowrap}\n.theme-toggle:hover{border-color:var(--link)}\n' + "</style>", 1)
HTML = HTML.replace("<h1>Open Bulletins</h1>", '<div class="page-heading"><h1>Open Bulletins</h1><button type="button" id="theme-toggle" class="theme-toggle" aria-label="Dark mode" aria-pressed="false" hidden>Dark mode</button></div>', 1)
HTML = HTML.replace("</body>", "<script>\n(()=>{\n const root=document.documentElement,button=document.getElementById('theme-toggle');\n const media=window.matchMedia('(prefers-color-scheme: dark)');\n let chosen=false;\n try{chosen=['light','dark'].includes(localStorage.getItem('open-bulletins-theme'));}catch(e){}\n function apply(theme){root.dataset.theme=theme;button.setAttribute('aria-pressed',String(theme==='dark'));button.textContent=theme==='dark'?'Light mode':'Dark mode';button.title=theme==='dark'?'Switch to light mode':'Switch to dark mode';}\n apply(root.dataset.theme);button.hidden=false;\n button.addEventListener('click',()=>{chosen=true;const theme=root.dataset.theme==='dark'?'light':'dark';apply(theme);try{localStorage.setItem('open-bulletins-theme',theme);}catch(e){}});\n media.addEventListener('change',e=>{if(!chosen)apply(e.matches?'dark':'light');});\n window.addEventListener('storage',e=>{if(e.key!=='open-bulletins-theme'&&e.key!==null)return;chosen=['light','dark'].includes(e.newValue);apply(chosen?e.newValue:(media.matches?'dark':'light'));});\n})();\n</script>" + "</body>", 1)
# Open DOT home link above the page title (same style as Open PDF Search).
HTML = HTML.replace("<main>", '<main><a class="opendot-brand" href="https://open-dot.org/" style="display:inline-block;margin-bottom:6px;color:var(--muted);font-size:.85rem;font-weight:600;letter-spacing:.02em;text-decoration:none">OpenDOT</a>', 1)

# Original PDF handler, with grouped search response.
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote
import json
import re
db_connect = core.db_connect

def serve(args):
    conn=db_connect(args.out/'bulletins.sqlite3')
    source_map={x['doc_id']:dict(x) for x in conn.execute('SELECT * FROM files')}
    conn.close()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            u=urlparse(self.path);qs=parse_qs(u.query)
            if u.path=='/': return self.send_bytes(200,HTML.encode(),'text/html; charset=utf-8')
            if u.path=='/api/search':
                q=qs.get('q',[''])[0].strip()[:300]
                agency=qs.get('agency',['all'])[0]
                try:
                    c=db_connect(args.out/'bulletins.sqlite3')
                    try: result=grouped_search(c,q,agency,int(qs.get('page',['1'])[0]),**{k:qs[k][0] for k in ('year_from','year_to','number_from','number_to','sort') if k in qs})
                    finally:c.close()
                    return self.send_json(200,result)
                except Exception as exc: return self.send_json(400,{'error':str(exc)[:250]})
            if u.path.startswith('/pdf/'):
                docid=unquote(u.path[5:])
                if docid not in source_map: return self.send_error(404)
                f=source_map[docid]
                if f['mirrored_pdf']:
                    path=(args.out/f['mirrored_pdf']).resolve()
                    if args.out.resolve() not in path.parents:return self.send_error(403)
                else:
                    if not args.allow_original_pdfs: return self.send_error(404,'No mirrored PDF. Build with --copy-pdfs, or serve with --allow-original-pdfs locally.')
                    path=Path(f['source_path'])
                if not path.is_file():return self.send_error(404,'PDF unavailable on this host')
                # Support HTTP byte ranges to allow browser PDF viewers to seek within large files.
                total=path.stat().st_size
                start=0;end=total-1
                rang=self.headers.get('Range')
                if rang:
                    m=re.fullmatch(r'bytes=(\d*)-(\d*)',rang.strip())
                    if not m:return self.send_error(416)
                    if not m.group(1):
                        n=int(m.group(2) or '0');start=max(0,total-n)
                    else:
                        start=int(m.group(1));end=int(m.group(2)) if m.group(2) else end
                    if start>=total or start>end:
                        self.send_response(416);self.send_header('Content-Range',f'bytes */{total}');self.end_headers();return
                    end=min(end,total-1)
                self.send_response(206 if rang else 200)
                self.send_header('Content-Type','application/pdf')
                self.send_header('Accept-Ranges','bytes')
                self.send_header('Content-Disposition',f'inline; filename="{f["doc_id"]}.pdf"')
                self.send_header('Content-Length',str(end-start+1))
                self.send_header('Cache-Control','public, max-age=86400')
                if rang:self.send_header('Content-Range',f'bytes {start}-{end}/{total}')
                self.end_headers()
                with path.open('rb') as fh:
                    fh.seek(start);remaining=end-start+1
                    while remaining:
                        block=fh.read(min(128*1024,remaining))
                        if not block:break
                        self.wfile.write(block);remaining-=len(block)
                return
            self.send_error(404)
        def send_bytes(self,status,data,kind):
            self.send_response(status);self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(data)));self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers();self.wfile.write(data)
        def send_json(self,status,obj):
            self.send_bytes(status,json.dumps(obj,ensure_ascii=False).encode(),'application/json; charset=utf-8')
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    print('Open Bulletins grouped search at http://'+args.host+':'+str(args.port),flush=True)
    print('Serving locally by default. Do not expose publicly without deployment review.',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

def load_official_urls(path, dataset):
    """Accept only explicit agency URLs bound to the exact local PDF hash."""
    records=json.loads(path.read_text())
    if not isinstance(records,list): raise ValueError('Official URL map must be a JSON list')
    conn=db_connect(dataset/'bulletins.sqlite3')
    try: files={r['doc_id']:dict(r) for r in conn.execute('SELECT * FROM files')}
    finally: conn.close()
    urls={}
    for record in records:
        doc=files[record['doc_id']]
        url=record['url']; parsed=urlsplit(url)
        allowed=('idot.illinois.gov','dot.illinois.gov') if doc['agency']=='IDOT' else ('illinoistollway.com',)
        host=parsed.hostname or ''
        if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443) or not any(host==d or host.endswith('.'+d) for d in allowed):
            raise ValueError('URL is not an HTTPS PDF link on the matching agency domain')
        source=dataset/doc['mirrored_pdf'] if doc['mirrored_pdf'] else Path(doc['source_path'])
        with source.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
        if digest!=record['sha256']: raise ValueError('Official URL map PDF hash mismatch: '+doc['file_name'])
        if doc['doc_id'] in urls: raise ValueError('Duplicate document in official URL map')
        urls[doc['doc_id']]=url
    return urls


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['serve'])
    parser.add_argument('--out',type=Path,default=Path.home()/'open-bulletins-search-reviewed-v2')
    parser.add_argument('--backend',choices=['local'],default='local')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--allow-original-pdfs',action='store_true')
    parser.add_argument('--official-urls',type=Path,help='Verified per-document agency URL map')
    args=parser.parse_args()
    if not (args.out/'bulletins.sqlite3').is_file():
        parser.error('Existing dataset missing bulletins.sqlite3: '+str(args.out))
    if args.official_urls:
        OFFICIAL_URLS.update(load_official_urls(args.official_urls,args.out))
    serve(args)

if __name__=='__main__':main()
