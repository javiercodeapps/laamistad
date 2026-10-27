import socket
import logging

from .base import BaseProtocol

_logger = logging.getLogger(__name__)


class KretzProtocol(BaseProtocol):
    STX = 0x02
    ETX = 0x04
    RESP_STX = 0x07
    EQUIP_TYPE = 'C'
    EQUIP_ID = '01'

    RESPONSES = {
        '01': 'Comando ejecutado correctamente',
        '02': 'Comando inexistente',
        '10': 'Error de checksum',
        '11': 'Error de modelo de datos',
        '20': 'Registro inexistente',
        '30': 'Último registro leído',
        '40': 'No existen registros',
        '50': 'Capacidad máxima superada',
        '60': 'Error al ejecutar comando',
    }

    def __init__(self, host, port=1001, timeout=10, equip_id=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.equip_id = str(equip_id if equip_id is not None else self.EQUIP_ID).zfill(2)
        self._socket = None

    def connect(self):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(self.timeout)
        self._socket.connect((self.host, self.port))
        _logger.info('Conectado a balanza Kretz %s:%s', self.host, self.port)

    def disconnect(self):
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def _calc_checksum(self, data):
        total = sum(data) & 0xFF
        hi = ((total >> 4) & 0x0F) + 0x30
        lo = (total & 0x0F) + 0x30
        return bytes([hi, lo])

    def _build_command(self, command, data=''):
        payload = (
            self.EQUIP_TYPE.encode('latin-1')
            + self.equip_id.encode('latin-1')
            + command.encode('latin-1')
            + data.encode('latin-1')
        )
        frame = bytes([self.STX]) + payload
        checksum = self._calc_checksum(frame)
        frame += checksum + bytes([self.ETX])
        return frame

    def _parse_response(self, raw):
        if not raw or raw[0] != self.RESP_STX:
            raise ValueError('Respuesta inválida: sin STX de respuesta')
        if raw[-1] != self.ETX:
            raise ValueError('Respuesta inválida: sin ETX')
        payload = raw[1:-3]
        resp_group = payload[3:5].decode('latin-1')
        resp_code = payload[5:7].decode('latin-1')
        resp_data = payload[7:].decode('latin-1')
        return resp_group, resp_code, resp_data

    def send_command(self, command, data=''):
        if not self._socket:
            self.connect()
        frame = self._build_command(command, data)
        _logger.debug('Enviando comando: %s', frame.hex())
        self._socket.sendall(frame)
        raw = self._socket.recv(4096)
        _logger.debug('Respuesta raw: %s', raw.hex())
        return self._parse_response(raw)

    def test_communication(self, beep=True):
        cmd = '0001' if beep else '0002'
        group, code, data = self.send_command(cmd)
        return code == '01'

    def upsert_plu(self, plu_data):
        data = self._format_plu_data(plu_data)
        group, code, msg = self.send_command('2005', data)
        return code == '01', code, self.RESPONSES.get(code, msg)

    def upsert_plu_record(self, record):
        """Envía un registro PLU crudo (2005) tal como fue leído (read_plu).

        Permite reenviar un PLU existente con un solo campo modificado
        (ej: precio) sin regenerar el resto del registro.
        """
        group, code, msg = self.send_command('2005', record)
        return code == '01', code, self.RESPONSES.get(code, msg)

    def delete_plu(self, plu_number):
        data = f'{int(plu_number):06d}'
        group, code, msg = self.send_command('3005', data)
        return code == '01', code, self.RESPONSES.get(code, msg)

    def delete_all_plus(self):
        group, code, msg = self.send_command('4005')
        return code == '01', code, self.RESPONSES.get(code, msg)

    def read_plu(self, plu_number):
        data = f'{int(plu_number):06d}'
        group, code, msg = self.send_command('5005', data)
        return code == '01', code, msg

    def upsert_vendor(self, vendor_data):
        data = self._format_vendor_data(vendor_data)
        group, code, msg = self.send_command('2007', data)
        return code == '01', code, self.RESPONSES.get(code, msg)

    def delete_vendor(self, vendor_code):
        data = f'{int(vendor_code):02d}'
        group, code, msg = self.send_command('3007', data)
        return code == '01', code, self.RESPONSES.get(code, msg)

    def delete_all_vendors(self):
        group, code, msg = self.send_command('4007')
        return code == '01', code, self.RESPONSES.get(code, msg)

    def read_vendor_totals(self):
        group, code, msg = self.send_command('5009')
        return code == '01', code, msg

    def _format_plu_data(self, plu):
        """Formatea un PLU según el layout Kretz 2005 (validado contra logs de iTegra).

        El precio se envía con 2 decimales implícitos (x100).
        """
        price = int(round(float(plu.get('price') or 0) * 100))
        plu_code = int(plu.get('plu_code') or plu['number'])
        return (
            f'{int(plu["number"]):06d}'
            f'{int(plu.get("dept_code", 1)):03d}'
            f'{int(plu.get("family_code", 0)):03d}'
            f'{plu.get("name", "")[:26]:26s}'
            f'{plu.get("description", "")[:26]:26s}'
            f'{plu_code:05d}'
            f'{plu.get("plu_type", "P"):1s}'
            f'{int(plu.get("fixed_value", 0)):07d}'
            f'{price:06d}'
            f'{int(plu.get("alt_price", 0) * 100):06d}'
            f'{int(plu.get("status", 1)):06d}'
            f'{int(plu.get("tax_1", 0)):06d}'
            f'{int(plu.get("tax_2", 0)):06d}'
            f'{int(plu.get("tare_prepack", 0)):05d}'
            f'{int(plu.get("tare_public", 0)):05d}'
            f'{int(plu.get("label_code", 1)):02d}'
            f'{int(plu.get("recipe_code", 0)):04d}'
            f'{int(plu.get("nutrition_code", 0)):04d}'
            f'{int(plu.get("packaging_date", 0)):04d}'
            f'0000'
        )

    def _format_vendor_data(self, vendor):
        return (
            f'{int(vendor["code"]):02d}'
            f'{vendor.get("name", ""):20s}'
        )
