"""Local search UI: one card per structure, its plan sets underneath, one click to the drawing.

    python3 app.py            # then open http://127.0.0.1:8766
"""
import argparse, csv, hmac, io, json, re, sqlite3, ssl, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sheets

ROOT = Path(__file__).resolve().parent
IDOT_BASE = 'https://apps.dot.illinois.gov/eplan/desenv/'
# Public links come only from Open PDF Search's verified link catalogue (exact names from IDOT's
# directory listings). No link is invented: a page without a verified URL gets none.
LINKS = {'public': False}


def pdf_url(chunk, idot_url, page):
    frag = f'#page={urllib.parse.quote(str(page or 1))}'
    if LINKS['public']:
        return idot_url + frag if idot_url else None
    return f'pdf?chunk={urllib.parse.quote(str(chunk))}' + frag
KIND_SETS = {'design': ('design', 'widening'), 'rehab': ('rehab',), 'maintenance': ('maintenance',), 'any': None,
             'partial': ('partial',), 'reference': ('reference',)}
SOURCES = ('confirmed', 'pay_items', 'inventory', 'plan_text', 'ai', 'conflict', 'unknown')


def connect(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def safe_pdf(root, path):
    if not path:
        raise FileNotFoundError('No PDF path recorded for this page')
    root = Path(root).resolve()
    rel = Path(path)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('Unsafe PDF path')
    f = (root / rel).resolve()
    if not f.is_relative_to(root) or f.suffix.lower() != '.pdf' or not f.is_file():
        raise FileNotFoundError(f'PDF not found under {root}: {path}')
    return f


def byte_range(header, size):
    if not header:
        return 0, size - 1, False
    m = re.fullmatch(r'bytes=(\d*)-(\d*)', header.strip())
    if not m or not any(m.groups()):
        raise ValueError('Unsupported range')
    a, b = m.groups()
    if not a:
        start, end = max(0, size - int(b)), size - 1
    else:
        start, end = int(a), min(int(b), size - 1) if b else size - 1
    if start >= size or start > end:
        raise ValueError('Range unsatisfiable')
    return start, end, True


def where_clause(f):
    w, a = [], []
    kinds = KIND_SETS.get(f.get('kind', 'design'), KIND_SETS['design'])
    if kinds:
        w.append(f"g.kind IN ({','.join('?' * len(kinds))})")
        a += kinds
    if f.get('type'):
        if f['type'] not in sheets.TYPES:
            raise ValueError('Unknown type')
        w.append('g.type=?')
        a.append(f['type'])
    if f.get('source') == 'settled':
        w.append("g.type_source IN ('confirmed','pay_items','inventory','plan_text','ai')")
    elif f.get('source') in SOURCES:
        w.append('g.type_source=?')
        a.append(f['source'])
    if f.get('construction') in ('precast', 'cast-in-place'):
        w.append('g.variants LIKE ?')
        a.append(f'%"{f["construction"]}%')
    if f.get('feature'):
        if not re.fullmatch(r'[a-z_]+', f['feature']):
            raise ValueError('Bad feature')
        w.append("EXISTS (SELECT 1 FROM contract_pay c2 WHERE c2.contract=g.contract AND c2.letting=substr(g.letting,1,10) "
                 "AND c2.features LIKE ?)")
        a.append(f'%"{f["feature"]}"%')
    if f.get('linked') == 'sn':
        w.append("g.sn!=''")
    elif f.get('linked') == 'none':
        w.append("g.sn=''")
    if f.get('q'):
        q = '%' + re.sub(r'([%_\\])', r'\\\1', f['q'].strip()) + '%'
        digits = re.sub(r'\D', '', f['q'])
        w.append("(s.carried LIKE ? ESCAPE '\\' OR s.crossed LIKE ? ESCAPE '\\' OR s.location LIKE ? ESCAPE '\\' "
                 "OR g.contract LIKE ? ESCAPE '\\'" + (" OR g.sn LIKE ?" if len(digits) >= 3 else '') + ')')
        a += [q] * 4 + ([digits + '%'] if len(digits) >= 3 else [])
    if f.get('county'):
        c = f['county'].strip()
        if re.fullmatch(r'\d{1,3}', c):
            w.append('substr(g.sn,1,3)=?')
            a.append(c.zfill(3))
        else:
            w.append('s.county LIKE ?')
            a.append(c.upper() + '%')
    for key, col, op in (('min_span', 's.max_span', '>='), ('max_span', 's.max_span', '<='),
                         ('min_year', 'g.letting_year', '>='), ('max_year', 'g.letting_year', '<=')):
        if f.get(key):
            w.append(f'{col} {op} ?')
            a.append(float(f[key]))
    return ('WHERE ' + ' AND '.join(w)) if w else '', a


ORDER = {'relevance': 'max(g.score) DESC, max(g.letting) DESC', 'newest': 'max(g.letting) DESC',
         'oldest': 'min(g.letting) ASC', 'span': 'max(s.max_span) DESC'}
GROUP_COLS = '''g.id, g.sn, g.contract, g.letting, g.kind, g.state, g.n_structural, g.has_gpe, g.type, g.type_source,
  g.inv_type, g.plan_types, g.era_match, g.score, p.path best_path, p.page best_page, p.sheet_kind best_kind,
  p.chunk_id best_chunk, r.type ai_type, r.drawings ai_drawings, r.quote ai_quote, r.quote_ok ai_quote_ok,
  g.pay_work, g.variants, cp.evidence pay_evidence, cp.eplan_link, p.idot_url best_idot_url'''
GROUP_JOINS = '''LEFT JOIN pages p ON p.group_id=g.id AND p.chunk_id=g.best_chunk
  LEFT JOIN reviews r ON r.group_key=g.gkey AND r.calibration=0
  LEFT JOIN contract_pay cp ON cp.contract=g.contract AND cp.letting=substr(g.letting,1,10)'''


def group_dict(r):
    d = dict(r)
    d['plan_types'] = json.loads(d['plan_types'] or '{}')
    d['pay_evidence'] = json.loads(d['pay_evidence'] or '[]')
    d['variants'] = json.loads(d['variants'] or '[]')
    d['best_url'] = pdf_url(d['best_chunk'], d.pop('best_idot_url', None), d['best_page']) if d['best_chunk'] else None
    d['file'] = (d['best_path'] or '').split('/')[-1]
    if LINKS['public']:
        d['_path'] = d.pop('best_path', None)       # used by the CSV export, not sent to the page
    return d


def search(db, f, limit=25, offset=0):
    where, args = where_clause(f)
    key = "CASE WHEN g.sn='' THEN 'doc:'||g.id ELSE g.sn END"
    base = f'FROM groups g LEFT JOIN structures s ON s.sn=g.sn {where}'
    total = db.execute(f'SELECT count(DISTINCT {key}) {base}', args).fetchone()[0]
    order = ORDER.get(f.get('sort', 'relevance'), ORDER['relevance'])
    keys = [r[0] for r in db.execute(f'SELECT {key} k {base} GROUP BY k ORDER BY {order} LIMIT ? OFFSET ?',
                                     args + [limit, offset])]
    items = []
    for k in keys:
        if k.startswith('doc:'):
            gid = int(k[4:])
            rows = db.execute(f'SELECT {GROUP_COLS} FROM groups g {GROUP_JOINS} WHERE g.id=?', (gid,)).fetchall()
            items.append({'sn': '', 'structure': None, 'groups': [group_dict(r) for r in rows], 'other_groups': 0})
            continue
        st = db.execute('SELECT * FROM structures WHERE sn=?', (k,)).fetchone()
        rows = db.execute(f'''SELECT {GROUP_COLS} FROM groups g LEFT JOIN structures s ON s.sn=g.sn {GROUP_JOINS}
                              {where + (' AND' if where else 'WHERE')} g.sn=? ORDER BY g.score DESC, g.letting DESC''',
                          args + [k]).fetchall()
        n_all = db.execute('SELECT count(*) FROM groups WHERE sn=?', (k,)).fetchone()[0]
        items.append({'sn': k, 'structure': dict(st) if st else None, 'groups': [group_dict(r) for r in rows],
                      'other_groups': n_all - len(rows)})
    return {'total': total, 'offset': offset, 'limit': limit, 'items': items}


def handler(db_path, pdf_root, public=False, proxy_token=None):
    LINKS['public'] = public
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, body, status=200, ctype='application/json; charset=utf-8', extra=None):
            if isinstance(body, dict):
                for it in body.get('items', []):
                    for g in it.get('groups', []):
                        g.pop('_path', None)
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not public and self.headers.get('Host', '').split(':')[0] not in ('127.0.0.1', 'localhost'):
                return self.send({'error': 'localhost only'}, 403)
            if proxy_token and not hmac.compare_digest(self.headers.get('X-OpenDOT-Proxy', ''), proxy_token):
                return self.send({'error': 'forbidden'}, 403)
            try:
                self.route()
            except BrokenPipeError:
                pass
            except (FileNotFoundError, LookupError) as e:
                self.send({'error': str(e)}, 404)
            except ValueError as e:
                self.send({'error': str(e)}, 400)
            except sqlite3.OperationalError as e:
                self.send({'error': f'Database unavailable ({e}). Has build_index.py run?'}, 503)

        def route(self):
            u = urllib.parse.urlsplit(self.path)
            f = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items() if v[-1].strip()}
            static = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                      '/style.css': ('style.css', 'text/css')}
            if u.path in static:
                name, ct = static[u.path]
                return self.send((ROOT / 'web' / name).read_bytes(), ctype=ct + '; charset=utf-8')
            if u.path in ('/health', '/healthz'):
                return self.send({'app': 'OpenDOT plan finder v3'})
            db = connect(db_path)
            try:
                if u.path == '/api/search':
                    limit, offset = int(f.pop('limit', 25)), int(f.pop('offset', 0))
                    return self.send(search(db, f, min(max(limit, 1), 100), max(offset, 0)))
                if u.path == '/api/stats':
                    where, args = where_clause({k: v for k, v in f.items() if k != 'type'})
                    counts = dict(db.execute(f'''SELECT g.type, count(DISTINCT CASE WHEN g.sn='' THEN 'd'||g.id ELSE g.sn END)
                        FROM groups g LEFT JOIN structures s ON s.sn=g.sn {where} GROUP BY g.type''', args).fetchall())
                    meta = {r[0]: json.loads(r[1]) for r in db.execute('SELECT k, v FROM meta')}
                    return self.send({'types': [{'id': t, 'label': sheets.LABELS[t], 'n': counts.get(t, 0)}
                                                for t in sheets.TYPES], 'built': meta.get('built'),
                                      'reviews': db.execute('SELECT count(*) FROM reviews WHERE calibration=0').fetchone()[0]})
                if u.path == '/api/group':
                    gid = int(f['id'])
                    rows = db.execute('''SELECT chunk_id, path, page, basis, sheet_kind, title, idot_url FROM pages WHERE group_id=?
                        ORDER BY (upper(path) LIKE '%ADDENDUM%' OR upper(path) LIKE '%REVIS%'), CASE sheet_kind WHEN 'general_plan' THEN 0 WHEN 'general_data' THEN 1 WHEN 'superstructure' THEN 2
                        WHEN 'culvert' THEN 3 WHEN 'substructure' THEN 4 WHEN 'borings' THEN 5 ELSE 6 END,
                        path, CAST(page AS INTEGER)''', (gid,)).fetchall()
                    pages = []
                    for r in rows:
                        d = dict(r) | {'kind_label': sheets.SHEET_LABELS.get(r['sheet_kind']),
                                       'url': pdf_url(r['chunk_id'], r['idot_url'], r['page']),
                                       'file': (r['path'] or '').split('/')[-1]}
                        d.pop('idot_url', None)
                        if public:
                            d.pop('path')
                        pages.append(d)
                    return self.send({'pages': pages})
                if u.path == '/export.csv':
                    out = io.StringIO()
                    w = csv.writer(out)
                    w.writerow(['SN', 'Type', 'Type source', 'Drawings', 'Contract', 'Letting', 'Structural sheets',
                                'Best sheet PDF', 'PDF page', 'County', 'Carried', 'Crossed', 'Built', 'Max span',
                                'Length', 'Inventory type'])
                    off = 0
                    while True:
                        res = search(db, f, 100, off)
                        for it in res['items']:
                            s = it['structure'] or {}
                            for g in it['groups']:
                                w.writerow([(f"{g['sn'][:3]}-{g['sn'][3:]}" if g['sn'] else ''),
                                            sheets.LABELS.get(g['type'], g['type'] or ''), g['type_source'], g['kind'],
                                            g['contract'], g['letting'], g['n_structural'],
                                            (g['best_url'] or '').split('#')[0] if public else g['best_path'],
                                            g['best_page'], s.get('county'), s.get('carried'), s.get('crossed'),
                                            s.get('built'), s.get('max_span'), s.get('length'), s.get('inv_type')])
                        off += 100
                        if off >= res['total']:
                            break
                    return self.send(out.getvalue().encode('utf-8-sig'), ctype='text/csv; charset=utf-8',
                                     extra={'Content-Disposition': 'attachment; filename="opendot-plans.csv"'})
                if u.path == '/pdf' and not public:
                    r = db.execute('SELECT path FROM pages WHERE chunk_id=? LIMIT 1', (f['chunk'],)).fetchone()
                    if not r:
                        raise LookupError('Unknown page')
                    pdf = safe_pdf(pdf_root, r['path'])
                    size = pdf.stat().st_size
                    try:
                        a, b, partial = byte_range(self.headers.get('Range'), size)
                    except ValueError:
                        return self.send(b'', 416, 'application/pdf', {'Content-Range': f'bytes */{size}'})
                    self.send_response(206 if partial else 200)
                    for k, v in {'Content-Type': 'application/pdf', 'Content-Length': str(b - a + 1),
                                 'Accept-Ranges': 'bytes', 'Content-Disposition': 'inline'}.items():
                        self.send_header(k, v)
                    if partial:
                        self.send_header('Content-Range', f'bytes {a}-{b}/{size}')
                    self.end_headers()
                    if self.command != 'HEAD':
                        with pdf.open('rb') as fh:
                            fh.seek(a)
                            left = b - a + 1
                            while left > 0:
                                chunk = fh.read(min(1 << 20, left))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                left -= len(chunk)
                    return
                raise LookupError('Not found')
            finally:
                db.close()
    return H


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, default=ROOT / 'data/finder3.sqlite')
    p.add_argument('--pdf-root', type=Path, default=ROOT / 'pdfs')
    p.add_argument('--port', type=int, default=8766)
    p.add_argument('--public', action='store_true',
                   help='web-host mode: links go to IDOT eplan, no local PDF serving, accepts proxied host names')
    p.add_argument('--host', default='127.0.0.1', help='address to listen on (the LAN IP behind the gateway)')
    p.add_argument('--tls-cert', type=Path, help='serve HTTPS with this certificate (the gateway verifies it)')
    p.add_argument('--tls-key', type=Path)
    p.add_argument('--proxy-token-file', type=Path,
                   help='require the gateway header X-OpenDOT-Proxy to match this file (same scheme as Open PDF Search)')
    a = p.parse_args()
    if a.host not in ('127.0.0.1', 'localhost') and not (a.public and a.proxy_token_file and a.tls_cert):
        p.error('listening beyond localhost requires --public, --tls-cert/--tls-key and --proxy-token-file')
    token = a.proxy_token_file.read_text().strip() if a.proxy_token_file else None
    if a.proxy_token_file and not re.fullmatch(r'[0-9a-f]{64}', token or ''):
        p.error('proxy token file must hold 64 hex characters')
    srv = ThreadingHTTPServer((a.host, a.port), handler(a.db, a.pdf_root, a.public, token))
    if a.tls_cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(a.tls_cert, a.tls_key)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print(f"Listening on {'https' if a.tls_cert else 'http'}://{a.host}:{a.port}   (Ctrl+C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
