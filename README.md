# CoronaBot - A bot module for tracking the Coronavirus epidermic
CoronaBot is a Discord bot module (or [cog](https://discordpy.readthedocs.io/en/stable/ext/commands/api.html#discord.ext.commands.Cog) in [`discord.py`](https://github.com/Rapptz/discord.py) jargon) made specifically for tracking the [Coronavirus epidermic](https://en.wikipedia.org/wiki/COVID-19_pandemic).
It fetches and parses data from the [JHU CSSE database](https://github.com/CSSEGISandData/COVID-19) then present it in a nice way.

### Usage
1. Make sure you've installed a compatible Python version (>3.4, Python 3.7 recommended).
1. Clone or download this repository to your computer, then make it the current working directory (`cd CoronaBot`).
1. Edit `token.txt` and replace the content with your bot's token, tutorial [here](https://github.com/rixinsc/Libereus-DHW19#registering-an-access-token-for-your-bot).
1. Run `bot.py`. (`python3 bot.py`)
1. Invite your bot to your server and have fun! Use `-help` to get started. (`-` is the default prefix, all command invocation must be preceded with the configured prefix)

### Feature Highlight
- Get a summary of the current situation of COVID-19 (`corona`)
- Get country ranking by confirmed cases count (`corona rank`)
- Check the number of infections in a country/province/state (`corona status US`)
- Subscribe to the update of the number of related cases in a particular region, updated every 20 minutes (`corona subscribe US`)
##### PS: You can get extended help for a command by prepending `help` in front of the command you would like to know more about. Example: `help corona rank` will show more information about `corona rank` command.

#### Available data:
1. Confirmed cases count
1. Deaths count
1. Recovered patients count
1. Active patients count
1. Incident rate
1. Country ranking by confirmed cases

### Primary File Structure
```
CoronaBot
|- bot.py        [The main executable for the bot, also the entry for the bot]
|- corona.py     [The primary module being used here, contains the source of all
|                 related commands about coronavirus]
|- classes.py    [All self-defined/inherited classes that're used to power the bot]
|- exceptions.py [All custom-defined exceptions classes]
|- helpers.py    [Helper functions that're used throughout the bot]
|- db.json       [A local database file that's automatically generated after
|                 the bot starts]
|_
```

This project is [MIT licensed](https://choosealicense.com/licenses/mit/), see the file `LICENSE` for more info.
