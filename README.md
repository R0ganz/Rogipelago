# Rogipelago - Roganz' Archipelago Tracker

An Archipelago Python script, wrapped as an executable. It allows you to connect to the instance as a tracker, hosting a basic website with information about every player's game, checks done, left and any new deaths.

# Percentages
At the top, we can see the global progress, with number of checks done, left and remaining, then a TOTAL percentage for everyone.

<img width="204" height="98" alt="image" src="https://github.com/user-attachments/assets/7e5582e6-aea3-4ed9-9e2c-b8b1d03abb89" />

Then, per player, you have their connected indicator, name, game, number of checks done, and left, then a percentage, with a glowing bar beneath. These names and colours change per player, with functionality in the python script to have it settable, otherwise it randomly assigns colours uniquely for each player.

<img width="413" height="68" alt="image" src="https://github.com/user-attachments/assets/dad7b13b-3522-46ba-8ada-23a4fee0a603" />

# Events
Upon a deathlink event, you will see a message within the "Recent Events" logs, with the person who died and a reason, if obtainable.
For item checks, players names will be displayed in their colour, items in a golden glow, the receiver in their colour follows, lastly the game it's retrieved from at the end in purple.

<img width="546" height="82" alt="image" src="https://github.com/user-attachments/assets/e61a63d4-3cdf-4dbf-a806-5e7a91d67a4b" />

# Updating the Checks
Currently the script will, every five minutes, send a `!status` to the Archipelago server, which will update the bars, percentages and checks completed for every person, and globally. I have, for ease of use, added a button on the website at the top `Refresh Status` so that you can complete this refresh yourself, outside of the five minute checks.

# Nerd Stuff
The script will retrieve a DataPackage from Archipelago, per game, one at a time. This is to avoid flooding the server at connection, the data is needed to properly translate the checks (Which are just numbers) to the relevant names. We also have the colours randomly assigned, if it's possible to add website configuration for each person I'd like that, although it'll be tricky I'm sure. Lastly, I need to do more testing, as this currently has only been tested by me, on my own, with me doing the only set of checks. I need to see it with more people, but until then, I release this hoping it helps folks and works well, but if there are issues, please contact me via Github or my Discord (roganz)
