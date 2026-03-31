from aiohttp import web
import aiohttp
import json
import time
import asyncio
import os
import base64
import random
import hashlib

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

def encode_base64(data: str) -> str:
    """Encode string to base64 (как StringUtils::encode)"""
    return base64.b64encode(data.encode('utf-8')).decode('utf-8')

def decode_base64(data: str) -> str:
    """Decode base64 to string (как StringUtils::decode)"""
    try:
        return base64.b64decode(data.encode('utf-8')).decode('utf-8')
    except:
        return data

def generate_proof_of_work():
    """
    Генерирует задачу для WorkingVM
    Формат: каждая инструкция = 2 hex (opcode) + 8 hex (operand) = 10 символов
    OpCodes: Add=0, Sub=1, Mul=2, Div=3, Ret=4
    """
    instructions = []
    result = 0
    
    # Генерируем простую задачу
    # Add 100
    instructions.append(f"00{100:08x}")
    result += 100
    
    # Add random number
    rand_add = random.randint(1, 50)
    instructions.append(f"00{rand_add:08x}")
    result += rand_add
    
    # Mul 2
    instructions.append(f"02{2:08x}")
    result *= 2
    
    # Ret (operand не важен)
    instructions.append(f"04{0:08x}")
    
    raw_program = "".join(instructions)
    encoded_program = encode_base64(raw_program)
    
    return encoded_program, result

class Client:
    def __init__(self, ws):
        self.ws = ws
        self.client_name = ""
        self.username = ""
        self.player_name = ""
        self.xuid = ""
        self.hwid = ""
        self.authenticated = False
        self.expected_pow_result = 0
        self.pow_sent = False

clients = {}

def make_op(opcode, data, success=True):
    return json.dumps({"o": opcode, "d": data, "s": success})

async def send_op(ws, opcode, data, success=True):
    """Отправляет операцию с base64 кодировкой"""
    try:
        raw_json = make_op(opcode, data, success)
        encoded = encode_base64(raw_json)
        await ws.send_str(encoded)
    except Exception as e:
        print(f"[!] Send error: {e}")

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
    return web.Response(text="Solstice IRC Server - Use WebSocket to connect")

async def handle_health(request):
    count = sum(1 for c in clients.values() if c.authenticated)
    return web.Response(text=f"OK - {count} users online")

async def handle_websocket(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    cid = id(ws)
    client = Client(ws)
    clients[cid] = client
    print(f"[+] New connection from {request.remote}")

    try:
        # Отправляем Proof of Work задачу
        pow_task, expected_result = generate_proof_of_work()
        client.expected_pow_result = expected_result
        client.pow_sent = True
        await send_op(ws, OpCode.Work, pow_task)
        print(f"[*] Sent PoW task, expected result: {expected_result}")

        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    # Декодируем base64
                    decoded = decode_base64(msg.data.strip())
                    
                    # Парсим JSON
                    if not decoded or decoded[0] != '{':
                        continue
                        
                    data = json.loads(decoded)
                    opcode = data.get("o", -1)
                    op_data = data.get("d", "")

                    print(f"[<] OpCode: {opcode}, Data: {op_data[:100]}...")

                    # Proof of Work verification
                    if opcode == OpCode.CompleteWork and not client.authenticated:
                        try:
                            result = int(op_data)
                            if result == client.expected_pow_result:
                                await send_op(ws, OpCode.AuthFinish, "OK")
                                client.authenticated = True
                                print(f"[+] Client authenticated (PoW correct: {result})")
                            else:
                                await send_op(ws, OpCode.Error, f"Invalid PoW result: got {result}, expected {client.expected_pow_result}")
                                print(f"[!] Invalid PoW: got {result}, expected {client.expected_pow_result}")
                        except ValueError:
                            await send_op(ws, OpCode.Error, "Invalid PoW format")
                        continue

                    if opcode == OpCode.KeyIn:
                        # Клиент отправляет свой ключ - мы его просто принимаем
                        print(f"[*] Received client key")
                        continue

                    if opcode == OpCode.IdentifyClient:
                        try:
                            info = json.loads(op_data)
                            client.client_name = info.get("0", "unknown")
                            client.hwid = info.get("1", "")
                            print(f"[*] Client identified: {client.client_name}, HWID: {client.hwid[:16]}...")
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
                            
                            if not old_name and client.authenticated:
                                join_msg = f"§a{client.username} §7(§f{client.player_name}§7) joined IRC"
                                await broadcast(OpCode.Join, join_msg)
                                await broadcast_user_list()
                        except Exception as e:
                            print(f"[!] IdentifyPlayer error: {e}")
                        continue

                    if opcode == OpCode.IdentifySkinData:
                        # Принимаем скин данные но не обрабатываем
                        print(f"[*] Received skin data from {client.username}")
                        continue

                    if opcode == OpCode.Message:
                        if not client.authenticated:
                            continue
                        name = client.username or "Unknown"
                        player = client.player_name or "Unknown"
                        msg_text = f"§b{name}§7 (§f{player}§7): §f{op_data}"
                        print(f"[MSG] {name}: {op_data}")
                        await broadcast(OpCode.Message, msg_text)
                        continue

                    if opcode == OpCode.ListUsers:
                        await broadcast_user_list()
                        continue

                    if opcode == OpCode.Ping:
                        # Клиент отвечает на пинг - всё ок
                        continue

                except json.JSONDecodeError as e:
                    print(f"[!] JSON decode error: {e}")
                except Exception as e:
                    print(f"[!] Error processing message: {e}")
                    import traceback
                    traceback.print_exc()

            elif msg.type == aiohttp.WSMsgType.ERROR:
                print(f"[!] WebSocket error: {ws.exception()}")
                break

    except Exception as e:
        print(f"[!] Connection error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if client.authenticated and client.username:
            leave_msg = f"§c{client.username} §7(§f{client.player_name}§7) left IRC"
            if cid in clients:
                del clients[cid]
            await broadcast(OpCode.Leave, leave_msg)
            await broadcast_user_list()
            print(f"[-] {client.username} disconnected")
        else:
            if cid in clients:
                del clients[cid]
            print(f"[-] Unauthenticated client disconnected")

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"=== Solstice IRC Server ===")
    print(f"Starting on port {port}")
    print(f"Waiting for connections...")
    web.run_app(app, host="0.0.0.0", port=port, print=None)
