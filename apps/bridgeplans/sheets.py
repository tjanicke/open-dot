"""Deterministic rules: inventory code mapping, sheet-title recognition and group summaries.

Everything here is plain regex/lookup logic, so it runs over the whole archive in minutes
and gives the same answer every time. The LLM is only used where these rules can't decide.
"""
import re

TYPES = ['steel_girder', 'ppc_girder', 'ppc_deck_beam', 'slab_bridge', 'concrete_girder', 'box_culvert',
         'arch', 'truss', 'rigid_frame', 'movable', 'cable_stayed', 'other']
LABELS = {'steel_girder': 'Steel girder', 'ppc_girder': 'PPC girder', 'ppc_deck_beam': 'PPC deck beam',
          'slab_bridge': 'Slab bridge', 'concrete_girder': 'Concrete girder / T-beam', 'box_culvert': 'Box culvert',
          'arch': 'Arch', 'truss': 'Truss', 'rigid_frame': 'Rigid frame', 'movable': 'Movable',
          'cable_stayed': 'Cable-stayed', 'other': 'Other'}


# ---------------------------------------------------------------- inventory (NBI 43A / 43B)
# 43A material: 1 concrete, 2 concrete continuous, 3 steel, 4 steel continuous,
# 5 prestressed, 6 prestressed continuous, 7 wood, 8 masonry, 9 aluminum/iron, 0 other.
# IDOT also uses codes outside the NBI list (e.g. material 'A', types 24/29/91); those are
# left unmapped and shown raw rather than guessed.
def inventory_type(mat, typ):
    mat = (mat or '').strip().upper()
    typ = (typ or '').strip().zfill(2)
    if typ == '19':
        return 'box_culvert' if mat in ('1', '2') else None   # steel/other culverts are usually pipes
    if typ in ('11', '12'): return 'arch'
    if typ in ('09', '10'): return 'truss'
    if typ in ('15', '16', '17'): return 'movable'
    if typ == '14': return 'cable_stayed'
    if typ == '07' and mat in ('1', '2', '3', '4', '5', '6'): return 'rigid_frame'
    if typ == '01' and mat in ('1', '2', '5', '6'): return 'slab_bridge'
    if mat in ('3', '4') and typ in ('02', '03', '04', '05', '06', '08', '21'): return 'steel_girder'
    if mat in ('5', '6') and typ in ('05', '06', '22'): return 'ppc_deck_beam'
    if mat in ('5', '6') and typ in ('02', '04', '21'): return 'ppc_girder'
    if mat in ('1', '2') and typ in ('02', '03', '04', '05', '06', '21'): return 'concrete_girder'
    return None


def num(x):
    try:
        v = float(str(x).strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def year(x):
    m = re.match(r'\s*(\d{4})', str(x or ''))
    y = int(m.group(1)) if m else 0
    return y if 1800 < y < 2100 else None


# ---------------------------------------------------------------- sheet recognition
# Patterns are tested against the OCR text around the structure number on each page,
# which in IDOT plans usually includes the title block (sheet title + "STRUCTURE NO.").
SHEET_PATTERNS = [
    ('index', r'INDEX\s+OF\s+SHEETS|SHEET\s+NO\.?\s+TITLE|INDEX\s+OF\s+HIGHWAY\s+STANDARDS'),
    ('general_plan', r'GENERAL\s+PLAN\s*(?:AND|&)\s*ELEVATION|GENERAL\s+PLAN\b|GENERAL\s+ELEVATION'),
    # Only the structure-wide sheet: pier, abutment and bar-list sheets carry their own "Bill of Material" tables.
    ('general_data', r'GENERAL\s+DATA|TOTAL\s+BILL\s+OF\s+MATERIAL'),
    ('superstructure', r'FRAMING\s+PLAN|SUPERSTRUCTURE|TOP\s+OF\s+SLAB\s+ELEV|DECK\s+BEAM\s+DETAILS?|'
                       r'BEAM\s+DETAILS?|GIRDER\s+DETAILS?|STRUCTURAL\s+STEEL|DIAPHRAGM|BEARING\s+DETAILS?|'
                       r'SLAB\s+REINFORCEMENT|DECK\s+(?:SLAB\s+)?DETAILS?|ARCH\s+RIB|TRUSS\s+DETAILS?|CAMBER'),
    ('substructure', r'ABUTMENT|PIER\s+DETAILS?|\bPIERS?\b|PILE\s+(?:DETAILS?|DATA|LAYOUT)|FOUNDATION\s+PLAN|'
                     r'WING\s*WALLS?|SUBSTRUCTURE'),
    ('culvert', r'BOX\s+CULVERT|CULVERT\s+(?:SECTION|PLAN|DETAILS?)|HEADWALL|BARREL\s+(?:SECTION|DETAILS?)'),
    ('borings', r'SOIL\s+BORING|BORING\s+LOGS?|SUBSURFACE\s+(?:DATA|EXPLORATION)'),
]
REHAB = re.compile(r'REPAIR|REHABILITAT|JOINT\s+REPLACEMENT|BEARING\s+REPLACEMENT|PATCHING|SCARIF|'
                   r'HYDRO-?DEMOLITION|RETROFIT|DECK\s+REPLACEMENT|SUPERSTRUCTURE\s+REPLACEMENT|EPOXY\s+INJECTION|'
                   r'(?:DECK|CONCRETE|LATEX|MICRO-?SILICA|POLYMER)\s+OVERLAY|STRENGTHENING|HEAT\s+STRAIGHTEN', re.I)
# Maintenance contracts: washing, cleaning, painting, sealing. These carry existing general plans for reference.
MAINT = re.compile(r'WASH(?:ING)?|CLEANING|FLUSHING|\bPAINT(?:ING)?\b|SEALING|\bSEALER\b|CRACK\s+SEAL|'
                   r'BIRD\s+(?:DROPPINGS|GUANO)|DEBRIS\s+REMOVAL|MAINTENANCE\s+(?:OF\s+)?STRUCTURE', re.I)
# Things that only appear when a structure (or a new superstructure) is actually being designed.
DESIGN = re.compile(r'FRAMING\s+PLAN|TOP\s+OF\s+SLAB\s+ELEV|BEAM\s+DETAILS?|GIRDER\s+DETAILS?|DECK\s+BEAM\s+DETAILS?|'
                    r'BAR\s+SPLICER|BILL\s+OF\s+MATERIAL|PILE\s+DATA|SOIL\s+BORING|BORING\s+LOGS?|'
                    r'(?:REMOVAL\s+OF\s+EXISTING|PROPOSED|NEW)\s+(?:STRUCTURE|BRIDGE|SUPERSTRUCTURE)|'
                    r'CULVERT\s+SECTION|BARREL\s+(?:SECTION|DETAILS?)|SLAB\s+REINFORCEMENT|DESIGN\s+(?:STRESSES|SPECIFICATIONS)|'
                    r'LRFD|HL-?93|SEISMIC\s+DATA', re.I)


def contract_profile(snippets):
    """Counts of maintenance / repair / new-design wording across a whole contract's plan text."""
    m = r = d = 0
    for t in snippets:
        m += bool(MAINT.search(t))
        r += bool(REHAB.search(t))
        d += bool(DESIGN.search(t))
    return {'n': len(snippets), 'maint': m, 'repair': r, 'design': d}


WIDENING = re.compile(r'WIDENING', re.I)
REFERENCE = re.compile(r'LOCATION\s+MAP|BRIDGE\s+OMISSION|SUMMARY\s+OF\s+QUANTITIES|SCHEDULE\s+OF\s+QUANTITIES|'
                       r'INDEX\s+OF\s+SHEETS|PLAN\s+AND\s+PROFILE|MAINTENANCE\s+OF\s+TRAFFIC|TRAFFIC\s+CONTROL|'
                       r'EROSION|BENCH\s*MARK|LIGHTING|SIGNING|PAVEMENT\s+MARKING', re.I)
EXISTING = re.compile(r'EXISTING\s+(?:STRUCTURE|BRIDGE|SUPERSTRUCTURE|DECK)|REMOVAL\s+OF\s+EXISTING', re.I)
STRUCTURAL_KINDS = ('general_plan', 'general_data', 'superstructure', 'substructure', 'culvert')
PICK_ORDER = {'general_plan': 0, 'general_data': 1, 'superstructure': 2, 'culvert': 3, 'substructure': 4}
SHEET_LABELS = {'general_plan': 'General plan & elevation', 'general_data': 'General data / bill of material',
                'index': 'Index of sheets', 'superstructure': 'Superstructure',
                'substructure': 'Substructure', 'culvert': 'Culvert', 'borings': 'Borings',
                'reference': 'Reference', 'other': 'Other'}
_COMPILED = [(k, re.compile(p, re.I)) for k, p in SHEET_PATTERNS]


def sheet_kind(text, occurrences=1):
    """Best guess at what a plan page is, from the OCR text around the structure number.

    A page naming the structure 5+ times is an index of sheets / cover sheet listing its drawings,
    not a drawing of it, even if "GENERAL PLAN" appears in the list.
    """
    t = ' '.join(str(text or '').split())
    if (occurrences or 1) >= 5:
        return 'index'
    for kind, pat in _COMPILED:
        if pat.search(t):
            if kind == 'general_data' and re.search(r'BAR\s+LIST', t, re.I) and not re.search(r'GENERAL\s+DATA', t, re.I):
                continue            # a bar list's "bill of material" is a detail table, not the general data sheet
            return kind
    if REFERENCE.search(t):
        return 'reference'
    return 'other'


def title_hint(text, width=90):
    """Short literal snippet showing the matched sheet title, for display."""
    t = ' '.join(str(text or '').split())
    for kind, pat in _COMPILED:
        m = pat.search(t)
        if m and kind != 'index':
            a = max(0, m.start() - 20)
            return ('…' if a else '') + t[a:m.end() + width].strip() + '…'
    return t[:width + 40] + ('…' if len(t) > width + 40 else '')


# ---------------------------------------------------------------- group summary
def summarize_group(pages, letting, inv_type, built, recon, contract=None, pay=None):
    """pages: dicts with keys basis, contexts(list), text, clue_types(list), sheet_kind.
    contract: contract_profile() of the whole contract/letting, or None.

    Returns the deterministic group record: drawing kind, state, plan type evidence and
    a resolved type with its source.
    """
    contract = contract or {'n': 0, 'maint': 0, 'repair': 0, 'design': 0}
    kinds = [p['sheet_kind'] for p in pages]
    structural = [p for p in pages if p['sheet_kind'] in STRUCTURAL_KINDS]
    all_text = ' '.join(p['text'] for p in pages)
    rehab_pages = sum(1 for p in pages if REHAB.search(p['text']))
    maint_pages = sum(1 for p in pages if MAINT.search(p['text']))
    design_pages = sum(1 for p in pages if DESIGN.search(p['text']) or p['sheet_kind'] == 'borings')
    has_gpe = 'general_plan' in kinds
    contexts = {c for p in pages for c in p['contexts']}
    ly = year(letting)
    built_match = bool(ly and year(built) and ly <= year(built) <= ly + 6)   # structure built from this letting

    # A general plan sheet alone is NOT evidence of new design: rehab and maintenance contracts
    # include the existing general plan. New design needs detail sheets, borings, "proposed"
    # wording, or an inventory build year right after the letting.
    design_evidence = design_pages + ('PROPOSED' in contexts) + 2 * built_match
    maint_contract = contract['maint'] > 0 and contract['design'] == 0
    repair_contract = contract['repair'] > contract['design']
    if (maint_pages or maint_contract) and design_evidence == 0 and not rehab_pages:
        kind = 'maintenance'
    elif rehab_pages and (rehab_pages >= design_pages or not built_match) and design_evidence < 3:
        kind = 'rehab'
    elif repair_contract and design_evidence == 0:
        kind = 'rehab'
    elif design_evidence and (has_gpe or len(structural) >= 2):
        kind = 'widening' if WIDENING.search(all_text) else 'design'
    elif structural:
        kind = 'partial'
    elif maint_contract:
        kind = 'maintenance'
    else:
        kind = 'reference'

    # Pay items are the record of what was actually paid for: they override the sheet rules.
    pay_work = pay['work'] if pay else None
    single = bool(pay) and pay.get('n_structures', 1) <= 1
    if pay_work == 'maintenance':
        kind = 'maintenance'
    elif pay_work in ('rehab', 'deck_replacement') and kind != 'reference':
        kind = 'rehab'
    elif pay_work in ('new', 'superstructure_replacement') and single and (structural or has_gpe):
        # One structure in the contract: the new work is this structure. With several structures the
        # contract-level items can't say which one is new, so the sheets decide.
        kind = 'widening' if WIDENING.search(all_text) else 'design'

    contexts = {c for p in pages for c in p['contexts']}
    existing_text = any(EXISTING.search(p['text']) for p in structural)
    if kind in ('rehab', 'maintenance'):
        state = 'existing'
    elif 'PROPOSED' in contexts and 'EXISTING' not in contexts:
        state = 'proposed'
    elif 'EXISTING' in contexts and 'PROPOSED' not in contexts and not has_gpe:
        state = 'existing'
    elif existing_text and has_gpe:
        state = 'replacement'
    else:
        state = 'unclear'
    if pay_work == 'superstructure_replacement' and kind == 'design':
        state = 'superstructure replacement'
    elif pay_work == 'deck_replacement':
        state = 'deck replacement'

    # Plan-text type clues, weighted toward pages whose title block names this structure.
    weights = {}
    for p in pages:
        w = 3 if (p['basis'] == 'LABELED_SN' and p['sheet_kind'] in STRUCTURAL_KINDS) else \
            2 if p['sheet_kind'] in STRUCTURAL_KINDS else 1
        for c in p['clue_types']:
            weights[c] = weights.get(c, 0) + w
    plan_types = dict(sorted(weights.items(), key=lambda kv: -kv[1]))
    plan_top = next(iter(plan_types), None)

    ly = year(letting)
    era = max(filter(None, [year(built), year(recon)]), default=None)
    # Inventory year within 0–6 years after the letting: the 2025 structure was likely built from these plans.
    era_match = bool(ly and era and ly <= era <= ly + 6)

    cands = sorted(pay['types']) if pay and pay_work in ('new', 'superstructure_replacement') else []
    if cands and not single and not (inv_type in cands or set(plan_types) & set(cands)):
        cands = []        # several structures, and nothing ties this one to a paid-for type
    if cands and kind in ('design', 'widening', 'partial'):
        if len(cands) == 1 and not single and cands[0] != inv_type and cands[0] not in plan_types:
            type_, source = None, 'unknown'
        elif len(cands) == 1 and inv_type and era_match and inv_type != cands[0]:
            # The contract paid for one type, but this structure, built from this letting, is another:
            # usually a second structure in the same contract. Keep it for review.
            type_, source = inv_type, 'conflict'
        elif len(cands) == 1:
            type_ = cands[0]
            source = 'confirmed' if (type_ == inv_type and era_match) or type_ in plan_types else 'pay_items'
        elif inv_type in cands and (era_match or inv_type in plan_types):
            type_, source = inv_type, 'confirmed'
        elif plan_top in cands:
            type_, source = plan_top, 'pay_items'
        else:
            type_, source = None, 'unknown'          # several paid-for types; the model picks among them
    elif inv_type and inv_type in plan_types:
        type_, source = inv_type, 'confirmed'
    elif inv_type and not plan_types:
        type_, source = inv_type, 'inventory'
    elif inv_type and plan_types:
        type_, source = (inv_type, 'conflict') if era_match else (plan_top, 'conflict')
    elif plan_types:
        type_, source = plan_top, 'plan_text'
    else:
        type_, source = None, 'unknown'

    score = (40 if has_gpe else 0) + {'design': 30, 'widening': 20, 'partial': 10, 'rehab': 5}.get(kind, 0) \
        + min(len(structural), 20) + (15 if era_match else 0) + (10 if source in ('confirmed', 'pay_items') else 0)
    return {'kind': kind, 'state': state, 'n_pages': len(pages), 'n_structural': len(structural),
            'has_gpe': int(has_gpe), 'plan_types': plan_types, 'era_match': int(era_match),
            'type': type_, 'type_source': source, 'score': score, 'pay_work': pay_work, 'candidates': cands,
            'variants': (pay or {}).get('variants', {}).get(type_, []) if cands else []}
