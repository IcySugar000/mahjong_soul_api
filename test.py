import asyncio
import hashlib
import hmac
import logging
import uuid
from optparse import OptionParser
from typing import Awaitable

import aiohttp

from ms.base import MSRPCChannel
from ms.rpc import Lobby
import ms.protocol_pb2 as pb
from google.protobuf.json_format import MessageToJson

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

MS_HOST = "https://game.maj-soul.com"


class Manager:
    lobby: Lobby
    channel: MSRPCChannel
    version_to_force: str
    token: str

    async def init(self):
        parser = OptionParser()
        parser.add_option("-u", "--username", type="string", help="Your account name.")
        parser.add_option(
            "-p", "--password", type="string", help="Your account password."
        )

        opts, _ = parser.parse_args()
        username = opts.username
        password = opts.password

        if not username or not password:
            parser.error("Username or password cant be empty")

        self.lobby, self.channel, self.version_to_force = await self.connect()
        await self.login(self.lobby, username, password, self.version_to_force)

        self.channel.add_hook(
            ".lq.NotifyRoomGameStart", self.hook_notify_room_game_start
        )

    async def connect(self) -> tuple[Lobby, MSRPCChannel, str]:
        async with aiohttp.ClientSession() as session:
            async with session.get("{}/1/version.json".format(MS_HOST)) as res:
                version = await res.json()
                logging.info(f"Version: {version}")
                version = version["version"]
                version_to_force = version.replace(".w", "")

            async with session.get(
                "{}/1/v{}/config.json".format(MS_HOST, version)
            ) as res:
                config = await res.json()
                logging.info(f"Config: {config}")

                server = config["ip"][0]["gateways"][1]["url"]
                endpoint = "wss://{}/gateway".format(server.strip("https://"))

        logging.info(f"Chosen endpoint: {endpoint}")
        channel = MSRPCChannel(endpoint)

        lobby = Lobby(channel)

        await channel.connect(MS_HOST)
        logging.info("Connection was established")

        return lobby, channel, version_to_force

    async def login(
        self, lobby: Lobby, username: str, password: str, version_to_force: str
    ):
        logging.info("Login with username and password")

        uuid_key = str(uuid.uuid1())

        req = pb.ReqLogin()
        req.account = username
        req.password = hmac.new(
            b"lailai", password.encode(), hashlib.sha256
        ).hexdigest()
        req.device.is_browser = True
        req.random_key = uuid_key
        req.gen_access_token = True
        req.client_version_string = f"web-{version_to_force}"
        req.currency_platforms.append(2)

        res = await lobby.login(req)
        self.token = res.access_token
        if not self.token:
            logging.error("Login Error:")
            logging.error(res)
            return False

        return True

    async def hook_notify_room_game_start(self, data: bytes):
        logging.info("Room Game Start!")
        msg = pb.NotifyRoomGameStart.FromString(data)
        logging.info(f"Game Start Info: \n{msg}")


async def main():
    m = Manager()
    await m.init()
    req = pb.ReqJoinRoom(room_id=31139, client_version_string=m.version_to_force)
    res = await m.lobby.join_room(req)
    room = res.room
    logging.info(room.room_id)
    logging.info(room.owner_id)
    logging.info(room.mode)
    logging.info(room.max_player_count)
    logging.info(room.persons)
    logging.info(room.ready_list)
    logging.info(room.is_playing)
    logging.info(room.public_live)
    logging.info(room.robot_count)
    logging.info(room.tournament_id)
    logging.info(room.seq)
    logging.info(room.pre_rule)
    logging.info(room.robots)
    logging.info(room.positions)

    req = pb.ReqRoomReady(ready=True)
    await m.lobby.ready_play(req)
    while True:
        coro: Awaitable | None = None
        await asyncio.sleep(1)
        if coro:
            res = await coro
            logging.info(res)
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
