from aiohttp import web
import aiohttp
import json
import time
import asyncio
import os

class OpCode:
    Work = 0
    CompleteWork = 1
    KeyIn = 2
    KeyOut = 3
    AuthFinish = 4
    IdentifyClient = 5
    IdentifyPlayer = 6
    ServerMessage = 7
    Error = 8
    Ping = 9
    Announcement = 10
    Join = 11
    Leave = 12
    Message = 13
    ListUsers = 14
    ConnectedUserList = 15
    IdentifySkinData = 16

class Client:
    def __init__(self, ws):
        self.ws = ws
        self.client_name = ""
        self.username = ""
        self.player_name = ""
        self.xuid = ""
        self.authenticated = False

clients = {}

def make_op(opcode, data, success=True):
    return json.dumps({"o": opcode, "d": data, "s": success})

async def send_op(ws, opcode, data, success=True):
    try:
        await ws.send_str(make_op(opcode, data, success))
    except:
        pass

async def broadcast(opcode, data, exclude_id=None):
    for cid, client in list(clients.items()):
        if cid == exclude_id or not client.authenticated:
            continue
        await send_op(client.ws, opcode, data)

async def broadcast_user_list():
    user_list = {}
    i = 0
    for cid, client in clients.items():
        if not client.authenticated:
            continue
        user_list[str(i)] = {
            "0": client.client_name,
            "1": client.username,
            "2": client.player_name,
            "3": client.xuid
        }
        i += 1
    data = json.dumps(user_list)
    for cid, client in list(clients.items()):
        if client.authenticated:
            await send_op(client.ws, OpCode.ConnectedUserList, data)

async def ping_loop(app):
    try:
        while True:
            await asyncio.sleep(5)
            for cid, client in list(clients.items()):
                if client.authenticated:
                    try:
                        await send_op(client.ws, OpCode.Ping, str(int(time.time() * 1000)))
                    except:
                        pass
    except asyncio.CancelledError:
        pass

async def handle_root(request):
    if request.headers.get('Upgrade', '').lower() == 'websocket':
        return await handle_websocket(request)
    return web.Response(text="OK")

async def handle_health(request):
    count = sum(1 for c in clients.values() if c.authenticated)
    return web.Response(text=f"OK - {count} users online")

async def handle_websocket(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    cid = id(ws)
    client = Client(ws)
    clients[cid] = client
    print(f"[+] New connection")

    try:
        await send_op(ws, OpCode.Work, "1")

        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    opcode = data.get("o", -1)
                    op_data = data.get("d", "")

                    if opcode == OpCode.CompleteWork and not client.authenticated:
                        await send_op(ws, OpCode.AuthFinish, "OK")
                        client.authenticated = True
                        print(f"[+] Client authenticated")
                        continue

                    if opcode == OpCode.KeyIn:
                        continue

                    if opcode == OpCode.IdentifyClient:
                        try:
                            info = json.loads(op_data)
                            client.client_name = info.get("0", "unknown")
                        except:
                            pass
                        continue

                    if opcode == OpCode.IdentifyPlayer:
                        try:
                            info = json.loads(op_data)
                            old_name = client.username
                            client.username = info.get("0", "unknown")
                            client.player_name = info.get("1", "unknown")
                            client.xuid = info.get("2", "")
                            print(f"[*] Player: {client.player_name} ({client.username})")
                            if not old_name:
                                join_msg = f"\u00a7a{client.username} ({client.player_name}) joined IRC"
                                await broadcast(OpCode.Join, join_msg)
                                await broadcast_user_list()
                        except:
                            pass
                        continue

                    if opcode == OpCode.IdentifySkinData:
                        continue

                    if opcode == OpCode.Message:
                        if not client.authenticated:
                            continue
                        msg_text = f"\u00a7b{client.username}\u00a7f ({client.player_name}): {op_data}"
                        print(f"[MSG] {client.username}: {op_data}")
                        await broadcast(OpCode.Message, msg_text)
                        continue

                    if opcode == OpCode.ListUsers:
                        await broadcast_user_list()
                        continue

                    if opcode == OpCode.Ping:
                        continue

                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    print(f"[!] Error: {e}")

            elif msg.type == aiohttp.WSMsgType.ERROR:
                print(f"[!] WebSocket error: {ws.exception()}")
                break

    except Exception as e:
        print(f"[!] Error: {e}")
    finally:
        if client.authenticated and client.username:
            leave_msg = f"\u00a7c{client.username} ({client.player_name}) left IRC"
            if cid in clients:
                del clients[cid]
            await broadcast(OpCode.Leave, leave_msg)
            await broadcast_user_list()
            print(f"[-] {client.username} disconnected")
        else:
            if cid in clients:
                del clients[cid]

    return ws

async def start_background(app):
    app['ping_task'] = asyncio.create_task(ping_loop(app))

async def stop_background(app):
    app['ping_task'].cancel()
    try:
        await app['ping_task']
    except asyncio.CancelledError:
        pass

app = web.Application()
app.router.add_get('/', handle_root)
app.router.add_get('/health', handle_health)
app.on_startup.append(start_background)
app.on_cleanup.append(stop_background)

port = int(os.environ.get("PORT", 33651))
print(f"=== Solstice IRC Server ===")
print(f"Starting on port {port}")
print(f"Waiting for connections...")
web.run_app(app, host="0.0.0.0", port=port, print=None)
