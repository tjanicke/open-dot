import os, sqlite3, time
from pathlib import Path
from flask import Flask, request, jsonify, Response, send_file, abort
import open_bulletins as search

search.HTML = search.HTML.replace('</head>', '<script defer src="https://collect.open-dot.org/script.js"\n data-website-id="4aa5fcba-266b-4cc5-a5d6-1df6a639a047"\n data-domains="bulletins.open-dot.org"\n data-exclude-search="true"\n data-exclude-hash="true"></script>\n</head>', 1)

DATA=Path(os.environ.get('BULLETINS_DATA','/data')).resolve()
app=Flask(__name__,static_folder=None)

def connect():
    c=sqlite3.connect((DATA/'bulletins.sqlite3').as_uri()+'?mode=ro',uri=True)
    c.row_factory=sqlite3.Row
    deadline=time.monotonic()+15
    c.set_progress_handler(lambda: int(time.monotonic()>deadline),10000)
    return c

with connect() as c:
    FILES={r['doc_id']:dict(r) for r in c.execute('SELECT * FROM files')}
for doc,row in FILES.items():
    path=(DATA/'pdfs'/f'{doc}.pdf').resolve()
    if path.parent != DATA/'pdfs' or not path.is_file():
        raise RuntimeError('Missing portable PDF: '+doc)

if (DATA/'verified-official-urls.json').is_file():
    search.OFFICIAL_URLS.update(search.load_official_urls(DATA/'verified-official-urls.json',DATA))

@app.after_request
def headers(r):
    r.headers['X-Content-Type-Options']='nosniff'
    r.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    r.headers['X-Frame-Options']='SAMEORIGIN'
    return r

@app.get('/')
def index():return Response(search.HTML,mimetype='text/html')

@app.get('/healthz')
def health():
    with connect() as c:c.execute('SELECT 1 FROM files LIMIT 1').fetchone()
    return jsonify(status='ok',files=len(FILES))

@app.get('/api/search')
def query():
    q=request.args.get('q','').strip()
    if len(q)>300:return jsonify(error='Use at most 300 characters.'),400
    agency=request.args.get('agency','all')
    if agency not in ('all','IDOT','ISTHA'):return jsonify(error='Unknown source.'),400
    try:
        page=int(request.args.get('page','1'))
        options={k:request.args[k] for k in ('year_from','year_to','number_from','number_to','sort') if k in request.args}
        c=connect()
        try:result=search.grouped_search(c,q,agency,page,**options)
        finally:c.close()
        return jsonify(result)
    except ValueError as e:return jsonify(error=str(e)),400
    except sqlite3.OperationalError:
        return jsonify(error='Search could not finish. Try a more specific query.'),503

@app.get('/pdf/<doc>')
def pdf(doc):
    if doc not in FILES:abort(404)
    return send_file(DATA/'pdfs'/f'{doc}.pdf',mimetype='application/pdf',
                     download_name=FILES[doc]['file_name'],conditional=True,max_age=86400)
