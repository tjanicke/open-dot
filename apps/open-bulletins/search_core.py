#!/usr/bin/env python3
"""Open Bulletins Search v1: source-preserving PDF -> Markdown, page search and optional ES indexing.

Python >=3.10; PyMuPDF required only for build. Server/SQLite/ES use stdlib.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse, unquote
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
DEFAULT_IDOT = Path.home()/'OpenDOT/Data/PTB_Data/idot_ptb_archives'
DEFAULT_TOLLWAY = Path.home()/'OpenDOT/Data/PSB_Data/istha_psb_archives'
INDEX_NAME = 'open-bulletins-v1'

# For preview only: these are indicative keywords, not verified per-project classifications.
PATTERNS = {
    'I': re.compile(r'\bphase\s*(?:1|i)\b|\bpreliminary\s+engineering\b', re.I),
    'II': re.compile(r'\bphase\s*(?:2|ii)\b|\bfinal\s+design\b', re.I),
    'III': re.compile(r'\bphase\s*(?:3|iii)\b|\bconstruction\s+engineering\b', re.I),
}

def classify_phase(text: str) -> list[str]:
    """Broad per-page terms; can include section boilerplate and mixed phase descriptions."""
    matches = [phase for phase, pattern in PATTERNS.items() if pattern.search(text)]
    return matches or ['other']

def source_paths(row: dict, idot: Path, tollway: Path) -> tuple[Path, str]:
    agency = row['agency']
    root = idot if agency == 'IDOT' else tollway
    rel = Path(row['relative_path'])
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('Unsafe source relative_path: '+str(rel))
    return root / rel, ('idot' if agency=='IDOT' else 'tollway')+'/'+rel.as_posix()

def load_sources(manifest: Path, idot: Path, tollway: Path):
    for row in json.loads(manifest.read_text()):
        path, rel = source_paths(row, idot, tollway)
        yield {'agency':row['agency'],'bulletin_number':row.get('bulletin_number') or '',
               'relative_path':rel,'source_path':str(path),
               'audit_status':row.get('audit_status',''),
               'source_coverage':row.get('source_coverage','')}

def compact_text(text: str) -> str:
    return '\n'.join(re.sub(r'\s+', ' ', ln).strip() for ln in text.replace('\x00','').splitlines() if ln.strip())

def db_connect(dbpath: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(dbpath)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_db(conn):
    conn.executescript('''
CREATE TABLE IF NOT EXISTS files (
 doc_id TEXT PRIMARY KEY, agency TEXT NOT NULL, bulletin_number TEXT,
 relative_path TEXT NOT NULL, source_path TEXT NOT NULL, file_name TEXT NOT NULL,
 page_count INTEGER NOT NULL, indexed_pages INTEGER NOT NULL,
 markdown_path TEXT, mirrored_pdf TEXT,
 audit_status TEXT, source_coverage TEXT
);
CREATE TABLE IF NOT EXISTS pages (
 page_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, page INTEGER NOT NULL,
 page_text TEXT NOT NULL, phase_tags TEXT NOT NULL, FOREIGN KEY (doc_id) REFERENCES files(doc_id)
);
CREATE INDEX IF NOT EXISTS pages_doc ON pages(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(page_id UNINDEXED, page_text, file_name, tokenize='unicode61');
''')

def build(args):
    try: import pymupdf
    except ImportError:
        print('Please install PyMuPDF: python3 -m pip install pymupdf', file=sys.stderr)
        return 2
    # Some historical PDFs contain malformed AcroForm widget appearances.
    # MuPDF can repeat a nonfatal diagnostic for every affected widget/page.
    # Silence the diagnostics only; Python exceptions and per-PDF failures
    # continue to be reported and recorded below.
    pymupdf.TOOLS.mupdf_display_errors(False)
    out = args.out.expanduser().resolve(); out.mkdir(parents=True, exist_ok=True)
    md_dir = out/'markdown'; md_dir.mkdir(exist_ok=True)
    dbpath = out/'bulletins.sqlite3'
    jsonpath = out/'pages.jsonl'
    # Refuse to silently mix a new corpus into an existing index.
    if dbpath.exists() and not args.replace:
        print('Output database exists. Use a new --out or explicit --replace.',file=sys.stderr)
        return 2
    if args.replace and dbpath.exists(): dbpath.unlink()
    conn = db_connect(dbpath); initialize_db(conn)
    source = list(load_sources(args.manifest, args.idot, args.tollway))
    if args.limit: source = source[:args.limit]
    failures=[]; missing=[]; indexed_files=0; indexed_pages=0; empty_pages=0; ocr_overlays_used=0
    started=time.monotonic()
    with jsonpath.open('w',encoding='utf-8') as indexout:
        for seq,row in enumerate(source,1):
            path=Path(row['source_path'])
            if not path.is_file():
                missing.append(str(path)); continue
            doc_id=hashlib.sha256(row['relative_path'].encode()).hexdigest()[:20]
            print(f'Processing {seq}/{len(source)}: {row["relative_path"]}',flush=True)
            try:
                read_path = path
                if args.ocr_pdf_root:
                    overlay = args.ocr_pdf_root / row['relative_path']
                    if overlay.is_file():
                        read_path=overlay
                pdf=pymupdf.open(read_path)
                if not pdf.is_pdf: raise ValueError('Not a PDF')
                total_pages=len(pdf)
                if read_path != path:
                    with pymupdf.open(path) as original:
                        if len(original) != total_pages:
                            raise ValueError('OCR overlay changes PDF page count; cannot link pages reliably')
                    ocr_overlays_used += 1
                markdown_path=md_dir/(row['relative_path']+'.md')
                markdown_path.parent.mkdir(parents=True,exist_ok=True)
                mirrored=''
                if args.copy_pdfs:
                    mirrored=str((out/'pdfs'/row['relative_path']).relative_to(out))
                    target=out/mirrored; target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(path,target)
                file_rows=0
                with markdown_path.open('w',encoding='utf-8') as md:
                    md.write('# '+row['agency']+' '+ ('PTB' if row['agency']=='IDOT' else 'PSB')+' '+row['bulletin_number']+' — '+path.name+'\n\n')
                    md.write('Source PDF: '+row['relative_path']+'\n\n')
                    md.write('> Automatic native-text extraction; not a verified legal or revision record.\n\n')
                    for page_num, page in enumerate(pdf,1):
                        # Avoid PyMuPDF's expensive synthetic-reading-order algorithm.
                        # Plain extraction is sufficient for page-level keyword search.
                        text=compact_text(page.get_text('text', sort=False))
                        md.write('## PDF page '+str(page_num)+'\n\n'+(text or '_No extractable text on this page._')+'\n\n')
                        if len(text.strip()) < 60:
                            empty_pages+=1
                        if not text.strip(): continue
                        tags=classify_phase(text)
                        page_id=f'{doc_id}-p{page_num:05d}'
                        record={'_id':page_id,'doc_id':doc_id,'agency':row['agency'],
                          'bulletin_number':row['bulletin_number'],'file_name':path.name,
                          'relative_path':row['relative_path'],
                          'page':page_num, 'page_text':text, 'phase_tags':tags,
                          'source_coverage':row['source_coverage']}
                        conn.execute('INSERT INTO pages(page_id,doc_id,page,page_text,phase_tags) VALUES (?,?,?,?,?)',
                                     (page_id,doc_id,page_num,text,','.join(tags)))
                        conn.execute('INSERT INTO pages_fts(page_id,page_text,file_name) VALUES (?,?,?)',
                                     (page_id,text,path.name))
                        indexout.write(json.dumps(record,ensure_ascii=False)+'\n')
                        file_rows+=1
                conn.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                     (doc_id,row['agency'],row['bulletin_number'],row['relative_path'],str(path),
                      path.name,total_pages,file_rows,str(markdown_path.relative_to(out)),mirrored,
                      row['audit_status'],row['source_coverage']))
                conn.commit(); indexed_files+=1; indexed_pages+=file_rows
                if seq%25 == 0 or seq==len(source):
                    print(f'{seq}/{len(source)} sources; {indexed_files} PDFs; {indexed_pages} searchable pages',flush=True)
                pdf.close()
            except Exception as e:
                conn.rollback(); failures.append({'pdf':str(path),'error':str(e)})
                print(f'ERROR: {path.name}: {e}',file=sys.stderr)
    conn.close()
    summary={'sources_in_manifest':len(source),'pdfs_built':indexed_files,'searchable_pages':indexed_pages,
             'pages_with_less_than_60_chars':empty_pages,'missing_sources':missing,'failures':failures,
             'ocr_overlays_used':ocr_overlays_used,'ocr_performed':False,'source_pdfs_modified':False,
             'elapsed_seconds':round(time.monotonic()-started,1),
             'database':str(dbpath),'markdown':str(md_dir),'index_jsonl':str(jsonpath)}
    (out/'build-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    return 0 if not missing and not failures else 1

def tokenize_query(q: str) -> str:
    q = q.replace('“', '"').replace('”', '"')
    if q.count('"') % 2:
        raise ValueError("Close the quotation marks around your phrase.")
    parts = []
    for piece in re.findall(r'"[^"]*"|[^"\s]+', q):
        terms = re.findall(r'[\w]+(?:[-/][\w]+)*', piece, flags=re.UNICODE)
        if piece.startswith('"'):
            if terms:
                parts.append('"' + ' '.join(terms) + '"*')
        else:
            parts.extend('"' + term + '"' for term in terms)
    return ' AND '.join(parts)


def local_search(conn, q:str, agency='all', phase='all', limit=15, offset=0):
    match=tokenize_query(q)
    if not match: return []
    where=['pages_fts MATCH ?']; params=[match]
    if agency in ('IDOT','ISTHA'):
        where.append('f.agency=?');params.append(agency)
    if phase in ('I','II','III','other'):
        where.append("instr(',' || p.phase_tags || ',', ',' || ? || ',') > 0");params.append(phase)
    params.extend([min(100,max(1,limit)),max(0,offset)])
    sql='''SELECT f.doc_id, f.agency, f.bulletin_number, f.file_name, f.relative_path,
 p.page, p.page_text, p.phase_tags,
 snippet(pages_fts,1,'HITSTART','HITEND','...',24) AS snippet,
 bm25(pages_fts, 0.0, 1.0, 2.0) AS score
 FROM pages_fts
 JOIN pages p ON p.page_id = pages_fts.page_id
 JOIN files f ON f.doc_id=p.doc_id
 WHERE '''+' AND '.join(where)+''' ORDER BY score LIMIT ? OFFSET ?'''
    try: return [dict(x) for x in conn.execute(sql,params)]
    except sqlite3.OperationalError as exc:
        raise ValueError('Unsupported search query: '+str(exc)) from exc

def search_local_cmd(args):
    conn=db_connect(args.out/'bulletins.sqlite3')
    hits=local_search(conn,args.query,args.agency,args.phase,args.limit)
    for h in hits:
        print(f"{h['agency']} | {h['file_name']} | PDF p.{h['page']} | phases {h['phase_tags']}")
        print(' ',re.sub(r'\s+',' ',h['snippet']).replace('HITSTART','[').replace('HITEND',']')[:500])
    print('Displayed',len(hits),'page matches (not distinct projects or documents).')
    return 0

INDEX_MAPPING={
 'settings':{'index':{'number_of_shards':1,'number_of_replicas':0},
  'analysis':{'analyzer':{'bulletins_text':{'type':'custom','tokenizer':'standard','filter':['lowercase','asciifolding']}}}},
 'mappings':{'properties':{
  'doc_id':{'type':'keyword'},'agency':{'type':'keyword'},'bulletin_number':{'type':'keyword'},
  'file_name':{'type':'text','fields':{'keyword':{'type':'keyword'}}},
  'relative_path':{'type':'keyword'},'page':{'type':'integer'},
  'page_text':{'type':'text','analyzer':'bulletins_text'},
  'phase_tags':{'type':'keyword'},'source_coverage':{'type':'keyword'}}}}

def es_call(url, method, data=None, args=None, content_type='application/json'):
    headers={'Content-Type':content_type}
    if args and args.api_key: headers['Authorization']='ApiKey '+args.api_key
    elif args and args.es_user:
        raw=f'{args.es_user}:{args.es_password or ""}'.encode()
        headers['Authorization']='Basic '+base64.b64encode(raw).decode()
    payload=(data if isinstance(data,bytes) else json.dumps(data).encode()) if data is not None else None
    request=Request(url, data=payload, method=method, headers=headers)
    try:
        with urlopen(request,timeout=40) as resp:
            body=resp.read()
            return (resp.status,json.loads(body)) if body else (resp.status,{})
    except HTTPError as exc:
        body=exc.read().decode('utf-8','replace')[:2000]
        raise RuntimeError(f'HTTP {exc.code}: {body}') from exc
    except URLError as exc:
        raise RuntimeError(f'Cannot connect to Elasticsearch: {exc}') from exc

def index_es(args):
    out=args.out.expanduser().resolve()
    jsonl=out/'pages.jsonl'
    if not jsonl.exists(): print('Run build first: missing '+str(jsonl),file=sys.stderr);return 2
    if not args.apply:
        print('DRY RUN: no Elasticsearch writes. Re-run with --apply to create or update '+args.index)
        print('Source:',jsonl)
        return 0
    base=args.es_url.rstrip('/')
    status, info=es_call(base,'GET',args=args)
    print('Connected to Elasticsearch:',info.get('version',{}).get('number','unknown'))
    # New index only. Never delete existing index automatically.
    try:
        es_call(base+'/'+args.index,'PUT',INDEX_MAPPING,args=args)
        print('Created',args.index)
    except RuntimeError as exc:
        if 'resource_already_exists_exception' not in str(exc): raise
        print('Index exists; upserting documents by stable page ID')
    done=0
    with jsonl.open(encoding='utf-8') as source:
        while True:
            records=[]
            for _ in range(100):
                line=source.readline()
                if not line:break
                records.append(json.loads(line))
            if not records:break
            lines=[]
            for record in records:
                _id=record.pop('_id')
                lines.append(json.dumps({'index':{'_index':args.index,'_id':_id}}))
                lines.append(json.dumps(record,ensure_ascii=False))
            data=('\n'.join(lines)+'\n').encode('utf-8')
            _,response=es_call(base+'/_bulk','POST',data,args=args,content_type='application/x-ndjson')
            if response.get('errors'):
                errors=[item for item in response['items'] if next(iter(item.values())).get('error')]
                raise RuntimeError('Bulk indexing errors: '+str(errors[:2])[:1000])
            done+=len(records)
            if done%1000==0:print('Indexed',done,'pages',flush=True)
    es_call(base+'/'+args.index+'/_refresh','POST',{},args=args)
    print(f'Indexed {done} page documents in {args.index}. Other indices untouched.')
    return 0

def search_es(args,query,agency='all',phase='all',limit=15,from_=0):
    filter_=[]
    if agency in ('IDOT','ISTHA'): filter_.append({'term':{'agency':agency}})
    if phase in ('I','II','III','other'): filter_.append({'term':{'phase_tags':phase}})
    body={
      'from':from_, 'size':limit,
      'query':{'bool':{'must':[{'multi_match':{
        'query':query,'fields':['page_text^3','file_name^2'],
        'type':'best_fields','operator':'and'}}], 'filter':filter_}},
      'collapse':{'field':'doc_id'},
      'highlight':{'pre_tags':['HITSTART'],'post_tags':['HITEND'],'fields':{'page_text':{'fragment_size':170,'number_of_fragments':2}}},
      '_source':['doc_id','agency','bulletin_number','file_name','relative_path','page','phase_tags']}
    _,r=es_call(args.es_url.rstrip('/')+'/'+args.index+'/_search','POST',body,args=args)
    hits=[]
    for h in r.get('hits',{}).get('hits',[]):
        item=h['_source']
        item['snippet']=' ... '.join(h.get('highlight',{}).get('page_text',[]))
        hits.append(item)
    return hits

PAGE_HTML='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Open Bulletins — Search Illinois Transportation Engineering Opportunities</title>
<style>
:root{font-family:system-ui,-apple-system,sans-serif;color:#1d2835;background:#f5f7fa}
*{box-sizing:border-box}main{max-width:920px;margin:40px auto;padding:0 18px}h1{margin-bottom:0;font-size:2rem}p{line-height:1.6}
.muted{color:#606e80}.panel{background:white;border:1px solid #dbe1e9;border-radius:12px;padding:22px;margin:22px 0;box-shadow:0 2px 6px #1a27370b}
.search{display:flex;gap:10px}input,select,button{font:inherit;padding:12px;border:1px solid #c7d0dc;border-radius:7px}
input{flex:1;min-width:0}button{background:#1b527d;color:white;border:0;cursor:pointer}
.filters{display:flex;gap:14px;margin-top:14px;flex-wrap:wrap}.filters label{display:flex;flex-direction:column;gap:6px;flex:1;min-width:150px}
.result{padding:18px 0;border-bottom:1px solid #e7eaf0}.result:last-child{border:0}.result a{font-weight:700;color:#135385;text-decoration:none}
.meta{font-size:.85em;color:#5c6778;margin:6px 0}.snippet{line-height:1.6;overflow-wrap:anywhere}mark{background:#fff2a8;padding:0 2px}
@media(max-width:550px){.search{flex-direction:column}}
</style></head><body><main><h1>Open Bulletins</h1><p class="muted">Search Illinois Transportation Engineering Opportunities</p>
<div class="panel"><form id="form"><div class="search"><input id="q" placeholder="Road, county, bridge, consulting service, project number" required aria-label="Keywords"><button type="submit">Search</button></div>
<div class="filters"><label>Source<select id="agency"><option value="all">All Bulletins</option><option value="IDOT">IDOT PTB</option><option value="ISTHA">Tollway PSB</option></select></label>
<label>Work phase (experimental)<select id="phase"><option value="all">All phases</option><option value="I">Phase I — Preliminary</option><option value="II">Phase II — Design</option><option value="III">Phase III — Construction</option><option value="other">Other / no phase term</option></select></label></div></form></div>
<div id="status" class="muted">Search any historical bulletin. Original, revised, and addendum PDFs may appear independently.</div><section class="panel" id="results" style="display:none"></section>
<p class="muted" style="font-size:.85em">Historical research tool, not a definitive procurement status or current-submission record. Always consult the original PDF and official agency notices.</p></main>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const highlighted=s=>esc(s||'').replaceAll('HITSTART','<mark>').replaceAll('HITEND','</mark>');
document.querySelector('#form').onsubmit=async e=>{
e.preventDefault();const q=document.querySelector('#q').value.trim();if(!q)return;
const p=new URLSearchParams({q,agency:document.querySelector('#agency').value,phase:document.querySelector('#phase').value});
const root=document.querySelector('#results');root.style.display='block';root.innerHTML='';document.querySelector('#status').textContent='Searching...';
try{const res=await fetch('/api/search?'+p);const v=await res.json();if(!res.ok)throw Error(v.error||res.statusText);
document.querySelector('#status').textContent=`${v.hits.length} matching ${v.backend==='elasticsearch'?'PDFs (top page per PDF)':'pages'} displayed`;
root.innerHTML=v.hits.length?v.hits.map(h=>`<article class="result"><a href="/pdf/${encodeURIComponent(h.doc_id)}#page=${h.page}" target="_blank" rel="noopener">${esc(h.file_name)}</a><div class="meta">${esc(h.agency==='IDOT'?'IDOT PTB':'Tollway PSB')} · Bulletin ${esc(h.bulletin_number)} · PDF page ${h.page}</div><div class="snippet">${highlighted(h.snippet||'')}</div></article>`).join(''):'<p>No matches. Try fewer or different terms.</p>';
}catch(err){document.querySelector('#status').textContent='Search error';root.textContent=err.message;}};
</script></body></html>'''

def serve(args):
    conn=db_connect(args.out/'bulletins.sqlite3')
    source_map={x['doc_id']:dict(x) for x in conn.execute('SELECT * FROM files')}
    conn.close()
    if args.backend=='elasticsearch':
        try: es_call(args.es_url.rstrip('/'),'GET',args=args)
        except Exception as exc: raise SystemExit('Elasticsearch unavailable: '+str(exc))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            u=urlparse(self.path);qs=parse_qs(u.query)
            if u.path=='/': return self.send_bytes(200,PAGE_HTML.encode(),'text/html; charset=utf-8')
            if u.path=='/api/search':
                q=qs.get('q',[''])[0].strip()[:300]
                agency=qs.get('agency',['all'])[0];phase=qs.get('phase',['all'])[0]
                if not q: return self.send_json(200,{'hits':[],'backend':args.backend})
                try:
                    if args.backend=='elasticsearch': hits=search_es(args,q,agency,phase,15)
                    else:
                        c=db_connect(args.out/'bulletins.sqlite3')
                        try: hits=local_search(c,q,agency,phase,15)
                        finally:c.close()
                    return self.send_json(200,{'hits':hits,'backend':args.backend})
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
    print('Open Bulletins Search v1 at http://'+args.host+':'+str(args.port),flush=True)
    print('Serving locally by default. Do not expose publicly without deployment review.',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='cmd',required=True)
    b=sub.add_parser('build',help='Read PDFs and write Markdown, SQLite preview, ES JSONL (no OCR)')
    b.add_argument('--manifest',type=Path,default=HERE/'advertisement_sources.json')
    b.add_argument('--idot',type=Path,default=DEFAULT_IDOT)
    b.add_argument('--tollway',type=Path,default=DEFAULT_TOLLWAY)
    b.add_argument('--out',type=Path,default=Path.home()/'open-bulletins-search-v1')
    b.add_argument('--limit',type=int,default=0)
    b.add_argument('--replace',action='store_true')
    b.add_argument('--copy-pdfs',action='store_true',help='Copy selected source PDFs to output for later serving; opt-in')
    b.add_argument('--ocr-pdf-root',type=Path,default=None,help='Optional shadow directory of OCR-searchable PDFs mirroring agency/year/name; original PDFs stay unchanged')
    b.set_defaults(run=build)
    l=sub.add_parser('search-local',help='Search local SQLite preview, no Elasticsearch')
    l.add_argument('query');l.add_argument('--out',type=Path,default=Path.home()/'open-bulletins-search-v1')
    l.add_argument('--agency',choices=['all','IDOT','ISTHA'],default='all');l.add_argument('--phase',choices=['all','I','II','III','other'],default='all')
    l.add_argument('--limit',type=int,default=10);l.set_defaults(run=search_local_cmd)
    for name in ('index-es','serve'):
        x=sub.add_parser(name)
        x.add_argument('--out',type=Path,default=Path.home()/'open-bulletins-search-v1')
        x.add_argument('--es-url',default=os.environ.get('OPEN_BULLETINS_ES_URL','http://127.0.0.1:9200'))
        x.add_argument('--index',default=INDEX_NAME)
        x.add_argument('--es-user',default=os.environ.get('ES_USERNAME',''))
        x.add_argument('--es-password',default=os.environ.get('ES_PASSWORD',''))
        x.add_argument('--api-key',default=os.environ.get('ES_API_KEY',''))
        if name=='index-es':
            x.add_argument('--apply',action='store_true',help='Required for actual Elasticsearch index writes');x.set_defaults(run=index_es)
        else:
            x.add_argument('--host',default='127.0.0.1');x.add_argument('--port',type=int,default=8766)
            x.add_argument('--backend',choices=['local','elasticsearch'],default='local')
            x.add_argument('--allow-original-pdfs',action='store_true',help='For local testing only; serve selected PDFs from original archive paths')
            x.set_defaults(run=serve)
    args=p.parse_args()
    return args.run(args) or 0

if __name__=='__main__':sys.exit(main())
