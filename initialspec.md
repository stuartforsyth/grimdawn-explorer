This is a cross-platform desktop application written in python

The aim of this application is to:
1. understand all of the skills and itemisation for the game grim dawn and have the ability to learn new information between patches and major content updates.
2. be able to read local grim dawn save files to understand the characters I am currently playing.
3. Be able to explore and suggest skills and items to further advance the character.


Notes for Skill and item Suggestions:
- https://www.grimtools.com/db/ is an authoritative source for infromation on grim dawn
- for suggested items, understand and suggest where to farm them

Design Parameters
- save file editing is out of scope for this iteration.  save file reading only to suggest skill and item combinations.
- claude will advise on how best to keep current item/skill database up to date (save to json preferred over actual db)
- claude will suggest how to look for build information on the web from verified sources
- the aim of this app is to UNDERSTAND BUILD SYNERGIES, ITEMISATION FOR BUILDS, AND SKILLS SYNERGIES over simply searching the web for combinations.  There needs to be a human in the loop feedback mechanism to determine if suggested advice is good or bad.  Additionally understanding build nuance and context from parsed web builds is important.
- Aim for an MVP first rather than a fully engineered option; it is important to iterate through permutations of this app to ensure it's doing what I want.
- the steam and local save directory for grim dawn changes across operating systems.  know which pathing to explore for which operating system.  once a folder is found, save it for future sessions to prevent having to look for it everytime.  have the ability to rescan or re-select the folder if the install changes.
- the ultimate aim is to provide visuals based on actual skill trees or items.  for the mvp this is not required until it's all working.

This spec is a first attempt at creating this tool.  Claude will suggest further improvements and design considerations.
Build the spec properly first before writing code.
