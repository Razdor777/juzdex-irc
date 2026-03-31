import asyncio
import json
import time
import os

try:
    import websockets
    from websockets.legacy.server import WebSocketServerProtocol
except ImportError:
    import websockets

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
        await ws.send(make_op(opcode, data, success))
    except:
        pass

async def broadcast(opcode, data, exclude=None):
    for ws, client in list(clients.items()):
        if ws == exclude or not client.authenticated:
            continue
        await send_op(ws, opcode, data)

async def broadcast_user_list():
    user_list = {}
    i = 0
    for ws, client in clients.items():
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
    for ws, client in list(clients.items()):
        if client.authenticated:
            await send_op(ws, OpCode.ConnectedUserList, data)

async def ping_loop():
    while True:
        await asyncio.sleep(5)
        for ws, client in list(clients.items()):
            if client.authenticated:
                try:
                    await send_op(ws, OpCode.Ping, str(int(time.time() * 1000)))
                except:
                    pass

async def handle_client(ws, path=None):
    client = Client(ws)
    clients[ws] = client
    print(f"[+] New connection")

    try:
        await send_op(ws, OpCode.Work, "1")

        async for raw_message in ws:
            try:
                data = json.loads(raw_message)
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
                            msg = f"\u00a7a{client.username} ({client.player_name}) joined IRC"
                            await broadcast(OpCode.Join, msg)
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

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[!] Error: {e}")
    finally:
        if client.authenticated and client.username:
            msg = f"\u00a7c{client.username} ({client.player_name}) left IRC"
            if ws in clients:
                del clients[ws]
            await broadcast(OpCode.Leave, msg)
            await broadcast_user_list()
            print(f"[-] {client.username} disconnected")
        else:
            if ws in clients:
                del clients[ws]

async def health_check(path, headers):
    if path == "/" or path == "/health":
        return (200, [], b"OK")

async def main():
    port = int(os.environ.get("PORT", 33651))
    print(f"=== Solstice IRC Server ===")
    print(f"Starting on port {port}")

    asyncio.create_task(ping_loop())

    try:
        async with websockets.serve(
            handle_client, "0.0.0.0", port,
            process_request=health_check
        ):
            await asyncio.Future()
    except TypeError:
        async with websockets.serve(handle_client, "0.0.0.0", port):
            await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
