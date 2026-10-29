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

    #: Posición del precio dentro del registro PLU (comando 2005/5005).
    PLU_PRICE_OFFSET = 77
    PLU_PRICE_SIZE = 6
    #: Cantidad de dígitos del número de PLU en el registro.
    PLU_NUMBER_SIZE = 6
    #: Posiciones extra a explorar al final de la tabla. El comando 5001
    #: informa la capacidad (ej. 10.000) pero en algunas unidades hay
    #: registros por encima de ese valor (se verificó un PLU real en la
    #: posición 10001 de una tabla que informa 10.000).
    PLU_TABLE_MARGIN = 32
    #: Código propio: la balanza devolvió un PLU distinto al pedido.
    CODE_WRONG_PLU = '99'

    RESPONSES = {
        CODE_WRONG_PLU: 'La balanza devolvió un PLU distinto al solicitado',
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
        """Lee un PLU por su número, resolviendo su posición real en la tabla.

        Importante: en la familia Report Nx el dato del comando 5005 es la
        **posición** del registro en la tabla de PLU (base 0), no el número de
        PLU. En una balanza real se verificó que pedir la posición 1 devuelve
        el PLU 2, y la posición 0 devuelve el PLU 1. Por eso se busca la
        posición por búsqueda binaria y se valida el número del registro
        devuelto: nunca se compara ni se escribe sobre el artículo equivocado.

        Returns:
            tuple: (ok: bool, code: str, data: str)
        """
        slot = self.find_plu_slot(plu_number)
        if slot is None:
            return False, '20', ''
        ok, code, data = self.read_plu_slot(slot)
        if not ok:
            return ok, code, data
        number = self.plu_number_from_record(data)
        if number != int(plu_number):
            _logger.warning(
                'Posición %s devolvió PLU %s, se pidió %s', slot, number,
                plu_number,
            )
            return False, self.CODE_WRONG_PLU, data
        return True, code, data

    # --- direccionamiento de PLUs por posición ---------------------------
    def read_plu_slot(self, slot):
        """Lee el registro que ocupa ``slot`` (0-based) en la tabla de PLU.

        Returns:
            tuple: (ok: bool, code: str, data: str)
        """
        group, code, msg = self.send_command('5005', f'{int(slot):06d}')
        return code == '01', code, msg

    @classmethod
    def plu_number_from_record(cls, record):
        """Extrae el número de PLU de un registro crudo (o None si no se puede)."""
        if not record or len(record) < cls.PLU_NUMBER_SIZE:
            return None
        try:
            return int(record[:cls.PLU_NUMBER_SIZE])
        except ValueError:
            return None

    def plu_count(self):
        """Cantidad de posiciones de la tabla de PLU (comando 5001).

        Devuelve 0 si la balanza no responde el comando.
        """
        group, code, msg = self.send_command('5001', '05')
        if code != '01' or len(msg) < 8:
            _logger.warning('Respuesta inesperada al 5001: %s %r', code, msg)
            return 0
        try:
            return int(msg[2:8])
        except ValueError:
            return 0

    def find_plu_slot(self, plu_number, max_slot=None):
        """Busca la posición del registro con el número de PLU indicado.

        La relación posición→número es no decreciente (varios slots pueden
        apuntar al mismo registro), así que se resuelve con búsqueda binaria:
        ~14 lecturas por PLU.

        Args:
            plu_number: número de PLU buscado.
            max_slot: cantidad de posiciones de la tabla. Si no se indica se
                consulta con el comando 5001, más un margen.

        Returns:
            int | None: posición del registro, o None si el PLU no existe.
        """
        target = int(plu_number)
        if max_slot is None:
            max_slot = self.plu_count() + self.PLU_TABLE_MARGIN
        hi = int(max_slot) - 1
        if hi < 0:
            return None

        lo = 0
        while lo < hi:
            mid = (lo + hi) // 2
            number = self._plu_number_at(mid)
            if number is None:
                # Posición sin registro legible. En la Report Nx esto ocurre
                # al final de la tabla (las posiciones fuera de rango no
                # devuelven datos), así que se descarta la mitad derecha.
                hi = mid
                continue
            if number < target:
                lo = mid + 1
            else:
                hi = mid

        if self._plu_number_at(lo) == target:
            return lo
        return None

    def _plu_number_at(self, slot):
        ok, _code, data = self.read_plu_slot(slot)
        return self.plu_number_from_record(data) if ok else None

    def scan_table(self, max_slot=None, progress=None):
        """Recorre la tabla completa de PLU y devuelve {numero: (slot, registro)}.

        Ojo: cuesta una lectura por posición (en una balanza Report Nx con
        10.000 posiciones son ~13 minutos), por eso es una operación de
        mantenimiento y no parte del día a día.

        Args:
            max_slot: cantidad de posiciones a recorrer (default: comando 5001
                más un margen).
            progress: callable(slot, total, encontrados) opcional.

        Returns:
            dict: {número de PLU: (slot, registro crudo)}
        """
        if max_slot is None:
            max_slot = self.plu_count() + self.PLU_TABLE_MARGIN
        total = int(max_slot)
        result = {}
        for slot in range(total):
            ok, _code, data = self.read_plu_slot(slot)
            if ok:
                number = self.plu_number_from_record(data)
                if number is not None and number not in result:
                    result[number] = (slot, data)
            if progress:
                progress(slot, total, len(result))
        return result

    def read_all_plus(self, max_slot=None, progress=None):
        """Igual que ``scan_table`` pero devuelve sólo {numero: registro}."""
        table = self.scan_table(max_slot=max_slot, progress=progress)
        return {number: data for number, (_slot, data) in table.items()}

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

        El precio se envía con los decimales indicados en ``price_decimals``
        (por defecto 2, es decir x100).
        """
        decimals = plu.get('price_decimals')
        decimals = 2 if decimals is None else int(decimals)
        factor = 10 ** decimals
        price = int(round(float(plu.get('price') or 0) * factor))
        alt_price = int(round(float(plu.get('alt_price') or 0) * factor))
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
            f'{alt_price:06d}'
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
