"""OpenDOT ODOT Selections: Ohio DOT consultant selections from Controlling Board records.

Separate module from the IDOT Open Selections app; same look, search pattern and
shared OpenDOT components. Reads three Parquet files written by export_odot_parquet.py:

    data/odot_selections.parquet   one row per agreement (2005+)
    data/odot_applicants.parquet   one row per LOI submission (2020+)
    data/odot_firms.parquet        one row per canonical firm

Run locally:
    solara run ohioselections.py --host 127.0.0.1 --port 8767
"""
import os
from pathlib import Path
from html import escape

import pandas as pd
import solara
import solara.lab
import ipyvuetify as vuetify
import traitlets


DATA_DIR = Path(os.environ.get("ODOT_DATA_DIR", Path(__file__).resolve().parent / "data"))
ITEMS_PER_PAGE = 25
ALL = "All"

SEL_COLUMNS = [
    "Group", "Group Date", "Agreement Number", "Project", "County", "District",
    "Service Category", "Selected Firm", "Project Description", "Est. Construction Cost",
    "Dollar Limitation", "Firms Submitting LOIs", "CB Request", "CB Meeting Date",
    "Firm Name as Listed", "Vendor Number", "Source File",
]
APP_COLUMNS = [
    "Group", "Group Date", "Firm", "Outcome", "Agreements Won", "Dollars Won",
    "City", "State", "CB Request", "Firm Name as Listed", "Source File",
]
FIRM_COLUMNS = [
    "Firm", "Agreements", "Total Dollar Limitation", "First Year", "Last Year",
    "Groups Applied", "Groups Won", "Win Rate", "Other Names", "Vendor Numbers",
]
NUMERIC = {"Group Year", "Agreements Won", "Firms Submitting LOIs", "Agreements", "First Year",
           "Last Year", "Groups Applied", "Groups Won", "Firm ID"}
CURRENCY = {"Est. Construction Cost", "Dollar Limitation", "Dollars Won", "Total Dollar Limitation"}
PERCENT = {"Win Rate"}
FIRMLIKE = {"Selected Firm", "Firm", "Firm Name as Listed"}
LONGTEXT = {"Project Description", "Other Names"}
REGION = {"County", "District", "Service Category"}
HEADERS = {
    "Group Date": "Group Advertised", "Agreement Number": "Agreement #", "CB Request": "CB Request",
    "Est. Construction Cost": "Est. Construction", "Firms Submitting LOIs": "LOIs in Group",
    "Total Dollar Limitation": "Total $ Limitation", "Source File": "Source",
}


def _read(name):
    frame = pd.read_parquet(DATA_DIR / name)
    for column in frame.columns:
        if pd.api.types.is_object_dtype(frame[column]) or pd.api.types.is_string_dtype(frame[column]):
            frame[column] = frame[column].astype("string").str.strip().replace("", pd.NA)
    return frame


@solara.memoize
def load_data():
    return (_read("odot_selections.parquet"), _read("odot_applicants.parquet"),
            _read("odot_firms.parquet"))


sel_all, app_all, firm_all = load_data()


def options(frame, column, *, numeric=False, descending=False, order_by=None):
    if order_by is not None:      # e.g. groups in advertised-date order
        ordered = frame.dropna(subset=[column]).sort_values(order_by, ascending=not descending)
        values = list(dict.fromkeys(ordered[column].astype(str)))
    else:
        values = frame[column].dropna().astype(str).unique().tolist()
        if numeric:
            values.sort(key=lambda v: (float(v), v), reverse=descending)
        else:
            values.sort(key=str.casefold, reverse=descending)
    return [ALL] + values


sel_groups = options(sel_all, "Group", descending=True, order_by="Group Date")
sel_years = options(sel_all, "Group Year", numeric=True)
sel_districts = [ALL] + sorted(
    sel_all["District"].dropna().unique().tolist(),
    key=lambda d: (not d.startswith("District"), int(d.split()[-1]) if d.split()[-1].isdigit() else 99, d))
sel_counties = options(sel_all, "County")
sel_categories = options(sel_all, "Service Category")
app_groups = options(app_all, "Group", descending=True, order_by="Group Date")
app_years = options(app_all, "Group Year", numeric=True)
app_states = options(app_all, "State")
OUTCOMES = [ALL, "Selected", "Not selected"]
SORT_ORDERS = ["Descending", "Ascending"]


# ------------------------------------------------------------------ filtering
def contains_all(series, query):
    """Every keyword must appear (case-insensitive, literal) in the same field."""
    match = pd.Series(True, index=series.index)
    for word in query.split():
        match &= series.str.contains(word, case=False, regex=False, na=False)
    return match


def year_range(frame, begin, end, column="Group Year"):
    if begin == ALL and end == ALL:
        return frame
    years = pd.to_numeric(frame[column], errors="coerce")
    keep = pd.Series(True, index=frame.index)
    if begin != ALL:
        keep &= years >= int(begin)
    if end != ALL:
        keep &= years <= int(end)
    return frame[keep]


def sort_frame(frame, column, order, tiebreak):
    columns, directions = [column], [order == "Ascending"]
    for col, asc in tiebreak:
        if col not in columns:
            columns.append(col)
            directions.append(asc)

    def key(series):
        if series.name in NUMERIC or series.name in CURRENCY or series.name in PERCENT:
            return pd.to_numeric(series, errors="coerce")
        return series.astype("string").str.casefold()
    return frame.sort_values(by=columns, ascending=directions, key=key, na_position="last", kind="stable")


def filter_selections(frame, *, firm="", project="", group=ALL, begin=ALL, end=ALL, district=ALL,
                      county=ALL, category=ALL, sort_column="Group Date", sort_order="Descending"):
    result = frame
    for column, value in (("Group", group), ("District", district), ("Service Category", category)):
        if value != ALL:
            result = result[result[column] == value]
    if county != ALL:      # multi-county projects list several names
        result = result[result["County"].str.contains(county, case=False, regex=False, na=False)]
    result = year_range(result, begin, end)
    if firm.strip():
        result = result[contains_all(result["Selected Firm"], firm)
                        | contains_all(result["Firm Name as Listed"], firm)]
    if project.strip():
        q = project.strip()
        result = result[result["Project"].str.contains(q, case=False, regex=False, na=False)
                        | result["Agreement Number"].str.contains(q, case=False, regex=False, na=False)
                        | contains_all(result["Project Description"], q)]
    return sort_frame(result, sort_column, sort_order,
                      [("Group Date", False), ("Dollar Limitation", False)])


def filter_applicants(frame, *, firm="", group=ALL, begin=ALL, end=ALL, outcome=ALL, state=ALL,
                      sort_column="Group Date", sort_order="Descending"):
    result = frame
    for column, value in (("Group", group), ("Outcome", outcome), ("State", state)):
        if value != ALL:
            result = result[result[column] == value]
    result = year_range(result, begin, end)
    if firm.strip():
        result = result[contains_all(result["Firm"], firm) | contains_all(result["Firm Name as Listed"], firm)]
    return sort_frame(result, sort_column, sort_order, [("Group Date", False), ("Firm", True)])


def filter_firms(frame, *, firm="", active=ALL, sort_column="Total Dollar Limitation", sort_order="Descending"):
    result = frame
    if firm.strip():
        result = result[contains_all(result["Firm"], firm) | contains_all(result["Other Names"], firm)]
    if active == "Applied since 2020":
        result = result[pd.to_numeric(result["Groups Applied"], errors="coerce") > 0]
    elif active == "Selected at least once":
        result = result[pd.to_numeric(result["Agreements"], errors="coerce") > 0]
    return sort_frame(result, sort_column, sort_order, [("Firm", True)])


# ------------------------------------------------------------------ rendering
def column_class(column):
    if column in NUMERIC or column in CURRENCY or column in PERCENT:
        return "selection-number"
    if column in LONGTEXT:
        return "selection-description"
    if column in FIRMLIKE:
        return "selection-firm"
    if column in REGION:
        return "selection-region"
    return "selection-text"


def cell_html(column, value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    if column in CURRENCY:
        return f"${float(value):,.0f}"
    if column in PERCENT:
        return f"{float(value):.0%}"
    if column == "Source File":
        url = str(value)
        if url.startswith("https://"):
            return f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">PDF</a>'
        return escape(url)
    if column == "Outcome":
        mark = "✓ " if value == "Selected" else ""
        return escape(mark + str(value))
    return escape(str(value))


def render_table(frame, label):
    headers = "".join(
        f'<th scope="col" class="{column_class(c)}">{escape(HEADERS.get(c, c))}</th>' for c in frame.columns)
    rows = []
    for values in frame.itertuples(index=False, name=None):
        cells = "".join(f'<td class="{column_class(c)}">{cell_html(c, v)}</td>'
                        for c, v in zip(frame.columns, values))
        rows.append(f"<tr>{cells}</tr>")
    return (f'<table class="odotselections-table" aria-label="{escape(label, quote=True)}">'
            f'<thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table>')


def csv_frame(frame):
    """CSV keeps raw numbers (no $ formatting) so it opens cleanly in Excel."""
    return frame.to_csv(index=False)


# Same responsive spacing, header alignment, row shading, and theme as OpenBidz.
APP_CSS = """
        .odotselections-app {
            width: 100%;
            max-width: 100%;
            min-width: 0;
            box-sizing: border-box;
            container-type: inline-size;
            container-name: odotselections;
        }
        .odotselections-panel {
            width: 100%;
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .odotselections-panel .v-card__text {
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .odotselections-app .odotselections-controls {
            display: grid !important;
            grid-template-columns: minmax(0, 1fr);
            gap: 12px;
            width: 100%;
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .odotselections-controls > * {
            min-width: 0;
            max-width: 100%;
        }
        @container odotselections (min-width: 900px) {
            .odotselections-app .odotselections-controls {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @container odotselections (min-width: 1200px) {
            .odotselections-app .odotselections-filter-controls {
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }
        }
        .odotselections-panel .v-expansion-panel-header {
            min-height: 48px;
        }
        .odotselections-panel .v-expansion-panel-content__wrap {
            padding: 0 12px 12px;
        }
        .odotselections-table-frame {
            width: 100%;
            max-width: 100%;
            min-width: 0;
            box-sizing: border-box;
            --selection-surface: #ffffff;
            --selection-header: #eef3f8;
            --selection-text: #1d2835;
            --selection-border: #c7d0dc;
            --selection-stripe: #f5f7fa;
            --selection-hover: #e6eff8;
            --selection-link: #135385;
        }
        .odotselections-table-frame.odotselections-dark-table {
            --selection-surface: #192433;
            --selection-header: #223247;
            --selection-text: #e7edf5;
            --selection-border: #495b70;
            --selection-stripe: #1d2b3d;
            --selection-hover: #2a4058;
            --selection-link: #8bc9ff;
        }
        .odotselections-results-scroll,
        .odotselections-top-scroll {
            display: block;
            width: 100%;
            max-width: 100%;
            min-width: 0;
            box-sizing: border-box;
            overflow-x: scroll;
            overflow-y: hidden;
            scrollbar-width: auto;
            scrollbar-color: #8493a5 var(--selection-header);
            -webkit-overflow-scrolling: touch;
            border: 1px solid var(--selection-border);
            border-radius: 8px;
            background: var(--selection-surface);
        }
        .odotselections-top-scroll {
            height: 20px;
            margin-bottom: 8px;
        }
        .odotselections-table-frame ::-webkit-scrollbar {
            height: 14px;
        }
        .odotselections-table-frame ::-webkit-scrollbar-track {
            background: var(--selection-header);
        }
        .odotselections-table-frame ::-webkit-scrollbar-thumb {
            background: #8493a5;
            border: 3px solid var(--selection-header);
            border-radius: 7px;
        }
        .odotselections-scroll-hint {
            margin: 0 0 6px;
            font-size: 13px;
            color: var(--selection-text);
        }
        .odotselections-table {
            width: 100%;
            border-collapse: collapse;
            font-family: inherit;
            font-size: 14px;
            color: var(--selection-text);
            background: var(--selection-surface);
        }
        .odotselections-table th,
        .odotselections-table td {
            padding: 12px 14px;
            text-align: left;
            vertical-align: top;
            line-height: 1.5;
            border-bottom: 1px solid var(--selection-border);
        }
        .odotselections-table thead th {
            background: var(--selection-header);
            color: var(--selection-text);
            font-weight: 700;
            vertical-align: middle;
            white-space: nowrap;
            border-bottom: 2px solid var(--selection-border);
        }
        .odotselections-table .selection-number {
            text-align: right;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }
        .odotselections-table .selection-center {
            text-align: center;
            white-space: nowrap;
        }
        .odotselections-table .selection-text {
            white-space: nowrap;
        }
        .odotselections-table .selection-description {
            min-width: 250px;
            max-width: 360px;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .odotselections-table tbody tr:nth-child(even) {
            background: var(--selection-stripe);
        }
        .odotselections-table tbody tr:hover {
            background: var(--selection-hover);
        }
        .odotselections-table tbody tr:last-child td {
            border-bottom: 0;
        }
        .odotselections-table a {
            color: var(--selection-link);
            font-weight: 600;
            text-decoration: underline;
        }
        @media (max-width: 599px) {
            .odotselections-panel {
                padding: 4px !important;
            }
            .odotselections-panel .v-card__title {
                font-size: 1.15rem;
                line-height: 1.4;
                overflow-wrap: anywhere;
            }
            .odotselections-panel .v-card__text {
                padding: 12px;
            }
            .odotselections-panel .v-btn {
                min-height: 44px;
            }
        }
    
        .odotselections-table .selection-firm {
            min-width: 200px;
            max-width: 300px;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .odotselections-table .selection-longtext {
            min-width: 260px;
            max-width: 380px;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .odotselections-views .v-btn-toggle, .odotselections-views .v-item-group {
            flex-wrap: wrap;
            height: auto !important;
            gap: 4px;
        }
        .odotselections-views .v-btn {
            min-height: 40px;
            font-weight: 600;
        }
        .odotselections-table .selection-region {
            min-width: 130px;
            max-width: 240px;
            white-space: normal;
            overflow-wrap: anywhere;
        }
"""


class SelectionTable(vuetify.VuetifyTemplate):
    """Native horizontal scroll areas synchronized entirely in the browser."""
    table_html = traitlets.Unicode("").tag(sync=True)
    dark = traitlets.Bool(False).tag(sync=True)

    @traitlets.default("template")
    def _table_template(self):
        return """
        <template>
          <div class="odotselections-table-frame"
               :class="{ 'odotselections-dark-table': dark }">
            <p v-show="hasOverflow" class="odotselections-scroll-hint">
              Scroll sideways to view all columns.
            </p>
            <div v-show="hasOverflow" ref="top"
                 class="odotselections-top-scroll" tabindex="0"
                 role="region" aria-label="Horizontal table scrollbar"
                 @scroll="scrollFromTop">
              <div ref="spacer" style="height: 1px;"></div>
            </div>
            <div ref="bottom" class="odotselections-results-scroll" tabindex="0"
                 role="region" aria-label="Scroll results horizontally"
                 @scroll="scrollFromBottom" v-html="table_html">
            </div>
          </div>
        </template>
        <script>
        export default {
          data() {
            return { hasOverflow: true };
          },
          mounted() {
            this.$nextTick(this.measure);
            if (typeof ResizeObserver !== 'undefined') {
              this._tableResizeObserver = new ResizeObserver(() => this.measure());
              this._tableResizeObserver.observe(this.$refs.bottom);
            }
            window.addEventListener('resize', this.measure);
          },
          watch: {
            table_html() { this.$nextTick(this.measure); },
            dark() { this.$nextTick(this.measure); }
          },
          methods: {
            measure() {
              const bottom = this.$refs.bottom;
              const top = this.$refs.top;
              const spacer = this.$refs.spacer;
              if (!bottom || !top || !spacer) return;
              // Equal client widths keep both scroll ranges identical.
              spacer.style.width = bottom.scrollWidth + 'px';
              this.hasOverflow = bottom.scrollWidth > bottom.clientWidth + 1;
              top.scrollLeft = bottom.scrollLeft;
            },
            scrollFromTop() {
              const top = this.$refs.top;
              const bottom = this.$refs.bottom;
              if (top && bottom && bottom.scrollLeft !== top.scrollLeft) {
                bottom.scrollLeft = top.scrollLeft;
              }
            },
            scrollFromBottom() {
              const top = this.$refs.top;
              const bottom = this.$refs.bottom;
              if (top && bottom && top.scrollLeft !== bottom.scrollLeft) {
                top.scrollLeft = bottom.scrollLeft;
              }
            },
            cleanup() {
              if (this._tableResizeObserver) this._tableResizeObserver.disconnect();
              window.removeEventListener('resize', this.measure);
            }
          },
          beforeDestroy() { this.cleanup(); },
          beforeUnmount() { this.cleanup(); }
        };
        </script>
        """


# ---- OpenDOT shared presentation and browser theme preference ----
import ipyvuetify as _od_vuetify
import traitlets as _od_traits



class _OpenDOTPagination(_od_vuetify.VuetifyTemplate):
    """Keep draft input in the browser; commit navigation only on Go/Enter."""
    page = _od_traits.Int(1).tag(sync=True)
    page_count = _od_traits.Int(1).tag(sync=True)
    template = _od_traits.Unicode(r'''<template>
      <nav aria-label="Results pages" style="display:flex;align-items:center;flex-wrap:wrap;gap:8px;color:rgb(var(--v-theme-on-surface));">
        <v-btn :disabled="page <= 1" @click="navigate(page - 1)">◀ Previous</v-btn>
        <span aria-live="polite">Page {{ page }} of {{ page_count }}</span>
        <v-btn :disabled="page >= page_count" @click="navigate(page + 1)">Next ▶</v-btn>
        <label style="display:flex;align-items:center;gap:6px;">Go to page
          <input type="number" min="1" :max="page_count" step="1" v-model="draft"
            @keydown.enter.prevent="go" aria-label="Go to results page"
            style="width:5.5rem;padding:6px 8px;border:1px solid currentColor;border-radius:6px;font:inherit;color:inherit;background:rgb(var(--v-theme-surface));">
        </label>
        <v-btn @click="go">Go</v-btn>
        <span v-if="error" role="alert">{{ error }}</span>
      </nav>
    </template>
    <script>
    module.exports = {
      data() { return {draft: String(this.page), error: ''}; },
      watch: {
        page() { this.draft = String(this.page); this.error = ''; },
        page_count() { this.draft = String(this.page); this.error = ''; }
      },
      methods: {
        navigate(value) {
          this.page = Math.max(1, Math.min(this.page_count, value));
          this.draft = String(this.page);
          this.error = '';
        },
        go() {
          const raw = String(this.draft).trim();
          const value = Number(raw);
          if (!raw || !Number.isSafeInteger(value)) {
            this.error = 'Enter a whole page number.';
            return;
          }
          this.navigate(value);
        }
      }
    };
    </script>''').tag(sync=True)


class _OpenDOTThemeSwitch(_od_vuetify.VuetifyTemplate):
    """Use the existing session theme, with persistence only in this browser."""
    dark = _od_traits.Bool(default_value=None, allow_none=True).tag(sync=True)
    template = _od_traits.Unicode(r'''
<template>
  <v-switch :model-value="dark === true"
    @update:model-value="choose" label="Dark mode" hide-details class="mt-0 pt-0" />
</template>
<script>
export default {
  mounted() {
    this._themeKey = 'opendot-solara-theme';
    this._themeMedia = window.matchMedia('(prefers-color-scheme: dark)');
    let saved = null;
    try { saved = localStorage.getItem(this._themeKey); } catch (_) {}
    this._themeChosen = saved === 'light' || saved === 'dark';
    this.dark = this._themeChosen ? saved === 'dark' : this._themeMedia.matches;
    this._themeMediaChanged = e => { if (!this._themeChosen) this.dark = e.matches; };
    this._themeStorageChanged = e => {
      if (e.key !== this._themeKey && e.key !== null) return;
      this._themeChosen = e.newValue === 'light' || e.newValue === 'dark';
      this.dark = this._themeChosen ? e.newValue === 'dark' : this._themeMedia.matches;
    };
    this._themeMedia.addEventListener('change', this._themeMediaChanged);
    window.addEventListener('storage', this._themeStorageChanged);
  },
  beforeUnmount() {
    this._themeMedia.removeEventListener('change', this._themeMediaChanged);
    window.removeEventListener('storage', this._themeStorageChanged);
  },
  methods: {
    choose(value) {
      this._themeChosen = true;
      this.dark = Boolean(value);
      try { localStorage.setItem(this._themeKey, this.dark ? 'dark' : 'light'); } catch (_) {}
    }
  }
};
</script>
''').tag(sync=True)


def _opendot_configure_theme():
    """Configure Vuetify 3's native colors for this visitor's session."""
    for mode, colors in (
        ('light', dict(primary='#1b527d', secondary='#596778', background='#f5f7fa', surface='#ffffff', surface_variant='#eef3f8', on_surface_variant='#1d2835')),
        ('dark', dict(primary='#a4d4ff', secondary='#b0bfd0', background='#101722', surface='#192433', surface_variant='#223247', on_surface_variant='#e7edf5')),
    ):
        target = getattr(solara.lab.theme.themes, mode)
        for name, value in colors.items():
            setattr(target, name, value)
        target.custom_theme_colors = dict(target.custom_theme_colors or {}, **{
            'on-background': '#1d2835' if mode == 'light' else '#e7edf5',
            'on-surface': '#1d2835' if mode == 'light' else '#e7edf5',
            'on-primary': '#ffffff' if mode == 'light' else '#102338',
            'outline': '#c7d0dc' if mode == 'light' else '#495b70',
            'focus': '#986500' if mode == 'light' else '#ffd36a',
        })


_OPENDOT_STYLE = "\n\n/* Use Vuetify 3 native theme variables, including teleported menus. */\n.v-application {\n  --od-bg:rgb(var(--v-theme-background));--od-panel:rgb(var(--v-theme-surface));\n  --od-text:rgb(var(--v-theme-on-surface));--od-muted:rgb(var(--v-theme-secondary));\n  --od-line:rgb(var(--v-theme-outline));--od-accent:rgb(var(--v-theme-primary));\n  --od-button:rgb(var(--v-theme-primary));--od-button-text:rgb(var(--v-theme-on-primary));\n  --od-focus:rgb(var(--v-theme-focus));\n}\n.v-application {\n  background:var(--od-bg)!important;color:var(--od-text)!important;\n  font-family:system-ui,-apple-system,sans-serif!important;\n}\n.v-application .v-main,.v-application .v-main__wrap {background:var(--od-bg)!important}\n.v-application .v-card,.v-application .v-expansion-panel,\n.v-application .v-list,.v-application .v-toolbar {\n  background-color:var(--od-panel)!important;color:var(--od-text)!important;\n}\n.v-application .v-card {border:1px solid var(--od-line);border-radius:12px!important;box-shadow:0 2px 6px #1a27370b!important}\n.v-application .opendot-page-heading {padding:12px 0 8px}\n.v-application .opendot-page-heading h1 {font-size:2rem!important;line-height:1.2;font-weight:700;margin:0 0 10px}\n.v-application .opendot-page-heading p {color:var(--od-muted);line-height:1.6;margin:0}\n.v-application .v-card__title {font-family:inherit!important;font-size:1.35rem!important;font-weight:650;line-height:1.4}\n.v-application .v-card__text,.v-application .v-label {color:var(--od-muted)!important}\n.v-application .v-input input,.v-application .v-input textarea,\n.v-application .v-field__input,.v-application .v-select__selection {color:var(--od-text)!important;font-family:inherit}\n.v-application .v-input input::placeholder {color:var(--od-muted)!important;opacity:1}\n.v-application .v-text-field--outlined fieldset {border-color:var(--od-line)!important;border-radius:7px}\n.v-application .v-field {color:var(--od-text);background-color:var(--od-panel)}\n.v-application .v-field__outline {color:var(--od-line)}\n.v-application .v-btn {border-radius:7px!important;text-transform:none!important;letter-spacing:normal!important;font-weight:600;min-height:40px}\n.v-application .v-btn:not(.v-btn--icon):not(.v-btn--text):not(.v-btn--disabled) {background-color:var(--od-button)!important;color:var(--od-button-text)!important}\n.v-application .primary--text {color:var(--od-accent)!important;caret-color:var(--od-accent)!important}\n.v-application a {color:var(--od-accent)}\n.v-application .v-icon {color:inherit}\n.v-application .v-input--switch .v-input--selection-controls__input {color:var(--od-accent)}\n.v-application button:focus-visible,.v-application a:focus-visible,\n.v-application input:focus-visible {outline:3px solid var(--od-focus);outline-offset:3px}\n.v-application .openbidz-app,.v-application .opentollz-app,\n.v-application .odotselections-app,.v-application .opentollselections-app {padding:12px;gap:18px!important}\n@media(max-width:600px){\n .v-application .openbidz-app,.v-application .opentollz-app,\n .v-application .odotselections-app,.v-application .opentollselections-app {padding:0}\n .v-application .v-card__title {font-size:1.15rem!important}\n}\n\n/* Override Jupyter Markdown's fixed text colors with the active theme. */\n.v-application .solara-markdown,\n.v-application .solara-markdown :is(h1,h2,h3,h4,h5,h6,p,strong,em,li,blockquote) {\n  color:rgb(var(--v-theme-on-surface))!important;\n}\n.v-application .opendot-page-heading .solara-markdown p {\n  color:rgb(var(--v-theme-secondary))!important;\n}\n"
# ---- End OpenDOT presentation ----

# ------------------------------------------------------------------ state
s_firm, s_project = solara.reactive(""), solara.reactive("")
s_group, s_begin, s_end = solara.reactive(ALL), solara.reactive(ALL), solara.reactive(ALL)
s_district, s_county, s_category = solara.reactive(ALL), solara.reactive(ALL), solara.reactive(ALL)
s_sort, s_order, s_page = solara.reactive("Group Date"), solara.reactive("Descending"), solara.reactive(0)

a_firm, a_group = solara.reactive(""), solara.reactive(ALL)
a_begin, a_end = solara.reactive(ALL), solara.reactive(ALL)
a_outcome, a_state = solara.reactive(ALL), solara.reactive(ALL)
a_sort, a_order, a_page = solara.reactive("Group Date"), solara.reactive("Descending"), solara.reactive(0)

f_firm, f_active = solara.reactive(""), solara.reactive(ALL)
f_sort, f_order, f_page = solara.reactive("Total Dollar Limitation"), solara.reactive("Descending"), solara.reactive(0)
FIRM_ACTIVITY = [ALL, "Selected at least once", "Applied since 2020"]
VIEWS = ["Selections", "Letters of Interest", "Firms"]
view = solara.reactive("Selections")


def reset(*pairs):
    for reactive, value in pairs:
        reactive.set(value)


def clear_selections():
    reset((s_firm, ""), (s_project, ""), (s_group, ALL), (s_begin, ALL), (s_end, ALL), (s_district, ALL),
          (s_county, ALL), (s_category, ALL), (s_sort, "Group Date"), (s_order, "Descending"), (s_page, 0))


def clear_applicants():
    reset((a_firm, ""), (a_group, ALL), (a_begin, ALL), (a_end, ALL), (a_outcome, ALL), (a_state, ALL),
          (a_sort, "Group Date"), (a_order, "Descending"), (a_page, 0))


def clear_firms():
    reset((f_firm, ""), (f_active, ALL), (f_sort, "Total Dollar Limitation"), (f_order, "Descending"), (f_page, 0))


def set_dark_mode(enabled):
    solara.lab.theme.dark = bool(enabled)


# ------------------------------------------------------------------ components
@solara.component
def Results(frame, columns, title, label, filename, page, dark, empty_hint):
    total = len(frame)
    with solara.Card(title, classes=["odotselections-panel"], margin=0, style="padding: 12px;"):
        solara.Markdown(f"### Found **{total:,}** matching records.")
        if not total:
            solara.Info(empty_hint)
            return
        page_count = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page_index = max(0, min(page.value, page_count - 1))
        with solara.Row(style="align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 12px;"):
            solara.FileDownload(data=lambda: csv_frame(frame[columns]), filename=filename,
                                label="📥 Download as CSV", mime_type="text/csv")
            _OpenDOTPagination.element(page=page_index + 1, page_count=page_count,
                                       on_page=lambda p: page.set(p - 1))
        start = page_index * ITEMS_PER_PAGE
        SelectionTable.element(table_html=render_table(frame[columns].iloc[start:start + ITEMS_PER_PAGE], label),
                               dark=dark)


@solara.component
def SelectionsTab(dark):
    deps = [s_firm.value, s_project.value, s_group.value, s_begin.value, s_end.value, s_district.value,
            s_county.value, s_category.value, s_sort.value, s_order.value]
    solara.use_memo(lambda: s_page.set(0), dependencies=deps)
    frame = solara.use_memo(lambda: filter_selections(
        sel_all, firm=s_firm.value, project=s_project.value, group=s_group.value, begin=s_begin.value,
        end=s_end.value, district=s_district.value, county=s_county.value, category=s_category.value,
        sort_column=s_sort.value, sort_order=s_order.value), dependencies=deps)
    active = sum([s_group.value != ALL, s_begin.value != ALL or s_end.value != ALL, s_district.value != ALL,
                  s_county.value != ALL, s_category.value != ALL])
    dollars = pd.to_numeric(frame["Dollar Limitation"], errors="coerce").sum()

    with solara.Card("Search ODOT Consultant Selections", classes=["odotselections-panel"], margin=0,
                     style="margin-bottom: 16px; padding: 12px;"):
        solara.Markdown("Search selected firms, projects (e.g. `FRA-33`), agreement numbers, or descriptions.",
                        style="margin-bottom: 8px;")
        with solara.Column(classes=["odotselections-controls"], gap="12px"):
            solara.InputText("Firm Name", value=s_firm)
            solara.InputText("Project, Agreement # or Description", value=s_project)
        with solara.ColumnsResponsive(default=12, small=12, medium=[8, 4], gutters_dense=True):
            solara.Markdown(f"**{len(frame):,}** agreements · **${dollars:,.0f}** total dollar limitation",
                            style="margin: 8px 0;")
            solara.Button(label="Clear Filters", on_click=clear_selections)
        with solara.Details(summary="More Filters" + (f" ({active} active)" if active else ""), expand=False):
            solara.Markdown("Groups are named by the date ODOT advertised them. Year ranges include both "
                            "endpoints. County is read from the project number; task-order agreements show "
                            "\"Various\".", style="margin-bottom: 8px;")
            with solara.Column(classes=["odotselections-controls", "odotselections-filter-controls"], gap="12px"):
                solara.Select(label="Programmatic Group", value=s_group, values=sel_groups)
                solara.Select(label="Beginning Year", value=s_begin, values=sel_years)
                solara.Select(label="Ending Year", value=s_end, values=sel_years)
                solara.Select(label="District", value=s_district, values=sel_districts)
                solara.Select(label="County", value=s_county, values=sel_counties)
                solara.Select(label="Service Category", value=s_category, values=sel_categories)
            if s_begin.value != ALL and s_end.value != ALL and int(s_begin.value) > int(s_end.value):
                solara.Warning("Beginning Year must be earlier than or equal to Ending Year.")
        with solara.Details(summary="Sort Options", expand=False):
            with solara.Column(classes=["odotselections-controls"], gap="12px"):
                solara.Select(label="Sort By", value=s_sort, values=SEL_COLUMNS[:-1])
                solara.Select(label="Direction", value=s_order, values=SORT_ORDERS)

    Results(frame, SEL_COLUMNS, "ODOT Consultant Selection Results", "ODOT consultant selection search results",
            "odot_selections.csv", s_page, dark,
            "No agreements match these searches and filters. Try fewer filters or Clear Filters.")


@solara.component
def ApplicantsTab(dark):
    deps = [a_firm.value, a_group.value, a_begin.value, a_end.value, a_outcome.value, a_state.value,
            a_sort.value, a_order.value]
    solara.use_memo(lambda: a_page.set(0), dependencies=deps)
    frame = solara.use_memo(lambda: filter_applicants(
        app_all, firm=a_firm.value, group=a_group.value, begin=a_begin.value, end=a_end.value,
        outcome=a_outcome.value, state=a_state.value, sort_column=a_sort.value, sort_order=a_order.value),
        dependencies=deps)
    won = int((frame["Outcome"] == "Selected").sum())
    rate = f" · selected in **{won / len(frame):.0%}**" if len(frame) else ""

    with solara.Card("Search ODOT Letters of Interest", classes=["odotselections-panel"], margin=0,
                     style="margin-bottom: 16px; padding: 12px;"):
        solara.Markdown(
            "Every firm that submitted a letter of interest for a programmatic group (2020 onward). "
            "**Selected** means the firm won at least one agreement in that group; ODOT's published list "
            "does not say which projects each firm pursued.", style="margin-bottom: 8px;")
        with solara.Column(classes=["odotselections-controls"], gap="12px"):
            solara.InputText("Firm Name", value=a_firm)
            solara.Select(label="Programmatic Group", value=a_group, values=app_groups)
        with solara.ColumnsResponsive(default=12, small=12, medium=[8, 4], gutters_dense=True):
            solara.Markdown(f"**{len(frame):,}** submissions{rate}", style="margin: 8px 0;")
            solara.Button(label="Clear Filters", on_click=clear_applicants)
        with solara.Details(summary="More Filters", expand=False):
            with solara.Column(classes=["odotselections-controls", "odotselections-filter-controls"], gap="12px"):
                solara.Select(label="Outcome", value=a_outcome, values=OUTCOMES)
                solara.Select(label="Beginning Year", value=a_begin, values=app_years)
                solara.Select(label="Ending Year", value=a_end, values=app_years)
                solara.Select(label="Firm State", value=a_state, values=app_states)
        with solara.Details(summary="Sort Options", expand=False):
            with solara.Column(classes=["odotselections-controls"], gap="12px"):
                solara.Select(label="Sort By", value=a_sort, values=APP_COLUMNS[:-1])
                solara.Select(label="Direction", value=a_order, values=SORT_ORDERS)

    Results(frame, APP_COLUMNS, "Letter of Interest Results", "ODOT letter of interest search results",
            "odot_letters_of_interest.csv", a_page, dark,
            "No submissions match these filters. Letters of interest are published for 2020 onward.")


@solara.component
def FirmsTab(dark):
    deps = [f_firm.value, f_active.value, f_sort.value, f_order.value]
    solara.use_memo(lambda: f_page.set(0), dependencies=deps)
    frame = solara.use_memo(lambda: filter_firms(
        firm_all, firm=f_firm.value, active=f_active.value, sort_column=f_sort.value, sort_order=f_order.value),
        dependencies=deps)

    with solara.Card("ODOT Consultant Firms", classes=["odotselections-panel"], margin=0,
                     style="margin-bottom: 16px; padding: 12px;"):
        solara.Markdown(
            "Each firm's ODOT programmatic record, with name changes and acquisitions combined where ODOT "
            "kept the same vendor number (e.g. Parsons Brinckerhoff → WSP). Applied/won counts and win rate "
            "cover 2020 onward, when letter-of-interest lists are available.", style="margin-bottom: 8px;")
        with solara.Column(classes=["odotselections-controls"], gap="12px"):
            solara.InputText("Firm Name (current or former)", value=f_firm)
            solara.Select(label="Show", value=f_active, values=FIRM_ACTIVITY)
        with solara.ColumnsResponsive(default=12, small=12, medium=[8, 4], gutters_dense=True):
            solara.Markdown(f"**{len(frame):,}** firms", style="margin: 8px 0;")
            solara.Button(label="Clear Filters", on_click=clear_firms)
        with solara.Details(summary="Sort Options", expand=False):
            with solara.Column(classes=["odotselections-controls"], gap="12px"):
                solara.Select(label="Sort By", value=f_sort, values=FIRM_COLUMNS)
                solara.Select(label="Direction", value=f_order, values=SORT_ORDERS)

    Results(frame, FIRM_COLUMNS, "Firm Results", "ODOT consultant firm search results",
            "odot_firms.csv", f_page, dark, "No firms match this search.")


@solara.component
def Page():
    solara.Title("OpenDOT ODOT Selections | Ohio DOT Engineering Consultant Selections")
    solara.use_effect(_opendot_configure_theme, [])
    selected_theme = solara.use_trait_observe(solara.lab.theme, "dark")
    effective_dark = solara.lab.use_dark_effective()
    dark = bool(effective_dark if selected_theme is None else selected_theme)
    first, last = int(sel_all["Group Year"].min()), int(sel_all["Group Year"].max())

    solara.Style(APP_CSS)
    solara.Style(_OPENDOT_STYLE)
    with solara.Column(classes=["odotselections-app"], gap="12px"):
        with solara.Row(justify="space-between", classes=["opendot-page-heading"],
                        style="align-items: center; flex-wrap: wrap; gap: 16px;"):
            solara.Markdown(f"# ODOT Selections\n\nOhio DOT programmatic engineering consultant selections, "
                            f"{first}–{last}, from Ohio Controlling Board records")
            _OpenDOTThemeSwitch.element(dark=selected_theme, on_dark=set_dark_mode)
        # View switcher (plain toggle buttons; avoids version-specific tab widgets)
        with solara.Row(classes=["odotselections-views"], style="flex-wrap: wrap; gap: 8px;"):
            solara.ToggleButtonsSingle(value=view, values=VIEWS)
        if view.value == "Letters of Interest":
            ApplicantsTab(dark)
        elif view.value == "Firms":
            FirmsTab(dark)
        else:
            SelectionsTab(dark)
