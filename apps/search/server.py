"""OpenDOT search WSGI app. Reads Elasticsearch only; no archive/PDF access."""
import json, os, re, ssl, sys, time, threading, sqlite3, hmac
from collections import OrderedDict
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler, HTTPRedirectHandler

ROOT=Path(__file__).resolve().parent
INDEX=os.environ.get('OPENDOT_INDEX','opendot_pages_history_v1')
META=['document_id','relative_pdf_path','pdf_name','contract','item_number','letting_date','document_type','source_url','page','chunk']
HIGHLIGHT={'fields':{'content':{'fragment_size':240,'number_of_fragments':2}},'pre_tags':['\ue000'],'post_tags':['\ue001']}
CACHE=OrderedDict(); LOCK=threading.Lock()
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def es(body):
    cfg=Path(os.environ.get('OPENDOT_CREDENTIALS',str(Path.home()/'opendot-search/config/search-api-key.json')))
    key=json.loads(cfg.read_text())['encoded']
    ca=Path(os.environ.get('OPENDOT_CA',str(Path.home()/'opendot-search/elasticsearch/http-ca.crt')))
    context=ssl.create_default_context(cafile=str(ca))
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context),NoRedirect())
    req=Request('https://localhost:9200/'+INDEX+'/_search',data=json.dumps(body).encode(),
                headers={'Authorization':'ApiKey '+key,'Content-Type':'application/json'})
    with opener.open(req,timeout=25) as r: data=json.load(r)
    if data.get('timed_out') or data.get('_shards',{}).get('failed',0): raise RuntimeError('Incomplete search response')
    return data

def integer(value,default,low,high):
    if not value: return default
    if not re.fullmatch(r'\d+',str(value)): raise ValueError('Enter a whole number.')
    n=int(value)
    if not low<=n<=high: raise ValueError(f'Number must be between {low} and {high}.')
    return n

def params(q):
    query=q.get('q','').strip()
    if len(query)>256: raise ValueError('Search text is limited to 256 characters.')
    start=integer(q.get('year_from'),None,2000,2099); end=integer(q.get('year_to'),None,2000,2099)
    if start and end and start>end: raise ValueError('Year From must not exceed Year To.')
    sort=q.get('sort','relevance')
    if sort not in ('relevance','newest','oldest'): raise ValueError('Unknown sort option.')
    kind=q.get('type','')
    if kind not in ('','plans','specifications','additional_information','unknown'): raise ValueError('Unknown document type.')
    contract=q.get('contract','').strip().upper()
    if contract and not re.fullmatch(r'[A-Z0-9-]{1,32}',contract): raise ValueError('Enter a valid contract number.')
    page=integer(q.get('page'),1,1,500)
    return dict(q=query,year_from=start,year_to=end,sort=sort,type=kind,contract=contract,page=page)

def search_body(p):
    filters=[]
    if p['year_from'] or p['year_to']:
        bounds={}
        if p['year_from']: bounds['gte']=f"{p['year_from']}-01-01"
        if p['year_to']: bounds['lt']=f"{p['year_to']+1}-01-01"
        filters.append({'range':{'letting_date':bounds}})
    for field,key in [('document_type','type'),('contract','contract')]:
        if p[key]: filters.append({'term':{field:p[key]}})
    query={'simple_query_string':{'query':p['q'],'fields':['content'],'default_operator':'and'}} if p['q'] else {'match_all':{}}
    sort=[{'_score':'desc'},{'document_id':'asc'}]
    if p['sort']!='relevance':sort=[{'letting_date':'desc' if p['sort']=='newest' else 'asc'},{'document_id':'asc'}]
    return {'size':11,'from':(p['page']-1)*10,'timeout':'20s','track_total_hits':10000,'_source':META,
            'query':{'bool':{'must':[query],'filter':filters}},'sort':sort,
            'aggs':{'pdfs':{'terms':{'field':'document_id','size':5001}},
                    'pdf_estimate':{'cardinality':{'field':'document_id','precision_threshold':40000}}},
            'collapse':{'field':'document_id','inner_hits':{'name':'matches','size':3,'_source':META+['content'],
                        'sort':[{'_score':'desc'},{'page':'asc'},{'chunk':'asc'}],'highlight':HIGHLIGHT}}}

def official(url):
    try:
        p=urlsplit(url)
        return bool(p.scheme=='https' and p.hostname in ('apps.dot.illinois.gov','apps1.dot.illinois.gov')
                    and p.port is None and not p.username and not p.password and not p.query and not p.fragment
                    and p.path.startswith('/eplan/desenv/') and not any(ord(c)<32 for c in url))
    except ValueError: return False

def catalog_url(doc):
    path=Path(os.environ.get('OPENDOT_LINKS',str(Path.home()/'opendot-search/state/idot-links.sqlite3')))
    if not path.exists():return ''
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        row=db.execute('SELECT url FROM links WHERE document_id=?',(doc,)).fetchone()
    return row[0] if row and official(row[0]) else ''

def public(source):
    result={k:source.get(k) for k in META}
    if not official(result.get('source_url') or ''): result['source_url']=catalog_url(result.get('document_id',''))
    return result

def search(p):
    key=json.dumps(p,sort_keys=True)
    with LOCK:
        cached=CACHE.get(key)
        if cached and cached[0]>time.monotonic(): CACHE.move_to_end(key); return cached[1]
    data=es(search_body(p)); result=[]
    for hit in data['hits']['hits'][:10]:
        row=public(hit['_source']); row['previews']=[]; seen=set()
        inner=hit.get('inner_hits',{}).get('matches',{}).get('hits',{})
        for match in inner.get('hits',[]):
            src=match['_source']; page=src.get('page')
            if page in seen:continue
            seen.add(page)
            row['previews'].append({'page':page,'snippet':' … '.join(match.get('highlight',{}).get('content',[])) or src.get('content','')[:450]})
        row['matching_passages']=inner.get('total',{}).get('value',0)
        result.append(row)
    total=data['hits']['total']
    agg=data.get('aggregations',{}); groups=agg.get('pdfs',{})
    exact='buckets' in groups and groups.get('sum_other_doc_count',0)==0
    count=len(groups.get('buckets',[])) if exact else int(agg.get('pdf_estimate',{}).get('value',0))
    pages=(count+9)//10
    output={'results':result,'matching_passages':total['value'],'total_relation':total['relation'],
            'matching_pdfs':count,'pdf_total_exact':exact,'total_pages':pages,'max_page':min(500,pages),
            'page':p['page'],'has_next':len(data['hits']['hits'])>10 and p['page']<500,
            'at_limit':p['page']==500,'took_ms':data.get('took',0)}
    with LOCK:
        CACHE[key]=(time.monotonic()+30,output);CACHE.move_to_end(key)
        while len(CACHE)>128:CACHE.popitem(last=False)
    return output

# BEGIN OpenDOT contract grouping
CONTRACT_CACHE=OrderedDict()

def describe(rows):
    """Add IDOT's description of each contract, from contract-descriptions.sqlite3 (built by
    build_descriptions.py): the bulletin description (2018 on) or the Notice to Bidders text in
    the specifications. Missing database or rows leave the cards as they were."""
    path=Path(os.environ.get('OPENDOT_DESCRIPTIONS',str(Path.home()/'opendot-search/state/contract-descriptions.sqlite3')))
    contracts=sorted({r['contract'] for r in rows if r['contract']})
    if not contracts or not path.exists():return
    marks=','.join('?'*len(contracts))
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
            found=db.execute(
                f"SELECT 0,contract,letting_date,description,counties,'' FROM bulletin WHERE contract IN ({marks}) AND description<>'' "
                f"UNION ALL SELECT 1,contract,letting_date,description,county,route FROM spec WHERE contract IN ({marks})",
                contracts+contracts).fetchall()
    except sqlite3.Error:
        return
    for row in rows:
        mine=[f for f in found if f[1]==row['contract']]
        if not mine:continue
        # Same letting first (a contract number can be re-let), then bulletin over specifications, then newest.
        mine.sort(key=lambda f:(f[2]!=row['letting_date'],f[0],[-ord(c) for c in f[2]]))
        same=[f for f in mine if f[2]==mine[0][2]]
        bulletin=next((f for f in same if f[0]==0),None); spec=next((f for f in same if f[0]==1),None)
        row['description']=(bulletin or spec)[3]
        row['counties']=(bulletin[4] if bulletin and bulletin[4] else spec[4] if spec else '')
        row['route']=spec[5] if spec else ''

def contract_search(p):
    key=json.dumps(p,sort_keys=True)
    with LOCK:
        cached=CONTRACT_CACHE.get(key)
        if cached and cached[0]>time.monotonic():
            CONTRACT_CACHE.move_to_end(key)
            return cached[1]
    body=search_body(p)
    body['collapse']={'field':'contract'}
    body['_source']=['contract','item_number','letting_date']
    body['aggs']={
        'contracts':{'cardinality':{'field':'contract','precision_threshold':40000}},
        'pdfs':{'cardinality':{'field':'document_id','precision_threshold':40000}},
    }
    data=es(body)
    hits=data['hits']['hits']
    rows=[]
    for hit in hits[:10]:
        src=hit['_source']
        rows.append({'contract':src.get('contract') or '',
                     'item_number':src.get('item_number') or '',
                     'letting_date':src.get('letting_date') or ''})
    describe(rows)
    total=data['hits']['total']
    agg=data.get('aggregations',{})
    contracts=int(agg.get('contracts',{}).get('value',0))
    pdfs=int(agg.get('pdfs',{}).get('value',0))
    # An exact contract filter has either one group or none.
    exact=bool(p['contract'])
    if exact:contracts=1 if hits else 0
    pages=(contracts+9)//10
    out={'results':rows,'matching_passages':total['value'],
         'total_relation':total['relation'],'matching_pdfs':pdfs,
         'pdf_total_exact':False,'matching_contracts':contracts,
         'contract_total_exact':exact,'total_pages':pages,'max_page':min(500,pages),
         'page':p['page'],'has_next':len(hits)>10 and p['page']<500,
         'at_limit':p['page']==500,'took_ms':data.get('took',0)}
    with LOCK:
        CONTRACT_CACHE[key]=(time.monotonic()+30,out)
        CONTRACT_CACHE.move_to_end(key)
        while len(CONTRACT_CACHE)>128:CONTRACT_CACHE.popitem(last=False)
    return out
# END OpenDOT contract grouping

STATS=None
def stats():
    global STATS
    with LOCK:
        if STATS and STATS[0]>time.monotonic():return STATS[1]
    data=es({'size':0,'track_total_hits':True,'query':{'bool':{'filter':[
        {'term':{'chunk':0}},{'exists':{'field':'page'}}]}}})
    out={'searchable_pages':data['hits']['total']['value']}
    with LOCK:STATS=(time.monotonic()+300,out)
    return out

def document_pages(q):
    doc=q.get('id','')
    if not re.fullmatch(r'[0-9a-f]{64}',doc):raise ValueError('Invalid document identifier.')
    after=integer(q.get('after'),0,0,1000000)
    query=search_body(params(q))['query']
    query['bool']['filter'].append({'term':{'document_id':doc}})
    # Bucket by PDF viewer page to merge matching chunks, retaining original page numbers.
    data=es({'size':0,'timeout':'20s','query':query,'aggs':{
        'pages':{'composite':{'size':26,'sources':[{'page':{'terms':{'field':'page'}}}],
                             'after':{'page':after}},
                 'aggs':{'sample':{'top_hits':{'size':1,'_source':['page','content'],
                                             'highlight':HIGHLIGHT}}}}}})
    buckets=data['aggregations']['pages']['buckets']; rows=[]
    for b in buckets[:25]:
        h=b['sample']['hits']['hits'][0]
        rows.append({'page':b['key']['page'],'snippet':' … '.join(h.get('highlight',{}).get('content',[])) or h['_source'].get('content','')[:450]})
    return {'pages':rows,'has_more':len(buckets)>25,'after':rows[-1]['page'] if rows else after}

def document(q):
    doc=q.get('id','')
    if not re.fullmatch(r'[0-9a-f]{64}',doc):raise ValueError('Invalid document identifier.')
    page=integer(q.get('page'),None,1,1000000)
    base=[{'term':{'document_id':doc}}]
    if page is None:
        first=es({'size':1,'_source':['page'],'query':{'bool':{'filter':base}},'sort':[{'page':'asc'},{'chunk':'asc'}]})
        if not first['hits']['hits']: raise ValueError('Document not found.')
        page=first['hits']['hits'][0]['_source'].get('page')
    filter_page={'term':{'page':page}} if page is not None else {'bool':{'must_not':[{'exists':{'field':'page'}}]}}
    data=es({'size':500,'track_total_hits':True,'_source':META+['content'],'query':{'bool':{'filter':base+[filter_page]}},'sort':[{'chunk':'asc'}]})
    hits=data['hits']['hits']
    if not hits:raise ValueError('Page not found.')
    if data['hits']['total']['value']>500:raise ValueError('This page is too large for the text reader.')
    text=''; last=None
    for hit in hits:
        src=hit['_source']; chunk=src.get('chunk',0); part=src.get('content','')
        if last is not None and chunk==last+1 and text[-200:]==part[:200]:part=part[200:]
        text+=part; last=chunk
    out=public(hits[0]['_source']);out.update(text=text,previous=None,next=None)
    if page is not None:
        nav=es({'size':0,'query':{'bool':{'filter':base}},'aggs':{
            'before':{'filter':{'range':{'page':{'lt':page}}},'aggs':{'n':{'max':{'field':'page'}}}},
            'after':{'filter':{'range':{'page':{'gt':page}}},'aggs':{'n':{'min':{'field':'page'}}}}}})
        for name,field in [('before','previous'),('after','next')]:
            n=nav['aggregations'][name]['n']['value'];out[field]=int(n) if n is not None else None
    return out

STATIC={'/':('index.html','text/html; charset=utf-8'),'/static/style.css':('static/style.css','text/css; charset=utf-8'),'/static/app.js':('static/app.js','application/javascript; charset=utf-8')}
def application(env,start):
    token_file=os.environ.get('OPENDOT_PROXY_TOKEN')
    if not token_file:raise RuntimeError('Public service requires a proxy credential')
    expected=Path(token_file).read_text().strip()
    supplied=env.get('HTTP_X_OPENDOT_PROXY','')
    if not expected or not hmac.compare_digest(expected.encode(),supplied.encode()):
        start('403 Forbidden',[('Content-Type','text/plain'),('Cache-Control','no-store')]);return [b'Forbidden']
    status='200 OK'; kind='application/json; charset=utf-8'
    try:
        if env.get('REQUEST_METHOD') not in ('GET','HEAD'): raise ValueError('Only GET and HEAD requests are supported.')
        path=env.get('PATH_INFO','/')
        raw=env.get('QUERY_STRING','')
        if len(raw)>4096:raise ValueError('Request is too long.')
        q={k:v[-1] for k,v in parse_qs(raw,max_num_fields=20).items()}
        if path in STATIC:
            file,kind=STATIC[path];body=(ROOT/file).read_bytes()
        elif path=='/api/search':body=json.dumps(search(params(q))).encode()
        elif path=='/api/contracts':body=json.dumps(contract_search(params(q))).encode()
        elif path=='/api/stats':body=json.dumps(stats()).encode()
        elif path=='/api/document-pages':body=json.dumps(document_pages(q)).encode()
        elif path=='/api/document':body=json.dumps(document(q)).encode()
        elif path=='/robots.txt':kind='text/plain';body=b'User-agent: *\nAllow: /\nDisallow: /api/\n'
        elif path=='/healthz':
            es({'size':0,'query':{'match_none':{}}});body=b'{"ok":true}'
        else:status='404 Not Found';body=b'{"error":"Not found"}'
    except ValueError as exc: status='400 Bad Request';body=json.dumps({'error':str(exc)}).encode()
    except Exception as exc:
        print('Search backend error:',type(exc).__name__,file=sys.stderr)
        status='503 Service Unavailable';body=b'{"error":"Search is temporarily unavailable. Please retry."}'
    start(status,[('Content-Type',kind),('Content-Length',str(len(body))),('Cache-Control','no-store'),
                  ('X-Content-Type-Options','nosniff'),('X-Frame-Options','DENY'),('Referrer-Policy','no-referrer'),
                  ('Content-Security-Policy',"default-src 'self'; script-src 'self' https://collect.open-dot.org; style-src 'self'; connect-src 'self' https://collect.open-dot.org; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")])
    return [] if env.get('REQUEST_METHOD')=='HEAD' else [body]
