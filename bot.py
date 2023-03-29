import asyncio
import json
import math
import random
from typing import Optional, Union

from telethon import TelegramClient, events
from telethon.errors import PeerIdInvalidError, ChatWriteForbiddenError, ChannelPrivateError
from telethon.tl.types import Message
from dotenv import dotenv_values
import sentry_sdk

config = dotenv_values(".env")
api_id, api_hash, dsn = config["API_ID"], config["API_HASH"], config["DSN"]

sentry_sdk.init(
    dsn=dsn,
    traces_sample_rate=1.0,
)

client = TelegramClient('session', int(api_id), api_hash)


class Settings:
    ADMIN = "@username"
    AD = "hashtag"
    CHANNEL = "@channel"
    LIMIT = 20

    def __init__(self, groups, last_message: Message = None):
        self.groups = groups
        self.last_message = last_message

    async def set_last_message(self, message: Message):
        self.last_message = message

    async def update(self, group_id, time):
        self.groups[group_id] = time
        await self.update_file()

    async def delete(self, group_id):
        self.groups.pop(group_id)
        await self.update_file()

    async def update_file(self):
        with open('db.json', "w") as f:
            f.write(json.dumps(self.groups))


with open("db.json", "r") as file:
    groups = file.read()

dict_groups = json.loads(groups)
real_groups = {int(key): time for key, time in dict_groups.items()}
settings = Settings(real_groups)


async def main():
    await settings.set_last_message(await get_last_message())
    while True:
        await asyncio.gather(
            *[send_message(group) for group, timer in settings.groups.items()]
        )
        await asyncio.sleep(600)


@client.on(events.NewMessage(chats=Settings.CHANNEL))
async def my_event_handler(event):
    if event.message.message.lower().find(Settings.AD) != -1:
        await settings.set_last_message(event.message)


@client.on(events.NewMessage(chats=Settings.ADMIN))
async def my_event_handler(event):
    message = event.message.message.lower()
    if message.startswith("@active_groups"):
        sending_message = []
        for key, value in settings.groups.items():
            try:
                entity = await client.get_entity(key)
            except Exception:
                sending_message.append(f"ID: {key} is private (seems like you were banned from it)")
            else:
                sending_message.append(f"ID: {entity.id} Title: {entity.title} Time: {value}")
        await client.send_message(Settings.ADMIN, "\n".join(sending_message))

    elif message.startswith("@update"):
        await handle_data(message.lstrip("@update"))

    elif message.startswith("@latest_groups"):
        sending_message = []
        dialogs = await client.get_dialogs(limit=Settings.LIMIT)
        for dialog in dialogs:
            if dialog.is_group:
                sending_message.append(f"Title: {dialog.title}, ID: {dialog.id}")
        await client.send_message(Settings.ADMIN, "\n".join(sending_message))

    elif message.startswith("@add"):
        data = message.lstrip("@add")
        validated_data = data.replace(" ", "").split(",")
        for group_change in validated_data:
            group_id, time = map(int, group_change.split("="))
            if not (group_id in settings.groups or -group_id in settings.groups):
                await settings.update(group_id, time)
            else:
                await client.send_message(Settings.ADMIN, "Already exists")

        await asyncio.gather(
            *[send_message(*map(int, group_change.split("="))) for group_change in validated_data]
        )

    elif message.startswith("@delete"):
        data = message.lstrip("@delete")
        validated_data = data.replace(" ", "").split(",")
        for group_id in validated_data:
            if group_id in settings.groups:
                await settings.delete(int(group_id))
            elif -group_id in settings.groups:
                await settings.delete(-int(group_id))
            else:
                await delayed_message(Settings.ADMIN, f"Group with ID {group_id} doesn't exist in active groups! Skipping...")

    elif message.startswith("@send"):
        await asyncio.gather(
            *[launch_trigger(group_id, settings.last_message) for group_id in settings.groups.keys()]
        )

    elif message.startswith("@set_all"):
        time = message.lstrip("@set_all").strip()
        try:
            time = int(time)
        except ValueError:
            await delayed_message(Settings.ADMIN,
                                  f"Incorrect format! Format is: @set_all <time_in_seconds> (Example: @set_all 3600) ")

        if time >= 600:
            for group_id in settings.groups.keys():
                settings.groups[group_id] = time

        else:
            await delayed_message(Settings.ADMIN,
                                  f"Time is less than 600 seconds! Changes were declined.")


async def handle_data(data: str):
    validated_data = data.replace(" ", "").split(",")
    for group_change in validated_data:
        group_id, time = map(int, group_change.split("="))
        try:
            if not (group_id in settings.groups or -group_id in settings.groups):
                await delayed_message(Settings.ADMIN, f"Group_id {group_id} is not in active groups! Skipping...")
            elif group_id in settings.groups:
                await settings.update(group_id, time)
            else:
                await settings.update(-group_id, time)
        except ValueError:
            await delayed_message(Settings.ADMIN, f"Incorrect group_id {group_id}! Skipping...")


async def send_message(group_id, *args):
    last_message = settings.last_message
    if last_message:
        while True:
            if settings.groups.get(group_id, False):
                if settings.groups[group_id] >= 600:
                    await asyncio.sleep(settings.groups[group_id])
                    try:
                        await delayed_forward(group_id, settings.last_message)
                    except ValueError:
                        await delayed_forward(group_id * (-1), settings.last_message)
                    except ChatWriteForbiddenError:
                        await delayed_message(Settings.ADMIN, f"Forbidden to send the message to group {group_id}")
                    except PeerIdInvalidError:
                        await delayed_message(Settings.ADMIN, f"Group with ID {group_id} doesn't exist! Skipping...")
                    except ChannelPrivateError:
                        await delayed_message(
                            Settings.ADMIN,
                            f"The group/channel {group_id} is private and you lack permission to access it. Another reason may be that you were banned from it. Skipping..."
                        )
                    else:
                        await delayed_message(Settings.ADMIN, f"Successfully forwarded the post to {group_id}")
                else:
                    await delayed_message(Settings.ADMIN, f"Group with ID {group_id} has less than 600 seconds of sleep time! Sleeping for 10 minutes...")
                    await asyncio.sleep(600)
            else:
                break


async def launch_trigger(target: Union[int, str], message: Message):
    try:
        await delayed_forward(target, settings.last_message)
    except ValueError:
        await delayed_forward(-target, settings.last_message)
    except ChatWriteForbiddenError:
        await delayed_message(Settings.ADMIN, f"Forbidden to send the message to group {target}")


async def get_last_message() -> Optional[Message]:
    channel_username = Settings.CHANNEL
    messages = await client.get_messages(channel_username, limit=10)
    for message in messages:
        try:
            if message.message.lower().find(Settings.AD) != -1:
                return message
        except AttributeError:
            # Todo handle this error
            pass
    return None


async def delayed_message(target: Union[int, str], message: str):
    await asyncio.sleep(random.randint(1, 2))
    await client.send_message(target, message)


async def delayed_forward(target: Union[int, str], message: Message):
    await asyncio.sleep(round(random.uniform(1, 10), 2))
    await client.forward_messages(target, message)


with client:
    client.loop.run_until_complete(main())