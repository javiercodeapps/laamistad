#!/usr/bin/env python3
"""Diagnóstico de una balanza Kretz Report Nx (protocolo JDataGate, R30).

Herramienta standalone: NO necesita Odoo. Sirve para responder empíricamente
las dos preguntas que el manual (R30 Junio 2023) deja abiertas:

1. ¿Cuál es el formato de request del comando 5001 (cantidad de registros)?
   El manual documenta la respuesta pero no da ejemplo del comando.
2. ¿La balanza tolera pipelining (varios comandos encolados antes de leer las
   respuestas)? Eso determina el tamaño de lote óptimo para leer todos los
   PLU.

Además mide la latencia real de lectura individual vs. por lotes, para saber
si el cuello de botella es la red (RTT) o el tiempo interno de la balanza.

Uso:
    python3 tools/scale_probe.py --host 192.168.50.106 --port 1001
    python3 tools/scale_probe.py --host 192.168.50.106 --equip 5 --sample 30
    python3 tools/scale_probe.py --host 192.168.50.106 --chunks 1,5,10,25,50

Solo envía comandos de LECTURA (0002, 1500, 1501, 1503, 1504, 5001, 5002,
5005). No modifica nada en la balanza.
"""

import argparse
import socket
import sys
import time

STX = 0x02
ETX = 0x04
RESP_STX = 0x07

RESPONSES = {
    '01': 'OK',
    '02': 'comando inexistente',
    '10': 'error de checksum',
    '11': 'error de modelo de datos',
    '20': 'registro inexistente',
    '30': 'último registro leído',
    '31': 'último registro borrado',
    '40': 'no existen registros',
    '41': 'no existen registros para borrar',
    '50': 'capacidad máxima superada',
    '60': 'error al ejecutar el comando',
}


def build_checksum(data):
    """Checksum Kretz: suma de bytes previos, 2 nibbles menos significativos
    en ASCII (+0x30)."""
    total = sum(data) & 0xFF
    hi = ((total >> 4) & 0x0F) + 0x30
    lo = (total & 0x0F) + 0x30
    return bytes([hi, lo])


def build_command(equip_type, equip_id, command, data=''):
    payload = (
        equip_type.encode('latin-1')
        + equip_id.encode('latin-1')
        + command.encode('latin-1')
        + data.encode('latin-1')
    )
    frame = bytes([STX]) + payload
    return frame + build_checksum(frame) + bytes([ETX])


class Frame:
    __slots__ = ('group', 'code', 'data', 'checksum_ok', 'raw')

    def __init__(self, group, code, data, checksum_ok, raw):
        self.group = group
        self.code = code
        self.data = data
        self.checksum_ok = checksum_ok
        self.raw = raw

    def __repr__(self):
        label = RESPONSES.get(self.code, '?')
        return (
            f'<Frame grupo={self.group} resp={self.code} ({label}) '
            f'len(datos)={len(self.data)} cksum={"ok" if self.checksum_ok else "MAL"}>'
        )


class KretzProbe:
    """Cliente Kretz con buffer de lectura, para soportar respuestas partidas o
    concatenadas (indispensable para pipelining)."""

    def __init__(self, host, port=1001, equip_id='01', timeout=10):
        self.host = host
        self.port = port
        self.equip_id = str(equip_id).zfill(2)
        self.timeout = timeout
        self.sock = None
        self._buf = b''

    # --- conexión ---------------------------------------------------------
    def __enter__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))
        return self

    def __exit__(self, *exc):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    # --- lectura con buffer ----------------------------------------------
    def _fill(self):
        chunk = self.sock.recv(4096)
        if not chunk:
            raise ConnectionError('la balanza cerró la conexión')
        self._buf += chunk

    def _pop_frame(self):
        """Extrae una trama completa del buffer, o None si falta data."""
        start = self._buf.find(bytes([RESP_STX]))
        if start < 0:
            # Basura antes del framing: la descartamos para resincronizar.
            self._buf = b''
            return None
        if start:
            self._buf = self._buf[start:]
        end = self._buf.find(bytes([ETX]))
        if end < 0:
            return None
        raw = self._buf[:end + 1]
        self._buf = self._buf[end + 1:]
        return self._parse(raw)

    def _parse(self, raw):
        # 0x07 'C' id(2) grupo(2) resp(2) datos... checksum(2) 0x04
        body = raw[:-1]              # sin ETX
        checksum = body[-2:]
        checksum_ok = build_checksum(body[:-2]) == checksum
        payload = body[1:-2]         # sin 0x07 ni checksum
        group = payload[3:5].decode('latin-1')
        code = payload[5:7].decode('latin-1')
        data = payload[7:].decode('latin-1')
        return Frame(group, code, data, checksum_ok, raw)

    def read_frames(self, count):
        frames = []
        deadline = time.monotonic() + self.timeout
        while len(frames) < count:
            frame = self._pop_frame()
            if frame is not None:
                frames.append(frame)
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f'esperaba {count} tramas, recibí {len(frames)}'
                )
            self._fill()
        return frames

    # --- envío ------------------------------------------------------------
    def send(self, command, data=''):
        frame = build_command('C', self.equip_id, command, data)
        self.sock.sendall(frame)
        return self.read_frames(1)[0]

    def send_batch(self, requests):
        """requests: lista de (comando, datos). Devuelve una trama por request."""
        blob = b''.join(
            build_command('C', self.equip_id, cmd, data) for cmd, data in requests
        )
        self.sock.sendall(blob)
        return self.read_frames(len(requests))

    def read_plu_numbers(self, numbers, chunk_size=1):
        """Lee varios PLU, de a chunk_size comandos encolados."""
        results = []
        for i in range(0, len(numbers), chunk_size):
            chunk = numbers[i:i + chunk_size]
            requests = [('5005', f'{n:06d}') for n in chunk]
            for number, frame in zip(chunk, self.send_batch(requests)):
                results.append((number, frame))
        return results


# --- comandos de diagnóstico ---------------------------------------------

def probe_identity(probe):
    print('\n== Identificación del equipo ==')
    checks = [
        ('1500', '', 'datos técnicos (SAP + firmware)'),
        ('1501', '', 'número de serie'),
        ('1503', '', 'capacidad de memoria'),
        ('1504', '05', 'capacidad real entidad PLU'),
    ]
    for cmd, data, label in checks:
        try:
            f = probe.send(cmd, data)
            print(f'  {cmd} {label:36s} resp={f.code} datos={f.data!r}')
        except Exception as e:
            print(f'  {cmd} {label:36s} ERROR {e}')


def probe_record_count(probe):
    """El manual no documenta el request del 5001: probamos variantes."""
    print('\n== 5001: cantidad de registros de la entidad PLU (05) ==')
    print('   (el manual documenta la respuesta pero no el request)')
    variants = [
        ('05', 'código de entidad como dato'),
        ('', 'sin datos'),
        ('05', 'repetición de control'),
    ]
    for data, label in variants:
        try:
            f = probe.send('5001', data)
            print(
                f'  request C{probe.equip_id}5001{data!r:6s} -> resp={f.code} '
                f'datos={f.data!r}  [{label}]'
            )
            if f.code in ('01', '20', '40'):
                print(f'      ^ este formato responde: {RESPONSES.get(f.code)}')
        except Exception as e:
            print(f'  request C{probe.equip_id}5001{data!r:6s} -> ERROR {e}')


def probe_field_lengths(probe):
    print('\n== 5002: largo de campos de la entidad PLU ==')
    for field in ('01', '05', '06', '09', '10'):
        try:
            f = probe.send('5002', '05' + field)
            print(f'  campo {field} -> resp={f.code} datos={f.data!r}')
        except Exception as e:
            print(f'  campo {field} -> ERROR {e}')


def _timed_reads(probe, numbers, chunk_size):
    t0 = time.perf_counter()
    try:
        results = probe.read_plu_numbers(numbers, chunk_size=chunk_size)
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return elapsed, 0, 0, str(e)
    elapsed = time.perf_counter() - t0
    ok = sum(1 for _, f in results if f.code == '01')
    bad_cksum = sum(1 for _, f in results if not f.checksum_ok)
    return elapsed, ok, bad_cksum, None


def probe_timing(probe, sample, chunks, start=1):
    print(f'\n== Latencia de lectura de PLU ({sample} PLUs por modo) ==')
    print(f'   PLU {start}..{start + sample - 1}')
    numbers = list(range(start, start + sample))

    # Referencia: 1 comando por envío (lo que hace el código actual)
    base = None
    print('\n  modo            chunk   tiempo     ms/PLU   ok   cksum mal  obs')
    print('  ' + '-' * 70)
    for chunk in chunks:
        elapsed, ok, bad, err = _timed_reads(probe, numbers, chunk)
        per = (elapsed / sample * 1000) if sample else 0
        note = err or ''
        print(
            f'  {"lote" if chunk > 1 else "individual":14s} {chunk:5d} '
            f'{elapsed:8.3f}s {per:8.2f} {ok:5d} {bad:10d}  {note}'
        )
        if chunk == 1:
            base = elapsed
        elif base and elapsed > 0:
            print(f'  {"":14s} {"":5s} -> {base / elapsed:5.1f}x más rápido '
                  f'que de a uno')

    if base is None:
        return
    print(
        f'\n  Lectura individual: {base / sample * 1000:.2f} ms por PLU '
        f'({base:.3f}s para {sample}).'
    )
    print(
        '  Si al subir el lote el ms/PLU casi no baja, el cuello de botella '
        'es la balanza (su procesamiento), no la red.'
    )


def probe_full_scan(probe, chunk_size, start=1):
    """Lee TODOS los PLU de la tabla y mide cuánto tarda el recorrido completo.

    Es la medición que responde "cuánto cuesta comparar todos los artículos".
    Usa el 5001 para saber cuántas posiciones tiene la tabla.
    """
    print('\n== Escaneo completo de la tabla de PLU ==')
    try:
        f = probe.send('5001', '05')
        if f.code != '01' or len(f.data) < 8:
            print(f'  5001 no devolvió la cantidad de registros '
                  f'(resp={f.code} datos={f.data!r}); abortando escaneo.')
            return
        count = int(f.data[2:8])
    except Exception as e:
        print(f'  ERROR consultando 5001: {e}')
        return

    print(f'  La tabla de PLU tiene {count} posiciones. '
          f'Leyendo {start}..{count} en lotes de {chunk_size}...')
    numbers = list(range(start, count + 1))
    if not numbers:
        print('  Nada para leer.')
        return

    t0 = time.perf_counter()
    try:
        results = probe.read_plu_numbers(numbers, chunk_size=chunk_size)
    except Exception as e:
        print(f'  ERROR durante el escaneo tras '
              f'{time.perf_counter() - t0:.1f}s: {e}')
        return
    elapsed = time.perf_counter() - t0

    exist = sum(1 for _, f in results if f.code == '01')
    missing = sum(1 for _, f in results if f.code == '20')
    other = len(results) - exist - missing
    bad_cksum = sum(1 for _, f in results if not f.checksum_ok)

    print(f'\n  Terminado en {elapsed:.2f}s '
          f'({elapsed / len(numbers) * 1000:.2f} ms por PLU)')
    print(f'  {exist} PLUs con datos, {missing} inexistentes, '
          f'{other} otras respuestas, {bad_cksum} checksums inválidos')
    if exist:
        print('  Primeros 5 PLUs leídos:')
        for number, frame in [r for r in results if r[1].code == '01'][:5]:
            d = frame.data
            price = d[77:83] if len(d) >= 83 else '?'
            name = d[12:38].strip() if len(d) >= 38 else '?'
            print(f'    PLU {number:06d}  precio_raw={price}  nombre={name!r}')


def main():
    ap = argparse.ArgumentParser(
        description='Diagnóstico de balanza Kretz (solo comandos de lectura).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument('--host', required=True)
    ap.add_argument('--port', type=int, default=1001)
    ap.add_argument('--equip', default='01', help='número de equipo (default 01)')
    ap.add_argument('--timeout', type=float, default=10)
    ap.add_argument('--sample', type=int, default=20,
                    help='cantidad de PLUs a leer para medir latencia')
    ap.add_argument('--start', type=int, default=1,
                    help='primer PLU a leer (default 1)')
    ap.add_argument('--full', action='store_true',
                    help='además, escanear TODA la tabla de PLU y medir el '
                         'tiempo total (usa 5001 para saber cuántos hay)')
    ap.add_argument('--full-chunk', type=int, default=25,
                    help='tamaño de lote para el escaneo completo (default 25)')
    ap.add_argument('--chunks', default='1,10,25,50',
                    help='tamaños de lote a comparar (default 1,10,25,50)')
    ap.add_argument('--skip-identity', action='store_true')
    args = ap.parse_args()

    chunks = [int(c) for c in args.chunks.split(',') if c.strip()]

    print(f'Conectando a {args.host}:{args.port} (equipo {args.equip})...')
    try:
        with KretzProbe(
            args.host, args.port, args.equip, args.timeout
        ) as probe:
            return _run(probe, args, chunks)
    except Exception as e:
        print(f'ERROR de conexión: {e}', file=sys.stderr)
        return 1


def _run(probe, args, chunks):
    t0 = time.perf_counter()
    f = probe.send('0002')   # test de comunicación sin sonido
    rtt = (time.perf_counter() - t0) * 1000
    print(f'  comunicación OK (resp={f.code}), RTT sin beep: {rtt:.1f} ms')

    if not args.skip_identity:
        probe_identity(probe)
        probe_record_count(probe)
        probe_field_lengths(probe)

    probe_timing(probe, args.sample, chunks, args.start)

    if args.full:
        probe_full_scan(probe, args.full_chunk, args.start)

    print('\nListo. No se modificó ningún dato de la balanza.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
