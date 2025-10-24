

import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from datetime import datetime
import json
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()
API_URL=os.getenv("API_URL")
CONFIG_FILE = "like_channels.json"

class LikeCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_host =API_URL
        self.config_data = self.load_config()
        self.cooldowns = {}
        self.session = aiohttp.ClientSession()


    def load_config(self):
        default_config = {
            "servers": {}
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    loaded_config = json.load(f)
                    loaded_config.setdefault("servers", {})
                    return loaded_config
            except json.JSONDecodeError:
                print(f"WARNING: The configuration file '{CONFIG_FILE}' is corrupt or empty. Resetting to default configuration.")
        self.save_config(default_config)
        return default_config

    def save_config(self, config_to_save=None):
        data_to_save = config_to_save if config_to_save is not None else self.config_data
        temp_file = CONFIG_FILE + ".tmp"
        with open(temp_file, 'w') as f:
            json.dump(data_to_save, f, indent=4)
        os.replace(temp_file, CONFIG_FILE)

    async def check_channel(self, ctx):
        if ctx.guild is None:
            return True
        guild_id = str(ctx.guild.id)
        like_channels = self.config_data["servers"].get(guild_id, {}).get("like_channels", [])
        return not like_channels or str(ctx.channel.id) in like_channels

    async def cog_load(self):
        pass

    @commands.hybrid_command(name="setlikechannel", description="Sets the channels where the /like command is allowed.")
    @commands.has_permissions(administrator=True)
    @app_commands.describe(channel="The channel to allow/disallow the /like command in.")
    async def set_like_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.", ephemeral=True)
            return

        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        like_channels = server_config.setdefault("like_channels", [])

        channel_id_str = str(channel.id)

        if channel_id_str in like_channels:
            like_channels.remove(channel_id_str)
            self.save_config()
            await ctx.send(f"✅ Channel {channel.mention} has been **removed** from allowed channels for /like commands. The command is now **disallowed** there.", ephemeral=True)
        else:
            like_channels.append(channel_id_str)
            self.save_config()
            await ctx.send(f"✅ Channel {channel.mention} is now **allowed** for /like commands. The command will **only** work in specified channels if any are set.", ephemeral=True)

    @commands.hybrid_command(name="like", description="Sends likes to a Free Fire player")
    @app_commands.describe(uid="Player UID (numbers only, minimum 6 characters)")
    async def like_command(self, ctx: commands.Context,server:str=None , uid: str = None):
        is_slash = ctx.interaction is not None

        if uid and server is None:
            return await ctx.send("UID and server are required",delete_after=10)
        if not await self.check_channel(ctx):
            msg = "This command is not available in this channel. Please use it in an authorized channel."
            if is_slash:
                await ctx.response.send_message(msg, ephemeral=True)
            else:
                await ctx.reply(msg, mention_author=False)
            return

        user_id = ctx.author.id
        cooldown = 30
        if user_id in self.cooldowns:
            last_used = self.cooldowns[user_id]
            remaining = cooldown - (datetime.now() - last_used).seconds
            if remaining > 0:
                await ctx.send(f"Please wait {remaining} seconds before using this command again.", ephemeral=is_slash)
                return
        self.cooldowns[user_id] = datetime.now()

        if not uid.isdigit() or len(uid) < 6:
            await ctx.reply("Invalid UID. It must contain only numbers and be at least 6 characters long.", mention_author=False, ephemeral=is_slash)
            return


        try:
            async with ctx.typing():
                url = f"{self.api_host}/like?uid={uid}&server={server}"
                print(url)
                async with self.session.get(url ) as response:
                    if response.status == 404:
                        await self._send_player_not_found(ctx, uid)
                        return

                    if response.status != 200:
                        print(f"API Error: {response.status} - {await response.text()}")
                        await self._send_api_error(ctx)
                        return

                    data = await response.json()
                    embed = discord.Embed(
                        title="FREE FIRE LIKE",
                        color=0x2ECC71 if data.get("status") == 1 else 0xE74C3C,
                        timestamp=datetime.now()
                    )

                    if data.get("status") == 1:
                        embed.description = (
                            f"\n"
                            f"┌  হিসাব\n"
                            f"├─ ডাকনাম : {data.get('player', 'Unknown')}\n"
                            f"├─ UID: {uid}\n"
                            f"└─ ফলাফল :\n"
                            f"   ├─ যোগ করা হয়েছে: +{data.get('likes_added', 0)}\n"
                            f"   ├─ আগে: {data.get('likes_before', 'N/A')}\n"
                            f"   └─ পরবর্তী: {data.get('likes_after', 'N/A')}\n"
                        )
                    else:
                        embed.description = "এই UID আজ সর্বাধিক লাইক পেয়েছে।.\nঅনুগ্রহ করে ২৪ ঘন্টা অপেক্ষা করুন এবং আবার চেষ্টা করুন।"

                    embed.set_footer(text="আমাদের সাথে থাকার জন্য আপনাকে ধন্যবাদ।")
                    
                    await ctx.send(embed=embed, mention_author=True, ephemeral=is_slash)

        except asyncio.TimeoutError:
            await self._send_error_embed(ctx, "Timeout", "The server took too long to respond.", ephemeral=is_slash)
        except Exception as e:
            print(f"Unexpected error in like_command: {e}")
            await self._send_error_embed(ctx, "Critical Error", "চিন্তা করবেন না , কোনো সমস্যা হলে এডমিন কে dm করুন , ধন্যবাদ ", ephemeral=is_slash)

    async def _send_player_not_found(self, ctx, uid):
        embed = discord.Embed(title="Player Not Found", description=f"The UID {uid} does not exist or is not accessible.", color=0xE74C3C)
        embed.add_field(name="Tip", value="Make sure that:\n- The UID is correct\n- The player is not private", inline=False)
        await ctx.send(embed=embed, ephemeral=True)
        
    async def _send_api_error(self, ctx):
        embed = discord.Embed(title="⚠️ Service Unavailable", description="দয়া করে অপেক্ষা  করেন জয় ভাই ঠিক করবে , চিন্তা করবেন  নাহ .", color=0xF39C12)
        embed.add_field(name="Solution", value="কয়েক মিনিটের মধ্যে আবার চেষ্টা করুন।.", inline=False)
        await ctx.send(embed=embed, ephemeral=True)

    async def _send_error_embed(self, ctx, title, description, ephemeral=True):
        embed = discord.Embed(title=f"❌ {title}", description=description, color=discord.Color.red(), timestamp=datetime.now())
        embed.set_footer(text="An error occurred.")
        await ctx.send(embed=embed, ephemeral=ephemeral)

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

async def setup(bot):
    await bot.add_cog(LikeCommands(bot))
