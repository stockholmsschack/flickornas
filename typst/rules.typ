#set text(costs: (widow: 100%))
#set text(9pt, font: "Roboto", weight: "regular")
= How it works

== Sorting rules

+ Total points: highest first (see next section for details of points)
+ Klass: ascending order

=== Tie-breakers:
+ Participation recency: This puts players who participated in recent tournaments first
+ Performance recency: This ranks by actual points earned in recent tournaments
+ Age tie-breaker: older players first
+ Total tournaments played: a player with fewer tournaments placed first

_Sort by total points, then by class, then prioritize players who played recently AND performed well recently, with age and total games as final tie-breakers._


== Points assignment

- For each tournament, filter to girls, group by Klass, and sort by place, scaled points, quality points (kv.p), and birth year
 - points are scaled by number of rounds since juniors and seniors may play different number of rounds
 - place sorts by individual performance between each pair of players
- In normal scoring, assign 11 STD points to the median
- In normal scoring with more than one player, assign 25 to first player and 5 to last player
- In normal scoring with one player, assign 5 points
- Scale and assign the rest of the points within this range (scaling formula is explained below)
- In non-JDM tournaments, E, F, and Z players are given 5 baseline points, and top 3 players get 8, 7, and 6 points

=== Points scaling

- Within each sorted Klass we calculate percentile placement (q)
  - How much better is this player compared to those who scored less?
- Formula: `q(i) = ( N - i ) / ( N - 1 )`, where `N` is total number of players. When `N = 1`, the code uses `q = 0`.
  - For groups with more than one player, this gives `1, 0.5, 0` as the top, middle, and bottom percentile scores when those positions exist.

- 5 to 11 is 6 places, whereas 11 to 25 is 14 places
  - So, we scale these two "piece-wise" and round them to the nearest integer
  - top half get: `11 + 28*(q-0.5)` (i.e. 25 through 11)
  - players below median get `5 + 12*q` (i.e. 10 through 5)

= Source of the Data / Datakälla

#show link: set text(blue)
#text(lang: "en")[The data in this document comes from the #link("https://member.schack.se")[Swedish Chess Federation's member system].]

#text(lang: "sv")[Uppgifterna i detta dokument kommer från #link("https://member.schack.se")[Sveriges Schackförbunds medlemssystem].]
