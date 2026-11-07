Captured from https://member.schack.se/public/api/v1 on 2026-10-30:

- `tournament.json`: `/tournament/tournament/id/7132`
- `group-{id}-table.json`: `/tournamentresults/table/id/{id}`
- `group-{id}-rounds.json`: `/tournamentresults/roundresults/id/{id}`
- `district-clubs.json`: `/organisation/district/clubs/5821`

The files contain unmodified upstream responses. Group IDs 19203–19208 and
names were verified before implementing the mapping. Tests use these captures
for an offline generation preview and synthetic players for scoring edge cases.
The preview uses captured district clubs; district rating membership is stubbed.
