import os
import re
import datetime as dt
from html import escape
from urllib.parse import urlsplit
import pandas as pd
import solara
import solara.lab  # Required for lab components like InputDate


# ==========================================
# STEP 1: DEFINE YOUR DATA BACKEND (PARQUET)
# ==========================================
@solara.memoize
def load_bid_data():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "data", "idot_bids.parquet")

    df = pd.read_parquet(file_path)

    df['Pay Item #'] = df['Pay Item #'].astype(str).str.strip()
    df['County'] = df['County'].astype(str).str.strip()
    df['Dist'] = df['Dist'].astype(str).str.strip()

    # Strip out trailing timestamps from the raw data safely
    if "Date" in df.columns:
        df["Date"] = df["Date"].astype(str).str.split(" ").str.get(0).str.strip()

    df = df.set_index('Pay Item #')
    return df


df_all = load_bid_data()

# ==========================================
# STEP 2: SET UP REACTIVE FILTERS
# ==========================================
available_counties = ["All"] + sorted(df_all["County"].dropna().unique().tolist())
available_districts = ["Any"] + sorted(df_all["Dist"].dropna().unique().tolist())
awarded_options = ["Any", "Yes", "No"]

sort_columns = [
    'Pay Item #', 'Pay Item Description', 'Unit', 'Quantity', 'Bid Unit Price',
    'Contract', 'AWARDED', 'County', 'SOURCE FILE', 'Date'
]
sort_orders = ["Ascending", "Descending"]

search_pay_item = solara.reactive("")
search_contract = solara.reactive("")
selected_county = solara.reactive("All")
selected_district = solara.reactive("Any")
selected_awarded = solara.reactive("Any")
min_quantity = solara.reactive(None)
max_quantity = solara.reactive(None)
start_date = solara.reactive(None)
end_date = solara.reactive(None)

chosen_sort_col = solara.reactive("Pay Item #")
chosen_sort_order = solara.reactive("Ascending")

# PERFORMANCE ADDITION: Current active page state
current_page = solara.reactive(0)
ITEMS_PER_PAGE = 25


def clear_filters():
    """Reset all searches, filters, sorting, and pagination."""
    search_pay_item.set("")
    search_contract.set("")
    selected_county.set("All")
    selected_district.set("Any")
    selected_awarded.set("Any")
    min_quantity.set(None)
    max_quantity.set(None)
    start_date.set(None)
    end_date.set(None)
    chosen_sort_col.set("Pay Item #")
    chosen_sort_order.set("Ascending")
    current_page.set(0)


def set_dark_mode(enabled):
    """Apply Solara's native theme to this visitor's app session."""
    solara.lab.theme.dark = bool(enabled)


DISPLAY_HEADERS = {
    "Dist": "District",
    "AWARDED": "Awarded",
    "SOURCE FILE": "Source File",
    "Date": "Letting Date",
    "FOLDER": "Folder",
    "Eplan_Link": "E-Plans",
    "Unit Price Bid": "Bid Unit Price",
}
PRICE_COLUMNS = {"Unit Price Bid", "Award Unit Price"}
NUMERIC_COLUMNS = {"Quantity"} | PRICE_COLUMNS
CENTER_COLUMNS = {"Unit", "Dist", "AWARDED"}


def render_results_table(page_df):
    """One header per column, including Pay Item #, with matching cell alignment."""
    frame = page_df.reset_index()
    columns = frame.columns.tolist()

    def column_class(column):
        if column in NUMERIC_COLUMNS:
            return "bid-number"
        if column in CENTER_COLUMNS:
            return "bid-center"
        if column == "Pay Item Description":
            return "bid-description"
        return "bid-text"

    headers = "".join(
        f'<th scope="col" class="{column_class(column)}">'
        f'{escape(DISPLAY_HEADERS.get(column, str(column)))}</th>'
        for column in columns
    )
    rows = []
    for values in frame.itertuples(index=False, name=None):
        cells = []
        for column, value in zip(columns, values):
            text = "" if pd.isna(value) else str(value)
            content = escape(text)
            if column in PRICE_COLUMNS and text:
                price = pd.to_numeric(value, errors="coerce")
                if pd.notna(price):
                    content = f"${price:,.2f}"
            elif column == "Eplan_Link":
                url = text.strip()
                parsed = urlsplit(url)
                if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
                    content = (
                        f'<a href="{escape(url, quote=True)}" target="_blank" '
                        'rel="noopener noreferrer">Go to E-Plans</a>'
                    )
                else:
                    content = "No Link"
            cells.append(f'<td class="{column_class(column)}">{content}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<table class="solara-custom-html-table" aria-label="IDOT bid item search results">'
        f'<thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


# ==========================================
# STEP 3: WRITE THE INTERFACE
# ==========================================
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


def filter_bid_data(frame, search_pay_item, search_contract, selected_county, selected_district, selected_awarded, min_quantity, max_quantity, start_date, end_date, chosen_sort_col, chosen_sort_order):
    filtered_df = frame

    # Apply reactive structural criteria
    if selected_county != "All":
        filtered_df = filtered_df[filtered_df["County"] == selected_county]

    if selected_district != "Any":
        filtered_df = filtered_df[filtered_df["Dist"] == selected_district]

    # Map human-readable "Yes"/"No" down to the required "Y"/"N" database flags
    if selected_awarded != "Any":
        db_flag = "Y" if selected_awarded == "Yes" else "N"
        filtered_df = filtered_df[filtered_df["AWARDED"].str.upper() == db_flag]

    # Apply Quantity Boundary Filtering
    if min_quantity is not None or max_quantity is not None:
        numeric_qty = pd.to_numeric(filtered_df["Quantity"], errors="coerce")
        if min_quantity is not None:
            filtered_df = filtered_df[numeric_qty >= min_quantity]
            numeric_qty = pd.to_numeric(filtered_df["Quantity"], errors="coerce")
        if max_quantity is not None:
            filtered_df = filtered_df[numeric_qty <= max_quantity]

    # Apply Letting Date Boundary Filtering
    if start_date is not None or end_date is not None:
        datetime_col = pd.to_datetime(filtered_df["Date"], errors="coerce")

        if start_date is not None:
            pd_start = pd.Timestamp(start_date)
            filtered_df = filtered_df[datetime_col >= pd_start]
            datetime_col = pd.to_datetime(filtered_df["Date"], errors="coerce")

        if end_date is not None:
            pd_end = pd.Timestamp(end_date)
            filtered_df = filtered_df[datetime_col <= pd_end]

    if search_pay_item.strip():
        query_text = search_pay_item.strip()
        match_index = filtered_df.index.str.contains(query_text, case=False, na=False)
        match_desc = pd.Series(True, index=filtered_df.index)
        for word in query_text.split():
            match_desc &= filtered_df["Pay Item Description"].str.contains(
                word, case=False, na=False, regex=False)
        filtered_df = filtered_df[match_index | match_desc]

    if search_contract:
        filtered_df = filtered_df[filtered_df["Contract"].str.contains(search_contract, case=False, na=False)]

    # ---- CORE DATA SORTING ENGINE ----
    is_ascending = chosen_sort_order == "Ascending"

    if chosen_sort_col == "Pay Item #":
        filtered_df = filtered_df.sort_index(ascending=is_ascending)
    elif chosen_sort_col == "Quantity":
        filtered_df = filtered_df.iloc[
            pd.to_numeric(filtered_df["Quantity"], errors="coerce").argsort(kind='mergesort')]
        if not is_ascending:
            filtered_df = filtered_df.iloc[::-1]
    elif chosen_sort_col == "Bid Unit Price":
        # UI label differs from the Parquet column; always sort numerically.
        filtered_df = (
            filtered_df.assign(
                __bid_price_sort=pd.to_numeric(
                    filtered_df["Unit Price Bid"], errors="coerce"
                )
            )
            .sort_values(
                "__bid_price_sort", ascending=is_ascending,
                na_position="last", kind="mergesort"
            )
            .drop(columns=["__bid_price_sort"])
        )
    else:
        filtered_df = filtered_df.sort_values(by=chosen_sort_col, ascending=is_ascending, na_position='last')

    return filtered_df


@solara.component
def Page():
    solara.use_effect(_opendot_configure_theme, [])
    selected_theme = solara.use_trait_observe(solara.lab.theme, "dark")
    effective_dark = solara.lab.use_dark_effective()
    dark_mode = bool(effective_dark if selected_theme is None else selected_theme)

    # OpenDOT browser title
    with solara.Head():
        solara.Title(
            "OpenDOT Bids | Illinois Highway Construction Bid Data"
        )

    # Reset page index to 0 whenever search queries or filters alter dataset bounds
    # This prevents pagination indexing ghost crashes
    solara.use_memo(
        lambda: current_page.set(0),
        dependencies=[search_pay_item.value, search_contract.value, selected_county.value,
                      selected_district.value, selected_awarded.value, min_quantity.value,
                      max_quantity.value, start_date.value, end_date.value, chosen_sort_col.value,
                      chosen_sort_order.value]
    )

    criteria = [search_pay_item.value, search_contract.value, selected_county.value, selected_district.value, selected_awarded.value, min_quantity.value, max_quantity.value, start_date.value, end_date.value, chosen_sort_col.value, chosen_sort_order.value]
    filtered_df = solara.use_memo(
        lambda: filter_bid_data(df_all, *criteria), dependencies=criteria
    )

    results_display_df = solara.use_memo(
        lambda: filtered_df.drop(columns=["Item"], errors="ignore"), dependencies=criteria
    )
    total_records = len(filtered_df)
    active_filter_count = sum([
        selected_county.value != "All",
        selected_district.value != "Any",
        selected_awarded.value != "Any",
        min_quantity.value is not None,
        max_quantity.value is not None,
        start_date.value is not None,
        end_date.value is not None,
    ])
    filter_summary = "More Filters"
    if active_filter_count:
        filter_summary += f" ({active_filter_count} active)"

    # Keep the search controls within the viewport even when the table is wide.
    solara.Style("""
        .openbidz-app {
            width: 100%;
            max-width: 100%;
            min-width: 0;
            box-sizing: border-box;
            container-type: inline-size;
            container-name: openbidz;
        }
        .openbidz-panel {
            width: 100%;
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .openbidz-panel .v-card__text {
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .openbidz-app .openbidz-controls {
            display: grid !important;
            grid-template-columns: minmax(0, 1fr);
            gap: 12px;
            width: 100%;
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .openbidz-controls > * {
            min-width: 0;
            max-width: 100%;
        }
        @container openbidz (min-width: 900px) {
            .openbidz-app .openbidz-controls {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @container openbidz (min-width: 1200px) {
            .openbidz-app .openbidz-filter-controls {
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }
        }
        .openbidz-panel .v-expansion-panel-header {
            min-height: 48px;
        }
        .openbidz-panel .v-expansion-panel-content__wrap {
            padding: 0 12px 12px;
        }
        .openbidz-results-scroll {
            display: block;
            width: 100%;
            max-width: 100%;
            min-width: 0;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            --bid-surface: #ffffff;
            --bid-header: #eef3f8;
            --bid-text: #1d2835;
            --bid-border: #c7d0dc;
            --bid-stripe: #f5f7fa;
            --bid-hover: #e6eff8;
            --bid-link: #135385;
            border: 1px solid var(--bid-border);
            border-radius: 8px;
            background: var(--bid-surface);
        }
        .openbidz-results-scroll.openbidz-dark-table {
            --bid-surface: #192433;
            --bid-header: #223247;
            --bid-text: #e7edf5;
            --bid-border: #495b70;
            --bid-stripe: #1d2b3d;
            --bid-hover: #2a4058;
            --bid-link: #8bc9ff;
        }
        .solara-custom-html-table {
            width: 100%;
            border-collapse: collapse;
            font-family: inherit;
            font-size: 14px;
            color: var(--bid-text);
            background: var(--bid-surface);
        }
        .solara-custom-html-table th,
        .solara-custom-html-table td {
            padding: 12px 14px;
            text-align: left;
            vertical-align: top;
            line-height: 1.5;
            border-bottom: 1px solid var(--bid-border);
        }
        .solara-custom-html-table thead th {
            background: var(--bid-header);
            color: var(--bid-text);
            font-weight: 700;
            vertical-align: middle;
            white-space: nowrap;
            border-bottom: 2px solid var(--bid-border);
        }
        .solara-custom-html-table .bid-number {
            text-align: right;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }
        .solara-custom-html-table .bid-center {
            text-align: center;
            white-space: nowrap;
        }
        .solara-custom-html-table .bid-text {
            white-space: nowrap;
        }
        .solara-custom-html-table .bid-description {
            min-width: 250px;
            max-width: 360px;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .solara-custom-html-table tbody tr:nth-child(even) {
            background: var(--bid-stripe);
        }
        .solara-custom-html-table tbody tr:hover {
            background: var(--bid-hover);
        }
        .solara-custom-html-table tbody tr:last-child td {
            border-bottom: 0;
        }
        .solara-custom-html-table a {
            color: var(--bid-link);
            font-weight: 600;
            text-decoration: underline;
        }
        @media (max-width: 599px) {
            .openbidz-panel {
                padding: 4px !important;
            }
            .openbidz-panel .v-card__title {
                font-size: 1.15rem;
                line-height: 1.4;
                overflow-wrap: anywhere;
            }
            .openbidz-panel .v-card__text {
                padding: 12px;
            }
            .openbidz-panel .v-btn {
                min-height: 44px;
            }
        }
    """)

    solara.Style(_OPENDOT_STYLE)
    with solara.Column(classes=["openbidz-app"], gap="12px"):
        with solara.Row(justify="space-between", classes=["opendot-page-heading"], style="align-items: center; flex-wrap: wrap; gap: 16px;"):
            with solara.Column(gap="2px", style="flex: 1 1 auto; min-width: 0;"):
                solara.HTML(tag="div", classes=["opendot-brand"], unsafe_innerHTML='<a href="https://open-dot.org/" style="color:rgb(var(--v-theme-secondary));font-size:.85rem;font-weight:600;letter-spacing:.02em;text-decoration:none">OpenDOT</a>')
                solara.Markdown('# Open Bids\n\nSearch historical IDOT bid items and contract records')
            _OpenDOTThemeSwitch.element(dark=selected_theme, on_dark=set_dark_mode)

        # ---- COMPACT RESPONSIVE SEARCH PANEL ----
        with solara.Card(
            "Search IDOT Bid Items",
            classes=["openbidz-panel"], margin=0,
            style="margin-bottom: 16px; padding: 12px;",
        ):
            solara.Markdown(
                "Search by pay item, description, or contract number.",
                style="margin-bottom: 8px;",
            )
            with solara.Column(classes=["openbidz-controls"], gap="12px"):
                solara.InputText("Pay Item # or Description", value=search_pay_item)
                solara.InputText("Contract Number", value=search_contract)

            with solara.ColumnsResponsive(default=12, small=12, medium=[8, 4], gutters_dense=True):
                solara.Markdown(
                    f"**{total_records:,}** matching bid item records",
                    style="margin: 8px 0;",
                )
                solara.Button(label="Clear Filters", on_click=clear_filters)

            # Additional filters and sorting start collapsed.
            with solara.Details(summary=filter_summary, expand=False):
                with solara.Column(classes=["openbidz-controls", "openbidz-filter-controls"], gap="12px"):
                    solara.Select(label="County", value=selected_county, values=available_counties)
                    solara.Select(label="District", value=selected_district, values=available_districts)
                    solara.Select(label="Awarded", value=selected_awarded, values=awarded_options)
                    solara.InputFloat(label="Min Quantity", value=min_quantity)
                    solara.InputFloat(label="Max Quantity", value=max_quantity)
                    solara.lab.InputDate(label="Start Letting Date", value=start_date, clearable=True)
                    solara.lab.InputDate(label="End Letting Date", value=end_date, clearable=True)

            with solara.Details(summary="Sort Options", expand=False):
                with solara.Column(classes=["openbidz-controls"], gap="12px"):
                    solara.Select(label="Sort By", value=chosen_sort_col, values=sort_columns)
                    solara.Select(label="Direction", value=chosen_sort_order, values=sort_orders)

        # ---- MAIN DATAFRAME RESULTS PANEL ----
        with solara.Card(
            "IDOT Bid Items Search Results",
            classes=["openbidz-panel"], margin=0,
            style="padding: 12px;",
        ):
            # Prepare a clean display DataFrame (drop the unused "Item" column)
            display_df = results_display_df

            # ---- DYNAMIC CSV FILE DOWNLOAD COMPONENT ----
            solara.Markdown(f"### Found **{total_records:,}** matching bid item records.")
            if total_records:
                page_count = (total_records + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
                page_index = max(0, min(current_page.value, page_count - 1))
                with solara.Row(style="align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 12px;"):
                    solara.FileDownload(
                        data=lambda: display_df.to_csv(index=True),
                        filename="filtered_bid_results.csv",
                        label="📥 Download as CSV",
                        mime_type="text/csv"
                    )
                    _OpenDOTPagination.element(
                        page=page_index + 1, page_count=page_count,
                        on_page=lambda page: current_page.set(page - 1),
                    )

            # Render formatted grid or error state
            if total_records > 0:
                start_idx = page_index * ITEMS_PER_PAGE
                end_idx = start_idx + ITEMS_PER_PAGE
                sliced_df = display_df.iloc[start_idx:end_idx].copy()

                html_table = render_results_table(sliced_df)
                table_classes = ["openbidz-results-scroll"]
                if dark_mode:
                    table_classes.append("openbidz-dark-table")
                solara.HTML(
                    tag="div",
                    classes=table_classes,
                    unsafe_innerHTML=html_table,
                    attributes={"tabindex": "0", "aria-label": "Scroll bid item results horizontally"},
                )

            else:
                # FIXED INDENTATION: Aligned correctly under the main total_records block check
                solara.Error("No records found matching current filtering combinations.")
