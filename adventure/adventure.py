import asyncio
import discord
import json
import random
import time
import logging
import os
from typing import Optional

from redbot.core import commands, bank, checks, Config
from redbot.core.commands.context import Context
from redbot.core.data_manager import bundled_data_path
from redbot.core.utils.chat_formatting import box, pagify, bold, humanize_list, escape
from redbot.core.utils.common_filters import filter_various_mentions
from redbot.core.utils.predicates import MessagePredicate, ReactionPredicate
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS, start_adding_reactions

from .charsheet import Character, Item, GameSession, AdventureGroup


BaseCog = getattr(commands, "Cog", object)

log = logging.getLogger("red.adventure")


class Adventure(BaseCog):
    """Adventure, derived from the Goblins Adventure cog by locastan"""

    def __init__(self, bot):
        self.bot = bot
        self._last_trade = {}

        self._adventure_actions = ["🗡", "🌟", "🗨", "🛐", "🏃"]
        self._adventure_run = ["🏃"]
        self._adventure_controls = {"fight": "🗡", "magic": "🌟", "talk": "🗨", "pray": "🛐", "run": "🏃"}
        self._order = [
            "head",
            "neck",
            "chest",
            "gloves",
            "belt",
            "legs",
            "boots",
            "left",
            "right",
            "two handed",
            "ring",
            "charm",
        ]
        self._group_actions = ["🗡", "🌟", "🗨", "🛐"]
        self._group_controls = {"fight": "🗡", "magic": "🌟", "talk": "🗨", "pray": "🛐"}
        self._treasure_controls = {"✅": "equip", "❎": "backpack", "💰": "sell"}

        self._adventure_countdown = {}
        self._rewards = {}
        self._trader_countdown = {}
        self._current_traders = {}
        self._sessions = {}
        self._groups = {}
        self.tasks = []

        self.config = Config.get_conf(self, 2710801001, force_registration=True)

        default_user = {
            "exp": 0,
            "lvl": 1,
            "att": 0,
            "cha": 0,
            "int": 0,
            "treasure": [0, 0, 0, 0],
            "items": {
                "head": {},
                "neck": {},
                "chest": {},
                "gloves": {},
                "belt": {},
                "legs": {},
                "boots": {},
                "left": {},
                "right": {},
                "ring": {},
                "charm": {},
                "backpack": {},
            },
            "loadouts": {},
            "class": {
                "name": "Hero",
                "ability": False,
                "desc": "Your basic adventuring hero.",
                "forage": 0,
            },
            "skill": {"pool": 0, "att": 0, "cha": 0, "int": 0},
        }

        default_guild = {"cart_channels": [], "god_name": "", "cart_name": "", "embed": True}
        default_global = {"god_name": "Herbert", "cart_name": "Hawl's brother", "theme": "default"}

        self.RAISINS: list = None
        self.THREATEE: list = None
        self.TR_COMMON: dict = None
        self.TR_RARE: dict = None
        self.TR_EPIC: dict = None
        self.TR_LEGENDARY: dict = None
        self.ATTRIBS: dict = None
        self.MONSTERS: dict = None
        self.LOCATIONS: list = None
        self.PETS: dict = None

        self.config.register_guild(**default_guild)
        self.config.register_global(**default_global)
        self.config.register_user(**default_user)
        self.cleanup_loop = self.bot.loop.create_task(self.cleanup_tasks())

    def __unload(self):
        for task in self.tasks:
            log.debug(f"removing task {task}")
            task.cancel()

    async def initialize(self):
        """This will load all the bundled data into respective variables"""
        theme = await self.config.theme()
        pets = bundled_data_path(self) / "{theme}/pets.json".format(theme=theme)
        with pets.open("r") as f:
            self.PETS = json.load(f)
        attribs_fp = bundled_data_path(self) / "{theme}/attribs.json".format(theme=theme)
        with attribs_fp.open("r") as f:
            self.ATTRIBS = json.load(f)
        monster_fp = bundled_data_path(self) / "{theme}/monsters.json".format(theme=theme)
        with monster_fp.open("r") as f:
            self.MONSTERS = json.load(f)
        locations_fp = bundled_data_path(self) / "{theme}/locations.json".format(theme=theme)
        with locations_fp.open("r") as f:
            self.LOCATIONS = json.load(f)
        raisins_fp = bundled_data_path(self) / "{theme}/raisins.json".format(theme=theme)
        with raisins_fp.open("r") as f:
            self.RAISINS = json.load(f)
        threatee_fp = bundled_data_path(self) / "{theme}/threatee.json".format(theme=theme)
        with threatee_fp.open("r") as f:
            self.THREATEE = json.load(f)
        common_fp = bundled_data_path(self) / "{theme}/tr_common.json".format(theme=theme)
        with common_fp.open("r") as f:
            self.TR_COMMON = json.load(f)
        rare_fp = bundled_data_path(self) / "{theme}/tr_rare.json".format(theme=theme)
        with rare_fp.open("r") as f:
            self.TR_RARE = json.load(f)
        epic_fp = bundled_data_path(self) / "{theme}/tr_epic.json".format(theme=theme)
        with epic_fp.open("r") as f:
            self.TR_EPIC = json.load(f)
        legendary_fp = bundled_data_path(self) / "{theme}/tr_legendary.json".format(theme=theme)
        with legendary_fp.open("r") as f:
            self.TR_LEGENDARY = json.load(f)

    async def cleanup_tasks(self):
        await self.bot.wait_until_ready()
        while self is self.bot.get_cog("Adventure"):
            for task in self.tasks:
                if task.done():
                    self.tasks.remove(task)
            await asyncio.sleep(300)

    async def allow_in_dm(self, ctx):
        """Checks if the bank is global and allows the command in dm"""
        if ctx.guild is not None:
            return True
        if ctx.guild is None and await bank.is_global():
            return True
        else:
            return False

    @staticmethod
    def E(t: str) -> str:
        return escape(filter_various_mentions(t), mass_mentions=True, formatting=True)

    @commands.command(hidden=True)
    @commands.is_owner()
    async def makecart(self, ctx):
        """
            Force cart to appear in a channel
        """
        await self._trader(ctx)

    @commands.group(name="backpack", autohelp=False)
    async def _backpack(self, ctx):
        """This shows the contents of your backpack.

        Selling: `[p]backpack sell item_name`
                 `[p]backpack sellrarity rarity_type
        Trading: `[p]backpack trade @user price item_name`
        Equip:   `[p]backpack equip item_name`
        or respond with the item name to the backpack command output.
        """
        if not await self.allow_in_dm(ctx):
            return await ctx.send("This command is not available in DM's on this bot.")
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        # bkpk = "Items in Backpack: \n"
        if not ctx.invoked_subcommand:
            backpack_contents = (
                f"[{self.E(ctx.author.display_name)}'s backpack] \n\n{c.__backpack__()}\n"
                f"(Reply with the name of an item or use {ctx.prefix}backpack "
                "equip 'name of item' to equip it.)"
            )
            for page in pagify(backpack_contents, delims=["\n"], shorten_by=20):
                await ctx.send(box(page, lang="css"))

            try:
                reply = await ctx.bot.wait_for(
                    "message", check=MessagePredicate.same_context(ctx), timeout=30
                )
            except asyncio.TimeoutError:
                return
            if not reply:
                return
            else:
                equip = None
                for name, item in c.backpack.items():
                    if (
                        reply.content.lower() in item.name.lower()
                        or reply.content.lower() in str(item).lower()
                    ):
                        equip = item
                        break
                if equip:
                    slot = item.slot[0]
                    if len(item.slot) > 1:
                        slot = "two handed"
                    if not getattr(c, item.slot[0]):
                        equip_msg = box(
                            f"{self.E(ctx.author.display_name)} equipped {item} ({slot} slot).",
                            lang="css",
                        )
                    else:
                        equip_msg = box(
                            (
                                f"{self.E(ctx.author.display_name)} equipped {item} "
                                f"({slot} slot) and put "
                                f"{humanize_list([str(getattr(c, s)) for s in item.slot])} "
                                "into their backpack."
                            ),
                            lang="css",
                        )
                    c = await c._equip_item(item, True)
                    # log.info(c)
                    await self.config.user(ctx.author).set(c._to_json())
                    current_stats = box(
                        (
                            f"{self.E(ctx.author.display_name)}'s new stats: "
                            f"Attack: {c.att} [{c.skill['att']}], "
                            f"Intelligence: {c.int} [{c.skill['int']}], "
                            f"Diplomacy: {c.cha} [{c.skill['cha']}]."
                        ),
                        lang="css",
                    )
                    await ctx.send(equip_msg + current_stats)

    @_backpack.command(name="equip")
    async def backpack_equip(self, ctx, *, equip_item: str):
        """Equip an item from your backpack"""
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        equip = None
        for name, item in c.backpack.items():
            if equip_item.lower() in item.name.lower() or equip_item.lower() in str(item).lower():
                equip = item
                break
        if equip:
            slot = item.slot[0]
            if len(item.slot) > 1:
                slot = "two handed"
            if not getattr(c, item.slot[0]):
                equip_msg = box(
                    f"{self.E(ctx.author.display_name)} equipped {item} ({slot} slot).", lang="css"
                )
            else:
                equip_msg = box(
                    (
                        f"{self.E(ctx.author.display_name)} equipped {item} "
                        f"({slot} slot) and put {getattr(c, item.slot[0])} into their backpack."
                    ),
                    lang="css",
                )
            await ctx.send(equip_msg)
            c = await c._equip_item(item, True)
            await self.config.user(ctx.author).set(c._to_json())

    @_backpack.command(name="sell")
    async def backpack_sell(self, ctx, *, item: str):
        """Sell an item from your backpack"""
        if item.startswith("."):
            item = item.replace("_", " ").replace(".", "")
        if item.startswith("["):
            item = item.replace("[", "").replace("]", "")
        if item.startswith("{.:'"):
            item = item.replace("{.:'", "").replace("':.}", "")
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if not any([x for x in c.backpack if item.lower() in x.lower()]):
            await ctx.send(
                f"{self.E(ctx.author.display_name)}, you have to specify "
                "an item (or partial name) from your backpack to sell."
            )
            return
        lookup = list(i for x, i in c.backpack.items() if item.lower() in x.lower())
        forged = [x for x in lookup if x.rarity == "forged"]
        if any(forged):
            device = forged[0]
            return await ctx.send(
                box(
                    (
                        f"\n{self.E(ctx.author.display_name)}, your {device} is "
                        "refusing to be sold and bit your finger for trying."
                    ),
                    lang="css",
                )
            )    
        await self._sell_items(ctx, lookup, c)
        
    @_backpack.command(name="sellrarity")
    async def backpack_sellrarity(self, ctx, *, rarity: str):
        if rarity.lower() not in ["normal", "rare", "epic", "legendary"]:
            return await ctx.send(
                box(
                    (
                        f"{self.E(ctx.author.display_name)}, {rarity} is not a valid loot type"
                        f"(normal, rare, epic, legendary)\n"
                    ),
                    lang="css",
                )
            )
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return

        item_list = list(i for x, i in c.backpack.items() if rarity.lower() in i.rarity)
        if not any(item_list):
            await ctx.send(
                box(
                    (
                        f"{self.E(ctx.author.display_name)}, you do not have "
                        f"any items of that rarity to sell."
                    ),
                    lang="css",
                )
            )
            return
        await self._sell_items(ctx, item_list, c)
        
    async def _sell_items(self, ctx, lookup: list, c: Character):
        item_str = box(humanize_list([f"{str(y)} - {y.owned}" for y in lookup]), lang="css")
        start_msg = await ctx.send(
            f"{self.E(ctx.author.display_name)}, do you want to sell these items? {item_str}"
        )
        currency_name = await bank.get_currency_name(ctx.guild)
        emojis = [
            "\N{DIGIT ONE}\N{COMBINING ENCLOSING KEYCAP}",
            "\N{CLOCKWISE RIGHTWARDS AND LEFTWARDS OPEN CIRCLE ARROWS}",
            "\N{CLOCKWISE RIGHTWARDS AND LEFTWARDS OPEN CIRCLE ARROWS WITH CIRCLED ONE OVERLAY}",
            "\N{CROSS MARK}",
        ]
        start_adding_reactions(start_msg, emojis)
        pred = ReactionPredicate.with_emojis(emojis, start_msg)
        try:
            await ctx.bot.wait_for("reaction_add", check=pred, timeout=60)
        except asyncio.TimeoutError:
            await self._clear_react(start_msg)
            return
        msg = ""
        if pred.result == 0:  # user reacted with one to sell.
            # sell one of the item
            total = 0
            for item in lookup:
                item.owned -= 1
                item_price = await self._sell(ctx.author, item)
                total += item_price
                msg += (
                    f"{self.E(ctx.author.display_name)} sold their "
                    f"{str(item)} for {item_price} {currency_name}.\n"
                )
                if item.owned <= 0:
                    del c.backpack[item.name]
            await bank.deposit_credits(ctx.author, total)
        if pred.result == 1:  # user wants to sell all owned.
            total = 0
            for item in lookup:
                item_total = 0
                for x in range(0, item.owned):
                    item.owned -= 1
                    item_price = await self._sell(ctx.author, item)
                    item_total += item_price
                    if item.owned <= 0:
                        del c.backpack[item.name]
                msg += (
                    f"{self.E(ctx.author.display_name)} sold all their "
                    f"{str(item)} for {item_total} {currency_name}.\n"
                )
                total += item_total
            await bank.deposit_credits(ctx.author, total)
        if pred.result == 2:  # user wants to sell all but one.
            total = 0
            for item in lookup:
                item_total = 0
                for x in range(1, item.owned):
                    item.owned -= 1
                    item_price = await self._sell(ctx.author, item)
                    item_total += item_price
                if item_total != 0:
                    msg += (
                        f"{self.E(ctx.author.display_name)} sold all but one of their "
                        f"{str(item)} for {item_total} {currency_name}.\n"
                    )
                total += item_total
            await bank.deposit_credits(ctx.author, total)
        if pred.result == 3:  # user doesn't want to sell those items.
            msg = "Not selling those items."
        if msg:
            await self.config.user(ctx.author).set(c._to_json())
            for page in pagify(msg, delims=["\n"]):
                await ctx.send(page)

    @_backpack.command(name="trade")
    async def backpack_trade(
        self, ctx, buyer: discord.Member, asking: Optional[int] = 1000, *, item
    ):
        """Trade an item from your backpack to another user"""
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if not any([x for x in c.backpack if item.lower() in x.lower()]):
            return await ctx.send(
                f"{self.E(ctx.author.display_name)}, you have to "
                "specify an item from your backpack to trade."
            )
        lookup = list(x for n, x in c.backpack.items() if item.lower() in x.name.lower())
        if len(lookup) > 1:
            await ctx.send(
                (
                    f"{self.E(ctx.author.display_name)}, I found multiple items "
                    f"({humanize_list([x.name for x in lookup])}) "
                    "matching that name in your backpack.\nPlease be more specific."
                )
            )
            return
        if any([x for x in lookup if x.rarity == "forged"]):
            device = [x for x in lookup if "{.:'" in x.lower()]
            return await ctx.send(
                box(
                    (
                        f"\n{self.E(ctx.author.display_name)}, your "
                        f"{device} does not want to leave you."
                    ),
                    lang="css",
                )
            )
        else:
            item = lookup[0]
            hand = item.slot[0] if len(item.slot) < 2 else "two handed"
            currency_name = await bank.get_currency_name(ctx.guild)
            if str(currency_name).startswith("<"):
                currency_name = "credits"
            trade_talk = box(
                (
                    f"{self.E(ctx.author.display_name)} wants to sell "
                    f"{item}. (Attack: {str(item.att)}, Intelligence: {str(item.int)}), "
                    f"Charisma: {str(item.cha)} "
                    f"[{hand}])\n{self.E(buyer.display_name)}, "
                    f"do you want to buy this item for {str(asking)} {currency_name}?"
                ),
                lang="css",
            )
            trade_msg = await ctx.send(f"{buyer.mention}\n{trade_talk}")
            start_adding_reactions(trade_msg, ReactionPredicate.YES_OR_NO_EMOJIS)
            pred = ReactionPredicate.yes_or_no(trade_msg, buyer)
            try:
                await ctx.bot.wait_for("reaction_add", check=pred, timeout=60)
            except asyncio.TimeoutError:
                await self._clear_react(trade_msg)
                return
            if pred.result:  # buyer reacted with Yes.
                try:
                    if await bank.can_spend(buyer, asking):
                        bal = await bank.transfer_credits(buyer, ctx.author, asking)
                        c.backpack[item.name].owned -= 1
                        if c.backpack[item.name].owned <= 0:
                            del c.backpack[item.name]
                        await self.config.user(ctx.author).set(c._to_json())
                        try:
                            buy_user = await Character._from_json(self.config, buyer)
                        except Exception:
                            log.error("Error with the new character sheet", exc_info=True)
                            return
                        if item.name in buy_user.backpack:
                            buy_user.backpack[item.name].owned += 1
                        else:
                            item.owned = 1
                            buy_user.backpack[item.name] = item
                        await self.config.user(buyer).set(buy_user._to_json())
                        await trade_msg.edit(
                            content=(
                                box(
                                    (
                                        f"\n{self.E(ctx.author.display_name)} traded {item} to "
                                        f"{self.E(buyer.display_name)} for "
                                        f"{asking} {currency_name}."
                                    ),
                                    lang="css",
                                )
                            )
                        )
                        await self._clear_react(trade_msg)
                    else:
                        await trade_msg.edit(
                            content=(
                                f"{self.E(buyer.display_name)}, "
                                f"you do not have enough {currency_name}."
                            )
                        )
                except discord.errors.NotFound:
                    pass
            else:
                try:
                    await trade_msg.delete()
                except discord.errors.Forbidden:
                    pass

    @commands.command()
    @commands.guild_only()
    @commands.cooldown(rate=1, per=900, type=commands.BucketType.user)
    async def bless(self, ctx):
        """[Cleric Class Only]

        This allows a praying Cleric to add
        substantial bonuses for heroes fighting the battle.
        (15min cooldown)
        """

        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if c.heroclass["name"] != "Cleric":
            ctx.command.reset_cooldown(ctx)
            return await ctx.send(
                f"{self.E(ctx.author.display_name)}, you need to be a Cleric to do this."
            )
        else:
            if c.heroclass["ability"]:
                return await ctx.send(
                    f"{self.E(ctx.author.display_name)}, ability already in use."
                )
            c.heroclass["ability"] = True
            await self.config.user(ctx.author).set(c._to_json())
            await ctx.send(
                f"📜 {bold(self.E(ctx.author.display_name))} " f"is starting an inspiring sermon. 📜"
            )

    @commands.group(aliases=["loadouts"])
    async def loadout(self, ctx):
        """Setup various adventure settings"""
        pass

    @loadout.command(name="save")
    async def save_loadout(self, ctx, name: str):
        """Save your current equipment as a loadout"""
        if not await self.allow_in_dm(ctx):
            return await ctx.send("This command is not available in DM's on this bot.")
        name = name.lower()
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if name in c.loadouts:
            await ctx.send(
                f"{self.E(ctx.author.display_name)}, you already have a loadout named {name}."
            )
            return
        else:
            loadout = await Character._save_loadout(c)
            c.loadouts[name] = loadout
            await self.config.user(ctx.author).set(c._to_json())
            await ctx.send(
                f"{self.E(ctx.author.display_name)}, your "
                f"current equipment has been saved to {name}."
            )

    @loadout.command(name="delete", aliases=["del", "rem", "remove"])
    async def remove_loadout(self, ctx, name: str):
        """Delete a saved loadout"""
        if not await self.allow_in_dm(ctx):
            return await ctx.send("This command is not available in DM's on this bot.")
        name = name.lower()
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if name not in c.loadouts:
            await ctx.send(
                f"{self.E(ctx.author.display_name)}, you don't have a loadout named {name}."
            )
            return
        else:
            del c.loadouts[name]
            await self.config.user(ctx.author).set(c._to_json())
            await ctx.send(f"{self.E(ctx.author.display_name)}, loadout {name} has been deleted.")

    @loadout.command(name="show")
    async def show_loadout(self, ctx, name: str = None):
        """Show saved loadouts"""
        if not await self.allow_in_dm(ctx):
            return await ctx.send("This command is not available in DM's on this bot.")
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if not c.loadouts:
            await ctx.send(
                f"{self.E(ctx.author.display_name)}, you don't have any loadouts saved."
            )
            return
        if name is not None and name.lower() not in c.loadouts:
            await ctx.send(
                f"{self.E(ctx.author.display_name)}, you don't have a loadout named {name}."
            )
            return
        else:
            msg_list = []
            index = 0
            count = 0
            for l_name, loadout in c.loadouts.items():
                if name and name.lower() == l_name:
                    index = count
                stats = await self._build_loadout_display({"items": loadout})
                msg = f"[{l_name} Loadout for {self.E(ctx.author.display_name)}]\n\n{stats}"
                msg_list.append(box(msg, lang="css"))
                count += 1
            await menu(ctx, msg_list, DEFAULT_CONTROLS, page=index)

    @loadout.command(name="equip", aliases=["load"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.user)
    async def equip_loadout(self, ctx, name: str):
        """Equip a saved loadout"""
        if not await self.allow_in_dm(ctx):
            return await ctx.send("This command is not available in DM's on this bot.")
        
        bal = await bank.get_balance(ctx.author)
        currency_name = await bank.get_currency_name(ctx.guild)
        if str(currency_name).startswith("<"):
            currency_name = "credits"
        spend = 1000
        msg = await ctx.send(
            box(
                (
                    f"This will cost {spend} {currency_name}. "
                    f"Do you want to continue, {self.E(ctx.author.display_name)}?"
                ),
                lang="css",
            )
        )
        broke = box(
            f"You don't have enough {currency_name} to pay your squire.",
            lang="css",
        )

        start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)
        pred = ReactionPredicate.yes_or_no(msg, ctx.author)
        try:
            await ctx.bot.wait_for("reaction_add", check=pred, timeout=60)
        except asyncio.TimeoutError:
            await self._clear_react(msg)
            return

        if not pred.result:
            await msg.edit(
                content=box(
                    (
                        f"{self.E(ctx.author.display_name)} decided"
                        f" not to change his loadout."
                    ),
                    lang="css",
                )
            )
            return await self._clear_react(msg)
        try:
            await bank.withdraw_credits(ctx.author, spend)
            await msg.edit(content=box(f"Your squire changed you in record time.", lang="css",))
            await self._clear_react(msg)
        except ValueError:
            await self._clear_react(msg)
            return await msg.edit(content=broke)

        name = name.lower()
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if name not in c.loadouts:
            await ctx.send(
                f"{self.E(ctx.author.display_name)}, you don't have a loadout named {name}."
            )
            return
        else:
            c = await c._equip_loadout(name)
            current_stats = box(
                (
                    f"{self.E(ctx.author.display_name)}'s new stats: "
                    f"Attack: {c.__stat__('att')} [{c.skill['att']}], "
                    f"Intelligence: {c.__stat__('int')} [{c.skill['int']}], "
                    f"Diplomacy: {c.__stat__('cha')} [{c.skill['cha']}]."
                ),
                lang="css",
            )
            await ctx.send(current_stats)
            await self.config.user(ctx.author).set(c._to_json())

    @commands.group()
    @checks.admin_or_permissions(administrator=True)
    @commands.guild_only()
    async def adventureset(self, ctx):
        """Setup various adventure settings"""
        pass

    @adventureset.command()
    async def god(self, ctx, *, name):
        """[Admin] Set the server's name of the god"""
        await self.config.guild(ctx.guild).god_name.set(name)
        await ctx.tick()

    @adventureset.command()
    @checks.is_owner()
    async def globalgod(self, ctx, *, name):
        """[Owner] Set the default name of the god"""
        await self.config.god_name.set(name)
        await ctx.tick()

    @adventureset.command(aliases=["embed"])
    async def embeds(self, ctx):
        """[Admin] Set whether or not to use embeds for the adventure game"""
        toggle = await self.config.guild(ctx.guild).embed()
        await self.config.guild(ctx.guild).embed.set(not toggle)
        await ctx.send(f"Embeds: {not toggle}")

    @adventureset.command()
    async def cartname(self, ctx, *, name):
        """[Admin] Set the server's name of the cart"""
        await self.config.guild(ctx.guild).cart_name.set(name)
        await ctx.tick()

    @adventureset.command()
    @checks.is_owner()
    async def globalcartname(self, ctx, *, name):
        """[Owner] Set the default name of the cart"""
        await self.config.cart_name.set(name)
        await ctx.tick()

    @adventureset.command()
    @checks.is_owner()
    async def theme(self, ctx, *, theme):
        """Change the theme for adventure"""
        log.debug(os.listdir(bundled_data_path(self) / "default"))
        if theme not in os.listdir(bundled_data_path(self)):
            await ctx.send("That theme pack does not exist!")
            return
        good_files = [
            "attribs.json",
            "bosses.json",
            "locations.json",
            "minibosses.json",
            "monsters.json",
            "pets.json",
            "raisins.json",
            "threatee.json",
            "tr_common.json",
            "tr_epic.json",
            "tr_rare.json",
            "tr_legendary.json",
        ]
        if os.listdir(bundled_data_path(self) / theme) != good_files:
            await ctx.send(
                "That theme pack is missing one or more"
                f"of the following files {humanize_list(good_files)}"
            )
            return
        else:
            await self.config.theme.set(theme)
            await ctx.tick()

    @adventureset.command()
    @checks.admin_or_permissions(administrator=True)
    @commands.guild_only()
    async def cart(self, ctx, *, channel: discord.TextChannel = None):
        """[Admin] Add or remove a text channel that the Trader cart can appear in.

        If the channel is already in the list, it will be removed.
        Use `[p]adventureset cart` with no arguments to show the channel list.
        """

        channel_list = await self.config.guild(ctx.guild).cart_channels()
        if not channel_list:
            channel_list = []
        if channel is None:
            msg = "Active Cart Channels:\n"
            if not channel_list:
                msg += "None."
            else:
                name_list = []
                for chan_id in channel_list:
                    name_list.append(self.bot.get_channel(chan_id))
                msg += "\n".join(chan.name for chan in name_list)
            return await ctx.send(box(msg))
        elif channel.id in channel_list:
            new_channels = channel_list.remove(channel.id)
            await ctx.send(f"The {channel} channel has been removed from the cart delivery list.")
            return await self.config.guild(ctx.guild).cart_channels.set(new_channels)
        else:
            channel_list.append(channel.id)
            await ctx.send(f"The {channel} channel has been added to the cart delivery list.")
            await self.config.guild(ctx.guild).cart_channels.set(channel_list)

    @commands.command()
    @commands.cooldown(rate=1, per=4, type=commands.BucketType.guild)
    async def convert(self, ctx, box_rarity: str, amount: int = 1):
        """Convert normal, rare or epic chests.

        Trade 6 normal treasure chests for 1 rare treasure chest.
        Trade 5 rare treasure chests for 1 epic treasure chest.
        Trade 4 epic treasure chests for 1 legendary treasure chest.
        """

        # Thanks to flare#0001 for the idea and writing the first instance of this
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if amount > 1:
            plural = "s"
        else:
            plural = ""
        if box_rarity.lower() == "normal":
            if c.treasure[0] >= (6 * amount):
                c.treasure[0] -= 6 * amount
                c.treasure[1] += 1 * amount
                await ctx.send(
                    box(
                        (
                            f"Successfully converted {(6 * amount)} normal treasure "
                            f"chests to {(1 * amount)} rare treasure chest{plural}. "
                            f"\n{self.E(ctx.author.display_name)} "
                            f"now owns {c.treasure[0]} normal, "
                            f"{c.treasure[1]} rare, {c.treasure[2]} epic "
                            f"and {c.treasure[3]} legendary treasure chests."
                        ),
                        lang="css",
                    )
                )
                await self.config.user(ctx.author).set(c._to_json())
            else:
                await ctx.send(
                    f"{self.E(ctx.author.display_name)}, you do not have {(6 * amount)} "
                    "normal treasure chests to convert."
                )
        elif box_rarity.lower() == "rare":
            if c.treasure[1] >= (5 * amount):
                c.treasure[1] -= 5 * amount
                c.treasure[2] += 1 * amount
                await ctx.send(
                    box(
                        (
                            f"Successfully converted {(5 * amount)} rare treasure "
                            f"chests to {(1 * amount)} epic treasure chest{plural}. "
                            f"\n{self.E(ctx.author.display_name)} "
                            f"now owns {c.treasure[0]} normal, "
                            f"{c.treasure[1]} rare, {c.treasure[2]} epic "
                            f"and {c.treasure[3]} legendary treasure chests."
                        ),
                        lang="css",
                    )
                )
                await self.config.user(ctx.author).set(c._to_json())
            else:
                await ctx.send(
                    f"{self.E(ctx.author.display_name)}, you do not have {(5 * amount)} "
                    "rare treasure chests to convert."
                )
        elif box_rarity.lower() == "epic":
            if c.treasure[2] >= (4 * amount):
                c.treasure[2] -= 4 * amount
                c.treasure[3] += 1 * amount
                await ctx.send(
                    box(
                        (
                            f"Successfully converted {(4 * amount)} epic treasure "
                            f"chests to {(1 * amount)} legendary treasure chest{plural}. "
                            f"\n{self.E(ctx.author.display_name)} "
                            f"now owns {c.treasure[0]} normal, "
                            f"{c.treasure[1]} rare, {c.treasure[2]} epic "
                            f"and {c.treasure[3]} legendary treasure chests."
                        ),
                        lang="css",
                    )
                )
                await self.config.user(ctx.author).set(c._to_json())
            else:
                await ctx.send(
                    f"{self.E(ctx.author.display_name)}, you do not have {(4 * amount)} "
                    "epic treasure chests to convert."
                )
        else:
            await ctx.send(
                f"{self.E(ctx.author.display_name)}, please select"
                " between normal, rare or epic treasure chests to convert."
            )

    @commands.command()
    async def equip(self, ctx, *, item: str = None):
        """This equips an item from your backpack.

        `[p]equip "name of item"`
        """
        if not await self.allow_in_dm(ctx):
            return await ctx.send("This command is not available in DM's on this bot.")
        if not item:
            return await ctx.send("Please use an item name with this command.")
        await ctx.invoke(self.backpack_equip, equip_item=item)

    @commands.command()
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.user)
    async def forge(self, ctx):
        """[Tinkerer Class Only]

        This allows a Tinkerer to forge two items into a device.
        (5s cooldown)
        """
        if not await self.allow_in_dm(ctx):
            return await ctx.send("This command is not available in DM's on this bot.")
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if c.heroclass["name"] != "Tinkerer":
            ctx.command.reset_cooldown(ctx)
            return await ctx.send(
                f"{self.E(ctx.author.display_name)}, you need to be a Tinkerer to do this."
            )
        else:
            consumed = []
            forgeables = len([i for n, i in c.backpack.items() if i.rarity != "forged"])
            if forgeables <= 1:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(
                    f"{self.E(ctx.author.display_name)}, you need at least"
                    " two forgeable items in your backpack to forge."
                )
            forgeables = (
                f"[{self.E(ctx.author.display_name)}'s forgeables]\n"
                f"{c.__backpack__(True)}\n(Reply with the full or partial name "
                "of item 1 to select for forging. Try to be specific.)"
            )
            for page in pagify(forgeables, delims=["\n"], shorten_by=20):
                await ctx.send(box(page, lang="css"))

            try:
                reply = await ctx.bot.wait_for(
                    "message", check=MessagePredicate.same_context(ctx), timeout=30
                )
            except asyncio.TimeoutError:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(
                    f"I don't have all day you know, {self.E(ctx.author.display_name)}."
                )
            for name, item in c.backpack.items():
                if reply.content.lower() in name.lower():
                    if item.rarity != "forgeable":
                        consumed.append(item)
                        break
                    else:
                        ctx.command.reset_cooldown(ctx)
                        return await ctx.send(
                            f"{self.E(ctx.author.display_name)}, "
                            "tinkered devices cannot be reforged."
                        )
            if not consumed:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(
                    f"{self.E(ctx.author.display_name)}, I could not"
                    " find that item - check your spelling."
                )
            forgeables = (
                f"[{self.E(ctx.author.display_name)}'s forgeables]\n"
                f"{c.__backpack__(True, consumed)}\n(Reply with the full or partial name "
                "of item 2 to select for forging. Try to be specific.)"
            )
            for page in pagify(forgeables, delims=["\n"], shorten_by=20):
                await ctx.send(box(page, lang="css"))
            # check = lambda m: m.author == ctx.author and not m.content.isnumeric()
            try:
                reply = await ctx.bot.wait_for(
                    "message", check=MessagePredicate.same_context(ctx), timeout=30
                )
            except asyncio.TimeoutError:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(
                    f"I don't have all day you know, {self.E(ctx.author.display_name)}."
                )
            for name, item in c.backpack.items():
                if reply.content.lower() in name and item not in consumed:
                    if item.rarity != "forged":
                        # item2 = backpack_items.get(item)
                        consumed.append(item)
                        break
                    else:
                        ctx.command.reset_cooldown(ctx)
                        return await ctx.send(
                            f"{self.E(ctx.author.display_name)}, "
                            "tinkered devices cannot be reforged."
                        )
            if len(consumed) < 2:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(
                    f"{self.E(ctx.author.display_name)}, I could"
                    " not find that item - check your spelling."
                )

            newitem = await self._to_forge(ctx, consumed)
            for x in consumed:
                c.backpack[x.name].owned -= 1
                if c.backpack[x.name].owned <= 0:
                    del c.backpack[x.name]
            await self.config.user(ctx.author).set(c._to_json())
            # save so the items are eaten up already
            log.debug("tambourine" in c.backpack)
            for items in c.current_equipment():
                if items.rarity == "forged":
                    c = await c._unequip_item(items)
            lookup = list(i for n, i in c.backpack.items() if i.rarity == "forged")
            if len(lookup) > 0:
                forge_msg = await ctx.send(
                    box(
                        f"{self.E(ctx.author.display_name)}, you already have a device. "
                        f"Do you want to replace {', '.join([str(x) for x in lookup])}?",
                        lang="css",
                    )
                )
                start_adding_reactions(forge_msg, ReactionPredicate.YES_OR_NO_EMOJIS)
                pred = ReactionPredicate.yes_or_no(forge_msg, ctx.author)
                try:
                    await ctx.bot.wait_for("reaction_add", check=pred, timeout=60)
                except asyncio.TimeoutError:
                    await self._clear_react(forge_msg)
                    return
                try:
                    await forge_msg.delete()
                except discord.errors.Forbidden:
                    pass
                if pred.result:  # user reacted with Yes.
                    for item in lookup:
                        del c.backpack[item.name]
                        await ctx.send(
                            box(
                                (
                                    f"{self.E(ctx.author.display_name)}, your new {newitem} "
                                    f"consumed {', '.join([str(x) for x in lookup])}"
                                    " and is now lurking in your backpack."
                                ),
                                lang="css",
                            )
                        )
                    c.backpack[newitem.name] = newitem
                    await self.config.user(ctx.author).set(c._to_json())
                else:
                    return await ctx.send(
                        box(
                            f"{self.E(ctx.author.display_name)}, {newitem} got"
                            " mad at your rejection and blew itself up.",
                            lang="css",
                        )
                    )
            else:
                c.backpack[newitem.name] = newitem
                await self.config.user(ctx.author).set(c._to_json())
                await ctx.send(
                    box(
                        f"{self.E(ctx.author.display_name)}, your new {newitem}"
                        " is lurking in your backpack.",
                        lang="css",
                    )
                )

    async def _to_forge(self, ctx, consumed):
        item1 = consumed[0]
        item2 = consumed[1]

        roll = random.randint(1, 20)
        if roll == 1:
            modifier = 0.4
        if roll > 1 and roll <= 6:
            modifier = 0.5
        if roll > 6 and roll <= 8:
            modifier = 0.6
        if roll > 8 and roll <= 10:
            modifier = 0.7
        if roll > 10 and roll <= 13:
            modifier = 0.8
        if roll > 13 and roll <= 16:
            modifier = 0.9
        if roll > 16 and roll <= 17:
            modifier = 1.0
        if roll > 17 and roll <= 19:
            modifier = 1.1
        if roll == 20:
            modifier = 1.2
        newatt = round((int(item1.att) + int(item2.att)) * modifier)
        newdip = round((int(item1.cha) + int(item2.cha)) * modifier)
        newint = round((int(item1.int) + int(item2.int)) * modifier)
        newslot = random.choice([item1.slot, item2.slot])
        if len(newslot) == 2:  # two handed weapons add their bonuses twice
            hand = "two handed"
        else:
            if newslot[0] == "right" or newslot[0] == "left":
                hand = newslot[0] + " handed"
            else:
                hand = newslot[0] + " slot"
        if len(newslot) == 2:
            await ctx.send(
                (
                    f"{self.E(ctx.author.display_name)}, your forging roll was 🎲({roll}).\n"
                    f"The device you tinkered will have "
                    f"{newatt * 2}🗡, {newdip * 2}🗨 and {newint * 2}🌟 and be {hand}."
                )
            )
        else:
            await ctx.send(
                (
                    f"{self.E(ctx.author.display_name)}, your forging roll was 🎲({roll}).\n"
                    "The device you tinkered will have "
                    f"{newatt}🗡, {newdip}🗨 and {newint}🌟 and be {hand}."
                )
            )
        await ctx.send(
            (
                f"{self.E(ctx.author.display_name)}, please respond with "
                "a name for your creation within 30s.\n"
                "(You will not be able to change it afterwards. 40 characters maximum.)"
            )
        )
        reply = None
        try:
            reply = await ctx.bot.wait_for(
                "message", check=MessagePredicate.same_context(ctx), timeout=30
            )
        except asyncio.TimeoutError:
            name = "Unnamed Artifact"
        if reply is None:
            name = "Unnamed Artifact"
        else:
            if hasattr(reply, "content"):
                if len(reply.content) > 40:
                    name = "Long-winded Artifact"
                else:
                    name = reply.content.lower()
        item = {name: {"slot": newslot, "att": newatt, "cha": newdip, "int": newint, "rarity": "forged"}}
        item = Item._from_json(item)
        return item

    @commands.group()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def give(self, ctx):
        """[Admin] Commands to add things to players' inventories."""

        pass

    @give.command(name="funds")
    @checks.admin_or_permissions(administrator=True)
    async def _give_funds(self, ctx, amount: int = 1, *, to: discord.Member = None):
        """[Admin] Adds currency to a specified member's balance.

        `[p]give funds 10 @Elder Aramis`
        will create 10 currency and add to Elder Aramis' total.
        """
        if await bank.is_global() and not await ctx.bot.is_owner(ctx.author):
            return await ctx.send("You are not worthy.")
        if to is None:
            return await ctx.send(
                f"You need to specify a receiving member, {self.E(ctx.author.display_name)}."
            )
        to_fund = discord.utils.find(lambda m: m.name == to.name, ctx.guild.members)
        if not to_fund:
            return await ctx.send(
                f"I could not find that user, {self.E(ctx.author.display_name)}."
                " Try using their full Discord name (name#0000)."
            )
        bal = await bank.deposit_credits(to, amount)
        currency = await bank.get_currency_name(ctx.guild)
        if str(currency).startswith("<:"):
            currency = "credits"
        await ctx.send(
            box(
                (
                    f"{self.E(ctx.author.display_name)}, you funded {amount} "
                    f"{currency}. {self.E(to.display_name)} now has {bal} {currency}."
                ),
                lang="css",
            )
        )

    @give.command(name="item")
    async def _give_item(
        self,
        ctx,
        item_name: str,
        rarity: str,
        atk: int,
        cha: int,
        int: int,
        position: str,
        user: discord.Member = None,
    ):
        """[Admin] Adds a custom item to a specified member.

        Item names containing spaces must be enclosed in double quotes.
        `[p]give item "fine dagger" rare 1 1 right @locastan`
        will give a right-handed .fine_dagger with 1/1 stats to locastan.
        """
        positions = [
            "head",
            "neck",
            "chest",
            "gloves",
            "belt",
            "legs",
            "boots",
            "left",
            "right",
            "ring",
            "charm",
            "twohanded",
        ]
        rarities = ["normal", "rare", "epic", "legendary"]
        item_name = item_name.lower()
        if item_name.isnumeric():
            return await ctx.send("Item names cannot be numbers.")
        if user is None:
            user = ctx.author
        if position not in positions:
            # itempos = ", ".join(pos for pos in positions)
            return await ctx.send(
                f"{self.E(ctx.author.display_name)}, "
                f"valid item slots are: {humanize_list(positions)}"
            )
        if (cha > 6 or atk > 6 or int > 6) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(
                f"{self.E(ctx.author.display_name)}, don't "
                "you think that's a bit overpowered? Not creating item."
            )
        if len(item_name) >= 40:
            return await ctx.send(
                f"{self.E(ctx.author.display_name)}, try again with a shorter name."
            )
        if rarity not in rarities:
            # item_rarity = ", ".join(r for r in rarities)
            return await ctx.send(
                (
                    f"{self.E(ctx.author.display_name)}, valid item "
                    f"rarities are: {humanize_list(rarities)}. If your created "
                    "item has a space in the name, enclose "
                    'the name in double quotes. ex: "item name".'
                )
            )

        pos = [position]
        if position == "twohanded":
            pos = ["right", "left"]

        new_item = {item_name: {"slot": pos, "att": atk, "cha": cha, "int": int, "rarity": rarity}}
        item = Item._from_json(new_item)
        try:
            c = await Character._from_json(self.config, user)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if item.name in c.backpack:
            c.backpack[item.name].owned += 1
        else:
            c.backpack[item.name] = item
        await self.config.user(user).set(c._to_json())
        await ctx.send(
            box(
                f"An item named {item} has been created"
                f" and placed in {self.E(user.display_name)}'s backpack.",
                lang="css",
            )
        )

    @give.command(name="loot")
    async def _give_loot(self, ctx, loot_type: str, user: discord.Member = None, number: int = 1):
        """[Admin] This rewards a treasure chest to a specified member.

        `[p]give loot normal @locastan 5`
        will give locastan 5 normal chests.
        Loot types: normal, rare, epic, legendary
        """

        if user is None:
            user = ctx.author
        loot_types = ["normal", "rare", "epic", "legendary"]
        if loot_type not in loot_types:
            return await ctx.send(
                "Valid loot types: `normal`, `rare`, `epic` or `legendary`:"
                f" ex. `{ctx.prefix}give loot normal @locastan` "
            )
        try:
            c = await Character._from_json(self.config, user)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if loot_type == "rare":
            c.treasure[1] += number
        elif loot_type == "epic":
            c.treasure[2] += number
        elif loot_type == "legendary":
            c.treasure[3] += number
        else:
            c.treasure[0] += number
        await ctx.send(
            box(
                (
                    f"{self.E(user.display_name)} now owns {str(c.treasure[0])} "
                    f"normal, {str(c.treasure[1])} rare, {str(c.treasure[2])} epic "
                    f"and {str(c.treasure[3])} legendary chests."
                ),
                lang="css",
            )
        )
        await self.config.user(user).set(c._to_json())

    @commands.command()
    @commands.cooldown(rate=1, per=600, type=commands.BucketType.user)
    async def heroclass(self, ctx, clz: str = None, action: str = None):
        """This allows you to select a class if you are Level 10 or above.
        For information on class use: `[p]heroclass "classname" info`
        """
        if not await self.allow_in_dm(ctx):
            return await ctx.send("This command is not available in DM's on this bot.")

        classes = {
            "Wizard": {
                "name": "Wizard",
                "ability": False,
                "desc": (
                    "Wizards have the option to focus and add big bonuses to their magic, "
                    "but their focus can sometimes go astray...\n"
                    "The magic glyphs tattooed on their body are known to be bound with god, "
                    "and can amplify the prayers.\n"
                    "Use the focus command when attacking in an adventure."
                ),
            },
            "Tinkerer": {
                "name": "Tinkerer",
                "ability": False,
                "desc": (
                    "Tinkerers can forge two different items into a device "
                    "bound to their very soul.\n"
                    "From time to time, Tinkerers will sharpen the weapons of the fighters or "
                    "craft mana potions for the magicians, slightly increasing their damages.\n"
                    "Use the forge command."
                ),
            },
            "Berserker": {
                "name": "Berserker",
                "ability": False,
                "desc": (
                    "Berserkers have the option to rage and add big bonuses to attacks, "
                    "but fumbles hurt.\n"
                    "When arguing with an enemy, Bersekers can enter in a state of wild fury, "
                    "that intimidates the enemy and makes the negotiation easier for the whole party.\n"
                    "Use the rage command when attacking in an adventure."
                ),
            },
            "Cleric": {
                "name": "Cleric",
                "ability": False,
                "desc": (
                    "Clerics can bless the entire group and add small bonus to each adventurer, "
                    "but prayers can remain unanswered...\n"
                    "Divine aura can radiate from Clerics while praying, increasing the critical chances and abilities of fighters and wizards.\n"
                    "Use the bless command when praying in an adventure."
                ),
            },
            "Ranger": {
                "name": "Ranger",
                "ability": False,
                "desc": (
                    "Rangers can gain a special pet, which can find items and give "
                    "reward bonuses.\nUse the pet command to see pet options."
                ),
                "pet": {},
                "forage": 0.0,
            },
            "Bard": {
                "name": "Bard",
                "ability": False,
                "desc": (
                    "Bards can perform to aid their comrades in diplomacy.\n"
                    "Due to their natural intelligence, they learnt a little bit about magic "
                    "and have a chance to decrease magic resistance with their melodious voices.\n"
                    "Bards are also talented with daggers and can weaken physical resistance through precision incisions.\n"
                    "Use the music command when being diplomatic in an adventure."
                ),
            },
        }

        if clz is None:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(
                (
                    f"So you feel like taking on a class, **{self.E(ctx.author.display_name)}**?\n"
                    "Available classes are: Tinkerer, Berserker, Wizard, Cleric, Ranger and Bard.\n"
                    f"Use `{ctx.prefix}heroclass name-of-class` to choose one."
                )
            )

        else:
            clz = clz.title()
            if clz in classes and action == "info":
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(f"{classes[clz]['desc']}")
            elif clz not in classes and action is None:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(f"{clz} may be a class somewhere, but not on my watch.")
            bal = await bank.get_balance(ctx.author)
            currency_name = await bank.get_currency_name(ctx.guild)
            if str(currency_name).startswith("<"):
                currency_name = "credits"
            spend = 10000
            class_msg = await ctx.send(
                box(
                    (
                        f"This will cost {spend} {currency_name}. "
                        f"Do you want to continue, {self.E(ctx.author.display_name)}?"
                    ),
                    lang="css",
                )
            )
            broke = box(
                f"You don't have enough {currency_name} to train to be a {clz.title()}.",
                lang="css",
            )
            try:
                c = await Character._from_json(self.config, ctx.author)
            except Exception:
                log.error("Error with the new character sheet", exc_info=True)
                return
            start_adding_reactions(class_msg, ReactionPredicate.YES_OR_NO_EMOJIS)
            pred = ReactionPredicate.yes_or_no(class_msg, ctx.author)
            try:
                await ctx.bot.wait_for("reaction_add", check=pred, timeout=60)
            except asyncio.TimeoutError:
                await self._clear_react(class_msg)
                return

            if not pred.result:
                await class_msg.edit(
                    content=box(
                        (
                            f"{self.E(ctx.author.display_name)} decided"
                            f" to continue being a {c.heroclass['name']}."
                        ),
                        lang="css",
                    )
                )
                return await self._clear_react(class_msg)
            if bal < spend:
                await class_msg.edit(content=broke)
                return await self._clear_react(class_msg)
            try:
                await bank.withdraw_credits(ctx.author, spend)
            except ValueError:
                return await class_msg.edit(content=broke)

            if clz in classes and action is None:
                now_class_msg = (
                    f"Congratulations, {self.E(ctx.author.display_name)}.\n"
                    f"You are now a {classes[clz]['name']}."
                )
                if c.lvl >= 10:
                    if c.heroclass["name"] == "Tinkerer" or c.heroclass["name"] == "Ranger":
                        if c.heroclass["name"] == "Tinkerer":
                            await self._clear_react(class_msg)
                            await class_msg.edit(
                                content=box(
                                    (
                                        f"{self.E(ctx.author.display_name)}, "
                                        "you will lose your forged"
                                        " device if you change your class.\nShall I proceed?"
                                    ),
                                    lang="css",
                                )
                            )
                        else:
                            await self._clear_react(class_msg)
                            await class_msg.edit(
                                content=box(
                                    (
                                        f"{self.E(ctx.author.display_name)}, "
                                        "you will lose your pet "
                                        "if you change your class.\nShall I proceed?"
                                    ),
                                    lang="css",
                                )
                            )
                        start_adding_reactions(class_msg, ReactionPredicate.YES_OR_NO_EMOJIS)
                        pred = ReactionPredicate.yes_or_no(class_msg, ctx.author)
                        try:
                            await ctx.bot.wait_for("reaction_add", check=pred, timeout=60)
                        except asyncio.TimeoutError:
                            await self._clear_react(class_msg)
                            return
                        if pred.result:  # user reacted with Yes.
                            if c.heroclass["name"] == "Tinkerer":
                                tinker_wep = []
                                for item in c.current_equipment():
                                    if item.rarity == "forged":
                                        c = await c._unequip_item(item)
                                for name, item in c.backpack.items():
                                    if item.rarity == "forged":
                                        tinker_wep.append(item)
                                if len(tinker_wep) >= 1:
                                    for item in tinker_wep:
                                        del c.backpack[item.name]
                                    await self.config.user(ctx.author).set(c._to_json())
                                    await class_msg.edit(
                                        content=box(
                                            (
                                                f"{humanize_list(tinker_wep)} has "
                                                "run off to find a new master."
                                            ),
                                            lang="css",
                                        )
                                    )
                            else:
                                c.heroclass["ability"] = False
                                c.heroclass["pet"] = {}
                                c.heroclass = classes[clz]
                                await self.config.user(ctx.author).set(c._to_json())
                                await self._clear_react(class_msg)
                                await class_msg.edit(
                                    content=box(
                                        (
                                            f"{self.E(ctx.author.display_name)} released their"
                                            f" pet into the wild.\n"
                                        ),
                                        lang="css",
                                    )
                                )
                            c.heroclass = classes[clz]
                            await self.config.user(ctx.author).set(c._to_json())
                            await self._clear_react(class_msg)
                            return await class_msg.edit(
                                content=class_msg.content + box(now_class_msg, lang="css")
                            )

                        else:
                            ctx.command.reset_cooldown(ctx)
                            return
                    else:
                        c.heroclass = classes[clz]
                        await self.config.user(ctx.author).set(c._to_json())
                        await self._clear_react(class_msg)
                        return await class_msg.edit(content=box(now_class_msg, lang="css"))
                else:
                    ctx.command.reset_cooldown(ctx)
                    await ctx.send(
                        f"{self.E(ctx.author.display_name)}, you need "
                        "to be at least level 10 to choose a class."
                    )

    @commands.command()
    @commands.cooldown(rate=1, per=4, type=commands.BucketType.user)
    async def loot(self, ctx: Context, box_type: str = None, amount: int = 1):
        """This opens one of your precious treasure chests.
        Use the box rarity type with the command: normal, rare, epic or legendary.
        """
        if not await self.allow_in_dm(ctx):
            return await ctx.send("This command is not available in DM's on this bot.")
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if not box_type:
            return await ctx.send(
                box(
                    (
                        f"{self.E(ctx.author.display_name)} owns {str(c.treasure[0])} "
                        f"normal, {str(c.treasure[1])} rare, {str(c.treasure[2])} epic "
                        f"and {str(c.treasure[3])} legendary chests."
                    ),
                    lang="css",
                )
            )
        if box_type == "normal":
            redux = [1, 0, 0, 0]
        elif box_type == "rare":
            redux = [0, 1, 0, 0]
        elif box_type == "epic":
            redux = [0, 0, 1, 0]
        elif box_type == "legendary":
            redux = [0, 0, 0, 1]
        else:
            return await ctx.send(
                f"There is talk of a {box_type} treasure chest but nobody ever saw one."
            )
        treasure = c.treasure[redux.index(1)]
        if treasure < amount:
            await ctx.send(
                f"{self.E(ctx.author.display_name)}, "
                f"you do not have enough {box_type} treasure chest to open."
            )
        else:
            c.treasure[redux.index(1)] -= amount
            await self.config.user(ctx.author).set(c._to_json())
            if amount > 1:
                items = await self._open_chests(ctx, ctx.author, box_type, amount)
                adjust = max([len(str(i)) for i in items])
                title_str = f" # - Name "
                buffer = f"-"
                msg = (
                    f"{self.E(ctx.author.display_name)}, "
                    f"you've opened the following items:\n"
                    f"{title_str} {buffer:>{adjust-4}} ( ATT  |  INT  |  CHA  )"
                )
                for item in items:
                    att_space = " " if len(str(item.att)) == 1 else ""
                    cha_space = " " if len(str(item.cha)) == 1 else ""
                    int_space = " " if len(str(item.int)) == 1 else ""
                    msg += (
                        f"\n {item.owned} - {str(item):<{adjust}} - "
                        f"( {item.att}{att_space}   | "
                        f" {item.int}{int_space}   | "
                        f" {item.cha}{cha_space}   )"
                    )
                for page in pagify(msg):
                    await ctx.send(box(page, lang="css"))
            else:
                await self._open_chest(ctx, ctx.author, box_type)  # returns item and msg

    @commands.command()
    @commands.guild_only()
    @commands.cooldown(rate=1, per=900, type=commands.BucketType.user)
    async def music(self, ctx):
        """[Bard Class Only]

        This allows a Bard to add substantial diplomacy bonuses for one battle.
        (15min cooldown)
        """

        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if c.heroclass["name"] != "Bard":
            ctx.command.reset_cooldown(ctx)
            return await ctx.send(
                f"{self.E(ctx.author.display_name)}, you need to be a Bard to do this."
            )
        else:
            if c.heroclass["ability"]:
                return await ctx.send(
                    f"{self.E(ctx.author.display_name)}, ability already in use."
                )
            c.heroclass["ability"] = True
            await self.config.user(ctx.author).set(c._to_json())
        await ctx.send(
            f"♪♫♬ {bold(ctx.author.display_name)} is whipping up a performance. ♬♫♪"
        )

    @commands.command(name="negaverse", aliases=["nv"])
    @commands.cooldown(rate=1, per=10, type=commands.BucketType.user)
    @commands.guild_only()
    async def _negaverse(self, ctx, offering: int = None):
        """This will send you to fight a nega-member!

        `[p]negaverse offering`
        'offering' in this context is the amount of currency you are sacrificing for this fight.
        """
        bal = await bank.get_balance(ctx.author)
        currency_name = await bank.get_currency_name(ctx.guild)

        if not offering:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send(
                (
                    f"{self.E(ctx.author.display_name)}, you need to specify how many "
                    f"{currency_name} you are willing to offer to the gods for your success."
                )
            )
        if offering <= 500 or bal <= 500:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("The gods refuse your pitiful offering.")
        if offering > bal:
            offering = bal

        nv_msg = await ctx.send(
            (
                f"{self.E(ctx.author.display_name)}, this will cost you at least "
                f"{offering} {currency_name}.\nYou currently have {bal}. Do you want to proceed?"
            )
        )
        start_adding_reactions(nv_msg, ReactionPredicate.YES_OR_NO_EMOJIS)
        pred = ReactionPredicate.yes_or_no(nv_msg, ctx.author)
        try:
            await ctx.bot.wait_for("reaction_add", check=pred, timeout=60)
        except asyncio.TimeoutError:
            await self._clear_react(nv_msg)
            return
        if not pred.result:
            try:
                ctx.command.reset_cooldown(ctx)
                await nv_msg.edit(
                    content=(
                        f"{self.E(ctx.author.display_name)} decides "
                        "against visiting the negaverse... for now."
                    )
                )
                return await self._clear_react(nv_msg)
            except discord.errors.Forbidden:
                pass

        entry_roll = random.randint(1, 20)
        if entry_roll == 1:
            tax_mod = random.randint(4, 8)
            tax = round(bal / tax_mod)
            if tax > offering:
                loss = tax
            else:
                loss = offering
            await bank.withdraw_credits(ctx.author, loss)
            entry_msg = (
                "A swirling void slowly grows and you watch in horror as it rushes to "
                "wash over you, leaving you cold... and your coin pouch significantly lighter. "
                "The portal to the negaverse remains closed."
            )
            return await nv_msg.edit(content=entry_msg)
        else:
            entry_msg = (
                "Shadowy hands reach out to take your offering from you and a swirling "
                "black void slowly grows and engulfs you, transporting you to the negaverse."
            )
            await nv_msg.edit(content=entry_msg)
            await self._clear_react(nv_msg)
            await bank.withdraw_credits(ctx.author, offering)

        negachar = bold(f"Nega-{self.E(random.choice(ctx.message.guild.members).display_name)}")
        nega_msg = await ctx.send(
            f"{bold(ctx.author.display_name)} enters the negaverse and meets {negachar}."
        )
        roll = random.randint(1, 20)
        versus = random.randint(1, 20)
        xp_mod = random.randint(1, 10)
        if roll == 1:
            loss_mod = random.randint(1, 10)
            loss = round((offering / loss_mod) * 3)
            try:
                await bank.withdraw_credits(ctx.author, loss)
                loss_msg = ""
            except ValueError:
                await bank.set_balance(ctx.author, 0)
                loss = "all of their"
            loss_msg = (
                f", losing {loss} {currency_name} as {negachar} rifled through their belongings"
            )
            await nega_msg.edit(
                content=(
                    f"{nega_msg.content}\n{bold(ctx.author.display_name)} "
                    f"fumbled and died to {negachar}'s savagery{loss_msg}."
                )
            )
        elif roll == 20:
            await nega_msg.edit(
                content=(
                    f"{nega_msg.content}\n{bold(ctx.author.display_name)} "
                    f"decapitated {negachar}. You gain {int(offering/xp_mod)} xp and take "
                    f"{offering} {currency_name} back from the shadowy corpse."
                )
            )
            await self._add_rewards(
                ctx, ctx.message.author, (int(offering / xp_mod)), offering, False
            )
        elif roll > versus:
            await nega_msg.edit(
                content=(
                    f"{nega_msg.content}\n{bold(ctx.author.display_name)} "
                    f"🎲({roll}) bravely defeated {negachar} 🎲({versus}). "
                    f"You gain {int(offering/xp_mod)} xp."
                )
            )
            await self._add_rewards(ctx, ctx.message.author, (int(offering / xp_mod)), 0, False)
        elif roll == versus:
            await nega_msg.edit(
                content=(
                    f"{nega_msg.content}\n{bold(ctx.author.display_name)} "
                    f"🎲({roll}) almost killed {negachar} 🎲({versus})."
                )
            )
        else:
            loss = round(offering * 0.8)
            try:
                await bank.withdraw_credits(ctx.author, loss)
                loss_msg = ""
            except ValueError:
                await bank.set_balance(ctx.author, 0)
                loss = "all of their"
            loss_msg = f", losing {loss} {currency_name} as {negachar} looted their backpack"
            await nega_msg.edit(
                content=(
                    f"{bold(ctx.author.display_name)} 🎲({roll}) "
                    f"was killed by {negachar} 🎲({versus}){loss_msg}."
                )
            )

    @commands.group(autohelp=False)
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.user)
    async def pet(self, ctx):
        """[Ranger Class Only]

        This allows a Ranger to tame or set free a pet or send it foraging.
        (5s cooldown)
        """

        if not await self.allow_in_dm(ctx):
            return await ctx.send("This command is not available in DM's on this bot.")
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if c.heroclass["name"] != "Ranger":
            return await ctx.send(
                box(
                    f"{self.E(ctx.author.display_name)}, you need to be a Ranger to do this.",
                    lang="css",
                )
            )
        if ctx.invoked_subcommand is None:
            if c.heroclass["pet"]:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(
                    box(
                        (
                            f"{self.E(ctx.author.display_name)}, you already have a pet. "
                            f"Try foraging ({ctx.prefix}pet forage)."
                        ),
                        lang="css",
                    )
                )

            pet = random.choice(list(self.PETS.keys()))
            roll = random.randint(1, 20)
            dipl_value = roll + c.cha + c.skill["cha"]

            pet_msg = box(
                f"{self.E(ctx.author.display_name)} is trying to tame a pet.", lang="css"
            )
            user_msg = await ctx.send(pet_msg)
            await asyncio.sleep(2)
            pet_msg2 = box(
                (
                    f"{self.E(ctx.author.display_name)} started tracking a wild "
                    f"{self.PETS[pet]['name']} with a roll of 🎲({roll})."
                ),
                lang="css",
            )
            await user_msg.edit(content=f"{pet_msg}\n{pet_msg2}")
            await asyncio.sleep(2)
            bonus = ""
            if roll == 1:
                bonus = "But they stepped on a twig and scared it away."
            elif roll == 20:
                bonus = "They happen to have its favorite food."
                dipl_value += 10
            if dipl_value > self.PETS[pet]["cha"] and roll > 1:
                pet_msg3 = box(
                    f"{bonus}\nThey successfully tamed the {self.PETS[pet]['name']}.", lang="css"
                )
                await user_msg.edit(content=f"{pet_msg}\n{pet_msg2}\n{pet_msg3}")
                c.heroclass["pet"] = self.PETS[pet]
                await self.config.user(ctx.author).set(c._to_json())
            else:
                pet_msg3 = box(f"{bonus}\nThe {self.PETS[pet]['name']} escaped.", lang="css")
                await user_msg.edit(content=f"{pet_msg}\n{pet_msg2}\n{pet_msg3}")

    @pet.command(name="forage")
    async def _forage(self, ctx):
        """
            Use your pet to forage for items!
        """
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if c.heroclass["name"] != "Ranger":
            return await ctx.send(
                box(
                    f"{self.E(ctx.author.display_name)}, you need to be a Ranger to do this.",
                    lang="css",
                )
            )
        if not c.heroclass["pet"]:
            return await ctx.send(
                box(
                    f"{self.E(ctx.author.display_name)}, you need to have a pet to do this.",
                    lang="css",
                )
            )
        if "forage" not in c.heroclass:
            c.heroclass["forage"] = 901
        if c.heroclass["forage"] <= time.time() - 900:
            await self._open_chest(ctx, c.heroclass["pet"]["name"], "pet")
            try:
                c = await Character._from_json(self.config, ctx.author)
            except Exception:
                log.error("Error with the new character sheet", exc_info=True)
                return
            c.heroclass["forage"] = time.time()
            await self.config.user(ctx.author).set(c._to_json())
        else:
            cooldown_time = (c.heroclass["forage"] + 900) - time.time()
            return await ctx.send(
                "This command is on cooldown. Try again in {:g}s".format(cooldown_time)
            )

    @pet.command(name="free")
    async def _free(self, ctx):
        """
            Free your pet :cry:
        """
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if c.heroclass["name"] != "Ranger":
            return await ctx.send(
                box(
                    f"{self.E(ctx.author.display_name)}, you need to be a Ranger to do this.",
                    lang="css",
                )
            )
        if c.heroclass["pet"]:
            c.heroclass["pet"] = {}
            await self.config.user(ctx.author).set(c._to_json())
            return await ctx.send(
                box(
                    f"{self.E(ctx.author.display_name)} released their pet into the wild.",
                    lang="css"
                )
            )
        else:
            return await ctx.send(
                box("You don't have a pet.", lang="css")
            )

    @commands.command()
    @commands.guild_only()
    @commands.cooldown(rate=1, per=900, type=commands.BucketType.user)
    async def rage(self, ctx):
        """[Berserker Class Only]

        This allows a Berserker to add substantial attack bonuses for one battle.
        (15min cooldown)
        """

        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if c.heroclass["name"] != "Berserker":
            ctx.command.reset_cooldown(ctx)
            return await ctx.send(
                f"{self.E(ctx.author.display_name)}, you need to be a Berserker to do this."
            )
        else:
            if c.heroclass["ability"] is True:
                return await ctx.send(
                    f"{self.E(ctx.author.display_name)}, ability already in use."
                )
            c.heroclass["ability"] = True
            await self.config.user(ctx.author).set(c._to_json())
            await ctx.send(
                f"{bold(ctx.author.display_name)} is starting to froth at the mouth...🗯️"
            )

    @commands.command()
    @commands.guild_only()
    @commands.cooldown(rate=1, per=900, type=commands.BucketType.user)
    async def focus(self, ctx):
        """[Wizard Class Only]

        This allows a Wizard to add substantial magic bonuses for one battle.
        (15min cooldown)
        """

        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if c.heroclass["name"] != "Wizard":
            ctx.command.reset_cooldown(ctx)
            return await ctx.send(
                f"{self.E(ctx.author.display_name)}, you need to be a Wizard to do this."
            )
        else:
            if c.heroclass["ability"] is True:
                return await ctx.send(
                    f"{self.E(ctx.author.display_name)}, ability already in use."
                )
            c.heroclass["ability"] = True
            await self.config.user(ctx.author).set(c._to_json())
            await ctx.send(
                f"{bold(ctx.author.display_name)} is focusing all of their energy...⚡️"
            )

    @commands.command()
    async def skill(self, ctx, spend: str = None):
        """This allows you to spend skillpoints.

        `[p]skill attack/diplomacy/intelligence`
        `[p]skill reset` Will allow you to reset your skill points for a cost.
        """
        if not await self.allow_in_dm(ctx):
            return await ctx.send("This command is not available in DM's on this bot.")
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        if spend == "reset":
            bal = c.bal
            currency_name = await bank.get_currency_name(ctx.guild)

            offering = int(bal / 8)
            nv_msg = await ctx.send(
                (
                    f"{self.E(ctx.author.display_name)}, this will cost you at least "
                    f"{offering} {currency_name}.\n"
                    f"You currently have {bal}. Do you want to proceed?"
                )
            )
            start_adding_reactions(nv_msg, ReactionPredicate.YES_OR_NO_EMOJIS)
            pred = ReactionPredicate.yes_or_no(nv_msg, ctx.author)
            try:
                await ctx.bot.wait_for("reaction_add", check=pred, timeout=60)
            except asyncio.TimeoutError:
                await self._clear_react(nv_msg)
                return

            if pred.result:
                c.skill["pool"] = c.skill["att"] + c.skill["cha"] + c.skill["int"]
                c.skill["att"] = 0
                c.skill["cha"] = 0
                c.skill["int"] = 0
                await self.config.user(ctx.author).set(c._to_json())
                await bank.withdraw_credits(ctx.author, offering)
                await ctx.send(
                    f"{self.E(ctx.author.display_name)}, your skill points have been reset."
                )
            else:
                await ctx.send(f"Don't play games with me, {self.E(ctx.author.display_name)}.")
            return

        if c.skill["pool"] == 0:
            return await ctx.send(
                f"{self.E(ctx.author.display_name)}, you do not have unspent skillpoints."
            )
        if spend is None:
            await ctx.send(
                (
                    f"{self.E(ctx.author.display_name)}, "
                    f"you currently have {bold(str(c.skill['pool']))} "
                    "unspent skillpoints.\n"
                    "If you want to put them towards a permanent attack, diplomacy or intelligence bonus, use "
                    f"`{ctx.prefix}skill attack`, `{ctx.prefix}skill diplomacy` or  `{ctx.prefix}skill intelligence`"
                )
            )
        else:
            if spend not in ["attack", "diplomacy", "intelligence"]:
                return await ctx.send(f"Don't try to fool me! There is no such thing as {spend}.")
            elif spend == "attack":
                c.skill["pool"] -= 1
                c.skill["att"] += 1
            elif spend == "diplomacy":
                c.skill["pool"] -= 1
                c.skill["cha"] += 1
            elif spend == "intelligence":
                c.skill["pool"] -= 1
                c.skill["int"] += 1
            await self.config.user(ctx.author).set(c._to_json())
            await ctx.send(
                f"{self.E(ctx.author.display_name)}, you "
                f"permanently raised your {spend} value by one."
            )

    @commands.command()
    async def stats(self, ctx, *, user: discord.Member = None):
        """This draws up a charsheet of you or an optionally specified member.

        `[p]stats @locastan`
        will bring up locastans stats.
        `[p]stats` without user will open your stats.
        """
        if not await self.allow_in_dm(ctx):
            return await ctx.send("This command is not available in DM's on this bot.")
        if user is None:
            user = ctx.author
        if user.bot:
            return
        try:
            c = await Character._from_json(self.config, user)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        msg = await ctx.send(box(c, lang="css"))
        await msg.add_reaction("\N{CROSS MARK}")
        pred = ReactionPredicate.same_context(msg, ctx.author)
        try:
            react, user = await self.bot.wait_for("reaction_add", check=pred, timeout=60)
        except asyncio.TimeoutError:
            return
        if str(react.emoji) == "\N{CROSS MARK}":
            await msg.delete()

    async def _build_loadout_display(self, userdata):
        form_string = "Items Equipped:"
        last_slot = ""
        for slot, data in userdata["items"].items():

            if slot == "backpack":
                continue
            if last_slot == "two handed":
                last_slot = slot
                continue

            if not data:
                last_slot = slot
                form_string += f"\n\n {slot.title()} slot"
                continue
            item = Item._from_json(data)
            slot_name = userdata["items"][slot]["".join(i for i in data.keys())]["slot"]
            slot_name = slot_name[0] if len(slot_name) < 2 else "two handed"
            form_string += f"\n\n {slot_name.title()} slot"
            last_slot = slot_name
            rjust = max([len(i) for i in data.keys()])
            form_string += f"\n  - {str(item):<{rjust}} - (ATT: {item.att} | DPL: {item.cha} | INT: {item.int})"

        return form_string + "\n"

    @commands.command()
    async def unequip(self, ctx, *, item: str):
        """This stashes a specified equipped item into your backpack.

        `[p]unequip name of item`
        You can only have one of each uniquely named item in your backpack.
        """

        if not await self.allow_in_dm(ctx):
            return await ctx.send("This command is not available in DM's on this bot.")
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        msg = ""
        for current_item in c.current_equipment():
            if item.lower() in current_item.name:
                await c._unequip_item(current_item)
                msg = (
                    f"{self.E(ctx.author.display_name)} removed the "
                    f"{current_item} and put it into their backpack."
                )
        if msg:
            await ctx.send(box(msg, lang="css"))
            await self.config.user(ctx.author).set(c._to_json())
        else:
            await ctx.send(
                f"{self.E(ctx.author.display_name)}, "
                f"you do not have an item matching {item} equipped."
            )

    @commands.command(name="adventure", aliases=["a"])
    @commands.guild_only()
    @commands.cooldown(rate=1, per=125, type=commands.BucketType.guild)
    async def _adventure(self, ctx, *, challenge=None):
        """This will ask which players want to go together on an adventure!
        
        You play by reacting with the offered emojis. 
        Your initial choice will be remembered. The difficulty of the adventure 
        will be determined by the players in your group. Remember your initial choice
        can be changed and should be tailored to the encounter!
        """
        if ctx.guild.id in self._sessions:
            return await ctx.send("There's already another adventure going on in this server.")
        if challenge and not await ctx.bot.is_owner(ctx.author):
            # Only let the bot owner specify a specific challenge
            challenge = None

        group = None
        group_msg = None
        amount = 1
        if not challenge:
            try:
                group, group_msg = await self._group(ctx, challenge)
                total_dmg = 0
                total_cha = 0
                for user_list in group.fight, group.magic, group.talk, group.pray:
                    for user in user_list:
                        c = await Character._from_json(self.config, user)
                        total_dmg += max(c.att + c.skill['att'], c.int + c.skill['int']) + 10  # assume average rolls
                        total_cha += c.cha + c.skill['cha'] + 10
                log.debug("passing through total_dmg: " + str(total_dmg) + ", total_cha: " + str(total_cha))
                challenge, amount = await self._find_challenge(total_dmg, total_cha)
            except Exception:
                log.error("Something went wrong forming the group", exc_info=True)
                return

        adventure_txt = ""
        try:
            reward, participants = await self._simple(ctx, adventure_txt, group_msg, group, challenge, amount)
        except Exception:
            log.error("Something went wrong controlling the game", exc_info=True)
            return
        reward_copy = reward.copy()
        for userid, rewards in reward_copy.items():
            if not rewards:
                pass
            else:
                user = ctx.guild.get_member(userid)  # bot.get_user breaks sometimes :ablobsweats:
                if user is None:
                    # sorry no rewards if you leave the server
                    continue
                await self._add_rewards(
                    ctx, user, rewards["xp"], rewards["cp"], rewards["special"]
                )
                self._rewards[userid] = {}
        if participants:
            for user in participants:  # reset activated abilities
                try:
                    c = await Character._from_json(self.config, user)
                except Exception:
                    log.error("Error with the new character sheet", exc_info=True)
                    continue
                if c.heroclass["name"] != "Ranger" and c.heroclass["ability"]:
                    c.heroclass["ability"] = False
                    await self.config.user(user).set(c._to_json())
        del self._sessions[ctx.guild.id]
        if group:
            del self._groups[ctx.guild.id]

    async def _find_challenge(self, dmg, dipl):
        challenges = list(self.MONSTERS.keys())
        random.shuffle(challenges)  # if we take the list and shuffle it... we can iterate through it rather than rely on random.choice
        i = 0
        challenge = challenges[i]
        boss_roll = random.randint(1, 10)
        strongest_stat = max(dmg, dipl)
        hp_dipl = "hp" if strongest_stat == dmg else "dipl"
        if boss_roll == 10:
             while not self.MONSTERS[challenge]["boss"] and i < len(challenges):
                i += 1
                challenge = challenges[i]
        else:
            while self.MONSTERS[challenge][hp_dipl] > strongest_stat and i < len(challenges) and not self.MONSTERS[challenge]["boss"]:
                i += 1
                challenge = challenges[i]
        amount = 1
        while self.MONSTERS[challenge][hp_dipl] * (amount+1) < strongest_stat:
            amount += 1  
        return challenge, amount

    async def _group(self, ctx, challenge=None):
        embed = discord.Embed(colour=discord.Colour.blurple())
        embed.description = f"{self.E(ctx.author.display_name)} is going on an adventure."
        adventure_msg = await ctx.send(embed=embed)
        
        timeout = 30
        timer = await self._adv_countdown(ctx, timeout, "Time remaining: ")
        self.tasks.append(timer)
        embed = discord.Embed(colour=discord.Colour.blurple())
        use_embeds = (
            await self.config.guild(ctx.guild).embed()
            and ctx.channel.permissions_for(ctx.me).embed_links
        )
        normal_text = (
            "Who among you are brave enough to help the cause?\n"
            "Heroes have 30s to participate via reaction:"
        )
        
        if use_embeds:
            embed.description = f"{normal_text}"
            group_msg = await ctx.send(embed=embed)
        else:
            group_msg = await ctx.send(f"{normal_text}")
        
        self._groups[ctx.guild.id] = AdventureGroup(guild=ctx.guild, message_id=group_msg.id)

        start_adding_reactions(group_msg, self._group_actions, ctx.bot.loop)
        group = self._groups[ctx.guild.id]
        # You chose to start an adventure, you're going to fight! We'll pick what you're best at because we're nice.
        # obviously can be changed via reactions
        c = await Character._from_json(self.config, ctx.author)
        max_stat = max(c.att + c.skill["att"], c.int + c.skill["int"], c.cha + c.skill["cha"])
        if max_stat == c.att + c.skill["att"]:
            group.fight.append(ctx.author)
        elif max_stat == c.int + c.skill["int"]:
            group.magic.append(ctx.author)
        else:
            group.talk.append(ctx.author)
        try:
            await asyncio.wait_for(timer, timeout=timeout + 5)
        except Exception:
            timer.cancel()
            log.error("Error with the countdown timer", exc_info=True)
            pass
        
        adventurers = len(group.fight) + len(group.talk) + len(group.pray) + len(group.magic)
        embed = discord.Embed(colour=discord.Colour.blurple())
        user_list = []
        for user in set(group.fight + group.talk + group.pray + group.magic):
            user_list.append(self.E(user.display_name))
        adj = "is"
        if adventurers > 1:
            adj = "are"            
        if use_embeds:
            embed.description = f"{humanize_list(user_list)} {adj} going on an adventure."
            await adventure_msg.edit(embed=embed)
        else:
            await adventure_msg.edit(content=box(f"{humanize_list(user_list)} {adj} going on an adventure."))

        return self._groups[ctx.guild.id], group_msg

    async def _simple(self, ctx, adventure_txt, group_msg, group, challenge, amount):
        text = ""
        if challenge and challenge.title() in list(self.MONSTERS.keys()):
            challenge = challenge.title()
        else:
            challenge = random.choice(list(self.MONSTERS.keys()))
        attribute = random.choice(list(self.ATTRIBS.keys()))

        if self.MONSTERS[challenge]["boss"]:
            timer = 90
            text = box(f"\n [{challenge} Alarm!]", lang="css")
        elif self.MONSTERS[challenge]["miniboss"]:
            timer = 60
        else:
            timer = 30
        self._sessions[ctx.guild.id] = GameSession(
            challenge=challenge,
            amount=amount,
            attribute=attribute,
            guild=ctx.guild,
            boss=self.MONSTERS[challenge]["boss"],
            miniboss=self.MONSTERS[challenge]["miniboss"],
            timer=timer,
            monster=self.MONSTERS[challenge],
        )
        session = self._sessions[ctx.guild.id]
        if group:
            session.fight, session.magic, session.pray, session.talk = group.fight, group.magic, group.pray, group.talk
        adventure_txt = (
            f"{adventure_txt}{text}\n{random.choice(self.LOCATIONS)}\n"
            f"**{self.E(ctx.author.display_name)}**{random.choice(self.RAISINS)}"
        )
        await self._choice(ctx, adventure_txt, group_msg)
        rewards = self._rewards
        participants = self._sessions[ctx.guild.id].participants
        return (rewards, participants)

    async def _choice(self, ctx, adventure_txt, adventure_msg):
        session = self._sessions[ctx.guild.id]
        if session.attribute[1] in ['a', 'e', 'i', 'o', 'u']:
            prefix = "an" if session.amount == 1 else str(session.amount)
        else:
            prefix = "a" if session.amount == 1 else str(session.amount)
        is_are = "is" if session.amount == 1 else "are"
        challenge, plural = await self._plural(session.challenge, session.amount)
        dragon_text = (
            f"but **{prefix}{session.attribute} {challenge}{plural}** "
            "just landed in front of you glaring! \n\n"
            "Is your group strong enough to handle this challenge?!\n"
        )
        basilisk_text = (
            f"but **{prefix}{session.attribute} {challenge}{plural}** stepped out looking around. \n\n"
        )
        normal_text = (
            f"but **{prefix}{session.attribute} {challenge}{plural}** "
            f"{is_are} guarding it with{random.choice(self.THREATEE)}. \n\n"
        )

        embed = discord.Embed(colour=discord.Colour.blurple())
        use_embeds = (
            await self.config.guild(ctx.guild).embed()
            and ctx.channel.permissions_for(ctx.me).embed_links
        )

        owner_challenge = False
        if not adventure_msg:
            adventure_msg = await ctx.send(f"Special challenge!")
            owner_challenge = True
        if session.boss:
            if use_embeds:
                embed.description = f"{adventure_txt}\n{dragon_text}"
                embed.colour = discord.Colour.dark_red()
                if session.monster["image"]:
                    embed.set_image(url=session.monster["image"])
                await adventure_msg.edit(embed=embed)
            else:
                await adventure_msg.edit(content=box(f"{adventure_txt}\n{dragon_text}"))
            timeout = 90

        elif session.miniboss:
            if use_embeds:
                embed.description = f"{adventure_txt}\n{basilisk_text}"
                embed.colour = discord.Colour.dark_green()
                if session.monster["image"]:
                    embed.set_image(url=session.monster["image"])
                await adventure_msg.edit(embed=embed)
            else:
                await adventure_msg.edit(content=box(f"{adventure_txt}\n{basilisk_text}"))
            timeout = 60
        else:
            if use_embeds:
                embed.description = f"{adventure_txt}\n{normal_text}"
                if session.monster["image"]:
                    embed.set_thumbnail(url=session.monster["image"])
                await adventure_msg.edit(embed=embed)
            else:
                await adventure_msg.edit(content=box(f"{adventure_txt}\n{normal_text}"))
            timeout = 30
        session.message_id = adventure_msg.id
        start_adding_reactions(adventure_msg, self._adventure_actions if owner_challenge else self._adventure_run, ctx.bot.loop)

        found_msg = await ctx.send(f"Your group encountered **{prefix}{session.attribute} {challenge}{plural}**!\n"
            f"What will you do and will any other heroes help your cause?\n"
            f"Heroes have {timeout}s to change their strategy or join the fight via reactions above!")
        timer = await self._adv_countdown(ctx, session.timer, "Time remaining: ")
        self.tasks.append(timer)

        try:
            await asyncio.wait_for(timer, timeout=timeout + 5)
        except Exception:
            timer.cancel()
            log.error("Error with the countdown timer", exc_info=True)
            pass
        
        await found_msg.delete()
        return await self._result(ctx, adventure_msg)

    async def _plural(self, challenge, amount):
        challenge_updt = challenge
        if amount > 1:
            plural = "s"
            if "Wolf" in challenge_updt:
                challenge_updt = challenge_updt.replace("Wolf", "Wolve")
            if "Phoenix" in challenge_updt or "Matriarch" in challenge_updt or "Witch" in challenge_updt:
                plural = "es"
            if "Succubus" in challenge_updt or "Incubus" in challenge_updt:
                challenge_updt = challenge_updt.replace("cubus", "cubi")
                plural = ""
            if "Wolves" in challenge_updt or "Cats" in challenge_updt:
                challenge_updt = challenge_updt.replace("Pack", "Packs")
                plural = ""
            if "Thief" in challenge_updt:
                challenge_updt = challenge_updt.replace("Thief", "Thieve")
        else:
            plural = ""
        return challenge_updt, plural

    async def on_reaction_add(self, reaction, user):
        """This will be a cog level reaction_add listener for game logic"""
        if user.bot:
            return
        try:
            guild = user.guild
        except AttributeError:
            return
        log.debug("reactions working")
        emojis = ReactionPredicate.NUMBER_EMOJIS[:5] + self._adventure_actions
        if str(reaction.emoji) not in emojis:
            log.debug("emoji not in pool")
            return
        guild = user.guild
        if guild.id in self._sessions:
            if reaction.message.id == self._sessions[guild.id].message_id:
                await self._handle_adventure(reaction, user)
        if guild.id in self._current_traders:
            if reaction.message.id == self._current_traders[guild.id]["msg"]:
                log.debug("handling cart")
                await self._handle_cart(reaction, user)
        if guild.id in self._groups:
            if reaction.message.id == self._groups[guild.id].message_id:
                await self._handle_group(reaction, user)

    async def _handle_group(self, reaction, user):
        action = {v: k for k, v in self._group_controls.items()}[str(reaction.emoji)]
        log.debug(action)
        group = self._groups[user.guild.id]
        for x in ["fight", "magic", "talk", "pray"]:
            if x == action:
                continue
            if user in getattr(group, x):
                symbol = self._group_controls[x]
                getattr(group, x).remove(user)
                try:
                    symbol = self._group_controls[x]
                    await reaction.message.remove_reaction(symbol, user)
                except Exception:
                    # print(e)
                    pass
        if user not in getattr(group, action):
            getattr(group, action).append(user)

    async def _handle_adventure(self, reaction, user):
        action = {v: k for k, v in self._adventure_controls.items()}[str(reaction.emoji)]
        log.debug(action)
        session = self._sessions[user.guild.id]
        for x in ["fight", "magic", "talk", "pray", "run"]:
            if x == action:
                continue
            if user in getattr(session, x):
                symbol = self._adventure_controls[x]
                getattr(session, x).remove(user)
                try:
                    symbol = self._adventure_controls[x]
                    await reaction.message.remove_reaction(symbol, user)
                except Exception:
                    # print(e)
                    pass
        if user not in getattr(session, action):
            getattr(session, action).append(user)

    async def _handle_cart(self, reaction, user):
        guild = user.guild
        emojis = ReactionPredicate.NUMBER_EMOJIS[:5]
        itemindex = emojis.index(str(reaction.emoji)) - 1
        items = self._current_traders[guild.id]["stock"][itemindex]
        spender = user
        channel = reaction.message.channel
        currency_name = await bank.get_currency_name(guild)
        if await bank.can_spend(spender, int(items["price"])):
            await bank.withdraw_credits(spender, int(items["price"]))
            try:
                c = await Character._from_json(self.config, user)
            except Exception:
                log.error("Error with the new character sheet", exc_info=True)
                return
            if "chest" in items["itemname"]:
                if items["itemname"] == ".rare_chest":
                    c.treasure[1] += 1
                elif items["itemname"] == "[epic chest]":
                    c.treasure[2] += 1
                else:
                    c.treasure[0] += 1
            else:
                item = Item._from_json({items["itemname"]: items["item"]})
                log.debug(item.name)
                if item.name in c.backpack:
                    log.debug("item already in backpack")
                    c.backpack[item.name].owned += 1
                else:
                    c.backpack[item.name] = item
            await self.config.user(user).set(c._to_json())
            await channel.send(
                (
                    f"{self.E(user.display_name)} bought the {items['itemname']} for "
                    f"{str(items['price'])} {currency_name} and put it into their backpack."
                )
            )
        else:
            currency_name = await bank.get_currency_name(guild)
            await channel.send(
                f"{self.E(user.display_name)} does not have enough {currency_name}."
            )

    async def _result(self, ctx: commands.Context, message: discord.Message):
        calc_msg = await ctx.send("Calculating...")
        attack = 0
        diplomacy = 0
        magic = 0
        fumblelist: list = []
        critlist: list = []
        failed = False
        session = self._sessions[ctx.guild.id]
        people = len(session.fight) + len(session.talk) + len(session.pray) + len(session.magic)

        try:
            await message.clear_reactions()
        except discord.errors.Forbidden:  # cannot remove all reactions
            pass
            # for key in controls.keys():
            # await message.remove_reaction(key, ctx.bot.user)

        fight_list = session.fight
        talk_list = session.talk
        pray_list = session.pray
        magic_list = session.magic
        challenge = session.challenge

        runners = []
        run_msg = ""
        run_list = []
        if len(list(session.run)) != 0:
            for user in session.run:
                flee = random.randint(1,5)
                if flee == 1:
                    run_list.append(user)
                else:
                    runners.append(self.E(user.display_name))
            if len(runners) != 0:
                run_msg += f"{bold(humanize_list(runners))} just ran away.\n"
        
        failed = await self.handle_basilisk(ctx, failed)
        fumblelist, attack, diplomacy, magic, pray_msg = await self.handle_pray(
            ctx.guild.id, fumblelist, attack, diplomacy, magic
        )
        fumblelist, critlist, diplomacy, talk_msg = await self.handle_talk(
            ctx.guild.id, fumblelist, critlist, diplomacy
        )

        # need to pass challenge because we need to query MONSTERS[challenge]["pdef"] (and mdef)
        fumblelist, critlist, attack, magic, fight_msg = await self.handle_fight(
            ctx.guild.id, fumblelist, critlist, attack, magic, challenge
        )

        result_msg = run_msg + pray_msg + talk_msg + fight_msg        
        challenge_attrib = session.attribute

        hp = self.MONSTERS[challenge]["hp"] * self.ATTRIBS[challenge_attrib][0] * session.amount
        dipl = self.MONSTERS[challenge]["dipl"] * self.ATTRIBS[challenge_attrib][1] * session.amount

        slain = (attack + magic) >= hp
        persuaded = diplomacy >= dipl
        damage_str = ""
        diplo_str = ""
        challenge_amount = "" if session.amount == 1 else f"{session.amount} "
        challenge, plural = await self._plural(challenge, session.amount)
        if attack or magic:
            damage_str = (
                f"The group {'hit the' if not slain else 'killed the'} {challenge_amount}{challenge}{plural} "
                f"**({attack+magic}/{int(hp)})**.\n"
            )
        if diplomacy:
            diplo_str = (
                f"The group {'tried to persuade' if not persuaded else 'distracted'} "
                f"the {challenge_amount}{challenge}{plural} "
                f"with {'flattery' if not persuaded else 'insults'}"
                f" **({diplomacy}/{int(dipl)})**.\n"
            )
        result_msg = result_msg + "\n" + damage_str + diplo_str

        fight_name_list = []
        wizard_name_list = []
        talk_name_list = []
        pray_name_list = []
        run_name_list = []
        for user in fight_list:
            fight_name_list.append(self.E(user.display_name))
        for user in magic_list:
            wizard_name_list.append(self.E(user.display_name))
        for user in talk_list:
            talk_name_list.append(self.E(user.display_name))
        for user in pray_list:
            pray_name_list.append(self.E(user.display_name))
        for user in run_list:
            run_name_list.append(self.E(user.display_name))

        fighters = " and ".join(
            [", ".join(fight_name_list[:-1]), fight_name_list[-1]]
            if len(fight_name_list) > 2
            else fight_name_list
        )
        wizards = " and ".join(
            [", ".join(wizard_name_list[:-1]), wizard_name_list[-1]]
            if len(wizard_name_list) > 2
            else wizard_name_list
        ) 
        talkers = " and ".join(
            [", ".join(talk_name_list[:-1]), talk_name_list[-1]]
            if len(talk_name_list) > 2
            else talk_name_list
        )
        preachermen = " and ".join(
            [", ".join(pray_name_list[:-1]), pray_name_list[-1]]
            if len(pray_name_list) > 2
            else pray_name_list
        )
        await calc_msg.delete()

        repair_list = []
        text = ""
        if slain or persuaded and not failed:
            CR = hp + dipl
            treasure = [0, 0, 0, 0]
            if session.miniboss:  # rewards 50:50 rare:normal chest for killing something like the basilisk
                treasure = random.choice([[0, 1, 0, 0], [1, 0, 0, 0]])
            elif CR >= 600:  # super hard stuff
                treasure = [0, 0, 1, 0]  # guaranteed epic
            elif CR >= 320:  # rewards 50:50 rare:epic chest for killing hard stuff.
                treasure = random.choice([[0, 0, 1, 0], [0, 1, 0, 0]])
            elif CR >= 180:  # rewards 50:50 rare:normal chest for killing hardish stuff
                treasure = random.choice([[1, 0, 0, 0], [0, 1, 0, 0]])
            elif CR >= 80:  # small chance of a normal chest on killing stuff that's not terribly weak
                roll = random.randint(1,5)
                if roll == 1:
                    treasure = [1, 0, 0, 0]

            if session.boss:  # always rewards at least an epic chest.
                # roll for legendary chest
                roll = random.randint(1, 5)
                if roll == 1:
                    treasure[3] += 1
                else:
                    treasure[2] += 1
            if len(critlist) != 0:
                treasure[0] += 1
            if treasure == [0, 0, 0, 0]:
                treasure = False

        if session.miniboss and failed:
            session.participants = set(fight_list + talk_list + pray_list + magic_list + run_list + fumblelist)
            if len(run_name_list) >= 1:
                result_msg += (f"\n{bold(humanize_list(run_name_list))} wanted to run away but froze in fear.")
            result_msg += session.miniboss["defeat"]
            await ctx.send(result_msg)
            return await self.repair_users(ctx, session.participants, " to repay a passing cleric that unfroze the group.\n", " to be unfrozen...\n")
        if session.miniboss and not slain and not persuaded:
            session.participants = set(fight_list + talk_list + pray_list + magic_list + run_list + fumblelist)
            if len(run_name_list) >= 1:
                result_msg += (f"\n{bold(humanize_list(run_name_list))} wanted to run away but froze in fear.")
            miniboss = session.challenge
            item = session.miniboss["requirements"][0]
            special = session.miniboss["special"]
            result_msg += (
                f"The {item} countered the {miniboss}'s "
                f"{special}, but he still managed to kill you."
            )
            repair_list.append([session.participants, " to repay a passing cleric that resurrected the group.\n", " to be resurrected...\n"])
        
        amount = hp + dipl
        if people == 1:
            if slain:
                group = fighters if len(fight_list) == 1 else wizards
                text = f"{bold(group)} has slain the {challenge_amount}{challenge}{plural} in an epic battle!"
                text += await self._reward(
                    ctx, fight_list + magic_list + pray_list, amount, round(((attack if group == fighters else magic) / hp) * 0.2), treasure
                )

            if persuaded:
                text = (
                    f"{bold(talkers)} almost died in battle, but confounded "
                    f"the {challenge_amount}{challenge}{plural} in the last second."
                )
                text += await self._reward(
                    ctx, talk_list + pray_list, amount, round((diplomacy / dipl) * 0.2), treasure
                )

            if not slain and not persuaded:
                users = fight_list + magic_list + talk_list + pray_list + run_list + fumblelist
                if len(run_name_list) >= 1:
                    result_msg += (f"\n{bold(humanize_list(run_name_list))} wanted to run away but froze in fear.")
                repair_list.append([users, " to repair their gear.\n", " to have their gear repaired...\n"])
                options = [
                    f"No amount of diplomacy or valiant fighting could save you.\n",
                    f"This challenge was too much for one hero.\n",
                    f"You tried your best, but the group couldn't succeed at their attempt.\n"
                ]
                text = random.choice(options)
        else:
            if slain and persuaded:
                if len(pray_list) > 0:
                    god = await self.config.god_name()
                    if await self.config.guild(ctx.guild).god_name():
                        god = await self.config.guild(ctx.guild).god_name()
                    if len(magic_list) > 0 and len(fight_list) > 0:
                        text = (
                            f"{bold(fighters)} slayed the {challenge_amount}{challenge}{plural} "
                            f"in battle, while {bold(talkers)} distracted with flattery, "
                            f"{bold(wizards)} chanted magical incantations and "
                            f"{bold(preachermen)} aided in {god}'s name."
                        )
                    else:
                        group = fighters if len(fight_list) > 0 else wizards
                        text = (
                            f"{bold(group)} slayed the {challenge_amount}{challenge}{plural} "
                            f"in battle, while {bold(talkers)} distracted with flattery and "
                            f"{bold(preachermen)} aided in {god}'s name."
                        )
                else:
                    if len(magic_list) > 0 and len(fight_list) > 0:
                        text = (
                        f"{bold(fighters)} slayed the {challenge_amount}{challenge}{plural} "
                        f"in battle, while {bold(talkers)} distracted with insults and "
                        f"{bold(wizards)} chanted magical incantations."
                    )
                    else:
                        group = fighters if len(fight_list) > 0 else wizards
                        text = (
                            f"{bold(group)} slayed the {challenge_amount}{challenge}{plural} "
                            f"in battle, while {bold(talkers)} distracted with insults."
                        )
                text += await self._reward(
                    ctx,
                    fight_list + magic_list + talk_list + pray_list,
                    amount,
                    round((((attack+magic) / hp) + (diplomacy / dipl)) * 0.2),
                    treasure,
                )

            if not slain and persuaded:
                if len(pray_list) > 0:
                    text = (
                        f"{bold(talkers)} talked the {challenge_amount}{challenge}{plural} "
                        f"down with {bold(preachermen)}'s blessing."
                    )
                else:
                    text = f"{bold(talkers)} talked the {challenge_amount}{challenge}{plural} down."
                text += await self._reward(
                    ctx, talk_list + pray_list, amount, round((diplomacy / dipl) * 0.2), treasure
                )

            if slain and not persuaded:
                if len(pray_list) > 0:
                    if len(magic_list) > 0 and len(fight_list) > 0:
                        text = (
                            f"{bold(fighters)} killed the {challenge_amount}{challenge}{plural} "
                            f"in a most heroic battle with a little help from {bold(preachermen)} and "
                            f"{bold(wizards)} chanting magical incantations."
                        )
                    else:
                        group = fighters if len(fight_list) > 0 else wizards
                        text = (
                            f"{bold(group)} killed the {challenge_amount}{challenge}{plural} "
                            f"in a most heroic battle with a little help from {bold(preachermen)}."
                        )
                else:
                    if len(magic_list) > 0 and len(fight_list) > 0:
                        text = (
                            f"{bold(fighters)} killed the {challenge_amount}{challenge}{plural} "
                            f"in a most heroic battle with {bold(wizards)} chanting magical incantations."
                        )
                    else:
                        group = fighters if len(fight_list) > 0 else wizards
                        text = f"{bold(group)} killed the {challenge_amount}{challenge}{plural} in an epic fight."
                text += await self._reward(
                    ctx, fight_list + magic_list + pray_list, amount, round(((attack+magic) / hp) * 0.2), treasure
                )

            if not slain and not persuaded:
                users = fight_list + magic_list + talk_list + pray_list + run_list + fumblelist
                if len(run_name_list) >= 1:
                    result_msg += (f"\n{bold(humanize_list(run_name_list))} wanted to run away but froze in fear.")
                repair_list.append([users, " to repair their gear.\n", " to have their gear repaired...\n"])
                options = [
                    f"No amount of diplomacy or valiant fighting could save you.\n",
                    f"This challenge was too much for the group.\n",
                    f"You tried your best, but couldn't succeed.\n"
                ]
                text = random.choice(options)

        await ctx.send(result_msg + "\n" + text)
        # Failing basilisk with the correct item would lead to 2 lists and allows for more in future
        for repairs in repair_list:
            await self.repair_users(ctx, repairs[0], repairs[1], repairs[2])
        await self._data_check(ctx)
        session.participants = set(fight_list + magic_list + talk_list + pray_list + run_list + fumblelist)

    async def repair_users(self, ctx, users, repair_msg = " to repair their gear.\n", fail_repair_msg = " to have their gear repaired...\n"):
        currency_name = await bank.get_currency_name(ctx.author.guild)
        repaired = []
        broke = []
        loss_list = []
        naked_list = []
        if str(currency_name).startswith("<"):
            currency_name = "credits"
        
        for user in users:
            c = await Character._from_json(self.config, user)
            repair_cost = 0 
            for current_item in c.current_equipment():
                if "normal" in current_item.rarity:
                    repair_cost += 10
                elif "rare" in current_item.rarity:
                    repair_cost += 25
                elif "epic" in current_item.rarity:
                    repair_cost += 100
                elif "legendary" in current_item.rarity:
                    repair_cost += 250
                elif "forged" in current_item.rarity:  # specialised equipment, hard to repair!
                    repair_cost += 500
            try:
                await bank.withdraw_credits(user, repair_cost)
                repaired.append([user, repair_cost])
            except ValueError:
                broke.append([user, repair_cost])
        
        if len(repaired) > 0:
            for user, loss in repaired:
                if loss > 0:
                    loss_list.append(f"{bold(self.E(user.display_name))} used {str(loss)} {currency_name}")
                else:
                    naked_list.append(f"{bold(self.E(user.display_name))}")                    
            repair_text = ("" if not loss_list else f"{humanize_list(loss_list)} {repair_msg}")
            repair_text +=  ("" if not naked_list else f"{humanize_list(naked_list)} had nothing to repair.")
            await ctx.send(repair_text)
        
        for user, loss in broke:
            c = await Character._from_json(self.config, user)
            broke_msg = (f"{bold(self.E(user.display_name))} couldn't afford {str(loss)} {currency_name} {fail_repair_msg}"
                                f"Don't worry, I'll take items from your backpack to make up for it!\n")
            msg = await ctx.send(broke_msg)
            bal = await bank.get_balance(user)
            while bal <= loss:
                if len(c.backpack.items()) == 0:
                    empty_msg = f"Looks like you have nothing left {self.E(user.display_name)}... pity.\n"
                    await ctx.send(empty_msg)
                    break
                name, item = random.choice(list(c.backpack.items()))
                item.owned -= 1
                price = await self._sell(user, item)
                await bank.deposit_credits(user, price)
                sold_msg = (
                    f"{self.E(user.display_name)} sold their "
                    f"{item} for {price} {currency_name}.\n"
                )
                await ctx.send(sold_msg)
                if item.owned <= 0:
                    del c.backpack[item.name]
                bal = await bank.get_balance(user)
            try:
                await bank.withdraw_credits(user, loss)
                even_msg = (f"Your debt is paid {self.E(user.display_name)}.\n")
                await ctx.send(even_msg)
            except ValueError:
                pass
            await self.config.user(user).set(c._to_json())

    async def _class_bonus(self, class_name, user_list, stat_checks):
        ability_triggered = False
        bonus_stat = 0
        bonus = 0
        bonus_user = None
        for user in user_list:
            if ability_triggered:
                break
            try:
                c = await Character._from_json(self.config, user)
            except Exception:
                log.error("Error with the new character sheet", exc_info=True)
                continue
            if c.heroclass["name"] == class_name:
                for stat in stat_checks:
                    bonus_stat += getattr(c, stat) + c.skill[stat]
                bonus_stat = int(bonus_stat / len(stat_checks))
                chance = min(int(bonus_stat / 2.5 + 1), c.lvl)
                roll = random.randint(1, 100)
                if roll in range (1, chance):
                    ability_triggered = True
                    bonus = int(chance * 0.4) + 3
                    bonus_user = user
        return bonus, bonus_user

    async def _cleric_bonus(self, session):
        aura = False
        bless_bonus = 0
        aura_chance = 0
        blessed_user = None
        for user in session.pray: #check if a cleric is praying and calculate the possible bonus
            try:
                c = await Character._from_json(self.config, user)
            except Exception:
                log.error("Error with the new character sheet", exc_info=True)
                continue
            bonus_cleric = int((c.int + c.skill["int"] + c.att + c.skill["att"] + c.cha + c.skill["cha"])/3)
            if c.heroclass["name"] == "Cleric" and not aura:
                chance = min(int(bonus_cleric / 1.5 + 1), c.lvl * 2)
                aura_roll = random.randint(1, 100)
                if aura_roll in range (1, chance):
                    aura = True
                    aura_chance = chance
                    blessed_user = user
            if c.heroclass["name"] == "Cleric" and c.heroclass["ability"]:
                bless_base = max(10, int((10 + bonus_cleric) * 0.5))
                bless_bonus += max(1, int(bless_base / len(session.fight + session.magic + session.talk)))
        return aura_chance, bless_bonus, blessed_user

    async def handle_fight(self, guild_id, fumblelist, critlist, attack, magic, challenge):
        session = self._sessions[guild_id]
        pdef = self.MONSTERS[challenge]["pdef"]
        mdef = self.MONSTERS[challenge]["mdef"]
        # make sure we pass this check first
        if len(session.fight + session.magic) >= 1:
            msg = ""
            if len(session.fight) >= 1:
                if pdef >= 1.5:
                    msg+= f"Swords bounce off this monster as it's skin is **almost impenetrable!**"
                elif pdef >= 1.25:
                    msg+= f"This monster has **extremely tough** armour!"
                elif pdef > 1:
                    msg+= f"This monster has **thick skin!**"
                elif pdef >= 0.75 and pdef < 1:
                    msg+= f"This monster is **soft and easy** to slice!"
                elif pdef > 0 and pdef != 1:
                    msg+= f"Swords slice through this monster like a **hot knife through butter!**"
                if pdef != 1:
                    mult = 1/pdef
                    msg+= f" *[🗡 x{mult:0.2f}]*\n"
            if len(session.magic) >= 1:
                if mdef >= 1.5:
                    msg+= f"Magic? Pfft, your puny magic is **no match** for this creature!"
                elif mdef >= 1.25:
                    msg+= f"This monster has **substantial magic resistance!**"
                elif mdef > 1:
                    msg+= f"This monster has increased **magic resistance!**"
                elif mdef >= 0.75 and mdef < 1:
                    msg+= f"This monster's hide **melts to magic!**"
                elif mdef > 0 and mdef != 1:
                    msg+= f"Magic spells are **hugely effective** against this monster!"
                if mdef != 1:
                    mult = 1/mdef
                    msg+= f" *[🌟 x{mult:0.2f}]*\n"
            report = "Attack Party: "
        else:
            return (fumblelist, critlist, attack, magic, "")

        sharpen_bonus, sharpen_user = await self._class_bonus("Tinkerer", session.fight, ["att"])
        if sharpen_bonus > 0:
            msg += f"{bold(self.E(sharpen_user.display_name))} sharpened the weapons of the party! *[🗡 +{sharpen_bonus}%]*\n"
        incision_bonus, incision_user = await self._class_bonus("Bard", session.fight, ["att", "cha"])
        if incision_bonus > 0:
            msg += f"{bold(self.E(incision_user.display_name))} strikes precise incisions with his dagger! *[-{incision_bonus}% to 🗡 resistance]*\n"
        potion_bonus, potion_user = await self._class_bonus("Tinkerer", session.magic, ["int"])
        if potion_bonus > 0:
            msg += f"{bold(self.E(potion_user.display_name))} crafted mana potion for the party! *[🌟 +{potion_bonus}%]*\n"
        melody_bonus, melody_user = await self._class_bonus("Bard", session.magic, ["int", "cha"])
        if melody_bonus > 0:
            msg += f"{bold(self.E(melody_user.display_name))} whispered a dissonant melody to the enemy, wracking it with terrible pain! *[-{melody_bonus}% to 🌟 resistance]*\n"
        aura_chance, bless_bonus, blessed_user = await self._cleric_bonus(session)
        if aura_chance > 0:
            msg += f"A holy aura starts surrounding {bold(self.E(blessed_user.display_name))} while praying! *[+{aura_chance}% to 🗡/🌟 critical chance and 🗯️/⚡️ dmg]*\n"
        aura_bonus = int(aura_chance * 0.2)
        bless_display = f" +🛐{bless_bonus}" if bless_bonus != 0 else ""

        for user in session.fight:
            roll = random.randint(1, 20)
            crit_roll = min(random.randint(1, 20) + aura_bonus, 20)
            try:
                c = await Character._from_json(self.config, user)
            except Exception:
                log.error("Error with the new character sheet", exc_info=True)
                continue
            att_value = c.att + c.skill["att"]
            if roll == 1:
                hero_dmg = 0
                msg += f"{bold(self.E(user.display_name))} fumbled the attack.\n"
                if c.heroclass["name"] == "Berserker" and c.heroclass["ability"]:
                    ability = "🗯️"
                    bonus_roll = random.randint(5, 15)
                    bonus_multi = random.choice([0.2, 0.3, 0.4, 0.5])
                    bonus = int(max(bonus_roll, int((roll + att_value) * bonus_multi)) * (1 + (aura_chance / 100)))
                    hero_dmg = int((roll - bonus + att_value + bless_bonus) * (1 + (sharpen_bonus / 100)) / (pdef * (1 - incision_bonus / 100)))
                    attack += hero_dmg
                    bonus = ability + str(bonus)
                    report += (
                        f"| {bold(self.E(user.display_name))}: "
                        f"🎲({roll}) -💥{bonus} +🗡{str(att_value)}{bless_display} did **🗡{hero_dmg} dmg** | "
                    )
                if hero_dmg <= 0:
                    fumblelist.append(user)
            elif crit_roll == 20 or (c.heroclass["name"] == "Berserker" and c.heroclass["ability"]):
                ability = ""
                if crit_roll == 20:
                    msg += f"{bold(self.E(user.display_name))} landed a critical hit.\n"
                    critlist.append(user)
                bonus_roll = random.randint(5, 15)
                bonus_multi = 0.5 if (c.heroclass["name"] == "Berserker" and c.heroclass["ability"]) else random.choice([0.2, 0.3, 0.4, 0.5])
                if c.heroclass["ability"]:
                    ability = "🗯️"
                    bonus = int(max(bonus_roll, int((roll + att_value) * bonus_multi)) * (1 + (aura_chance / 100)))
                else:
                    bonus = max(bonus_roll, int((roll + att_value) * bonus_multi))
                hero_dmg = int((roll + bonus + att_value + bless_bonus) * (1 + (sharpen_bonus / 100)) / (pdef * (1 - incision_bonus / 100)))
                attack += hero_dmg
                bonus = ability + str(bonus)
                report += (
                    f"| {bold(self.E(user.display_name))}: "
                    f"🎲({roll}) +💥{bonus} +🗡{str(att_value)}{bless_display} did **🗡{hero_dmg} dmg** | "
                )
            else:
                hero_dmg = int((roll + att_value + bless_bonus) * (1 + (sharpen_bonus / 100)) / (pdef * (1 - incision_bonus / 100))) 
                attack += hero_dmg
                report += (
                    f"| {bold(self.E(user.display_name))}: 🎲({roll}) +🗡{str(att_value)}{bless_display} did **🗡{hero_dmg} dmg** | "
                )

        for user in session.magic:
            roll = random.randint(1, 20)
            crit_roll = min(random.randint(1, 20) + aura_bonus, 20)
            try:
                c = await Character._from_json(self.config, user)
            except Exception:
                log.error("Error with the new character sheet", exc_info=True)
                continue
            int_value = c.int + c.skill["int"]
            if roll == 1:
                hero_dmg = 0
                msg += f"{bold(self.E(user.display_name))} almost set themselves on fire.\n"
                if c.heroclass["name"] == "Wizard" and c.heroclass["ability"]:
                    ability = "⚡️"
                    bonus_roll = random.randint(5, 15)
                    bonus_multi = random.choice([0.2, 0.3, 0.4, 0.5])
                    bonus = int(max(bonus_roll, int((roll + int_value) * bonus_multi)) * (1 + (aura_chance / 100)))
                    hero_dmg = int((roll - bonus + int_value + bless_bonus) * (1 + (potion_bonus / 100)) / (mdef * (1 - melody_bonus / 100)))
                    magic += hero_dmg
                    bonus = ability + str(bonus)
                    report += (
                        f"| {bold(self.E(user.display_name))}: "
                        f"🎲({roll}) -💥{bonus} +🌟{str(int_value)}{bless_display} did **🌟{hero_dmg} dmg** | "
                    )
                if hero_dmg <= 0:
                    fumblelist.append(user)
            elif crit_roll == 20 or (c.heroclass["name"] == "Wizard" and c.heroclass["ability"]):
                ability = ""
                if crit_roll == 20:
                    msg += f"{bold(self.E(user.display_name))} had a surge of energy.\n"
                    critlist.append(user)
                bonus_roll = random.randint(5, 15)
                bonus_multi = 0.5 if (c.heroclass["name"] == "Wizard" and c.heroclass["ability"]) else random.choice([0.2, 0.3, 0.4, 0.5])
                if c.heroclass["ability"]:
                    ability = "⚡️"
                    bonus = int(max(bonus_roll, int((roll + int_value) * bonus_multi)) * (1 + (aura_chance / 100)))
                else:
                    bonus = max(bonus_roll, int((roll + int_value) * bonus_multi))
                hero_dmg = int((roll + bonus + int_value + bless_bonus) * (1 + (potion_bonus / 100)) / (mdef * (1 - melody_bonus / 100)))
                magic += hero_dmg
                bonus = ability + str(bonus)
                report += (
                    f"| {bold(self.E(user.display_name))}: "
                    f"🎲({roll}) +💥{bonus} +🌟{str(int_value)}{bless_display} did **🌟{hero_dmg} dmg** | "
                )
            else:
                hero_dmg = int((roll + int_value + bless_bonus) * (1 + (potion_bonus / 100)) / (mdef * (1 - melody_bonus / 100)))
                magic += hero_dmg
                report += (
                    f"| {bold(self.E(user.display_name))}: 🎲({roll}) +🌟{str(int_value)}{bless_display} did **🌟{hero_dmg} dmg** | "
                )
        
        for user in fumblelist:
            if user in session.fight:
                session.fight.remove(user)
            elif user in session.magic:
                session.magic.remove(user)
        if report == "Attack Party: ":
            report = ""  # if everyone fumbles
        msg = msg + report + "\n"
        return (fumblelist, critlist, attack, magic, msg)

    async def handle_pray(self, guild_id, fumblelist, attack, diplomacy, magic):
        session = self._sessions[guild_id]
        talk_list = session.talk
        pray_list = session.pray
        fight_list = session.fight
        magic_list = session.magic
        bless_base = 0
        bless_bonus = 0
        total_bless_bonus = 0
        bless_list_name = []
        if len(pray_list) >= 1:
            msg = ""
            report = ""
        else:
            return (fumblelist, attack, diplomacy, magic, "")
        god = await self.config.god_name()
        if await self.config.guild(self.bot.get_guild(guild_id)).god_name():
            god = await self.config.guild(self.bot.get_guild(guild_id)).god_name()
        
        total_size = len(fight_list + talk_list + magic_list)
        if total_size == 0:
            pray_list_name = []
            for user in pray_list:
                pray_list_name.append(self.E(user.display_name))
            attrib = f"a madman" if len(pray_list_name) == 1 else f"madmen"
            msg += f"{bold(humanize_list(pray_list_name))} blessed like {attrib} but nobody was there to receive it.\n"
            return (fumblelist, attack, diplomacy, magic, msg)
        
        glyphs_bonus, glyphs_user = await self._class_bonus("Wizard", session.magic, ["int"])
        if glyphs_bonus > 0:
            msg += f"{bold(self.E(glyphs_user.display_name))}'s magic glyphs start glowing, amplifying all prayers! *[🛐 +{glyphs_bonus}%]*\n"
        for user in pray_list:
            try:
                c = await Character._from_json(self.config, user)
            except Exception:
                log.error("Error with the new character sheet", exc_info=True)
                continue
            pray_bonus = int((c.int + c.skill["int"] + c.att + c.skill["att"] + c.cha + c.skill["cha"])/3)
            roll = random.randint(1, 20)
            pray_score = pray_bonus + roll
            if c.heroclass["name"] == "Cleric" and c.heroclass["ability"]: #always calculate the bless bonus and its total
                bless_base = max(10, int((10 + pray_bonus) * 0.5))
                bless_bonus = max(1, int(bless_base / total_size))
                bless_list_name.append(self.E(user.display_name))
                total_bless_bonus += bless_bonus
            if roll == 1: #fumble
                if c.heroclass["name"] == "Cleric" and c.heroclass["ability"]:#malus that compensate the bonus granted to the party
                    pray_score = pray_score - bless_base - bless_bonus * total_size
                    msg += f"{bold(self.E(user.display_name))}'s sermon offended the mighty {god}.\n"
                    contrib_attack = int(((len(fight_list) / total_size) * pray_score + len(fight_list) * c.lvl / 10) * (1 + (glyphs_bonus / 100)))
                    contrib_diplomacy = int(((len(talk_list) / total_size) * pray_score + len(talk_list) * c.lvl / 10) * (1 + (glyphs_bonus / 100)))
                    contrib_magic = int(((len(magic_list) / total_size) * pray_score + len(magic_list) * c.lvl / 10) * (1 + (glyphs_bonus / 100)))
                    attack += contrib_attack
                    diplomacy += contrib_diplomacy
                    magic += contrib_magic
                    report += (
                    f"| {bold(self.E(user.display_name))}: "
                    f"🎲({roll}) +🛐{str(pray_bonus)} did **🗡{contrib_attack}/🗨{contrib_diplomacy}/🌟{contrib_magic}** | "
                    )
                    if (contrib_attack + contrib_magic + contrib_diplomacy) <= 0:
                        fumblelist.append(user)
                else: #no cleric's bonus activated and roll 1
                    msg += f"{bold(self.E(user.display_name))}'s prayers went unanswered by {god}.\n"
                    fumblelist.append(user)
            else:
                if roll == 20:
                    msg += f"{bold(self.E(user.display_name))} turned into an avatar of mighty {god}!\n"
                contrib_attack = int(((len(fight_list) / total_size) * pray_score + len(fight_list) * c.lvl / 10) * (1 + (glyphs_bonus / 100)))
                contrib_diplomacy = int(((len(talk_list) / total_size) * pray_score + len(talk_list) * c.lvl / 10) * (1 + (glyphs_bonus / 100)))
                contrib_magic = int(((len(magic_list) / total_size) * pray_score + len(magic_list) * c.lvl / 10) * (1 + (glyphs_bonus / 100)))
                attack += contrib_attack
                diplomacy += contrib_diplomacy
                magic += contrib_magic
                report += (
                    f"| {bold(self.E(user.display_name))}: "
                    f"🎲({roll}) +🛐{str(pray_bonus)} did **🗡{contrib_attack}/🗨{contrib_diplomacy}/🌟{contrib_magic}** | "
                )
        header = "Pray Party: " if (attack + diplomacy + magic) != 0 else ""
        if len(bless_list_name) > 0:
            bless_msg = f"The party is greatly inspired by {bold(humanize_list(bless_list_name))}! *[+{total_bless_bonus} to 🗡/🗨/🌟]*\n"
        else:
            bless_msg = ""
        msg = bless_msg + msg + header + report + "\n"
        for user in fumblelist:
            if user in pray_list:
                pray_list.remove(user)
        return (fumblelist, attack, diplomacy, magic, msg)

    async def handle_talk(self, guild_id, fumblelist, critlist, diplomacy):
        session = self._sessions[guild_id]
        if len(session.talk) >= 1:
            report = "Talking Party: "
            msg = ""
        else:
            return (fumblelist, critlist, diplomacy, "")
        fury_bonus, fury_user = await self._class_bonus("Berserker", session.fight, ["cha"])
        if fury_bonus > 0:
            msg += f"{bold(self.E(fury_user.display_name))}'s fury intimidates the enemy! *[🗨 +{fury_bonus}%]*\n"
        aura_chance, bless_bonus, blessed_user = await self._cleric_bonus(session)

        for user in session.talk:
            try:
                c = await Character._from_json(self.config, user)
            except Exception:
                log.error("Error with the new character sheet", exc_info=True)
                continue
            roll = random.randint(1, 20)
            dipl_value = c.cha + c.skill["cha"]     
            if roll == 1:
                hero_talk = 0
                msg += f"{bold(self.E(user.display_name))} accidentally offended the enemy.\n"
                if c.heroclass["name"] == "Bard" and c.heroclass["ability"]:
                    ability = "🎵"
                    bonus_roll = random.randint(5, 15)
                    bonus_multi = random.choice([0.2, 0.3, 0.4, 0.5])
                    bonus = max(bonus_roll, int((roll + dipl_value) * bonus_multi))
                    hero_talk = int((roll - bonus + dipl_value + bless_bonus) * (1 + (fury_bonus / 100)))
                    diplomacy += hero_talk
                    bonus = ability + str(bonus)
                    report += (
                        f"| {bold(self.E(user.display_name))} "
                        f"🎲({roll}) -💥{bonus} +🗨{str(dipl_value)} did **🗨{hero_talk}** | "
                    )
                if hero_talk <= 0:
                    fumblelist.append(user)
            elif roll == 20 or c.heroclass["name"] == "Bard" and c.heroclass["ability"]:
                ability = ""
                if roll == 20:
                    msg += f"{bold(self.E(user.display_name))} made a compelling argument.\n"
                    critlist.append(user)
                if c.heroclass["ability"]:
                    ability = "🎵"
                bonus_roll = random.randint(5, 15)
                bonus_multi = 0.5 if (c.heroclass["name"] == "Bard" and c.heroclass["ability"]) else random.choice([0.2, 0.3, 0.4, 0.5])
                bonus = max(bonus_roll, int((roll + dipl_value) * bonus_multi))
                hero_talk = int((roll + bonus + dipl_value + bless_bonus) * (1 + (fury_bonus / 100)))
                diplomacy += hero_talk
                bonus = ability + str(bonus)
                report += (
                    f"| {bold(self.E(user.display_name))} "
                    f"🎲({roll}) +💥{bonus} +🗨{str(dipl_value)} did **🗨{hero_talk}** | "
                )
            else:
                hero_talk = int((roll + dipl_value + bless_bonus) * (1 + (fury_bonus / 100)))
                diplomacy += hero_talk
                report += (
                    f"| {bold(self.E(user.display_name))} 🎲({roll}) +🗨{str(dipl_value)} did **🗨{hero_talk}** | "
                )
        
        for user in fumblelist:
            if user in session.talk:
                session.talk.remove(user)
        if report == "Talking Party: ":
            report = ""  # if everyone fumbles
        msg = msg + report + "\n"
        return (fumblelist, critlist, diplomacy, msg)

    async def handle_basilisk(self, ctx, failed):
        session = self._sessions[ctx.guild.id]
        fight_list = session.fight
        magic_list = session.magic
        talk_list = session.talk
        pray_list = session.pray
        challenge = session.challenge
        if session.miniboss:
            failed = True
            item, slot = session.miniboss["requirements"]
            for user in (
                fight_list + magic_list + talk_list + pray_list
            ):  # check if any fighter has an equipped mirror shield to give them a chance.
                try:
                    c = await Character._from_json(self.config, user)
                except Exception:
                    log.error("Error with the new character sheet", exc_info=True)
                    continue
                try:
                    current_item = getattr(c, slot)
                    if item in str(current_item):
                        failed = False
                        break
                except KeyError:
                    continue
        else:
            failed = False
        return failed

    async def _total_xp_required(self, level):
        total_xp = 0
        for lvl in range(1, level + 1):
            total_xp += 10 * (lvl ** 2) + ((lvl-1) * 100) + 100
        return total_xp

    async def _add_rewards(self, ctx, user, exp, cp, special):
        try:
            c = await Character._from_json(self.config, user)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        c.exp += exp
        member = ctx.guild.get_member(user.id)
        await bank.deposit_credits(member, cp)
        lvl_start = c.lvl
        lvl_end = lvl_start
        xp_needed = await self._total_xp_required(lvl_end)
        while c.exp >= xp_needed:
            lvl_end += 1
            xp_needed = await self._total_xp_required(lvl_end)

        if lvl_start < lvl_end:
            # recalculate free skillpoint pool based on new level and already spent points.
            await ctx.send(f"{user.mention} is now level {lvl_end}!")
            c.lvl = lvl_end
            c.skill["pool"] = int(lvl_end / 3) - (c.skill["att"] + c.skill["cha"] + c.skill["int"])
            if c.skill["pool"] > 0:
                await ctx.send(f"{self.E(user.display_name)}, you have skillpoints available.")
        if special is not False:
            c.treasure = [sum(x) for x in zip(c.treasure, special)]
        await self.config.user(user).set(c._to_json())

    async def _adv_countdown(self, ctx, seconds, title) -> asyncio.Task:
        await self._data_check(ctx)

        async def adv_countdown():
            secondint = int(seconds)
            adv_end = await self._get_epoch(secondint)
            timer, done, sremain = await self._remaining(adv_end)
            message_adv = await ctx.send(f"⏳ [{title}] {timer}s")
            while not done:
                timer, done, sremain = await self._remaining(adv_end)
                self._adventure_countdown[ctx.guild.id] = (timer, done, sremain)
                if done:
                    await message_adv.delete()
                    break
                elif int(sremain) % 5 == 0:
                    await message_adv.edit(content=(f"⏳ [{title}] {timer}s"))
                await asyncio.sleep(1)
            log.info("Timer countdown done.")

        return ctx.bot.loop.create_task(adv_countdown())

    async def _cart_countdown(self, ctx, seconds, title) -> asyncio.Task:
        await self._data_check(ctx)

        async def cart_countdown():
            secondint = int(seconds)
            cart_end = await self._get_epoch(secondint)
            timer, done, sremain = await self._remaining(cart_end)
            message_cart = await ctx.send(f"⏳ [{title}] {timer}s")
            while not done:
                timer, done, sremain = await self._remaining(cart_end)
                self._trader_countdown[ctx.guild.id] = (timer, done, sremain)
                if done:
                    await message_cart.delete()
                    break
                if int(sremain) % 5 == 0:
                    await message_cart.edit(content=(f"⏳ [{title}] {timer}s"))
                await asyncio.sleep(1)

        return ctx.bot.loop.create_task(cart_countdown())

    @staticmethod
    async def _clear_react(msg):
        try:
            await msg.clear_reactions()
        except discord.errors.Forbidden:
            pass

    async def _data_check(self, ctx):
        try:
            self._adventure_countdown[ctx.guild.id]
        except KeyError:
            self._adventure_countdown[ctx.guild.id] = 0
        try:
            self._rewards[ctx.author.id]
        except KeyError:
            self._rewards[ctx.author.id] = {}
        try:
            self._trader_countdown[ctx.guild.id]
        except KeyError:
            self._trader_countdown[ctx.guild.id] = 0

    @staticmethod
    async def _get_epoch(seconds: int):
        epoch = time.time()
        epoch += seconds
        return epoch

    async def on_message(self, message):
        if not message.guild:
            return
        channels = await self.config.guild(message.guild).cart_channels()
        if not channels:
            return
        if message.channel.id not in channels:
            return
        if not message.author.bot:
            try:
                self._last_trade[message.guild.id]
            except KeyError:
                self._last_trade[message.guild.id] = 0
            if self._last_trade[message.guild.id] == 0:
                self._last_trade[message.guild.id] = time.time()
            roll = random.randint(1, 20)
            if roll == 20:
                ctx = await self.bot.get_context(message)
                await self._trader(ctx)

    async def _roll_chest(self, chest_type: str):
        roll = random.randint(1, 500)
        if chest_type.lower() in "pet":
            if roll == 1:
                chance = self.TR_LEGENDARY
            elif roll <= 25:
                chance = self.TR_EPIC
            elif roll <= 125:
                chance = self.TR_RARE
            elif roll <= 375:
                chance = self.TR_COMMON
            else:
                return None
        if chest_type.lower() in "normal":
            if roll == 1:
                chance = self.TR_LEGENDARY
            elif roll <= 5:
                chance = self.TR_EPIC
            elif roll <= 25:
                chance = self.TR_RARE
            else:
                chance = self.TR_COMMON
        elif chest_type.lower() in "rare":
            if roll <= 6:
                chance = self.TR_LEGENDARY
            elif roll <= 30:
                chance = self.TR_EPIC
            elif roll <= 150:
                chance = self.TR_RARE
            else:
                chance = self.TR_COMMON
        elif chest_type.lower() in "epic":
            if roll <= 30:
                chance = self.TR_LEGENDARY
            elif roll <= 150:
                chance = self.TR_EPIC
            else:
                chance = self.TR_RARE
        elif chest_type.lower() in "legendary":
            if roll <= 100:
                chance = self.TR_LEGENDARY
            else:
                chance = self.TR_EPIC
        else:
            chance = self.TR_COMMON
        itemname = random.choice(list(chance.keys()))
        return Item._from_json({itemname: chance[itemname]})

    async def _open_chests(self, ctx: Context, user: discord.Member, chest_type: str, amount: int):
        """This allows you you to open multiple chests at once and put them in your inventory"""
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        await asyncio.sleep(2)
        items = [await self._roll_chest(chest_type) for i in range(1, amount+1)]

        for item in items:
            if item.name in c.backpack:
                c.backpack[item.name].owned += 1
            else:
                c.backpack[item.name] = item
        await self.config.user(ctx.author).set(c._to_json())
        return items

    async def _open_chest(self, ctx, user, chest_type):
        if hasattr(user, "display_name"):
            chest_msg = (
                f"{self.E(user.display_name)} is opening a treasure chest. What riches lay inside?"
            )
        else:
            chest_msg = (
                f"{self.E(ctx.author.display_name)}'s {user[:1] + user[1:]} is "
                "foraging for treasure. What will it find?"
            )
        try:
            c = await Character._from_json(self.config, ctx.author)
        except Exception:
            log.error("Error with the new character sheet", exc_info=True)
            return
        open_msg = await ctx.send(box(chest_msg, lang="css"))
        await asyncio.sleep(2)

        item = await self._roll_chest(chest_type)
        if chest_type == "pet" and not item:
            await open_msg.edit(
                    content=box(
                        f"{chest_msg}\nThe {user[:1] + user[1:]} found nothing of value.",
                        lang="css",
                    )
                )
            return None
        slot = item.slot[0]
        if len(item.slot) > 1:
            slot = "two handed"
        if hasattr(user, "display_name"):

            chest_msg2 = (
                f"{self.E(user.display_name)} found a {item}. (Attack: "
                f"{str(item.att)}, Intelligence: {str(item.int)}, Charisma: {str(item.cha)}) [{slot}]"
            )
            await open_msg.edit(
                content=box(
                    (
                        f"{chest_msg}\n{chest_msg2}\nDo you want to equip "
                        "this item, put in your backpack, or sell this item?"
                    ),
                    lang="css",
                )
            )
        else:
            chest_msg2 = (
                f"The {user} found a {item}. (Attack: "
                f"{str(item.att)}, Intelligence: {str(item.int)}, Charisma: {str(item.cha)}) [{slot}]"
            )
            await open_msg.edit(
                content=box(
                    (
                        f"{chest_msg}\n{chest_msg2}\nDo you want to equip "
                        "this item, put in your backpack, or sell this item?"
                    ),
                    lang="css",
                )
            )

        start_adding_reactions(open_msg, self._treasure_controls.keys())
        if hasattr(user, "id"):
            pred = ReactionPredicate.with_emojis(
                tuple(self._treasure_controls.keys()), open_msg, user
            )
        else:
            pred = ReactionPredicate.with_emojis(
                tuple(self._treasure_controls.keys()), open_msg, ctx.author
            )
        try:
            react, user = await ctx.bot.wait_for("reaction_add", check=pred, timeout=60)
        except asyncio.TimeoutError:
            await self._clear_react(open_msg)
            if item.name in c.backpack:
                c.backpack[item.name].owned += 1
            else:
                c.backpack[item.name] = item
            await open_msg.edit(
                content=(
                    box(
                        f"{self.E(ctx.author.display_name)} put the {item} into their backpack.",
                        lang="css",
                    )
                )
            )
            await self.config.user(ctx.author).set(c._to_json())
            return
        await self._clear_react(open_msg)
        if self._treasure_controls[react.emoji] == "sell":
            price = await self._sell(ctx.author, item)
            await bank.deposit_credits(ctx.author, price)
            currency_name = await bank.get_currency_name(ctx.guild)
            if str(currency_name).startswith("<"):
                currency_name = "credits"
            await open_msg.edit(
                content=(
                    box(
                        (
                            f"{self.E(ctx.author.display_name)} sold "
                            f"the {item} for {price} {currency_name}."
                        ),
                        lang="css",
                    )
                )
            )
            await self._clear_react(open_msg)
            await self.config.user(ctx.author).set(c._to_json())
        elif self._treasure_controls[react.emoji] == "equip":
            # equip = {"itemname": item[0]["itemname"], "item": item[0]["item"]}
            if not getattr(c, item.slot[0]):
                equip_msg = box(
                    f"{self.E(ctx.author.display_name)} equipped {item} ({slot} slot).", lang="css"
                )
            else:
                equip_msg = box(
                    (
                        f"{self.E(ctx.author.display_name)} equipped {item} "
                        f"({slot} slot) and put {getattr(c, item.slot[0])} into their backpack."
                    ),
                    lang="css",
                )
            await open_msg.edit(content=equip_msg)
            c = await c._equip_item(item, False)
            await self.config.user(ctx.author).set(c._to_json())
        else:
            # async with self.config.user(ctx.author).all() as userinfo:
            # userinfo["items"]["backpack"].update({item[0]["itemname"]: item[0]["item"]})
            if item.name in c.backpack:
                c.backpack[item.name].owned += 1
            else:
                c.backpack[item.name] = item
            await open_msg.edit(
                content=(
                    box(
                        f"{self.E(ctx.author.display_name)} put the {item} into their backpack.",
                        lang="css",
                    )
                )
            )
            await self._clear_react(open_msg)
            await self.config.user(ctx.author).set(c._to_json())

    @staticmethod
    async def _remaining(epoch):
        remaining = epoch - time.time()
        finish = remaining < 0
        m, s = divmod(remaining, 60)
        h, m = divmod(m, 60)
        s = int(s)
        m = int(m)
        h = int(h)
        if h == 0 and m == 0:
            out = "{:02d}".format(s)
        elif h == 0:
            out = "{:02d}:{:02d}".format(m, s)
        else:
            out = "{:01d}:{:02d}:{:02d}".format(h, m, s)
        return out, finish, remaining

    async def _reward(self, ctx, userlist, amount, modif, special):
        if modif == 0:
            modif = 0.5
        xp = max(1, round(amount))
        cp = max(1, round(amount * modif))
        rewards_list = []
        phrase = ""
        for user in userlist:
            self._rewards[user.id] = {}
            try:
                c = await Character._from_json(self.config, user)
            except Exception:
                log.error("Error with the new character sheet", exc_info=True)
                return
            roll = random.randint(1, 5)
            if (
                roll == 5
                and c.heroclass["name"] == "Ranger"
                and c.heroclass["pet"]
            ):
                self._rewards[user.id]["xp"] = int(xp * c.heroclass["pet"]["bonus"])
                self._rewards[user.id]["cp"] = int(cp * c.heroclass["pet"]["bonus"])
                percent = round((c.heroclass["pet"]["bonus"] - 1.0) * 100)
                phrase = (
                    f"\n{bold(self.E(user.display_name))} received a {bold(str(percent))}% "
                    f"reward bonus from their {c.heroclass['pet']['name']}."
                )

            else:
                self._rewards[user.id]["xp"] = xp
                self._rewards[user.id]["cp"] = cp
            if special is not False:
                self._rewards[user.id]["special"] = special
            else:
                self._rewards[user.id]["special"] = False
            rewards_list.append(self.E(user.display_name))

        currency_name = await bank.get_currency_name(ctx.guild)
        to_reward = " and ".join(
            [", ".join(rewards_list[:-1]), rewards_list[-1]]
            if len(rewards_list) > 2
            else rewards_list
        )

        word = "has" if len(userlist) == 1 else "have"
        if special is not False and sum(special) == 1:
            types = [" normal", " rare", "n epic", " legendary"]
            chest_type = types[special.index(1)]
            phrase += (
                f"\n{bold(to_reward)} {word} been awarded {xp} xp and found {cp} {currency_name}. "
                f"You also secured **a{chest_type} treasure chest**!"
            )
        elif special is not False and sum(special) > 1:
            phrase += (
                f"\n{bold(to_reward)} {word} been awarded {xp} xp and found {cp} {currency_name}. "
                f"You also secured **several treasure chests**!"
            )
        else:
            phrase += (
                f"\n{bold(to_reward)} {word} been awarded {xp} xp and found {cp} {currency_name}."
            )
        return phrase

    @staticmethod
    async def _sell(user, item: Item):
        if isinstance(item, tuple):
            thing = item[0]
        else:
            thing = item
        if item.rarity == "legendary":
            base = (2000, 5000)
        elif item.rarity == "epic":
            base = (500, 1000)
        elif item.rarity == "rare":
            base = (100, 500)
        else:
            base = (10, 200)
        price = random.randint(base[0], base[1]) * max(item.att + item.cha + item.int, 1)
        return price

    async def _trader(self, ctx):
        em_list = ReactionPredicate.NUMBER_EMOJIS[:5]
        react = False
        controls = {em_list[1]: 0, em_list[2]: 1, em_list[3]: 2, em_list[4]: 3}
        cart = await self.config.cart_name()
        if await self.config.guild(ctx.guild).cart_name():
            cart = await self.config.guild(ctx.guild).cart_name()
        text = box(f"[{cart} is bringing the cart around!]", lang="css")
        if ctx.guild.id not in self._last_trade:
            self._last_trade[ctx.guild.id] = 0

        if self._last_trade[ctx.guild.id] == 0:
            self._last_trade[ctx.guild.id] = time.time()
        elif (
            self._last_trade[ctx.guild.id] >= time.time() - 10800
        ):  # trader can return after 3 hours have passed since last visit.
            return  # silent return.
        self._last_trade[ctx.guild.id] = time.time()
        stock = await self._trader_get_items()
        currency_name = await bank.get_currency_name(ctx.guild)
        if str(currency_name).startswith("<"):
            currency_name = "credits"
        for index, item in enumerate(stock):
            item = stock[index]
            if "chest" not in item["itemname"]:
                if len(item["item"]["slot"]) == 2:  # two handed weapons add their bonuses twice
                    hand = "two handed"
                    att = item["item"]["att"] * 2
                    cha = item["item"]["cha"] * 2
                    intel = item["item"]["int"] * 2
                else:
                    if item["item"]["slot"][0] == "right" or item["item"]["slot"][0] == "left":
                        hand = item["item"]["slot"][0] + " handed"
                    else:
                        hand = item["item"]["slot"][0] + " slot"
                    att = item["item"]["att"]
                    cha = item["item"]["cha"]
                    intel = item["item"]["int"]
                text += box(
                    (
                        f"\n[{str(index + 1)}] {item['itemname']} (Attack: {str(att)}, Intelligence: {str(intel)}, "
                        f"Charisma: {str(cha)} [{hand}]) for {item['price']} {currency_name}."
                    ),
                    lang="css",
                )
            else:
                text += box(
                    (
                        f"\n[{str(index + 1)}] {item['itemname']} "
                        f"for {item['price']} {currency_name}."
                    ),
                    lang="css",
                )
        text += "Do you want to buy any of these fine items? Tell me which one below:"
        msg = await ctx.send(text)
        start_adding_reactions(msg, controls.keys())
        self._current_traders[ctx.guild.id] = {"msg": msg.id, "stock": stock}
        timeout = self._last_trade[ctx.guild.id] + 180 - time.time()
        if timeout <= 0:
            timeout = 0
        timer = await self._cart_countdown(ctx, timeout, "The cart will leave in: ")
        self.tasks.append(timer)
        try:
            await asyncio.wait_for(timer, timeout + 5)
        except asyncio.TimeoutError:
            pass
        try:
            await msg.delete()
        except Exception:
            log.error("Error deleting the cart message", exc_info=True)
            pass

    async def _trader_get_items(self):
        items = {}
        output = {}

        chest_type = random.randint(1, 100)
        while len(items) < 4:
            chance = None
            roll = random.randint(1, 100)
            if chest_type <= 60:
                if roll <= 5:
                    chance = self.TR_EPIC
                elif roll > 5 and roll <= 25:
                    chance = self.TR_RARE
                elif roll >= 90:
                    chest = [1, 0, 0]
                    types = ["normal chest", ".rare_chest", "[epic chest]"]
                    if "normal chest" not in items:
                        items.update(
                            {
                                "normal chest": {
                                    "itemname": "normal chest",
                                    "item": chest,
                                    "price": 2000,
                                }
                            }
                        )
                else:
                    chance = self.TR_COMMON
            elif chest_type <= 75:
                if roll <= 15:
                    chance = self.TR_EPIC
                elif roll > 15 and roll <= 45:
                    chance = self.TR_RARE
                elif roll >= 90:
                    chest = random.choice([[0, 1, 0], [1, 0, 0]])
                    types = ["normal chest", ".rare_chest", "[epic chest]"]
                    prices = [2000, 5000, 10000]
                    chesttext = types[chest.index(1)]
                    price = prices[chest.index(1)]
                    if chesttext not in items:
                        items.update(
                            {
                                chesttext: {
                                    "itemname": "{}".format(chesttext),
                                    "item": chest,
                                    "price": price,
                                }
                            }
                        )
                else:
                    chance = self.TR_COMMON
            else:
                if roll <= 25:
                    chance = self.TR_EPIC
                elif roll >= 90:
                    chest = random.choice([[0, 1, 0], [0, 0, 1]])
                    types = ["normal chest", ".rare_chest", "[epic chest]"]
                    prices = [2000, 5000, 10000]
                    chesttext = types[chest.index(1)]
                    price = prices[chest.index(1)]
                    if chesttext not in items:
                        items.update(
                            {
                                chesttext: {
                                    "itemname": "{}".format(chesttext),
                                    "item": chest,
                                    "price": price,
                                }
                            }
                        )
                else:
                    chance = self.TR_RARE

            if chance is not None:
                itemname = random.choice(list(chance.keys()))
                item = chance[itemname]
                if len(item["slot"]) == 2:  # two handed weapons add their bonuses twice
                    hand = "two handed"
                    att = item["att"] * 2
                    cha = item["cha"] * 2
                    intel = item["int"] * 2
                else:
                    att = item["att"]
                    cha = item["cha"]
                    intel = item["int"]
                if "[" in itemname:
                    price = random.randint(1000, 2000) * max(att + cha + intel, 1)
                elif "." in itemname:
                    price = random.randint(200, 1000) * max(att + cha + intel, 1)
                else:
                    price = random.randint(10, 200) * max(att + cha + intel, 1)
                if itemname not in items:
                    items.update({itemname: {"itemname": itemname, "item": item, "price": price}})

        for index, item in enumerate(items):
            output.update({index: items[item]})
        return output
