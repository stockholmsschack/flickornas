# Standings Calculation for Girls' Tournaments

# Prerequisites

A list of tournaments is available to the application. Tournament details (groups, player ids, results) are fetched for each tournament via API from the server and processed as below. We also fetch a list of all clubs associated with Sweden, and save a list of players along with club locality (see [Known Issues](#known-issues)).

## Local web applications and Mercure

The workspace's shared top-level `../Caddyfile` hosts all local applications and one Mercure
endpoint. The project-local [Caddyfile](Caddyfile) remains available when Flickornas is checked out
and run independently.

- Playtime: `http://playtime.localhost:5000`, proxying port 1612
- Flickornas: `http://flickornas.localhost:5000`, proxying port 7001
- JGP: `http://jgp.localhost:5000`, proxying port 8001
- Senior: `http://senior.localhost:5000`, proxying port 9001
- Available files: `http://flickornas.localhost:5000/downloads`
- File downloads below `/downloads/`, served directly from `output/runs/`
- Reports: `http://flickornas.localhost:5000/reports`
- Report downloads below `/reports/`, served directly from `output/runs/`
- Mercure: `/.well-known/mercure` on either same-origin application address

Start Flickornas from its project directory:

```sh
MERCURE_JWT_SECRET='!ChangeThisMercureHubJWTSecretKey!' uv run flickornas-web
```

The standalone app also serves the latest public standings without Caddy or Verktyg:

```sh
curl -fsS http://127.0.0.1:7001/api/v1/standings/flickornas | jq .
```

Run `uv run flickornas generate` to publish a fresh payload. The endpoint returns `404` until a
full generation has published a snapshot. The payload contains `last_updated`, the JSON generation
time in UTC ISO 8601 format (for example, `2026-10-29T12:34:56+00:00`). This timestamp stays fixed
when the API serves the snapshot.
The payload also contains `tournament_ids`, an array of
integer IDs in standings-column order (tournament start date, then tournament ID), and `standings`,
the list of player rows. Each row includes the player's integer `member_id` alongside `placement`,
`name`, `birth_year`, `club`, `tournaments` and `total_points`. Consumers of the earlier array
payload must now read rows under `standings`. Existing snapshots keep their format until regenerated.

From the workspace top-level directory, start shared Caddy with the same publisher secret:

```sh
MERCURE_JWT_SECRET='!ChangeThisMercureHubJWTSecretKey!' /usr/local/bin/caddy_mercure run --config Caddyfile
```

For an independent Flickornas checkout, run the same Caddy command from the project directory; it
uses the project-local configuration.

Set `FLICKORNAS_DOWNLOAD_ROOT` when the generated-file directory is not
`./output/runs`. Caddy serves the standings PDF and workbooks below
`/downloads/`, and standings data plus diagnostic reports below `/reports/`.
The PDF, standings workbook, and validation workbook from a generation share a
UTC datetime suffix such as `20260801T120000Z`, making separately downloaded
generations easy to distinguish.
Flask renders both indexes and supplies their links but does not transfer file
contents. Typst sources and rendering support files are not listed. The
Available files page can clear every generated download and report after an
explicit confirmation while retaining the active configuration.

Generated-file links use `FLICKORNAS_FILES_PUBLIC_ORIGIN`, which defaults to
`http://flickornas.localhost:5000`. This keeps downloads on Caddy even when the
Flask UI is opened directly on port 7001. Set it to the authenticated public
origin when the Blueprint is deployed.

Mercure delivery is best effort. Omitting `MERCURE_JWT_SECRET` disables publishing
without disabling generation; operation status files remain authoritative. The
browser receives only the same-origin `MERCURE_PUBLIC_URL`, which defaults to
`/.well-known/mercure`. The server publishes through the loopback-only
`MERCURE_HUB_URL`, which defaults to
`http://127.0.0.1:5000/.well-known/mercure`. Publisher credentials stay in the
server environment.

## Mounting in a host

A host, such as the Verktyg portal, mounts Flickornas in its own Flask application with
`flickornas_standings.web.register(app, settings)`. `MANIFEST` gives the tool's `id` (`flickornas`),
`name` and default `url_prefix` (`/tools/flickornas`). Every page, API, static, help and status link
follows the prefix. `tests/test_web_hosting.py` is a minimal working host. Standalone,
`create_app` registers the same Blueprint at the root, and `flickornas-web` listens on port 7001.

Required settings (registration raises `KeyError` without them):

- `STATE_DIRECTORY` and `OUTPUT_DIRECTORY`: the writable directories Flickornas owns (`state/`,
  holding the active configuration, `typst/rules.typ` and `operations/`, and `output/`).
- `MEMBER_SYSTEM_CLIENT`: the member-system client.
- `FILES_PUBLIC_ORIGIN`: the origin the host's file server serves `output/runs/` from, at both
  `/downloads/` and `/reports/`. It may carry a path.

Optional settings:

- `BASE_TEMPLATE`: the host's shell; Flickornas fills its `title` and `content` blocks and appends
  to its `head` and `scripts` blocks.
- `LOCALE` (a callable returning `sv` or `en`) and `DEFAULT_LOCALE` (`sv`).
- `ACTOR`: a callable returning who acts; each operation record keeps it.
- `MUTATION_PROTECTION`: a callable; when it returns false, every Flickornas POST, PUT and DELETE
  gets `403`.
- `GENERATION_TOURNAMENT_SELECTION_AUTHORIZER`: whether the user may choose a run's tournaments.
  Without it, nobody may. Standalone grants it to a loopback `Host` header.
- `MERCURE_PUBLISHER`, with `MERCURE_PUBLIC_URL` for the browser. Topics are
  `https://stockholmsschack.se/flickornas/operations/<id>`. Without a publisher, or when it fails,
  the dialog polls the operation's status.
- `CLOCK`, and `GENERATION_EXECUTOR`, `GENERATION_RUNNER` and `GENERATION_RENDERER` for tests.

The host guards access to the whole prefix, CSRF and auditing; Flickornas has no login. The host's
file server serves the generated files itself, applying its own access check. Those files are for
operators; the operation's "View files" link is the prefix plus `/downloads`. The public standings
are the snapshot `flickornas_standings.artifact_publication.read_public_snapshot(OUTPUT_DIRECTORY)`
returns, the allowlisted JSON, or `None` when nothing is published (a `404`). A partial run, one
given its own tournaments, never replaces it, and Clear downloads removes it.

One generation runs at a time across processes. A file lock holds the lease, so a worker that dies
releases it; its unfinished operation is marked failed (`interrupted`) when Flickornas next starts
or the next generation is requested. Generation needs the `typst` command on the `PATH`; it renders
with the bundled fonts only.

Before accepting a Flickornas revision, the host runs `uv run pytest` from the Flickornas tree.
`tests/test_web_hosting.py` covers the mounted contract.

## Tests

Run the suite with `uv run pytest`. pytest also runs the remaining `unittest` test cases. Write new
tests as pytest functions, using the fixtures in `tests/conftest.py`. Convert a `unittest` module when
you change it substantially. `python -m unittest` no longer finds the pytest tests.

## Run-derived dates

Each run resolves one `effective_year`, using an explicit value when supplied
and otherwise the current calendar year. The youngest birth-year group starts
at `effective_year - 9`; for an effective year of 2026 its label is therefore
`2017 -`. Recording the resolved year makes the run explainable after the
calendar changes.

The district rating list is requested for the end date of the chronologically
latest configured tournament. Before standings calculation, authoritative
tournament metadata is sorted by start date oldest first; the operator cannot
override that order. Tournament ID ascending breaks equal-date ties. Every
configured tournament must supply valid ISO `YYYY-MM-DD` start and end dates;
generation fails instead of substituting the wall clock when either is missing
or malformed.

# Step 1: Filtering

1. Players who had *only* walkover losses are removed. These are players who registered but were *No Show*. Players who had a W.O. in earlier rounds but played later rounds are retained.  
2. Players who played no matches are removed. These are also no shows, but the conducting club has left them in the list.  
3. All male players are filtered out.

**Note:** Players in *all* groups are given points, unlike JGP standing where groups from E onward are not considered.

# Step 2: Computation

The Standings points are computed within each tournament `klass`, after filtering to female players. A `klass` can contain players from multiple tournament groups when those groups map to the same `klass` value.

For each tournament, within each `klass`, players are sorted by:

1. tournament place, ascending;
2. scaled points, descending, where points are divided by the number of rounds;
3. quality points, descending;
4. birth year, descending.

In this sorted order players are assigned *Sequence Points* (see below).

## Sequence Points

### Overview of the Points Assignment Method

Minimum players: Points are assigned when there is at least one player in the `klass`.

For normal `klass` scoring with more than one player, the first player receives 25 points and the last player receives 5 points. Players in between are scaled by percentile rank:

`q = (N - rank) / (N - 1)`

where `N` is the number of players in the `klass`.

The percentile is converted to sequence points using a piecewise formula:

* Top half: `11 + 28 * (q - 0.5)`
* Bottom half: `5 + 12 * q`

The result is rounded to the nearest integer.

If a normal `klass` contains only one player, the implementation sets `q` to 0, so that player receives 5 points.

For non-JDM tournaments, `klass` `e`, `f`, and `z` use special scoring: rank 1 gets 8 points, rank 2 gets 7 points, rank 3 gets 6 points, and all other ranked players get 5 points.

Under normal scoring, players marked as dropouts by the preprocessing step have negative tournament points and receive 4 sequence points.

### Ties

The current implementation does not split or share sequence points for tied players. Players receive consecutive ranks after sorting by place, scaled points, quality points, and birth year.

# Step 3: Collation

After Sequence Points are assigned to each `klass` within a tournament and all tournaments are processed in the same fashion, the results are merged.

The results from all the tournaments are merged, with no points assigned to players who did not play in the tournament (this is in the same style as the **JGP Standings** sheet)

The total sequence points across all tournaments for each player is computed and the list is sorted in descending order across all `klass` values.

The final sort order is:

1. total sequence points, descending;
2. latest `klass`, ascending;
3. tournament participation recency, with players who played more recent tournaments first;
4. tournament performance recency, using raw tournament points from newer tournaments first;
5. birth year, ascending, so older players are listed first;
6. number of tournaments played, ascending, so players with fewer tournaments are listed first.

All else being equal, the order from the member system's results is maintained.

### Player Eligibility

Only players who are members of clubs in the *Stockholm Chess Federation* are eligible for the finals. Scores of players from all clubs are used in the computation of the sequence points. Once all the computation is complete, non-Stockholm players are removed from the published list.

# Step 4: Export

An Excel file which includes the tournament points and quality points is exported for *validation*. These are then removed, columns are reordered and renamed as needed and the final Standings Excel file is exported.

# Known Issues {#known-issues}

## Non-Local Players

Some players have multiple club memberships with their main club being outside the Stockholm District. The API lists only the main club. These players are currently filtered out.

For privacy reasons the API will not list all club memberships.

The proposed strategy is for the API to include district-level membership as this is sufficient for us to include the player in the standings. WIP.

A *temporary* alternative is to provide an override as and when we are notified.

When it is possible for the main club to be switched, it is incumbent on the player and their club to request the change in the member system.

## Group Size Distorting Point Allocation

The number of players in a `klass` affects the distribution of points below the top score. In normal `klass` scoring with more than one player, the first player receives 25 points and the last receives 5 points, but the values assigned to intermediate ranks depend on the `klass` size.

Changing the allocation to use top scoring points would give more points to players in small groups (like one or two players) simply by virtue of being in a small group.

We could normalize the scores by group size, but we need to clarify the purpose of the standings w.r.t what the finals’ composition must look like.

## Group naming

See [the group naming conventions](KLASS_NAMING.md) for accepted names and how to correct refused groups.
