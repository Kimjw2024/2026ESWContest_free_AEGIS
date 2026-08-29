import socket
import struct
import time

import zmq


TCP_HOST = "0.0.0.0"
TCP_PORT = 5560

ZMQ_ENDPOINT = "tcp://127.0.0.1:5555"

MAX_PACKET = 8 * 1024 * 1024


def recv_exact(conn, count):
    data = bytearray()

    while len(data) < count:
        chunk = conn.recv(count - len(data))

        if not chunk:
            raise ConnectionError("peer closed")

        data.extend(chunk)

    return bytes(data)


ctx = zmq.Context()

pub = ctx.socket(zmq.PUB)
pub.setsockopt(zmq.LINGER, 0)
pub.setsockopt(zmq.SNDHWM, 4)

# Fusion owns/binds :5555.
# Bridge only connects through Windows loopback.
pub.connect(ZMQ_ENDPOINT)

server = socket.socket(
    socket.AF_INET,
    socket.SOCK_STREAM
)

server.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_REUSEADDR,
    1
)

server.bind((TCP_HOST, TCP_PORT))
server.listen(1)

print("=" * 65)
print(" AEGIS TCP -> LOCAL ZMQ BRIDGE")
print(f" TCP LISTEN : {TCP_HOST}:{TCP_PORT}")
print(f" LOCAL ZMQ  : {ZMQ_ENDPOINT}")
print("=" * 65)

try:
    while True:

        print(">> Waiting for Raspberry Pi...")

        conn, addr = server.accept()

        conn.setsockopt(
            socket.IPPROTO_TCP,
            socket.TCP_NODELAY,
            1
        )

        conn.settimeout(3.0)

        print(">> Pi connected:", addr)

        count = 0
        last_count = 0
        last_seq_time = time.time()
        last_print = time.time()

        try:
            while True:

                header = recv_exact(conn, 4)

                size = struct.unpack("!I", header)[0]

                if size <= 0 or size > MAX_PACKET:
                    raise RuntimeError(
                        f"invalid packet size: {size}"
                    )

                payload = recv_exact(conn, size)

                # Exact original pickle payload forwarded locally.
                pub.send(payload)

                count += 1

                now = time.time()

                if now - last_print >= 1.0:
                    hz = (
                        count - last_count
                    ) / (now - last_print)

                    print(
                        f"[BRIDGE] rx={hz:.1f}Hz "
                        f"packets={count} "
                        f"size={size/1024:.1f}KB"
                    )

                    last_count = count
                    last_print = now

        except (
            ConnectionError,
            socket.timeout,
            OSError,
            RuntimeError
        ) as e:

            print(
                f">> Pi disconnected/reset: {e}"
            )

        finally:
            try:
                conn.close()
            except Exception:
                pass

finally:
    server.close()
    pub.close()
    ctx.term()
