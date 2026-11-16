"""OpenTollz: Illinois Tollway bid-item search, based on OpenBidz.
Run: solara run opentollz.py --host=0.0.0.0 --port=8765
Keep tollway_bids.parquet alongside this file.
"""
import os
from html import escape

import pandas as pd
import solara
import solara.lab

DATA_COLUMNS = [
    "Pay Item #", "Pay Item Description", "Unit", "Quantity", "Contract",
    "Unit Price Bid", "SOURCE FILE", "Date", "Project Description",
]


@solara.memoize
def load_bid_data():
    file_path = os.environ.get("OPENTOLL_DATA_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tollway_bids.parquet"))
    df = pd.read_parquet(file_path)
    missing = [column for column in DATA_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"Tollway data is missing required columns: {', '.join(missing)}")
    original_column = "Pay Item Description Original"
    if original_column not in df:
        df[original_column] = df["Pay Item Description"]
    columns = DATA_COLUMNS + [original_column]
    df = df[columns].copy()
    for column in columns:
        if column not in {"Quantity", "Unit Price Bid", "Date"}:
            df[column] = df[column].fillna("").astype(str).str.strip()
    # Quantity and price arrive as strings; convert once for numeric filtering/sorting.
    for column in ("Quantity", "Unit Price Bid"):
        text = df[column].astype("string").str.replace(",", "", regex=False).str.replace("$", "", regex=False).str.strip()
        df[column] = pd.to_numeric(text, errors="coerce")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.normalize()
    return df.set_index("Pay Item #")


df_all = load_bid_data()
sort_columns = DATA_COLUMNS.copy()
sort_orders = ["Ascending", "Descending"]
search_pay_item = solara.reactive("")
search_contract = solara.reactive("")
search_project_description = solara.reactive("")
min_quantity = solara.reactive(None)
max_quantity = solara.reactive(None)
start_date = solara.reactive(None)
end_date = solara.reactive(None)
chosen_sort_col = solara.reactive("Pay Item #")
chosen_sort_order = solara.reactive("Ascending")
current_page = solara.reactive(0)
ITEMS_PER_PAGE = 25


def clear_filters():
    """Reset all searches, filters, sorting, and pagination."""
    for value in (search_pay_item, search_contract, search_project_description):
        value.set("")
    for value in (min_quantity, max_quantity, start_date, end_date):
        value.set(None)
    chosen_sort_col.set("Pay Item #")
    chosen_sort_order.set("Ascending")
    current_page.set(0)


def set_dark_mode(enabled):
    solara.lab.theme.dark = bool(enabled)


def match_words(values, query):
    """All literal partial words must appear, regardless of order or case."""
    mask = pd.Series(True, index=values.index)
    for word in query.split():
        mask &= values.str.contains(word, case=False, regex=False, na=False)
    return mask


def filter_bid_data(frame, pay_item="", contract="", project_description="",
                    quantity_min=None, quantity_max=None, date_start=None, date_end=None,
                    sort_column="Pay Item #", sort_order="Ascending"):
    """Apply combined filters and stable sorting without modifying the source data."""
    filtered = frame
    if pay_item.strip():
        query = pay_item.strip()
        item_match = filtered.index.str.contains(query, case=False, regex=False, na=False)
        description_match = match_words(filtered["Pay Item Description"], query)
        if "Pay Item Description Original" in filtered:
            description_match |= match_words(filtered["Pay Item Description Original"], query)
        filtered = filtered[item_match | description_match]
    if contract.strip():
        filtered = filtered[filtered["Contract"].str.contains(contract.strip(), case=False, regex=False, na=False)]
    if project_description.strip():
        filtered = filtered[match_words(filtered["Project Description"], project_description.strip())]
    if quantity_min is not None:
        filtered = filtered[filtered["Quantity"] >= quantity_min]
    if quantity_max is not None:
        filtered = filtered[filtered["Quantity"] <= quantity_max]
    if date_start is not None:
        filtered = filtered[filtered["Date"] >= pd.Timestamp(date_start).normalize()]
    if date_end is not None:
        filtered = filtered[filtered["Date"] <= pd.Timestamp(date_end).normalize()]
    ascending = sort_order == "Ascending"
    if sort_column == "Pay Item #":
        return filtered.sort_index(ascending=ascending, kind="mergesort")
    return filtered.sort_values(sort_column, ascending=ascending, kind="mergesort", na_position="last")


DISPLAY_HEADERS = {
    "SOURCE FILE": "Source File",
    "Date": "Letting Date",
    "Unit Price Bid": "Bid Unit Price",
}
PRICE_COLUMNS = {"Unit Price Bid"}
NUMERIC_COLUMNS = {"Quantity"} | PRICE_COLUMNS
CENTER_COLUMNS = {"Unit"}


def render_results_table(page_df):
    """One header per column, including Pay Item #, with matching cell alignment."""
    frame = page_df.reset_index()[DATA_COLUMNS]
    columns = frame.columns.tolist()

    def column_class(column):
        if column in NUMERIC_COLUMNS:
            return "bid-number"
        if column in CENTER_COLUMNS:
            return "bid-center"
        if column in {"Pay Item Description", "Project Description"}:
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
            if column == "Date" and text:
                content = escape(pd.Timestamp(value).strftime("%Y-%m-%d"))
            elif column in PRICE_COLUMNS and text:
                price = pd.to_numeric(value, errors="coerce")
                if pd.notna(price):
                    content = f"${price:,.2f}"
            cells.append(f'<td class="{column_class(column)}">{content}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<table class="solara-custom-html-table" aria-label="Illinois Tollway bid item search results">'
        f'<thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


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
    solara.Title("OpenDOT Tolls | Illinois Tollway Construction Bid Items")
    solara.use_effect(_opendot_configure_theme, [])
    selected_theme = solara.use_trait_observe(solara.lab.theme, "dark")
    effective_dark = solara.lab.use_dark_effective()
    dark_mode = bool(effective_dark if selected_theme is None else selected_theme)
    criteria = [
        search_pay_item.value, search_contract.value, search_project_description.value,
        min_quantity.value, max_quantity.value, start_date.value, end_date.value,
        chosen_sort_col.value, chosen_sort_order.value,
    ]
    solara.use_memo(lambda: current_page.set(0), dependencies=criteria)
    filtered_df = solara.use_memo(lambda: filter_bid_data(df_all, *criteria), dependencies=criteria)
    total_records = len(filtered_df)
    active_filter_count = sum(value is not None for value in criteria[3:7])
    filter_summary = "More Filters"
    if active_filter_count:
        filter_summary += f" ({active_filter_count} active)"

    # Keep the search controls within the viewport even when the table is wide.
    solara.Style("""
        .opentollz-app {
            width: 100%;
            max-width: 100%;
            min-width: 0;
            box-sizing: border-box;
            container-type: inline-size;
            container-name: opentollz;
        }
        .opentollz-panel {
            width: 100%;
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .opentollz-panel .v-card__text {
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .opentollz-app .opentollz-controls {
            display: grid !important;
            grid-template-columns: minmax(0, 1fr);
            gap: 12px;
            width: 100%;
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
        }
        .opentollz-controls > * {
            min-width: 0;
            max-width: 100%;
        }
        @container opentollz (min-width: 900px) {
            .opentollz-app .opentollz-controls {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @container opentollz (min-width: 1200px) {
            .opentollz-app .opentollz-filter-controls {
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }
        }
        .opentollz-panel .v-expansion-panel-header {
            min-height: 48px;
        }
        .opentollz-panel .v-expansion-panel-content__wrap {
            padding: 0 12px 12px;
        }
        .opentollz-results-scroll {
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
        .opentollz-results-scroll.opentollz-dark-table {
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
            .opentollz-panel {
                padding: 4px !important;
            }
            .opentollz-panel .v-card__title {
                font-size: 1.15rem;
                line-height: 1.4;
                overflow-wrap: anywhere;
            }
            .opentollz-panel .v-card__text {
                padding: 12px;
            }
            .opentollz-panel .v-btn {
                min-height: 44px;
            }
        }
    """)

    solara.Style(_OPENDOT_STYLE)
    with solara.Column(classes=["opentollz-app"], gap="12px"):
        with solara.Row(justify="space-between", classes=["opendot-page-heading"], style="align-items: center; flex-wrap: wrap; gap: 16px;"):
            solara.Markdown('# Open Tolls\n\nSearch historical Illinois Tollway bid items and contract records')
            _OpenDOTThemeSwitch.element(dark=selected_theme, on_dark=set_dark_mode)

        # ---- COMPACT RESPONSIVE SEARCH PANEL ----
        with solara.Card(
            "Search Illinois Tollway Bid Items",
            classes=["opentollz-panel"], margin=0,
            style="margin-bottom: 16px; padding: 12px;",
        ):
            solara.Markdown(
                "Search by pay item, description, contract number, or project description.",
                style="margin-bottom: 8px;",
            )
            with solara.Column(classes=["opentollz-controls"], gap="12px"):
                solara.InputText("Pay Item # or Description", value=search_pay_item)
                solara.InputText("Contract Number", value=search_contract)
                solara.InputText(
                    "Project Description", value=search_project_description,
                    message="Partial words, any order; all words must match. Press Enter or leave the field to search.",
                )

            with solara.ColumnsResponsive(default=12, small=12, medium=[8, 4], gutters_dense=True):
                solara.Markdown(
                    f"**{total_records:,}** matching bid item records",
                    style="margin: 8px 0;",
                )
                solara.Button(label="Clear Filters", on_click=clear_filters)

            # Additional filters and sorting start collapsed.
            with solara.Details(summary=filter_summary, expand=False):
                with solara.Column(classes=["opentollz-controls", "opentollz-filter-controls"], gap="12px"):
                    solara.InputFloat(label="Min Quantity", value=min_quantity, optional=True, clearable=True)
                    solara.InputFloat(label="Max Quantity", value=max_quantity, optional=True, clearable=True)
                    solara.lab.InputDate(label="Start Letting Date", value=start_date, optional=True, clearable=True)
                    solara.lab.InputDate(label="End Letting Date", value=end_date, optional=True, clearable=True)

            with solara.Details(summary="Sort Options", expand=False):
                with solara.Column(classes=["opentollz-controls"], gap="12px"):
                    solara.Select(label="Sort By", value=chosen_sort_col, values=sort_columns)
                    solara.Select(label="Direction", value=chosen_sort_order, values=sort_orders)

        # ---- MAIN DATAFRAME RESULTS PANEL ----
        with solara.Card(
            "Illinois Tollway Bid Items Search Results",
            classes=["opentollz-panel"], margin=0,
            style="padding: 12px;",
        ):
            display_df = filtered_df

            # ---- DYNAMIC CSV FILE DOWNLOAD COMPONENT ----
            solara.Markdown(f"### Found **{total_records:,}** matching bid item records.")
            if total_records:
                page_count = (total_records + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
                page_index = max(0, min(current_page.value, page_count - 1))
                with solara.Row(style="align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 12px;"):
                    solara.FileDownload(
                        data=lambda: display_df.to_csv(index=True),
                        filename="filtered_tollway_bid_results.csv",
                        label="📥 Download as CSV",
                        mime_type="text/csv"
                    )
                    _OpenDOTPagination.element(
                        page=page_index + 1, page_count=page_count,
                        on_page=lambda page: current_page.set(page - 1),
                    )

            # Render formatted grid or error state
            if total_records > 0:
                max_pages = (total_records - 1) // ITEMS_PER_PAGE
                page_index = max(0, min(current_page.value, max_pages))
                start_idx = page_index * ITEMS_PER_PAGE
                end_idx = start_idx + ITEMS_PER_PAGE
                sliced_df = display_df.iloc[start_idx:end_idx].copy()

                html_table = render_results_table(sliced_df)
                table_classes = ["opentollz-results-scroll"]
                if dark_mode:
                    table_classes.append("opentollz-dark-table")
                solara.HTML(
                    tag="div",
                    classes=table_classes,
                    unsafe_innerHTML=html_table,
                    attributes={"tabindex": "0", "aria-label": "Scroll bid item results horizontally"},
                )

            else:
                solara.Error("No records found matching current filtering combinations.")
