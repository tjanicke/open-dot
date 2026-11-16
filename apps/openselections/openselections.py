"""OpenSelections: IDOT consultant-selection search.

Place ptb_selection_data.parquet beside this file, then run:
    solara run openselections.py --host 127.0.0.1 --port 8766

Dependencies: solara, pandas, pyarrow (same as OpenBidz).
"""
from pathlib import Path
from html import escape

import pandas as pd
import solara
import solara.lab
import ipyvuetify as vuetify
import traitlets


DATA_FILENAME = "data/ptb_selection_data.parquet"
ITEMS_PER_PAGE = 25
ALL = "All"
FIRM_COLUMNS = [
    "Selected Firm", "Proposed Subconsultants", "First Alternate", "Second Alternate",
]
FIRM_ROLES = ["Selected Firm", "Any Firm Role"] + FIRM_COLUMNS[1:]
NUMERIC_COLUMNS = {
    "PTB Number", "Item Number", "PTB Bulletin Year", "Firms Submitted", "Firms Eligible",
}
# Keep the project beside its selected firm; all source columns remain available.
DISPLAY_COLUMNS = [
    "PTB Number", "Item Number", "PTB Bulletin Year", "Job Number",
    "Selected Firm", "Project Description", "District", "County",
    "Proposed Subconsultants", "First Alternate", "Second Alternate",
    "Firms Submitted", "Firms Eligible", "Source File",
]
DISPLAY_HEADERS = {
    "PTB Number": "PTB #",
    "Item Number": "Item #",
    "PTB Bulletin Year": "Bulletin Year",
}


@solara.memoize
def load_selection_data():
    frame = pd.read_parquet(Path(__file__).resolve().parent / DATA_FILENAME)
    # The supplied file has a trailing space in "District ".
    frame.columns = frame.columns.str.strip()
    missing = set(DISPLAY_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError("Missing required selection columns: " + ", ".join(sorted(missing)))
    for column in frame.columns:
        if pd.api.types.is_object_dtype(frame[column]) or pd.api.types.is_string_dtype(frame[column]):
            frame[column] = frame[column].astype("string").str.strip().replace("", pd.NA)
    return frame


df_all = load_selection_data()


def filter_options(column, *, numeric=False, descending=False):
    values = df_all[column].dropna().astype(str).unique().tolist()
    if numeric:
        values.sort(key=lambda value: (float(value), value), reverse=descending)
    else:
        values.sort(key=str.casefold)
    return [ALL] + values


available_counties = filter_options("County")
available_districts = filter_options("District")
available_ptbs = filter_options("PTB Number", numeric=True, descending=True)
available_years = filter_options("PTB Bulletin Year", numeric=True)
sort_columns = DISPLAY_COLUMNS
sort_orders = ["Ascending", "Descending"]

search_firm = solara.reactive("")
search_project = solara.reactive("")
selected_county = solara.reactive(ALL)
selected_district = solara.reactive(ALL)
selected_ptb = solara.reactive(ALL)
selected_beginning_year = solara.reactive(ALL)
selected_ending_year = solara.reactive(ALL)
selected_firm_role = solara.reactive("Selected Firm")
chosen_sort_col = solara.reactive("PTB Number")
chosen_sort_order = solara.reactive("Descending")
current_page = solara.reactive(0)


def clear_filters():
    search_firm.set("")
    search_project.set("")
    selected_county.set(ALL)
    selected_district.set(ALL)
    selected_ptb.set(ALL)
    selected_beginning_year.set(ALL)
    selected_ending_year.set(ALL)
    selected_firm_role.set("Selected Firm")
    chosen_sort_col.set("PTB Number")
    chosen_sort_order.set("Descending")
    current_page.set(0)


def set_dark_mode(enabled):
    solara.lab.theme.dark = bool(enabled)


def filter_selection_data(
    frame, *, firm_query="", project_query="", county=ALL, district=ALL,
    ptb=ALL, beginning_year=ALL, ending_year=ALL, firm_role="Selected Firm",
    sort_column="PTB Number", sort_order="Descending",
):
    """Filter literal, case-insensitive searches and sort numbers numerically."""
    result = frame
    for column, value in [
        ("County", county), ("District", district), ("PTB Number", ptb),
    ]:
        if value != ALL:
            result = result[result[column] == value]

    # Include both endpoints; All leaves that side of the range unrestricted.
    if beginning_year != ALL or ending_year != ALL:
        years = pd.to_numeric(result["PTB Bulletin Year"], errors="coerce")
        keep = pd.Series(True, index=result.index)
        if beginning_year != ALL:
            keep &= years >= int(beginning_year)
        if ending_year != ALL:
            keep &= years <= int(ending_year)
        result = result[keep]

    if firm_query.strip():
        columns = FIRM_COLUMNS if firm_role == "Any Firm Role" else [firm_role]
        # Each keyword must appear within the same firm's role field.
        role_matches = pd.Series(False, index=result.index)
        for column in columns:
            field_match = pd.Series(True, index=result.index)
            for keyword in firm_query.split():
                field_match &= result[column].str.contains(keyword, case=False, regex=False, na=False)
            role_matches |= field_match
        result = result[role_matches]

    if project_query.strip():
        query = project_query.strip()
        job_match = result["Job Number"].str.contains(query, case=False, regex=False, na=False)
        description_match = pd.Series(True, index=result.index)
        for keyword in query.split():
            description_match &= result["Project Description"].str.contains(
                keyword, case=False, regex=False, na=False,
            )
        result = result[job_match | description_match]

    ascending = sort_order == "Ascending"
    columns, directions = [sort_column], [ascending]
    for column, direction in [("PTB Number", False), ("Item Number", True)]:
        if column not in columns:
            columns.append(column)
            directions.append(direction)

    def sort_key(series):
        if series.name in NUMERIC_COLUMNS:
            return pd.to_numeric(series, errors="coerce")
        return series.astype("string").str.casefold()

    return result.sort_values(
        by=columns, ascending=directions, key=sort_key, na_position="last", kind="stable",
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
        if column in {"County", "District"}:
            return "selection-region"
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
            text = "" if pd.isna(value) else str(value)
            cells.append(f'<td class="{column_class(column)}">{escape(text)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<table class="openselections-table" aria-label="IDOT consultant selection search results">'
        f'<thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


# Same responsive spacing, header alignment, row shading, and theme as OpenBidz.
APP_CSS = """
        .openselections-app {
            width: 100%;
            max-width: 100%;
            min-width: 0;
            box-sizing: border-box;
            container-type: inline-size;
            container-name: openselections;
        }
        .openselections-panel {
            width: 100%;
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .openselections-panel .v-card__text {
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .openselections-app .openselections-controls {
            display: grid !important;
            grid-template-columns: minmax(0, 1fr);
            gap: 12px;
            width: 100%;
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .openselections-controls > * {
            min-width: 0;
            max-width: 100%;
        }
        @container openselections (min-width: 900px) {
            .openselections-app .openselections-controls {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @container openselections (min-width: 1200px) {
            .openselections-app .openselections-filter-controls {
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }
        }
        .openselections-panel .v-expansion-panel-header {
            min-height: 48px;
        }
        .openselections-panel .v-expansion-panel-content__wrap {
            padding: 0 12px 12px;
        }
        .openselections-table-frame {
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
        .openselections-table-frame.openselections-dark-table {
            --selection-surface: #192433;
            --selection-header: #223247;
            --selection-text: #e7edf5;
            --selection-border: #495b70;
            --selection-stripe: #1d2b3d;
            --selection-hover: #2a4058;
            --selection-link: #8bc9ff;
        }
        .openselections-results-scroll,
        .openselections-top-scroll {
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
        .openselections-top-scroll {
            height: 20px;
            margin-bottom: 8px;
        }
        .openselections-table-frame ::-webkit-scrollbar {
            height: 14px;
        }
        .openselections-table-frame ::-webkit-scrollbar-track {
            background: var(--selection-header);
        }
        .openselections-table-frame ::-webkit-scrollbar-thumb {
            background: #8493a5;
            border: 3px solid var(--selection-header);
            border-radius: 7px;
        }
        .openselections-scroll-hint {
            margin: 0 0 6px;
            font-size: 13px;
            color: var(--selection-text);
        }
        .openselections-table {
            width: 100%;
            border-collapse: collapse;
            font-family: inherit;
            font-size: 14px;
            color: var(--selection-text);
            background: var(--selection-surface);
        }
        .openselections-table th,
        .openselections-table td {
            padding: 12px 14px;
            text-align: left;
            vertical-align: top;
            line-height: 1.5;
            border-bottom: 1px solid var(--selection-border);
        }
        .openselections-table thead th {
            background: var(--selection-header);
            color: var(--selection-text);
            font-weight: 700;
            vertical-align: middle;
            white-space: nowrap;
            border-bottom: 2px solid var(--selection-border);
        }
        .openselections-table .selection-number {
            text-align: right;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }
        .openselections-table .selection-center {
            text-align: center;
            white-space: nowrap;
        }
        .openselections-table .selection-text {
            white-space: nowrap;
        }
        .openselections-table .selection-description {
            min-width: 250px;
            max-width: 360px;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .openselections-table tbody tr:nth-child(even) {
            background: var(--selection-stripe);
        }
        .openselections-table tbody tr:hover {
            background: var(--selection-hover);
        }
        .openselections-table tbody tr:last-child td {
            border-bottom: 0;
        }
        .openselections-table a {
            color: var(--selection-link);
            font-weight: 600;
            text-decoration: underline;
        }
        @media (max-width: 599px) {
            .openselections-panel {
                padding: 4px !important;
            }
            .openselections-panel .v-card__title {
                font-size: 1.15rem;
                line-height: 1.4;
                overflow-wrap: anywhere;
            }
            .openselections-panel .v-card__text {
                padding: 12px;
            }
            .openselections-panel .v-btn {
                min-height: 44px;
            }
        }
    
        .openselections-table .selection-firm {
            min-width: 200px;
            max-width: 300px;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .openselections-table .selection-longtext {
            min-width: 260px;
            max-width: 380px;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .openselections-table .selection-region {
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
          <div class="openselections-table-frame"
               :class="{ 'openselections-dark-table': dark }">
            <p v-show="hasOverflow" class="openselections-scroll-hint">
              Scroll sideways to view all columns.
            </p>
            <div v-show="hasOverflow" ref="top"
                 class="openselections-top-scroll" tabindex="0"
                 role="region" aria-label="Horizontal table scrollbar"
                 @scroll="scrollFromTop">
              <div ref="spacer" style="height: 1px;"></div>
            </div>
            <div ref="bottom" class="openselections-results-scroll" tabindex="0"
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
    solara.Title("OpenDOT Selections | IDOT Engineering Consultant Selections")
    solara.use_effect(_opendot_configure_theme, [])
    selected_theme = solara.use_trait_observe(solara.lab.theme, "dark")
    effective_dark = solara.lab.use_dark_effective()
    dark_mode = bool(effective_dark if selected_theme is None else selected_theme)

    filter_dependencies = [
        search_firm.value, search_project.value, selected_county.value,
        selected_district.value, selected_ptb.value,
        selected_beginning_year.value, selected_ending_year.value,
        selected_firm_role.value, chosen_sort_col.value, chosen_sort_order.value,
    ]
    solara.use_memo(lambda: current_page.set(0), dependencies=filter_dependencies)
    filtered_df = solara.use_memo(
        lambda: filter_selection_data(
            df_all, firm_query=search_firm.value, project_query=search_project.value,
            county=selected_county.value, district=selected_district.value,
            ptb=selected_ptb.value,
            beginning_year=selected_beginning_year.value, ending_year=selected_ending_year.value,
            firm_role=selected_firm_role.value, sort_column=chosen_sort_col.value,
            sort_order=chosen_sort_order.value,
        ),
        dependencies=filter_dependencies,
    )
    display_df = filtered_df[DISPLAY_COLUMNS]
    total_records = len(display_df)
    active_count = sum([
        selected_county.value != ALL, selected_district.value != ALL,
        selected_ptb.value != ALL,
        selected_beginning_year.value != ALL or selected_ending_year.value != ALL,
        selected_firm_role.value != "Selected Firm",
    ])
    filter_summary = "More Filters" + (f" ({active_count} active)" if active_count else "")

    solara.Style(APP_CSS)
    solara.Style(_OPENDOT_STYLE)
    with solara.Column(classes=["openselections-app"], gap="12px"):
        with solara.Row(justify="space-between", classes=["opendot-page-heading"], style="align-items: center; flex-wrap: wrap; gap: 16px;"):
            solara.Markdown('# Open Selections\n\nSearch historical IDOT engineering consultant selections')
            _OpenDOTThemeSwitch.element(dark=selected_theme, on_dark=set_dark_mode)

        with solara.Card(
            "Search IDOT Consultant Selections",
            classes=["openselections-panel"], margin=0,
            style="margin-bottom: 16px; padding: 12px;",
        ):
            solara.Markdown(
                "Search selected firms, project descriptions, or job numbers.",
                style="margin-bottom: 8px;",
            )
            with solara.Column(classes=["openselections-controls"], gap="12px"):
                solara.InputText("Firm Name", value=search_firm)
                solara.InputText("Project Description or Job Number", value=search_project)
            with solara.ColumnsResponsive(default=12, small=12, medium=[8, 4], gutters_dense=True):
                solara.Markdown(f"**{total_records:,}** matching selection records", style="margin: 8px 0;")
                solara.Button(label="Clear Filters", on_click=clear_filters)

            with solara.Details(summary=filter_summary, expand=False):
                solara.Markdown(
                    "Year ranges include both endpoints; All leaves an endpoint open. "
                    "Choose a firm role to search subconsultants or alternates.",
                    style="margin-bottom: 8px;",
                )
                with solara.Column(classes=["openselections-controls", "openselections-filter-controls"], gap="12px"):
                    solara.Select(label="PTB Number", value=selected_ptb, values=available_ptbs)
                    solara.Select(label="Beginning Year", value=selected_beginning_year, values=available_years)
                    solara.Select(label="Ending Year", value=selected_ending_year, values=available_years)
                    solara.Select(label="District / Bureau", value=selected_district, values=available_districts)
                    solara.Select(label="County", value=selected_county, values=available_counties)
                    solara.Select(label="Firm Role", value=selected_firm_role, values=FIRM_ROLES)

                if selected_beginning_year.value != ALL and selected_ending_year.value != ALL:
                    if int(selected_beginning_year.value) > int(selected_ending_year.value):
                        solara.Warning("Beginning Year must be earlier than or equal to Ending Year.")

            with solara.Details(summary="Sort Options", expand=False):
                with solara.Column(classes=["openselections-controls"], gap="12px"):
                    solara.Select(label="Sort By", value=chosen_sort_col, values=sort_columns)
                    solara.Select(label="Direction", value=chosen_sort_order, values=sort_orders)

        with solara.Card(
            "IDOT Consultant Selection Search Results",
            classes=["openselections-panel"], margin=0, style="padding: 12px;",
        ):
            solara.Markdown(f"### Found **{total_records:,}** matching selection records.")
            if total_records:
                page_count = (total_records + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
                page_index = max(0, min(current_page.value, page_count - 1))
                with solara.Row(style="align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 12px;"):
                    solara.FileDownload(
                        data=display_df.to_csv(index=False),
                        filename="filtered_selection_results.csv",
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
