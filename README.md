# Rogipelago - Roganz' Archipelago Tracker

An Archipelago Python script, wrapped as an executable. It allows you to connect to the instance as a tracker, hosting a basic website with information about every player's game, checks done, left and any new deaths. Using some basic logging to keep track of things if you get disconnected, as well as automatically trying to reconnect on failure.

# Percentages
At the top, we can see the global progress, with number of checks done, left and remaining, then a TOTAL percentage for everyone.

<img width="204" height="98" alt="image" src="https://github.com/user-attachments/assets/7e5582e6-aea3-4ed9-9e2c-b8b1d03abb89" />

Then, per player, you have their connected indicator, name, game, number of checks done, and left, then a percentage, with a glowing bar beneath. These names and colours change per player, with functionality in the python script to have it settable, otherwise it randomly assigns colours uniquely for each player. We also have deathlink tracking, and counters for that, as well as a timer for when they are connected, counting time, and stopping at 100%.

<img width="566" height="269" alt="image" src="https://github.com/user-attachments/assets/f3591b9e-46ab-4365-b267-850070997482" />

# Events
The event log is scrollable but limited to a set number to help stop it crashing. Each event has the time next to it to show when it happened, AND if hovered over it tells you the time for the relevant player, so you can see at what point in their run this event happened.

Upon a deathlink event, you will see a message within the "Recent Events" logs, with the person who died and a reason, if obtainable.

For item checks, players names will be displayed in their colour, items in a golden glow, the receiver in their colour follows, lastly the game it's retrieved from at the end in purple.

<img width="959" height="145" alt="image" src="https://github.com/user-attachments/assets/f552f872-e456-46a4-8ca0-789b6c72b81a" />

# Updating the Checks
The script will manually count up with each event that comes in, adding 1 to the counter for each event. Incase of incorrect numbers, the manual refresh on the site, or a player running !status, will automatically correct the numbers. !status is truth.

# Nerd Stuff
The script will retrieve a DataPackage from Archipelago, per game, one at a time. This is to avoid flooding the server at connection, the data is needed to properly translate the checks (Which are just numbers) to the relevant names. We also have the colours randomly assigned, if it's possible to add website configuration for each person I'd like that, although it'll be tricky I'm sure. Lastly, I need to do more testing, as this currently has only been tested by me, on my own, with me doing the only set of checks. I need to see it with more people, but until then, I release this hoping it helps folks and works well, but if there are issues, please contact me via Github or my Discord (roganz)
