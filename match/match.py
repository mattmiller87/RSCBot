import traceback
import ast
import random
from datetime import datetime
import json

from redbot.core import Config
from redbot.core import commands
from redbot.core import checks

defaults = {"MatchDay": 0, "Schedule": {}}

class Match(commands.Cog):
    """Used to get the match information"""

    MATHCES_KEY = "Matches"
    TEAM_DAY_INDEX_KEY = "TeamDays"

    def __init__(self, bot):
        self.config = Config.get_conf(self, identifier=1234567893, force_registration=True)
        self.config.register_guild(**defaults)
        self.team_manager = bot.get_cog("TeamManager")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setMatchDay(self, ctx, day: str):
        """Sets the active match day to the specified day.

        This match day is used when accessing the info in the !match command.
        """
        await self._save_match_day(ctx, str(day))
        await ctx.send("Done")

    @commands.command()
    @commands.guild_only()
    async def getMatchDay(self, ctx):
        """Gets the currently active match day."""
        match_day = await self._match_day(ctx)
        if match_day:
            await ctx.send(
                "Current match day is: {0}".format(match_day))
        else:
            await ctx.send(":x: Match day not set. Set with setMatchDay "
                               "command.")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def printScheduleData(self, ctx):
        """Print all raw schedule data.

        Note: In the real server, this will likely fail just due to the amount
        of data. Intended for use in debugging on test servers. Basically,
        when there are only a handful of matches total.

        TODO: Might even comment this out in prod.
        """
        schedule = await self._schedule(ctx)
        dump = json.dumps(schedule, indent=4, sort_keys=True)
        await ctx.send("Here is all of the schedule data in "
                           "JSON format.\n```json\n{0}\n```".format(dump))

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def clearSchedule(self, ctx):
        """Clear all scheduled matches."""
        await self._save_schedule(ctx, {})
        await ctx.send("Done.")

    @commands.command()
    @commands.guild_only()
    async def match(self, ctx, *args):
        """Get match info.

        If no arguments are provided, retrieve the match info for the
        server's currently active match day for the requesting user's
        team or teams. This will fail if the user has no team role or if
        the match day is not set.

        If one argument is provided, it must be the match day to retrieve. If
        more than one argument is provided, the first must be the match day
        followed by a list of teams for which the match info should be
        retrieved.

        Example: `!match 1 derechos "killer bees"`

        Note: If no team names are sent, GMs (or anyone with multiple team
        roles) will get matchups for all their teams. User's without a team
        role will get nothing.
        """
        match_day = args[0] if args else await self._match_day(ctx)
        if not match_day:
            await ctx.send("Match day not provided and not set for "
                               "the server.")
            return
        team_names = []
        user_team_names = await self.team_manager.teams_for_user(
            ctx, ctx.message.author)

        team_names_provided = len(args) > 1
        if team_names_provided:
            team_names = args[1:]
        else:
            team_names = user_team_names

        if not team_names:
            await ctx.send("No teams found. If you provided teams, "
                               "check the spelling. If not, you do not have "
                               "roles corresponding to a team.")
            return

        for team_name in team_names:
            team_name_for_info = team_name if user_team_names else None
            match_index = await self._team_day_match_index(ctx, team_name,
                                                     match_day)
            if match_index is not None:
                await ctx.message.author.send(
                    await self._format_match_info(ctx, match_index,
                                            team_name_for_info))
            else:
                await ctx.message.author.send(
                    "No match on day {0} for {1}".format(match_day,
                                                         team_name)
                )
        await ctx.message.delete()

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def addMatches(self, ctx, *matches):
        """Add the matches provided to the schedule.

        Arguments:

        matches -- One or more matches in the following format:

        "['<matchDay>','<matchDate>','<home>','<away>','<roomName>','<roomPassword>']"

        Each match should be separated by a space. Also, matchDate should be
        formatted with the full month name, day of month and 4-digit year.
        The room name and password are optional. They will be generated if
        absent. Note that the placment of the double versus single quotes is
        important, as is the comma after the day of month.

        Examples:

        [p]addMatches "['1','September 10, 2018','Fire Ants','Leopards',
        'octane','worst car']"
        [p]addMatches "['1','September 10, 2018','Fire Ants','Leopards']" "[
        '2','September 13, 2018','Leopards','Fire Ants']"

        """
        addedCount = 0
        try:
            for matchStr in matches:
                match = ast.literal_eval(matchStr)
                await ctx.send("Adding match: {0}".format(repr(match)))
                resultMatch = await self._add_match(ctx, *match)
                if resultMatch:
                    addedCount += 1
        except Exception as e:
            await ctx.send(e)
        finally:
            await ctx.send("Added {0} match(es).".format(addedCount))

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def addMatch(self, ctx, match_day, match_date, home, away, *args):
        """Adds a single match to the schedule.

        Arguments:
            ctx -- the bot context
            match_day -- the match_day to add the match to
            match_date -- the date the match should be played
            home -- the home team (must match the role name)
            away -- the away team (must match the role name)
            roomName -- (optional) the name for the RL match lobby,
                        Autogenerated if not provided.
            roomPass -- (optional) the password for the match lobby.
                        Autogenerated if not provided.
        Note: Any "extra" arguments are ignored.
        """
        match = await self._add_match(ctx, match_day, match_date,
                                      home, away, *args)
        if match:
            await ctx.send("Done")

    async def _add_match(self, ctx, match_day, match_date, home, away, *args):
        """Does the actual work to save match data."""
        # Process inputs to normalize the data (e.g. convert team names to
        # roles)
        match_date_error = None
        try:
            datetime.strptime(match_date, '%B %d, %Y').date()
        except Exception as err:
            match_date_error = "Date not valid: {0}".format(err)
        homeRoles = await self.team_manager._roles_for_team(ctx, home)
        awayRoles = await self.team_manager._roles_for_team(ctx, away)
        roomName = args[0] if args else self._generate_name_pass()
        roomPass = args[1] if len(args) > 1 else self._generate_name_pass()

        # Validation of input
        # There are other validations we could do, but don't
        #     - that there aren't extra args
        errors = []
        if match_date_error:
            errors.append("Date provided is not valid. "
                          "(Make sure to use the right format.)")
        if not homeRoles:
            errors.append("Home team roles not found.")
        if not awayRoles:
            errors.append("Away team roles not found.")
        if errors:
            await ctx.send(":x: Errors with input:\n\n  "
                               "* {0}\n".format("\n  * ".join(errors)))
            return

        # Schedule "schema" in pseudo-JSON style:
        # "schedule": {
        #   "matches": [ <list of all matches> ],
        #   "teamDays": { <dict where keys are tuples of team role names and
        #                 match days with list of indexes of all matches> }
        # }

        # Load the data we will use. Race conditions are possible, but
        # our change will be consistent, it might just override what someone
        # else does if they do it at roughly the same time.
        schedule = await self._schedule(ctx)
        # Check for pre-existing matches
        home_match_index = await self._team_day_match_index(
            ctx, home, match_day)
        away_match_index = await self._team_day_match_index(
            ctx, away, match_day)
        errors = []
        if home_match_index is not None:
            errors.append("Home team already has a match for "
                          "match day {0}".format(match_day))
        if away_match_index is not None:
            errors.append("Away team already has a match for "
                          "match day {0}".format(match_day))
        if errors:
            await ctx.send(":x: Could not create match:\n"
                               "\n  * {0}\n".format("\n  * ".join(errors)))
            return

        match_data = {
            'matchDay': match_day,
            'matchDate': match_date,
            'home': home,
            'away': away,
            'roomName': roomName,
            'roomPass': roomPass
        }

        # Append new match and create an index in "teamDays" for both teams.
        matches = schedule.setdefault(self.MATHCES_KEY, [])
        team_days = schedule.setdefault(self.TEAM_DAY_INDEX_KEY, {})

        home_key = self._team_day_key(home, match_day)
        team_days[home_key] = len(matches)

        away_key = self._team_day_key(away, match_day)
        team_days[away_key] = len(matches)

        matches.append(match_data)

        await self._save_schedule(ctx, schedule)

        result = match_data.copy()
        result['home'] = home
        result['away'] = away
        return result

    async def _schedule(self, ctx):
        return await self.config.guild(ctx.guild).Schedule()

    async def _save_schedule(self, ctx, schedule):
        await self.config.guild(ctx.guild).Schedule.set(schedule)

    async def _matches(self, ctx):
        schedule = await self._schedule(ctx)
        return schedule.setdefault(self.MATHCES_KEY, {})

    async def _save_matches(self, ctx, matches):
        schedule = await self._schedule(ctx)
        schedule[self.MATHCES_KEY] = matches
        await self._save_schedule(ctx, schedule)

    async def _team_days_index(self, ctx):
        schedule = await self._schedule(ctx)
        return schedule.setdefault(self.TEAM_DAY_INDEX_KEY, {})

    async def _save_team_days_index(self, ctx, team_days_index):
        schedule = await self._schedule(ctx)
        schedule[self.TEAM_DAY_INDEX_KEY] = team_days_index
        await self._save_schedule(ctx, schedule)

    async def _match_day(self, ctx):
        return await self.config.guild(ctx.guild).MatchDay()

    async def _save_match_day(self, ctx, match_day):
        await self.config.guild(ctx.guild).MatchDay.set(match_day)

    async def _team_day_match_index(self, ctx, team, match_day):
        team_days_index = await self._team_days_index(ctx)
        return team_days_index.get(
            self._team_day_key(team, match_day))

    def _team_day_key(self, team, match_day):
        return "{0}|{1}".format(team, match_day)

    async def _format_match_info(self, ctx, match_index, user_team_name=None):
        matches = await self._matches(ctx)
        match = matches[match_index]
        # Match format:
        # match_data = {
        #     'matchDay': match_day,
        #     'matchDate': match_date,
        #     'home': home,
        #     'away': away,
        #     'roomName': roomName,
        #     'roomPass': roomPass
        # }
        home = match['home']
        away = match['away']
        message = "__Match Day {0}: {1}__\n".format(match['matchDay'],
                                                    match['matchDate'])
        message += "**{0}**\n    versus\n**{1}**\n\n".format(home,
                                                             away)
        message += ("Room Name: **{0}**\nPassword: "
                    "**{1}**\n").format(match['roomName'], match['roomPass'])
        if user_team_name and user_team_name == home:
            message += ("\nYou are the **home** team. You will create the "
                        "room using the above information. Contact the "
                        "other team when your team is ready to begin the "
                        "match. Do not join a team until the away team starts "
                        "to.\n"
                        "Remember to ask before the match begins if the other "
                        "team would like to switch server region after 2 "
                        "games.")
        elif user_team_name and user_team_name == away:
            message += ("\nYou are the **away** team. You will join the room "
                        "using the above information once the other team "
                        "contacts you. Do not begin joining a team until "
                        "your entire team is ready to begin playing.")

        # TODO: Add other info (complaint form, disallowed maps,
        #       enable crossplay, etc.)
        # REGULAR SEASON INFO
        message += ("\n\nBe sure that **crossplay is enabled**. Be sure to save replays "
                    "and screenshots of the end-of-game scoreboard. Do not leave "
                    "the game until screenshots have been taken. "
                   "These must be uploaded by one member of your team after the 4-game series "
                   "is over. Remember that the deadline to reschedule matches is "
                   "at 10 minutes before the currently scheduled match time. They "
                   "can be scheduled no later than 11:59 PM ET on the original match day.\n\n") 
        # PLAYOFF INFO
                    # "Playoff matches are a best of 5 series for every round until the finals. "
                    # "Screenshots and replays do not need to be uploaded to the website for "
                    # "playoff matches but you will need to report the scores in #score-reporting.\n\n")

        message += "**Home Team:**\n"
        message += await self.team_manager.format_roster_info(ctx, home)
        message += "\n**Away Team:**\n"
        message += await self.team_manager.format_roster_info(ctx, away)

        return message

    def _generate_name_pass(self):
        # TODO: Load from file?
        set = [
            'octane', 'takumi', 'dominus', 'hotshot', 'batmobile', 'mantis',
            'paladin', 'twinmill', 'centio', 'breakout', 'animus', 'venom',
            'xdevil', 'endo', 'masamune', 'merc', 'backfire', 'gizmo',
            'roadhog', 'armadillo', 'hogsticker', 'luigi', 'mario', 'samus',
            'sweettooth', 'cyclone', 'imperator', 'jager', 'mantis', 'nimbus',
            'samurai', 'twinzer', 'werewolf', 'maverick', 'artemis', 'charger',
            'skyline', 'aftershock', 'boneshaker', 'delorean', 'esper',
            'fast4wd', 'gazella', 'grog', 'jeep', 'marauder', 'mclaren',
            'mr11', 'proteus', 'ripper', 'scarab', 'tumbler', 'triton',
            'vulcan', 'zippy',

            'aquadome', 'beckwith', 'champions', 'dfh', 'mannfield',
            'neotokyo', 'saltyshores', 'starbase', 'urban', 'utopia',
            'wasteland', 'farmstead', 'arctagon', 'badlands', 'core707',
            'dunkhouse', 'throwback', 'underpass', 'badlands',

            '20xx', 'biomass', 'bubbly', 'chameleon', 'dissolver', 'heatwave',
            'hexed', 'labyrinth', 'parallax', 'slipstream', 'spectre',
            'stormwatch', 'tora', 'trigon', 'wetpaint',

            'ara51', 'ballacarra', 'chrono', 'clockwork', 'cruxe',
            'discotheque', 'draco', 'dynamo', 'equalizer', 'gernot', 'hikari',
            'hypnotik', 'illuminata', 'infinium', 'kalos', 'lobo', 'looper',
            'photon', 'pulsus', 'raijin', 'reactor', 'roulette', 'turbine',
            'voltaic', 'wonderment', 'zomba',

            'unranked', 'prospect', 'challenger', 'risingstar', 'allstar',
            'superstar', 'champion', 'grandchamp', 'bronze', 'silver', 'gold',
            'platinum', 'diamond',

            'dropshot', 'hoops', 'soccar', 'rumble', 'snowday', 'solo',
            'doubles', 'standard', 'chaos',

            'armstrong', 'bandit', 'beast', 'boomer', 'buzz', 'cblock',
            'casper', 'caveman', 'centice', 'chipper', 'cougar', 'dude',
            'foamer', 'fury', 'gerwin', 'goose', 'heater', 'hollywood',
            'hound', 'iceman', 'imp', 'jester', 'junker', 'khan', 'marley',
            'maverick', 'merlin', 'middy', 'mountain', 'myrtle', 'outlaw',
            'poncho', 'rainmaker', 'raja', 'rex', 'roundhouse', 'sabretooth',
            'saltie', 'samara', 'scout', 'shepard', 'slider', 'squall',
            'sticks', 'stinger', 'storm', 'sultan', 'sundown', 'swabbie',
            'tex', 'tusk', 'viper', 'wolfman', 'yuri'
        ]
        return set[random.randrange(len(set))]
