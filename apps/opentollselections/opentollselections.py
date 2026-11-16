"""OpenTollSelections: Illinois Tollway PSB consultant-selection search.

Place psb_selection_data.parquet beside this file, then run:
    solara run opentollselections.py --host 127.0.0.1 --port 8767

Dependencies: solara, pandas, pyarrow, ipyvuetify, traitlets.
"""
import os
from pathlib import Path
from html import escape

import pandas as pd
import solara
import solara.lab
import ipyvuetify as vuetify
import traitlets


DATA_FILENAME = "psb_selection_data.parquet"
ITEMS_PER_PAGE = 25
ALL = "All"

FIRM_COLUMNS = ["Selected Firm", "Proposed Subconsultants"]
FIRM_ROLES = ["Selected Firm", "Any Firm Role", "Proposed Subconsultants"]
NUMERIC_COLUMNS = {"Bulletin Year", "Item Number"}
DATE_COLUMN = "Selection Date"

DISPLAY_COLUMNS = [
    "PSB Number", "Bulletin Year", "Item Number", "Selection Date",
    "Contract #", "Selected Firm", "Project Description",
    "Proposed Subconsultants", "Source File",
]
DISPLAY_HEADERS = {
    "PSB Number": "PSB #",
    "Bulletin Year": "Bulletin Year",
    "Item Number": "Item #",
    "Contract #": "Contract #",
}
REQUIRED_COLUMNS = set(DISPLAY_COLUMNS)


def _normalize_selection_date(series):
    """Return a pandas datetime Series from Excel serials, strings, or timestamps."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")

    parsed = pd.to_datetime(series, errors="coerce")
    numeric = pd.to_numeric(series, errors="coerce")
    numeric_mask = numeric.notna()
    if numeric_mask.any():
        excel_dates = pd.Timestamp("1899-12-30") + pd.to_timedelta(numeric, unit="D")
        parsed = parsed.where(~numeric_mask, excel_dates)
    return parsed


@solara.memoize
def load_selection_data():
    path = Path(os.environ.get("OPENTOLL_DATA_FILE", str(Path(__file__).resolve().parent / DATA_FILENAME)))
    frame = pd.read_parquet(path)
    frame.columns = frame.columns.str.strip()

    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        found = ", ".join(map(str, frame.columns))
        raise ValueError(
            "The PSB parquet does not contain the Illinois Tollway selection table. "
            f"Missing columns: {', '.join(sorted(missing))}. Found: {found}"
        )

    for column in frame.columns:
        if pd.api.types.is_object_dtype(frame[column]) or pd.api.types.is_string_dtype(frame[column]):
            frame[column] = frame[column].astype("string").str.strip().replace("", pd.NA)

    frame[DATE_COLUMN] = _normalize_selection_date(frame[DATE_COLUMN])
    return frame


df_all = load_selection_data()


def filter_options(column, *, numeric=False, descending=False):
    values = df_all[column].dropna().astype(str).unique().tolist()
    if numeric:
        values.sort(key=lambda value: (float(value), value), reverse=descending)
    else:
        values.sort(key=str.casefold, reverse=descending)
    return [ALL] + values


available_psbs = filter_options("PSB Number", descending=True)
available_years = filter_options("Bulletin Year", numeric=True)
sort_columns = DISPLAY_COLUMNS
sort_orders = ["Ascending", "Descending"]

search_firm = solara.reactive("")
search_project = solara.reactive("")
selected_psb = solara.reactive(ALL)
selected_beginning_year = solara.reactive(ALL)
selected_ending_year = solara.reactive(ALL)
selected_firm_role = solara.reactive("Selected Firm")
chosen_sort_col = solara.reactive("PSB Number")
chosen_sort_order = solara.reactive("Descending")
current_page = solara.reactive(0)


def clear_filters():
    search_firm.set("")
    search_project.set("")
    selected_psb.set(ALL)
    selected_beginning_year.set(ALL)
    selected_ending_year.set(ALL)
    selected_firm_role.set("Selected Firm")
    chosen_sort_col.set("PSB Number")
    chosen_sort_order.set("Descending")
    current_page.set(0)


def set_dark_mode(enabled):
    solara.lab.theme.dark = bool(enabled)


def filter_selection_data(
    frame, *, firm_query="", project_query="", psb=ALL,
    beginning_year=ALL, ending_year=ALL, firm_role="Selected Firm",
    sort_column="PSB Number", sort_order="Descending",
):
    """Filter literal, case-insensitive searches and apply stable sorting."""
    result = frame

    if psb != ALL:
        result = result[result["PSB Number"].astype("string") == str(psb)]

    if beginning_year != ALL or ending_year != ALL:
        years = pd.to_numeric(result["Bulletin Year"], errors="coerce")
        keep = pd.Series(True, index=result.index)
        if beginning_year != ALL:
            keep &= years >= int(float(beginning_year))
        if ending_year != ALL:
            keep &= years <= int(float(ending_year))
        result = result[keep]

    if firm_query.strip():
        columns = FIRM_COLUMNS if firm_role == "Any Firm Role" else [firm_role]
        role_matches = pd.Series(False, index=result.index)
        for column in columns:
            field_match = pd.Series(True, index=result.index)
            for keyword in firm_query.split():
                field_match &= result[column].str.contains(keyword, case=False, regex=False, na=False)
            role_matches |= field_match
        result = result[role_matches]

    if project_query.strip():
        query = project_query.strip()
        contract_match = result["Contract #"].str.contains(query, case=False, regex=False, na=False)
        description_match = pd.Series(True, index=result.index)
        for keyword in query.split():
            description_match &= result["Project Description"].str.contains(
                keyword, case=False, regex=False, na=False,
            )
        result = result[contract_match | description_match]

    ascending = sort_order == "Ascending"
    columns, directions = [sort_column], [ascending]
    for column, direction in [("Bulletin Year", False), ("PSB Number", False), ("Item Number", True)]:
        if column not in columns:
            columns.append(column)
            directions.append(direction)

    def sort_key(series):
        if series.name in NUMERIC_COLUMNS:
            return pd.to_numeric(series, errors="coerce")
        if series.name == DATE_COLUMN:
            return pd.to_datetime(series, errors="coerce")
        return series.astype("string").str.casefold()

    return result.sort_values(
        by=columns, ascending=directions, key=sort_key,
        na_position="last", kind="stable",
    )


def render_results_table(frame):
    def column_class(column):
        if column in NUMERIC_COLUMNS:
            return "selection-number"
        if column == "Project Description":
            return "selection-description"
        if column == "Proposed Subconsultants":
            return "selection-longtext"
        if column in FIRM_COLUMNS:
            return "selection-firm"
        return "selection-text"

    headers = "".join(
        f'<th scope="col" class="{column_class(column)}">'
        f'{escape(DISPLAY_HEADERS.get(column, column))}</th>'
        for column in frame.columns
    )
    rows = []
    for values in frame.itertuples(index=False, name=None):
        cells = []
        for column, value in zip(frame.columns, values):
            if pd.isna(value):
                text = ""
            elif column == DATE_COLUMN:
                text = pd.Timestamp(value).strftime("%m/%d/%Y")
            else:
                text = str(value)
            cells.append(f'<td class="{column_class(column)}">{escape(text)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<table class="opentollselections-table" aria-label="Illinois Tollway consultant selection search results">'
        f'<thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


# Responsive layout, synchronized horizontal scrolling, and dark mode matching OpenSelections.
APP_CSS = """
        .opentollselections-app {
            width: 100%;
            max-width: 100%;
            min-width: 0;
            box-sizing: border-box;
            container-type: inline-size;
            container-name: opentollselections;
        }
        .opentollselections-panel {
            width: 100%;
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .opentollselections-panel .v-card__text {
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .opentollselections-app .opentollselections-controls {
            display: grid !important;
            grid-template-columns: minmax(0, 1fr);
            gap: 12px;
            width: 100%;
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .opentollselections-controls > * {
            min-width: 0;
            max-width: 100%;
        }
        @container opentollselections (min-width: 900px) {
            .opentollselections-app .opentollselections-controls {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @container opentollselections (min-width: 1200px) {
            .opentollselections-app .opentollselections-filter-controls {
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }
        }
        .opentollselections-panel .v-expansion-panel-header {
            min-height: 48px;
        }
        .opentollselections-panel .v-expansion-panel-content__wrap {
            padding: 0 12px 12px;
        }
        .opentollselections-table-frame {
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
        .opentollselections-table-frame.opentollselections-dark-table {
            --selection-surface: #192433;
            --selection-header: #223247;
            --selection-text: #e7edf5;
            --selection-border: #495b70;
            --selection-stripe: #1d2b3d;
            --selection-hover: #2a4058;
            --selection-link: #8bc9ff;
        }
        .opentollselections-results-scroll,
        .opentollselections-top-scroll {
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
        .opentollselections-top-scroll {
            height: 20px;
            margin-bottom: 8px;
        }
        .opentollselections-table-frame ::-webkit-scrollbar {
            height: 14px;
        }
        .opentollselections-table-frame ::-webkit-scrollbar-track {
            background: var(--selection-header);
        }
        .opentollselections-table-frame ::-webkit-scrollbar-thumb {
            background: #8493a5;
            border: 3px solid var(--selection-header);
            border-radius: 7px;
        }
        .opentollselections-scroll-hint {
            margin: 0 0 6px;
            font-size: 13px;
            color: var(--selection-text);
        }
        .opentollselections-table {
            width: 100%;
            border-collapse: collapse;
            font-family: inherit;
            font-size: 14px;
            color: var(--selection-text);
            background: var(--selection-surface);
        }
        .opentollselections-table th,
        .opentollselections-table td {
            padding: 12px 14px;
            text-align: left;
            vertical-align: top;
            line-height: 1.5;
            border-bottom: 1px solid var(--selection-border);
        }
        .opentollselections-table thead th {
            background: var(--selection-header);
            color: var(--selection-text);
            font-weight: 700;
            vertical-align: middle;
            white-space: nowrap;
            border-bottom: 2px solid var(--selection-border);
        }
        .opentollselections-table .selection-number {
            text-align: right;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }
        .opentollselections-table .selection-center {
            text-align: center;
            white-space: nowrap;
        }
        .opentollselections-table .selection-text {
            white-space: nowrap;
        }
        .opentollselections-table .selection-description {
            min-width: 250px;
            max-width: 360px;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .opentollselections-table tbody tr:nth-child(even) {
            background: var(--selection-stripe);
        }
        .opentollselections-table tbody tr:hover {
            background: var(--selection-hover);
        }
        .opentollselections-table tbody tr:last-child td {
            border-bottom: 0;
        }
        .opentollselections-table a {
            color: var(--selection-link);
            font-weight: 600;
            text-decoration: underline;
        }
        @media (max-width: 599px) {
            .opentollselections-panel {
                padding: 4px !important;
            }
            .opentollselections-panel .v-card__title {
                font-size: 1.15rem;
                line-height: 1.4;
                overflow-wrap: anywhere;
            }
            .opentollselections-panel .v-card__text {
                padding: 12px;
            }
            .opentollselections-panel .v-btn {
                min-height: 44px;
            }
        }
    
        .opentollselections-table .selection-firm {
            min-width: 200px;
            max-width: 300px;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .opentollselections-table .selection-longtext {
            min-width: 260px;
            max-width: 380px;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .opentollselections-table .selection-region {
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
          <div class="opentollselections-table-frame"
               :class="{ 'opentollselections-dark-table': dark }">
            <p v-show="hasOverflow" class="opentollselections-scroll-hint">
              Scroll sideways to view all columns.
            </p>
            <div v-show="hasOverflow" ref="top"
                 class="opentollselections-top-scroll" tabindex="0"
                 role="region" aria-label="Horizontal table scrollbar"
                 @scroll="scrollFromTop">
              <div ref="spacer" style="height: 1px;"></div>
            </div>
            <div ref="bottom" class="opentollselections-results-scroll" tabindex="0"
                 role="region" aria-label="Scroll selection results horizontally"
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


_OPENDOT_STYLE = "\n\n/* Use Vuetify 3 native theme variables, including teleported menus. */\n.v-application {\n  --od-bg:rgb(var(--v-theme-background));--od-panel:rgb(var(--v-theme-surface));\n  --od-text:rgb(var(--v-theme-on-surface));--od-muted:rgb(var(--v-theme-secondary));\n  --od-line:rgb(var(--v-theme-outline));--od-accent:rgb(var(--v-theme-primary));\n  --od-button:rgb(var(--v-theme-primary));--od-button-text:rgb(var(--v-theme-on-primary));\n  --od-focus:rgb(var(--v-theme-focus));\n}\n.v-application {\n  background:var(--od-bg)!important;color:var(--od-text)!important;\n  font-family:system-ui,-apple-system,sans-serif!important;\n}\n.v-application .v-main,.v-application .v-main__wrap {background:var(--od-bg)!important}\n.v-application .v-card,.v-application .v-expansion-panel,\n.v-application .v-list,.v-application .v-toolbar {\n  background-color:var(--od-panel)!important;color:var(--od-text)!important;\n}\n.v-application .v-card {border:1px solid var(--od-line);border-radius:12px!important;box-shadow:0 2px 6px #1a27370b!important}\n.v-application .opendot-page-heading {padding:12px 0 8px}\n.v-application .opendot-page-heading h1 {font-size:2rem!important;line-height:1.2;font-weight:700;margin:0 0 10px}\n.v-application .opendot-page-heading p {color:var(--od-muted);line-height:1.6;margin:0}\n.v-application .v-card__title {font-family:inherit!important;font-size:1.35rem!important;font-weight:650;line-height:1.4}\n.v-application .v-card__text,.v-application .v-label {color:var(--od-muted)!important}\n.v-application .v-input input,.v-application .v-input textarea,\n.v-application .v-field__input,.v-application .v-select__selection {color:var(--od-text)!important;font-family:inherit}\n.v-application .v-input input::placeholder {color:var(--od-muted)!important;opacity:1}\n.v-application .v-text-field--outlined fieldset {border-color:var(--od-line)!important;border-radius:7px}\n.v-application .v-field {color:var(--od-text);background-color:var(--od-panel)}\n.v-application .v-field__outline {color:var(--od-line)}\n.v-application .v-btn {border-radius:7px!important;text-transform:none!important;letter-spacing:normal!important;font-weight:600;min-height:40px}\n.v-application .v-btn:not(.v-btn--icon):not(.v-btn--text):not(.v-btn--disabled) {background-color:var(--od-button)!important;color:var(--od-button-text)!important}\n.v-application .primary--text {color:var(--od-accent)!important;caret-color:var(--od-accent)!important}\n.v-application a {color:var(--od-accent)}\n.v-application .v-icon {color:inherit}\n.v-application .v-input--switch .v-input--selection-controls__input {color:var(--od-accent)}\n.v-application button:focus-visible,.v-application a:focus-visible,\n.v-application input:focus-visible {outline:3px solid var(--od-focus);outline-offset:3px}\n.v-application .openbidz-app,.v-application .opentollz-app,\n.v-application .openselections-app,.v-application .opentollselections-app {padding:12px;gap:18px!important}\n@media(max-width:600px){\n .v-application .openbidz-app,.v-application .opentollz-app,\n .v-application .openselections-app,.v-application .opentollselections-app {padding:0}\n .v-application .v-card__title {font-size:1.15rem!important}\n}\n\n/* Override Jupyter Markdown's fixed text colors with the active theme. */\n.v-application .solara-markdown,\n.v-application .solara-markdown :is(h1,h2,h3,h4,h5,h6,p,strong,em,li,blockquote) {\n  color:rgb(var(--v-theme-on-surface))!important;\n}\n.v-application .opendot-page-heading .solara-markdown p {\n  color:rgb(var(--v-theme-secondary))!important;\n}\n"
# ---- End OpenDOT presentation ----


@solara.component
def Page():
    solara.Title("OpenDOT Toll Selections | Illinois Tollway Engineering Consultant Selections")
    solara.use_effect(_opendot_configure_theme, [])
    selected_theme = solara.use_trait_observe(solara.lab.theme, "dark")
    effective_dark = solara.lab.use_dark_effective()
    dark_mode = bool(effective_dark if selected_theme is None else selected_theme)

    filter_dependencies = [
        search_firm.value, search_project.value, selected_psb.value,
        selected_beginning_year.value, selected_ending_year.value,
        selected_firm_role.value, chosen_sort_col.value, chosen_sort_order.value,
    ]
    solara.use_memo(lambda: current_page.set(0), dependencies=filter_dependencies)
    filtered_df = solara.use_memo(
        lambda: filter_selection_data(
            df_all,
            firm_query=search_firm.value,
            project_query=search_project.value,
            psb=selected_psb.value,
            beginning_year=selected_beginning_year.value,
            ending_year=selected_ending_year.value,
            firm_role=selected_firm_role.value,
            sort_column=chosen_sort_col.value,
            sort_order=chosen_sort_order.value,
        ),
        dependencies=filter_dependencies,
    )
    display_df = filtered_df[DISPLAY_COLUMNS]
    total_records = len(display_df)
    active_count = sum([
        selected_psb.value != ALL,
        selected_beginning_year.value != ALL or selected_ending_year.value != ALL,
        selected_firm_role.value != "Selected Firm",
    ])
    filter_summary = "More Filters" + (f" ({active_count} active)" if active_count else "")

    solara.Style(APP_CSS)
    solara.Style(_OPENDOT_STYLE)
    with solara.Column(classes=["opentollselections-app"], gap="12px"):
        with solara.Row(justify="space-between", classes=["opendot-page-heading"], style="align-items: center; flex-wrap: wrap; gap: 16px;"):
            solara.Markdown('# Open Toll Selections\n\nSearch historical Illinois Tollway engineering consultant selections')
            _OpenDOTThemeSwitch.element(dark=selected_theme, on_dark=set_dark_mode)

        with solara.Card(
            "Search Illinois Tollway Consultant Selections",
            classes=["opentollselections-panel"], margin=0,
            style="margin-bottom: 16px; padding: 12px;",
        ):
            solara.Markdown(
                "Search selected firms, proposed subconsultants, project descriptions, or contract numbers.",
                style="margin-bottom: 8px;",
            )
            with solara.Column(classes=["opentollselections-controls"], gap="12px"):
                solara.InputText("Firm Name", value=search_firm)
                solara.InputText("Project Description or Contract Number", value=search_project)

            with solara.ColumnsResponsive(default=12, small=12, medium=[8, 4], gutters_dense=True):
                solara.Markdown(f"**{total_records:,}** matching selection records", style="margin: 8px 0;")
                solara.Button(label="Clear Filters", on_click=clear_filters)

            with solara.Details(summary=filter_summary, expand=False):
                solara.Markdown(
                    "Year ranges include both endpoints; All leaves an endpoint open. "
                    "Choose Any Firm Role to search both selected firms and proposed subconsultants.",
                    style="margin-bottom: 8px;",
                )
                with solara.Column(
                    classes=["opentollselections-controls", "opentollselections-filter-controls"], gap="12px"
                ):
                    solara.Select(label="PSB Number", value=selected_psb, values=available_psbs)
                    solara.Select(label="Beginning Year", value=selected_beginning_year, values=available_years)
                    solara.Select(label="Ending Year", value=selected_ending_year, values=available_years)
                    solara.Select(label="Firm Role", value=selected_firm_role, values=FIRM_ROLES)

                if selected_beginning_year.value != ALL and selected_ending_year.value != ALL:
                    if int(float(selected_beginning_year.value)) > int(float(selected_ending_year.value)):
                        solara.Warning("Beginning Year must be earlier than or equal to Ending Year.")

            with solara.Details(summary="Sort Options", expand=False):
                with solara.Column(classes=["opentollselections-controls"], gap="12px"):
                    solara.Select(label="Sort By", value=chosen_sort_col, values=sort_columns)
                    solara.Select(label="Direction", value=chosen_sort_order, values=sort_orders)

        with solara.Card(
            "Illinois Tollway Consultant Selection Search Results",
            classes=["opentollselections-panel"], margin=0, style="padding: 12px;",
        ):
            solara.Markdown(f"### Found **{total_records:,}** matching selection records.")
            if total_records:
                page_count = (total_records + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
                page_index = max(0, min(current_page.value, page_count - 1))
                with solara.Row(style="align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 12px;"):
                    export_df = display_df.copy()
                    export_df[DATE_COLUMN] = export_df[DATE_COLUMN].dt.strftime("%m/%d/%Y")
                    solara.FileDownload(
                        data=export_df.to_csv(index=False),
                        filename="filtered_tollway_selection_results.csv",
                        label="📥 Download as CSV", mime_type="text/csv",
                    )
                    _OpenDOTPagination.element(
                        page=page_index + 1, page_count=page_count,
                        on_page=lambda page: current_page.set(page - 1),
                    )


            if total_records:
                max_page = (total_records - 1) // ITEMS_PER_PAGE
                page_index = max(0, min(current_page.value, max_page))
                start = page_index * ITEMS_PER_PAGE
                SelectionTable.element(
                    table_html=render_results_table(display_df.iloc[start:start + ITEMS_PER_PAGE]),
                    dark=dark_mode,
                )
            else:
                solara.Info("No records match these searches and filters. Try fewer filters or Clear Filters.")

