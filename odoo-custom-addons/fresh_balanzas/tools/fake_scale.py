#!/usr/bin/env python3
"""Balanza Kretz simulada, para probar scale_probe.py sin hardware.

Implementa el framing del manual (R30) y las respuestas de los comandos
de lectura usados por el probe. Configurable:
  --fragment   para partir cada respuesta en dos paquetes TCP (simula red real)
  --latency    latencia artificial por respuesta (ms)
  --process    tiempo de procesamiento interno por comando (ms)
  --plus       cantidad de PLUs existentes
"""

import argparse
import socket
import socketserver
import time

STX = 0x02
ETX = 0x04
RESP_STX = 0x07


def checksum(data):
    total = sum(data) & 0xFF
    return bytes([((total >> 4) & 0x0F) + 0x30, (total & 0x0F) + 0x30])


def frame(equip_id, group, code, data=''):
    body = (
        bytes([RESP_STX])
        + b'C'
        + equip_id.encode()
        + group.encode()
        + code.encode()
        + data.encode('latin-1')
    )
    return body + checksum(body) + bytes([ETX])


def plu_record(number):
    """Layout 2005 del módulo (135 caracteres), precio en [77:83]."""
    price = 10000 + number * 7
    return (
        f'{number:06d}001000'
        + f'{"PRODUCTO " + str(number):26s}'[:26]
        + f'{"DESC " + str(number):26s}'[:26]
        + f'{number:05d}'
        + 'N'
        + '0000000'
        + f'{price:06d}'
        + '000000'
        + '000001'
        + '000000'
        + '000000'
        + '00000'
        + '00000'
        + '01'
        + '0000'
        + '0000'
        + '0000'
        + '0000'
    )


class Handler(socketserver.BaseRequestHandler):
    opts = None

    def handle(self):
        o = self.opts
        buf = b''
        self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        while True:
            try:
                chunk = self.request.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            if o.rtt:
                # Emula latencia de red: cada ráfaga de comandos recibida
                # paga un RTT (con pipelining se amortiza entre comandos).
                time.sleep(o.rtt / 1000.0)
            # Procesar todas las tramas completas del buffer
            while True:
                start = buf.find(bytes([STX]))
                if start < 0:
                    break
                end = buf.find(bytes([ETX]), start)
                if end < 0:
                    break
                raw = buf[start:end + 1]
                buf = buf[end + 1:]
                reply = self.process(raw)
                if reply:
                    time.sleep(o.process / 1000.0)
                    if o.fragment and len(reply) > 2:
                        mid = len(reply) // 2
                        self.request.sendall(reply[:mid])
                        time.sleep(0.002)
                        self.request.sendall(reply[mid:])
                    else:
                        self.request.sendall(reply)

    def process(self, raw):
        o = self.opts
        payload = raw[1:-3].decode('latin-1')   # sin STX/checksum/ETX
        equip_id = payload[1:3]
        command = payload[3:7]
        data = payload[7:]

        if command == '0002':
            return frame(equip_id, '00', '01')
        if command == '1500':
            return frame(equip_id, '15', '01', 'SAP1234567890' + '0001' + ' ' * 20)
        if command == '1501':
            return frame(equip_id, '15', '01', '000012345')
        if command == '1503':
            return frame(equip_id, '15', '01', '0000400010000800')
        if command == '1504':
            return frame(equip_id, '15', '01', '05' + f'{o.plus:06d}')
        if command == '5001':
            if data == '05':
                return frame(equip_id, '05', '01', '05' + f'{o.plus:06d}')
            return frame(equip_id, '50', '02')
        if command == '5002':
            return frame(equip_id, '05', '01', data + '006')
        if command == '5005':
            try:
                number = int(data)
            except ValueError:
                return frame(equip_id, '05', '11')
            if 1 <= number <= o.plus:
                return frame(equip_id, '05', '01', plu_record(number))
            return frame(equip_id, '05', '20')
        return frame(equip_id, '00', '02')


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=11001)
    ap.add_argument('--plus', type=int, default=300)
    ap.add_argument('--fragment', action='store_true')
    ap.add_argument('--process', type=float, default=0.5,
                    help='ms de procesamiento por comando')
    ap.add_argument('--rtt', type=float, default=0,
                    help='ms de latencia de red por ráfaga recibida')
    args = ap.parse_args()

    Handler.opts = args
    with Server((args.host, args.port), Handler) as srv:
        print(f'Balanza simulada en {args.host}:{args.port} '
              f'({args.plus} PLUs, fragment={args.fragment})')
        srv.serve_forever()
