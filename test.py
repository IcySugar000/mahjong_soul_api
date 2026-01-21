import base64
import asyncio
import hashlib
import hmac
import logging
import uuid
from optparse import OptionParser
from typing import Awaitable

import aiohttp
from google.protobuf.message import Message

from ms.base import MSRPCChannel
from ms.rpc import Lobby, FastTest, Route
import ms.protocol_pb2 as pb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

MS_HOST = "https://game.maj-soul.com"


class Manager:
    lobby: Lobby
    fast_test: FastTest
    route: Route
    channel: MSRPCChannel
    version_to_force: str
    endpoint_raw: str

    token: str
    account_id: int
    client_version_string: str

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

        await self.connect()
        await self.login(username, password)

        self.channel.add_hook(
            ".lq.NotifyRoomGameStart", self.hook_notify_room_game_start
        )

    async def connect(self):
        async with aiohttp.ClientSession() as session:
            async with session.get("{}/1/version.json".format(MS_HOST)) as res:
                version = await res.json()
                logging.info(f"Version: {version}")
                version = version["version"]
                self.version_to_force = version.replace(".w", "")
                self.client_version_string = f"web-{self.version_to_force}"

            async with session.get(
                "{}/1/v{}/config.json".format(MS_HOST, version)
            ) as res:
                config = await res.json()
                logging.info(f"Config: {config}")

                server = config["ip"][0]["gateways"][1]["url"]
                self.endpoint_raw = server.strip("https://")
                endpoint = f"wss://{self.endpoint_raw}/gateway"

        logging.info(f"Chosen endpoint: {endpoint}")
        self.channel = MSRPCChannel(endpoint)

        self.lobby = Lobby(self.channel)
        await self.channel.connect(MS_HOST)
        logging.info("Connection was established")

    async def login(self, username: str, password: str):
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
        req.client_version_string = self.client_version_string
        req.currency_platforms.append(2)

        res = await self.lobby.login(req)
        self.token = res.access_token
        if not self.token:
            logging.error("Login Error:")
            logging.error(res)
            return False

        self.account_id = res.account_id

        return True

    async def hook_notify_room_game_start(self, data: bytes):
        logging.info("Room Game Start!")
        start_data = pb.NotifyRoomGameStart.FromString(data)
        logging.info(f"Game Start Info: \n{start_data}")

        new_channel = MSRPCChannel(endpoint=f"wss://{self.endpoint_raw}/game-gateway")
        self.fast_test = FastTest(channel=new_channel)
        await new_channel.connect(MS_HOST)
        new_channel.add_hook(".lq.ActionPrototype", self.hook_action_prototype)

        logging.info("Authing Game...")
        auth_req = pb.ReqAuthGame(
            account_id=self.account_id,
            token=start_data.connect_token,
            game_uuid=start_data.game_uuid,
        )
        logging.info(f"Using req:\n{auth_req}")
        auth_res = await self.fast_test.auth_game(auth_req)
        logging.info(f"Auth Game Succeeded. Info: \n{auth_res}")

        logging.info("Entering Game...")
        await self.fast_test.enter_game(pb.ReqCommon())
        logging.info("Enter Game Succeeded")

    async def hook_action_prototype(self, data: bytes):
        action = pb.ActionPrototype.FromString(data)
        logging.info(f"Received Action: \n{action}")

        action_name_to_type: dict[str, type[Message]] = {
            "ActionMJStart": pb.ActionMJStart,
            "ActionDiscardTile": pb.ActionDiscardTile,
            "ActionDealTile": pb.ActionDealTile,
            "ActionChiPengGang": pb.ActionChiPengGang,
            "ActionNewRound": pb.ActionNewRound,
        }
        if action.name not in action_name_to_type.keys():
            logging.info(f"Action Not Available: {action.name}")
            return
        action_data = action_name_to_type[action.name].FromString(action.data)
        logging.info(f"Action Data:\n{action_data}")
        logging.info(pb.GameAction.FromString(action.data))


async def main():
    m = Manager()
    await m.init()
    req = pb.ReqJoinRoom(room_id=40752, client_version_string=m.version_to_force)
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
