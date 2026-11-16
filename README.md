# Open DOT

Free tools for searching public Illinois transportation contract information: IDOT and Illinois
Tollway lettings, bids, consultant selections and bulletins. Live at
**[open-dot.org](https://open-dot.org/)**.

This repository holds the source code of the public-facing apps. Bridge structural engineering
tools are in a separate repository, [tjanicke/bridge-se](https://github.com/tjanicke/bridge-se).

| App | Live at | Folder |
|---|---|---|
| OpenBidz: IDOT bid results | [bids.open-dot.org](https://bids.open-dot.org/) | `apps/openbidz/` |
| OpenSelections: IDOT PTB consultant selections | [selections.open-dot.org](https://selections.open-dot.org/) | `apps/openselections/` |
| OpenTollz: Illinois Tollway bid results | [tolls.open-dot.org](https://tolls.open-dot.org/) | `apps/opentollz/` |
| OpenTollSelections: Tollway PSB selections | [tollselections.open-dot.org](https://tollselections.open-dot.org/) | `apps/opentollselections/` |
| ODOT Selections: Ohio DOT consultant selections | [odotselections.open-dot.org](https://odotselections.open-dot.org/) | `apps/ohioselections/` |
| Open Bulletins: IDOT PTB and Tollway PSB bulletin search | [bulletins.open-dot.org](https://bulletins.open-dot.org/) | `apps/open-bulletins/` |
| Open DOT Search: letting document search | [search.open-dot.org](https://search.open-dot.org/) | `apps/search/` |
| Home page | [open-dot.org](https://open-dot.org/) | `site/homepage/` |

## Where the data comes from

Every dataset behind these apps is built from publicly accessible government websites and
records: IDOT and Illinois Tollway letting results, bulletins and selection announcements.
Open DOT does not use proprietary or commercially aggregated data, and it does not publish
consultant-prepared proposals or other consultant-originated work.

## What is not in this repository

- **Data.** The bid, selection and bulletin tables (parquet and CSV files) are not included. Each
  app reads its table from a data folder or a path set by an environment variable (for example
  `OPENTOLL_DATA_FILE` or `BULLETINS_DATA`). Some Dockerfiles copy a data file into the image, so
  place the matching file next to the Dockerfile before building.
- **The data collection pipelines and server configuration**, which are kept private.
- **Credentials.** Apps that need them (Open Bulletins and Open DOT Search, which query
  Elasticsearch) read them from environment variables such as `ES_USERNAME`, `ES_PASSWORD` and
  `ES_API_KEY`. None are stored here.

## Run an app locally

The Solara apps (OpenBidz, OpenSelections, OpenTollz, OpenTollSelections):

```
cd apps/openbidz
pip install -r requirements.txt
# put the data file where the app expects it, then:
solara run openbidz.py
```

Open Bulletins runs with gunicorn (`web:app`) and needs an Elasticsearch index. Open DOT Search
runs `server.py` behind a reverse proxy and also needs Elasticsearch.

## Keeping secrets out

This repository is public. Before each push run `bash scripts/check-secrets.sh`, or install it as
a pre-commit hook:

```
cp scripts/check-secrets.sh .git/hooks/pre-commit
```

GitHub also scans every push (`.github/workflows/secret-scan.yml`). If a secret is ever pushed,
change the secret first; removing the commit is not enough once it has been public.

## License

[GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0). You may use, study, change and share
this code. If you run a modified version as a website or other network service, you must make your
modified source code available to its users under the same license. Provided without warranty.

Copyright (c) 2026 tjanicke (Open DOT)
