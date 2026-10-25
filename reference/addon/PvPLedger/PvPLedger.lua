-- Verified protocol headers from PvP Ledger 1.3.4 (schema 7).
-- Source SHA-256: e354b2fe2c1404c3fb47e92f5ffdcf0c3a9362e9930b6a30396b8475974480b1
-- Schema 6 (1.3.2/1.3.3) has the same column layout. No player data.
local MATCH_HEADER = {
  "Match ID","Date","Time","Character","Realm","Class","Spec","PvP item level","Equipped item level",
  "Map","Type","Rated","Result","Duration (s)","Minutes played","Late join",
  "KB","HK","Deaths","Damage","Healing","Honor (scoreboard)","Rating change","MMR before","MMR after",
  "Team deaths","Enemy deaths","Team damage","Enemy damage","Team healing","Enemy healing",
  "Team healers","Enemy healers","Premade present","Premade members","My objectives","Score detail",
  "Alliance score","Horde score","My team score","Enemy team score",
  "Honor awarded","Conquest awarded","Addon version","Schema version",
  "Attendance ticks","Epoch","Queue type",
}
local ROSTER_HEADER = {
  "Match ID","Player","Realm","Team","Class","Spec","KB","HK","Deaths","Damage","Healing",
  "Honor","Rating change","Is me","Is premade","Objectives",
  "Ticks present","Ticks total","Joined late","Left early","Schema version",
}
