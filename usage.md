# Operator reference

The installed `flickornas` CLI supports configuration validation, end-to-end
generation, immutable rerendering, and global download cleanup. The examples
below use `uv run flickornas` from a source checkout; after package
installation, run the same commands without the `uv run` prefix.

## Local web application

Start the local web application with:

```console
uv run flickornas-web
```

It listens on `127.0.0.1:7001` by default and treats the local operator as
authorized. Open `http://127.0.0.1:7001/` to inspect retained run records or
edit the active configuration's default tournament selection in Swedish or
English. Generation and the remaining structured configuration fields are not
yet available through this web interface.

On the configuration page, tournament search starts after three typed
characters. Selecting a result verifies it against the member system before
adding it. Selected tournaments appear above the search controls as canonical
titles and IDs and are always ordered by start date, oldest first. The operator
cannot override this order.

Unsaved verified selections survive switching the interface language in the
same browser session. Removing one tournament or all tournaments requires
confirmation that names the affected selection. Success and failure
notifications remain fixed in the viewport, including when a selection was
made from the middle of a long result list.

Use different state and output locations when needed:

```console
uv run flickornas-web \
  --state-directory /path/to/state \
  --output-directory /path/to/output \
  --port 8000
```

Bootstrap, `lit-html`, and application JavaScript are served from the installed
package; the web UI does not require a CDN or the portal. Bootstrap supplies
the confirmation dialogs and notifications, while `lit-html` updates the
stateful picker without clearing prior results during a replacement search.

## Active configuration

There is one configuration document:

```text
state/active-configuration.toml
```

It contains default tournament IDs, known-local-player overrides, contributor
details, layout policy, and PDF-only club aliases. It does not contain a year.

Validate it without generating artifacts or changing state:

```console
uv run flickornas validate
```

The command uses `state/` and `output/` by default. To use other locations,
place the shared options before the command:

```console
uv run flickornas \
  --state-directory /path/to/state \
  --output-directory /path/to/output \
  validate
```

The active configuration is always named `active-configuration.toml` within
the selected state directory. Prepare another state directory with ordinary
filesystem commands:

```console
mkdir -p /path/to/state
cp state/active-configuration.toml /path/to/state/active-configuration.toml
```

## Generate standings

```console
uv run flickornas generate
```

With no selectors, the command uses the current calendar year and all configured
tournaments. A successful full generation publishes both the public JSON
snapshot and PDF by default.

Override the inputs for one run without changing configuration:

```console
uv run flickornas generate \
  --year 2026 \
  --tournament 6336 \
  --tournament 6544
```

An explicit tournament list creates a partial run. The calculation, totals,
diagnostics, rating-list date, and artifacts use only those tournaments, and
user-facing artifact names include `-partial`. Partial runs publish nothing by
default.

An explicit year that is not the current calendar year must be accompanied by
at least one explicit `--tournament`. Empty, duplicate, or unresolvable
tournament selections fail before calculation.

Publication can be controlled explicitly:

```console
uv run flickornas generate --no-publish
uv run flickornas generate --tournament 6336 --publish
```

`--no-publish` suppresses publication. Explicit publication of a partial run
advances only the PDF; it never replaces the full public JSON snapshot.
`--publish` and `--no-publish` cannot be combined.

Override the configured page-orientation policy for one run:

```console
uv run flickornas generate --layout landscape
```

On success, the command prints the absolute path of the committed PDF. On
failure, it exits non-zero and names the failed stage.

## Rerender a PDF

```console
uv run flickornas render --from-run 20260727T113749Z-3810b71c
```

Rendering creates a new immutable run from the source run's persisted rendering
projection. It does not fetch upstream data, recalculate standings, parse an
artifact, or alter the source run. A missing, cleared, or otherwise unavailable
source fails explicitly.

Without `--from-run`, rendering uses the run selected by `output/published-pdf`.
If that reference does not exist, the command first creates a full unpublished
generation as its source, then creates the separate unpublished render run.

Rendering is unpublished by default. Publish only its PDF with:

```console
uv run flickornas render \
  --from-run 20260727T113749Z-3810b71c \
  --publish
```

## Choose page orientation

Generation and rendering accept:

```console
--layout auto
--layout portrait
--layout landscape
```

`auto` applies the configured tournament-count threshold. A per-run override
does not mutate configuration.

The layout section in `state/active-configuration.toml` is:

```toml
[layout]
landscape_starts_at = 15
base_side_margin_cm = 0.8
margin_reduction_starts_after = 7
margin_reduction_per_tournament_cm = 0.05
minimum_side_margin_cm = 0.5
```

Set `landscape_starts_at = 0` to disable automatic landscape. Side margins
shrink only after the configured count and never below the minimum. The 2.8 cm
top margin is fixed.

## Short club names in PDFs

Add exact canonical-name mappings to the active configuration:

```toml
[club_display_names]
"Kista FKUM Schack Sektion" = "Kista FKUM"
```

Aliases affect only Typst and PDF. Public JSON and workbooks retain canonical
club names. A rerender applies the current aliases without recalculation.

## Publication defaults

| Invocation | Published result |
| --- | --- |
| `flickornas generate` | Full JSON and PDF |
| `flickornas generate --no-publish` | Nothing |
| `flickornas generate --tournament ID` | Nothing |
| `flickornas generate --tournament ID --publish` | PDF only |
| `flickornas render --from-run RUN_ID` | Nothing |
| `flickornas render --from-run RUN_ID --publish` | PDF only |

## Artifacts and retained state

Full run artifacts include:

```text
standings-<YYYYMMDDTHHMMSSZ>.pdf
standings.typ
standings-<YYYYMMDDTHHMMSSZ>.xlsx
standings.json
validation-<YYYYMMDDTHHMMSSZ>.xlsx
diagnostics/<report-name>.txt
```

The PDF and both workbooks from one generation share the same UTC timestamp.
Partial user-facing artifacts place `-partial` before the timestamp suffix.

Run records under `state/runs/` retain effective year, tournament IDs in
authoritative start-date order (oldest first), kind, layout, outcome,
availability, and render provenance. Operators choose tournament membership,
not order. Render-ready published rows are stored separately under
`state/rendering-projections/`.

## Clear downloads

```console
uv run flickornas clear-downloads
```

The global clear operation removes:

- every generated run directory under `output/runs/`;
- every rendering projection;
- the public JSON reference; and
- the published PDF reference.

It preserves the active configuration and run metadata. Retained run records
report that their artifacts are unavailable, and public snapshot and PDF reads
return not found. The command reports how many retained run records it marked
unavailable, and it can be repeated safely.

## Group naming

See [the group naming conventions](KLASS_NAMING.md) for accepted names and how to correct refused groups.
