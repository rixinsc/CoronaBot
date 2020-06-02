import discord
from discord.ext import commands, tasks
from helpers import log
from classes import TimedLock
from exceptions import BotValueError, BotRuntimeError
from typing import Union, Optional
from collections import OrderedDict
import datetime
import aiohttp
import time


class Corona(commands.Cog):
    """Commands related to the coronavirus."""

    def __init__(self, bot, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = bot

        self._corona_serviceID = "Nc2JKvYFoAEOFCG5JSI6"
        self._corona_url = "https://services9.arcgis.com/N9p5hsImWXAccRNI/" \
            "arcgis/rest/services/{service}/FeatureServer/" \
            "{feature_server_id}/query"

        self._corona_lock = TimedLock()
        self.coronaFeedTask.add_exception_type(aiohttp.ClientConnectionError)  # noqa:E501 pylint: disable=no-member
        self.coronaFeedTask.start()  # pylint: disable=no-member
        log(content="queued task to loop")

    def cog_unload(self):
        self.coronaFeedTask.clear_exception_types()  # noqa:E501 pylint: disable=no-member
        self.coronaFeedTask.stop()  # pylint: disable=no-member
        log(content="coronaTask stopped")

    def _coronaGetSession(self):
        session = aiohttp.ClientSession(headers={
            "User-Agent": "Mozilla/5.0 (Linux; Android 8.0.0;) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/80.0.3987.149 Mobile Safari/537.36",
            "referer": "https://www.arcgis.com/apps/opsdashboard/"
            "index.html"},
            timeout=aiohttp.ClientTimeout(total=120.0))
        self.bot.scheduleClose(session.close)
        return session

    async def _coronaAPICall(self, ctx: Optional[commands.Context],
                             feature_server_id: Union[int, str], *,
                             where: str = "1=1", statistics: list = '',
                             output_fields: tuple = tuple(),
                             order_by: str = '', offset: int = None,
                             limit: int = None) -> dict:
        """
        Calls Arcgis API to retrieve coronavirus' data.

        Feature server ids: (name, displayField, type)
        1 - States and Region/City (Cases, Province_State, Feature Layer)
        2 - Country (Cases_country, Country_Region, Feature Layer)
        3 - States (Cases_state, Province_State, Feature Layer)
        4 - Data with Delta_Confirmed and Delta_Recovered (States only maybe)
            (Cases_time, Country_Region, Table)
        """
        sess = self._coronaGetSession()
        async with sess.get(
            self._corona_url.format(service=self._corona_serviceID,
                                    feature_server_id=feature_server_id),
            params={"f": "json",
                    "where": where,
                    "returnGeometry": "false",
                    "spatialRel": "esriSpatialRelIntersects",
                    "outFields": ','.join(output_fields) if output_fields
                                 else '*',
                    "outStatistics": str(statistics),
                    "orderByFields": order_by if order_by else "",
                    "resultOffset": offset if offset is not None else '',
                    "resultRecordCount": limit if limit is not None else ''}
        ) as resp:
            res = await resp.json(encoding='utf-8', content_type="text/plain")
            log(content=res)

        if "error" in res:
            err = res['error']
            if ctx:
                log(ctx, 'err', reason="request failed in covid19 query",
                    content="Code: {code}\nMessage: {msg}\nDetails: {details}"
                    .format(code=err['code'], msg=err['message'],
                            details=err['details']))
            else:
                print("An error occurred when calling Arcgis API for "
                      "COVID-19 query:\n Code: {code}\n Message: {msg}\n"
                      " Details: {details}".format(
                          code=err['code'], msg=err['message'],
                          details=err['details']))
            raise BotRuntimeError(err["message"], format=True, dont_log=True)

        return res

    async def _getCountryList(self, ctx) -> tuple:
        # return cache if it's still valid
        if hasattr(self, "_corona_countries") and \
                (time.time() - self._corona_countries[1]) < (20*60):  # noqa:E501 pylint: disable=access-member-before-definition
            return self._corona_countries[0]  # noqa:E501 pylint: disable=access-member-before-definition
        # fetch countries
        clist = await self._coronaAPICall(
            ctx, 2, output_fields=("Country_Region",),
            order_by="Confirmed desc")
        # format: tuple(tuple of countries, time)
        clist = (tuple(
            c["attributes"]["Country_Region"] for c in clist["features"]),
            time.time())

        self._corona_countries = clist
        self._corona_country_sum = (len(clist[0]), time.time())
        return clist[0]

    async def _getCountrySum(self, ctx) -> int:
        if hasattr(self, '_corona_country_sum') and \
                (time.time() - self._corona_country_sum[1]) < (60*60):
            return self._corona_country_sum[0]

        csum = await self._coronaAPICall(ctx, 2, statistics=[{
            "statisticType": "count",  "onStatisticField":
            "OBJECTID", "outStatisticFieldName": "value"}])
        csum = csum["features"][0]["attributes"]["value"]
        self._corona_country_sum = (csum, time.time())
        return csum

    # database structure for corona:
    # {
    #     "guildID": {
    #         "meta": {"instanceName": name, "lastExec": UNIXTime},
    #         "subscriptions": [{
    #             "ID": chnlID,
    #             "Country" | "Province": cname | pname,
    #             "Confirmed": num,
    #             "Recovered": num,
    #             "Deaths": num},
    #             {"chnlID2": {...}},
    #             ...
    #         ],
    #     "guildID2": {...},
    #     ...
    # }

    @tasks.loop(minutes=20.0)
    async def coronaFeedTask(self):
        log(content="Running coronaFeedTask...")
        async with self._corona_lock:
            subscribers = await self.bot.db.fetchset("corona", {})
            # for every subscibed guild
            for guildID, guildData in subscribers.items():
                # if not current instance and lastExec < 40 mins then skip
                if guildData["meta"]["instanceName"] != \
                    self.bot.instance_name and \
                        (time.time() - guildData["meta"]["lastExec"]) < 40*60:
                    continue
                if guildData["meta"]["instanceName"] == \
                    self.bot.instance_name and \
                        (time.time() - guildData["meta"]["lastExec"]) < 20*60:
                    # skip also if lastExec is < 20 mins
                    continue
                guild = self.bot.get_guild(guildID)
                # for every subscription in a guild
                for i, subscription in enumerate(guildData["subscriptions"]):
                    # call API
                    if subscription.get("Country"):
                        res = await self._coronaAPICall(
                            None, 2,
                            where="Country_Region="
                                  f"'{subscription['Country']}'",
                            output_fields=("Confirmed", "Deaths", "Recovered",
                                           "Last_Update"))
                        name = subscription["Country"]
                    elif subscription.get("Province"):
                        res = await self._coronaAPICall(
                            None, 3,
                            where="Province_State="
                                  f"'{subscription['Province']}'",
                            output_fields=("Country_Region", "Confirmed",
                                           "Deaths", "Recovered",
                                           "Last_Update"))
                        name = "{province}, {country}".format(
                            province=subscription["Province"],
                            country=res["features"][0]["attributes"][
                                "Country_Region"])
                    res = res["features"][0]["attributes"]

                    # get difference
                    changes = {}
                    for attribute, value in subscription.items():
                        # skip country and province
                        if attribute in ("Country", "Province", "ID"):
                            continue
                        if res[attribute] and res[attribute] != value:
                            changes[attribute] = str(res[attribute] - value)
                            subscription[attribute] = res[attribute]
                            # append suitable symbol
                            if not changes[attribute].startswith('-'):
                                changes[attribute] = '+' + changes[attribute]

                    # send update if got changes
                    if changes:
                        # generate description
                        description = "```yaml\n- Changes -"
                        longest_str = len(max(changes.keys(), key=len))
                        for key, val in changes.items():
                            description += f"\n{key:>{longest_str}}: {val}"
                        description += "```"
                        # generate embed
                        embed = discord.Embed(
                            title="COVID-19 Status Update for {name}"
                                  .format(name=name),
                            description=description + "\n**Current status:**",
                            timestamp=datetime.datetime.utcfromtimestamp(
                                res['Last_Update']/1000) if res["Last_Update"]
                            else discord.Embed.Empty)
                        if res["Last_Update"]:
                            embed.set_footer(text="Last Update")
                        embed.set_author(name="Data by JHU CSSE",
                                         icon_url="https://pbs.twimg.com/"
                                         "profile_images/1206665181444493313"
                                         "/jIv91Sqp.jpg")
                        # add fields
                        for entry, value in res.items():
                            if entry in ("Confirmed", "Deaths", "Recovered") \
                                    and value:
                                embed.add_field(name=entry, value=value)
                        # send update message
                        channel = guild.get_channel(subscription["ID"])
                        await channel.send(embed=embed)

                    subscribers[guildID]["subscriptions"][i] = subscription
                subscribers[guildID]["meta"]["instanceName"] = \
                    self.bot.instance_name
                subscribers[guildID]["meta"]["lastExec"] = int(time.time())
            await self.bot.db.aset("corona", subscribers)
        log(content="coronaFeedTask completed.")

    @coronaFeedTask.before_loop
    async def before_coronaFeedTask(self):
        await self.bot.wait_until_ready()
        log(content="Bot is ready. Now starting coronaFeedTask")

    @commands.group(aliases=['covid19', 'coronavirus', 'covid'],
                    invoke_without_command=True)
    async def corona(self, ctx):
        """
        Commands to monitor the global trend of COVID-19.
        Shows summary if no subcommand is called.

        Usage: corona
        """
        confirmed_sum = await self._coronaAPICall(ctx, 2, statistics=[{
            "statisticType": "sum", "onStatisticField":
            "Confirmed", "outStatisticFieldName": "value"}])
        recovered_sum = await self._coronaAPICall(ctx, 2, statistics=[{
            "statisticType": "sum", "onStatisticField":
            "Recovered", "outStatisticFieldName": "value"}])
        deaths_sum = await self._coronaAPICall(ctx, 2, statistics=[{
            "statisticType": "sum", "onStatisticField":
            "Deaths", "outStatisticFieldName": "value"}])
        countries_sum = await self._getCountrySum(ctx)
        top3_countries = await self._coronaAPICall(
            ctx, 2, output_fields=("Country_Region", "Confirmed"),
            order_by="Confirmed desc", limit=3)
        top3_region = await self._coronaAPICall(
            ctx, 3, output_fields=("Province_State", "Confirmed"),
            order_by="Confirmed desc", limit=3)

        confirmed_sum = confirmed_sum["features"][0]["attributes"]["value"]
        recovered_sum = recovered_sum["features"][0]["attributes"]["value"]
        deaths_sum = deaths_sum["features"][0]["attributes"]["value"]
        top3_countries = [c["attributes"] for c in top3_countries["features"]]
        top3_region = [r["attributes"] for r in top3_region["features"]]

        embed = discord.Embed(title="Global COVID-19 Status")
        embed.set_author(name="Data by JHU CSSE",
                         icon_url="https://pbs.twimg.com/profile_images/"
                         "1206665181444493313/jIv91Sqp.jpg")

        embed.add_field(name="Total Confirmed",
                        value=f"```json\n{confirmed_sum}```")
        embed.add_field(name="Total Recovered",
                        value=f"```json\n{recovered_sum}```")
        embed.add_field(name="Total Deaths",
                        value=f"```json\n{deaths_sum}```")

        embed.add_field(name="Affected Countries Count",
                        value=f"```json\n{countries_sum}```")
        embed.add_field(name="Most Affected Countries",
                        value="```json\n{c1}: {n1}\n{c2}: {n2}\n{c3}: {n3}```"
                        .format(c1=top3_countries[0]["Country_Region"],
                                c2=top3_countries[1]["Country_Region"],
                                c3=top3_countries[2]["Country_Region"],
                                n1=top3_countries[0]["Confirmed"],
                                n2=top3_countries[1]["Confirmed"],
                                n3=top3_countries[2]["Confirmed"]))
        embed.add_field(name="Most Affected Province",
                        value="```json\n{r1}: {n1}\n{r2}: {n2}\n{r3}: {n3}```"
                        .format(r1=top3_region[0]["Province_State"],
                                r2=top3_region[1]["Province_State"],
                                r3=top3_region[2]["Province_State"],
                                n1=top3_region[0]["Confirmed"],
                                n2=top3_region[1]["Confirmed"],
                                n3=top3_region[2]["Confirmed"]))

        await ctx.send(embed=embed)

    @corona.command(name='rank')
    async def corona_rank(self, ctx, start: int = 1, number: int = 6):
        """
        Shows a certain number of countries from starting point that're
        affected by the COVID-19 outbreak, sorted from most confirmed
        cases to least.
        Will show first 6 countries by default.

        Usage: corona rank [start = 1] [number of countries to show = 6]
        number of countries to show should be either 3, 6 or 9.
        """
        if start < 1:
            raise BotValueError("Invalid starting point.")
        if number not in (3, 6, 9):
            raise BotValueError("Number of countries to show should be either"
                                " 3, 6 or 9.")
        country_sum = await self._getCountrySum(ctx)
        start = start if (start + number - 1) <= country_sum else \
            country_sum - number + 1

        res = await self._coronaAPICall(
            ctx, 2, order_by="Confirmed desc",
            output_fields=("Country_Region", "Confirmed", "Deaths",
                           "Recovered"),
            offset=start-1, limit=number)

        countries = res["features"]
        if len(countries) > 0:
            description = ("Showing first {start} to {end} "
                           "countries infected by the disease.").format(
                               start=start, end=start + len(countries) - 1)
        else:
            await ctx.send("No data. Try reducing start value.")
            return

        embed = discord.Embed(title="Affected Country List of COVID-19",
                              description=description)
        embed.set_footer(text="Total Affected Countries: {count}"
                         .format(count=await self._getCountrySum(ctx)))
        embed.set_author(name="Data by JHU CSSE",
                         icon_url="https://pbs.twimg.com/profile_images/"
                                  "1206665181444493313/jIv91Sqp.jpg")

        for i in range(0, number):
            country = countries[i]["attributes"]

            embed.add_field(name=f"#{start+i} **{country['Country_Region']}**",
                            value=("```json\nConfirmed: {confirmed}\n"
                                   "Deaths: {deaths}\n"
                                   "Recovered: {recovered}```")
                            .format(confirmed=country["Confirmed"],
                                    deaths=country["Deaths"],
                                    recovered=country["Recovered"]))

        await ctx.send(embed=embed)

    @corona.command(name='status', aliases=['stats', 'stat'])
    async def corona_status(self, ctx, *, name: str):
        """
        Check how COVID-19 virus spread in a country/province/state.

        Usage: corona status <country/province/state>
        """
        # little sanity check
        if "'" in name:
            raise BotValueError("Not a valid region name.")
        elif name.lower() == "taiwan":
            name = "Taiwan*"

        # query country
        key = "Country_Region"
        res = await self._coronaAPICall(
            ctx, 2, where=f"{key}='{name.capitalize()}'",
            output_fields=("Country_Region", "Last_Update",
                           "Confirmed", "Deaths", "Recovered", "Active",
                           "Incident_Rate", "People_Tested"))

        if not res["features"]:
            key = "Province_State"
            res = await self._coronaAPICall(
                ctx, 3, where=f"{key}='{name.capitalize()}'",
                output_fields=("Country_Region", "Province_State",
                               "Last_Update", "Confirmed", "Deaths",
                               "Recovered", "Active", "Incident_Rate",
                               "People_Tested"))

        if res["features"]:
            attributes = res['features'][0]['attributes']
        else:
            await ctx.send("No data is found. Did you made a typo?")
            return

        # check diff if querying country
        if key == "Country_Region":
            delta_res = await self._coronaAPICall(
                ctx, 4, where=f"Country_Region='{attributes[key]}'",
                output_fields=("Delta_Confirmed", "Delta_Recovered",
                               "Last_Update"),
                order_by="Last_Update desc")

            attributes["Delta_Confirmed"] = 0
            attributes["Delta_Recovered"] = 0
            last24hr = (int(time.time()) - (48*60*60)) * 1000
            for record in delta_res['features']:
                record = record["attributes"]
                if record["Last_Update"] and \
                        record["Last_Update"] >= last24hr:
                    attributes["Delta_Confirmed"] += \
                        record["Delta_Confirmed"] \
                        if record["Delta_Confirmed"] else 0
                    attributes["Delta_Recovered"] += \
                        record["Delta_Recovered"] \
                        if record["Delta_Recovered"] else 0

        # original key: displayed key
        displayed_fields = OrderedDict((
            ("Confirmed", "Confirmed"),
            ("Deaths", "Deaths"),
            ("Recovered", "Recovered"),
            ("Active", "Active"),
            ("Incident_Rate", "Incident Rate"),
            ("People_Tested", "People Tested"),
            ("Delta_Confirmed", "Confirmed Last 48hr"),
            ("Delta_Recovered", "Recovered Last 48hr")
        ))

        # filter out junk and leave only useful fields
        filtered_result = {}
        for ori_field in displayed_fields.keys():
            if ori_field in attributes and attributes[ori_field]:
                filtered_result[ori_field] = attributes[ori_field]

        if key == "Province_State":
            description = "{province}, {country}".format(
                province=attributes["Province_State"],
                country=attributes["Country_Region"])
        else:
            description = "Country ranked #{0}".format(
                (await self._getCountryList(ctx)).index(attributes[key]) + 1)

        embed = discord.Embed(
            title="{country}'s COVID-19 Status"
                  .format(country=attributes[key]),
            description=description,
            timestamp=datetime.datetime.utcfromtimestamp(
                attributes['Last_Update']/1000)
            if attributes["Last_Update"] else discord.Embed.Empty)
        if attributes["Last_Update"]:
            embed.set_footer(text="Last Update")
        embed.set_author(name="Data by JHU CSSE",
                         icon_url="https://pbs.twimg.com/profile_images/"
                         "1206665181444493313/jIv91Sqp.jpg")

        for entry, data in filtered_result.items():
            embed.add_field(name=displayed_fields[entry],
                            value=data)

        await ctx.send(embed=embed)

    @corona.command(name='subscribe', aliases=['sub'])
    @commands.has_permissions(manage_webhooks=True)
    async def corona_subscribe(self, ctx, channel: discord.TextChannel,
                               *, region: str):
        """
        Subscribe to a country/province/state's COVID-19 status update.

        Usage: corona subscribe <channel> <country/province/state>
        """
        # little sanity check
        if "'" in region:
            raise BotValueError("Not a valid region name.")

        async with self._corona_lock:
            # fetch db and check subsciption amount
            subscribers = await self.bot.db.fetchset("corona", {})
            if len(subscribers.get(ctx.guild.id, {})
                   .get("subscriptions", {})) == 10:
                raise BotRuntimeError("This server already subscribed to 10 "
                                      "source, consider unsubscribe some.")

            # query region
            key = "Country_Region"
            res = await self._coronaAPICall(
                ctx, 2, where=f"{key}='{region.capitalize()}'",
                output_fields=("Country_Region", "Confirmed", "Deaths",
                               "Recovered", "Last_Update"))
            if not res['features']:
                key = "Province_State"
                res = await self._coronaAPICall(
                    ctx, 3, where=f"{key}='{region.capitalize()}'",
                    output_fields=("Country_Region", "Province_State",
                                   "Confirmed", "Deaths", "Recovered",
                                   "Last_Update"))

            # validate legitimacy and send reponse
            if res["features"]:
                attributes = res['features'][0]['attributes']
                await ctx.send("Subscribing to {type} {region} in {channel}."
                               .format(type=key.split('_')[0].lower(),
                                       region=attributes[key],
                                       channel=channel.mention))
            else:
                raise BotValueError("Not a valid region. Did you made a "
                                    "typo?")

            # set subscription data
            subscription_data = {key.split("_")[0]: attributes[key]}
            for attribute, data in attributes.items():
                # ignore last update and country region
                if attribute in ("Country_Region", "Last_Update",
                                 "Province_State"):
                    continue
                subscription_data[attribute] = data
            subscription_data["ID"] = channel.id

            # update db
            if not subscribers.get(ctx.guild.id):
                subscribers[ctx.guild.id] = {"meta": {}, "subscriptions": []}
            subscribers[ctx.guild.id]["meta"] = {
                "instanceName": ctx.bot.instance_name,
                "lastExec": int(time.time())
            }
            subscribers[ctx.guild.id]["subscriptions"].append(
                subscription_data)
            await self.bot.db.aset("corona", subscribers)

        # create embed
        embed = discord.Embed(
            title="{region}'s COVID-19 Status".format(region=attributes[key]),
            timestamp=datetime.datetime.utcfromtimestamp(
                attributes['Last_Update']/1000) if attributes["Last_Update"]
            else discord.Embed.Empty)
        if attributes["Last_Update"]:
            embed.set_footer(text="Last Update")
        embed.set_author(name="Data by JHU CSSE",
                         icon_url="https://pbs.twimg.com/profile_images/"
                                  "1206665181444493313/jIv91Sqp.jpg")
        # add fields
        for entry, data in attributes.items():
            # skip last update
            if entry in ("Last_Update", "Country_Region", "Province_State"):
                continue
            if data:
                embed.add_field(name=entry, value=data)

        await channel.send(embed=embed)

    _corona_sub_nolock = object()
    @corona.command(name='unsubscribe', aliases=['unsub'])
    @commands.has_permissions(manage_webhooks=True)
    async def corona_unsubscribe(self, ctx, id_: int = None):
        """
        Cancel subscription to a country/province/state's COVID-19
        status update.

        Usage: corona unsubscribe [id]
        """
        async with self._corona_lock:
            # send user a list of active subscriptions
            if id_ is None:
                await ctx.invoke(ctx.bot.get_command("corona subscription"),
                                 self._corona_sub_nolock)
                if not ctx.bot.db["corona"].get(ctx.guild.id):
                    return
            elif id_ < 0:
                raise BotValueError("Where did you get that negative ID? "
                                    ":thinking: Try running it again without "
                                    "argument for options.")
            else:
                await ctx.bot.db.fetchset("corona", {})

            # initialise some variables and request user's reponse
            subscribers = ctx.bot.db["corona"]
            try:
                subscriptions = subscribers[ctx.guild.id]["subscriptions"]
            except KeyError:
                raise BotRuntimeError("There're no active subscription in "
                                      "this server.")
            if id_ is None:
                await ctx.send("Respond with the ID to unsubscribe from.")
                resp = await ctx.bot.wait_for(
                    'message',
                    check=lambda msg: msg.author == ctx.author and
                    msg.channel == ctx.channel and msg.content.isdigit(),
                    timeout=300.0)
                id_ = int(resp.content)
            if id_ >= len(subscriptions):
                raise BotValueError(":x: ID given is out of range.")

            # save important variables for bot response later
            if subscriptions[id_].get("Country"):
                region = subscriptions[id_]["Country"]
            else:
                region = subscriptions[id_]["Province"]
            channelID = subscriptions[id_]["ID"]

            # delete subscription and apply changes to online db
            del subscriptions[id_]
            # delete whole entry if no subscription left
            if len(subscriptions) == 0:
                del subscribers[ctx.guild.id]
            else:
                subscribers[ctx.guild.id]["subscriptions"] = subscriptions
            await ctx.bot.db.aset('corona', subscribers)
        await ctx.send("Successfully unsubscribed status update of "
                       "{region} in {channel}."
                       .format(region=region,
                               channel=ctx.guild.get_channel(
                                   channelID).mention))

    @corona.command(name="subscription", aliases=["subscriptions", 'subs'])
    async def corona_subscription(self, ctx, __nolock=None):
        """
        Get current server's subscription to country/province/state's COVID-19
        status update.

        Usage: corona subscription
        """
        if __nolock is not self._corona_sub_nolock:
            await self._corona_lock.acquire()
        subscribers = await ctx.bot.db.fetchset("corona", {})
        if __nolock is not self._corona_sub_nolock:
            self._corona_lock.release()

        subscriptions = subscribers.get(ctx.guild.id, {}).get(
            "subscriptions", [])
        if not subscriptions:
            await ctx.send("No active subscription found.")
            return
        # generate response text
        res = "```css"
        for i, subscription in enumerate(subscriptions):
            res += "\n[{i}] #{chnl_name} - {region}".format(
                i=i, chnl_name=ctx.guild.get_channel(subscription["ID"]),
                region=subscription["Country"] if
                subscription.get("Country") else
                subscription["Province"])
        res += "```"
        await ctx.send(res)


def setup(bot):
    bot.add_cog(Corona(bot))
