import discord

from discord.ext import commands

class BulkRoleManager:
    """Used to manage roles role for large numbers of members"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(pass_context=True)
    async def getAllWithRole(self, ctx, role : discord.Role):
        empty = True
        for member in ctx.message.server.members:
            if role in member.roles:
                await self.bot.say("{0.name}#{0.numbers}".format(member))
                empty = False
        if empty:
            await self.bot.say("Nobody has the role {}".format(role.mention))

def setup(bot):
    bot.add_cog(BulkRoleManager(bot))