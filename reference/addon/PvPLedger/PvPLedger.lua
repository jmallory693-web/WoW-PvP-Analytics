-- Protocol header fixture only. No player observations.
local MATCH_HEADER = {
  "Match ID","Date","Time","Character","Realm","Class","Spec","PvP item level","Equipped item level",
  "Map","Type","Rated","Result","Duration (s)","Minutes played","Late join",
  "KB","HK","Deaths","Damage","Healing","Honor (scoreboard)","Rating change","MMR before","MMR after",
  "Team deaths","Enemy deaths","Team damage","Enemy damage","Team healing","Enemy healing",
  "Team healers","Enemy healers","Premade present","Premade members","My objectives","Score detail",
  "Alliance score","Horde score","My team score","Enemy team score",
  "Honor awarded","Conquest awarded","Addon version","Schema version",
  "Attendance ticks",
}

local ROSTER_HEADER = {
  "Match ID","Player","Realm","Team","Class","Spec","KB","HK","Deaths","Damage","Healing",
  "Honor","Rating change","Is me","Is premade","Objectives",
  "Ticks present","Ticks total","Joined late","Left early","Schema version",
}
