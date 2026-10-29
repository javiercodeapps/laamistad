import importlib.util
import os
import sys
import unittest


def _load_kretz_protocol():
    """Carga KretzProtocol sin dependencias de Odoo."""
    base_path = os.path.join(
        os.path.dirname(__file__), '..', 'protocols', 'base.py'
    )
    kretz_path = os.path.join(
        os.path.dirname(__file__), '..', 'protocols', 'kretz.py'
    )
    # Crear paquete virtual para que los imports relativos funcionen
    import types
    pkg = types.ModuleType('protocols')
    pkg.__path__ = [os.path.dirname(kretz_path)]
    sys.modules['protocols'] = pkg

    base_spec = importlib.util.spec_from_file_location('protocols.base', base_path)
    base_mod = importlib.util.module_from_spec(base_spec)
    sys.modules['protocols.base'] = base_mod
    base_spec.loader.exec_module(base_mod)

    kretz_spec = importlib.util.spec_from_file_location('protocols.kretz', kretz_path)
    kretz_mod = importlib.util.module_from_spec(kretz_spec)
    sys.modules['protocols.kretz'] = kretz_mod
    kretz_spec.loader.exec_module(kretz_mod)
    return kretz_mod.KretzProtocol


class TestKretzProtocol(unittest.TestCase):

    def setUp(self):
        KretzProtocol = _load_kretz_protocol()
        self.proto = KretzProtocol('192.168.50.106', 1001)

    def test_build_command_stx_etx(self):
        frame = self.proto._build_command('0001')
        self.assertEqual(frame[0], 0x02)
        self.assertEqual(frame[-1], 0x04)

    def test_build_command_contains_payload(self):
        frame = self.proto._build_command('0001')
        self.assertIn(b'C01', frame)

    def test_checksum_is_ascii_hex(self):
        frame = self.proto._build_command('0001')
        checksum = frame[-3:-1]
        self.assertTrue(
            all(0x30 <= b <= 0x39 or 0x41 <= b <= 0x46 for b in checksum)
        )

    def test_checksum_varies_with_payload(self):
        f1 = self.proto._build_command('0001')
        f2 = self.proto._build_command('0002')
        self.assertNotEqual(f1[-3:-1], f2[-3:-1])

    def test_plu_format_length(self):
        data = self.proto._format_plu_data({
            'number': 1,
            'dept_code': 1,
            'family_code': 1,
            'name': 'TEST',
            'description': 'TEST DESC',
            'plu_code': '00001',
            'plu_type': 'P',
            'price': 10.0,
            'label_code': 1,
        })
        self.assertEqual(len(data), 135)

    def test_plu_format_fields(self):
        data = self.proto._format_plu_data({
            'number': 123,
            'dept_code': 5,
            'family_code': 10,
            'name': 'Test Product',
            'description': 'Test Desc',
            'plu_code': '12345',
            'plu_type': 'P',
            'price': 25.50,
            'label_code': 1,
        })
        self.assertIn('000123', data)
        self.assertIn('005', data)
        self.assertIn('010', data)
        self.assertIn('P', data)

    def test_plu_format_price_scaled_100(self):
        """Por defecto el precio se envía con 2 decimales implícitos (x100)."""
        data = self.proto._format_plu_data({
            'number': 1,
            'price': 199.0,
        })
        self.assertEqual(data[77:83], '019900')

    def test_plu_format_price_decimals_configurable(self):
        """``price_decimals`` define la escala del precio enviado."""
        cases = [
            (0, 199, '000199'),
            (1, 199.5, '001995'),
            (2, 199.5, '019950'),
            (3, 19.5, '019500'),
        ]
        for decimals, price, expected in cases:
            with self.subTest(decimals=decimals):
                data = self.proto._format_plu_data({
                    'number': 1,
                    'price': price,
                    'price_decimals': decimals,
                })
                self.assertEqual(data[77:83], expected)
                self.assertEqual(len(data), 135)

    def test_plu_format_alt_price_uses_same_decimals(self):
        data = self.proto._format_plu_data({
            'number': 1,
            'price': 10.0,
            'alt_price': 12.5,
            'price_decimals': 3,
        })
        self.assertEqual(data[83:89], '012500')

    def test_plu_format_matches_itegra_log(self):
        """Regression: un PLU real del log de iTegra debe reproducirse igual.

        Log: equipo 05, comando C052005 PLU 000001 ACELGA depto 001 familia 000,
        precio 90.00 (raw 009000), label 01.
        """
        data = self.proto._format_plu_data({
            'number': 1,
            'dept_code': 1,
            'family_code': 0,
            'name': 'ACELGA',
            'description': '',
            'plu_type': 'N',
            'price': 90.0,
            'label_code': 1,
        })
        expected = (
            '000001'
            '001'
            '000'
            'ACELGA' + ' ' * 20
            + ' ' * 26
            + '00001'
            'N'
            '0000000'
            '009000'
            '000000'
            '000001'
            '000000'
            '000000'
            '00000'
            '00000'
            '01'
            '0000'
            '0000'
            '0000'
            '0000'
        )
        self.assertEqual(len(data), 135)
        self.assertEqual(data, expected)

    def test_plu_code_zero_padding(self):
        data = self.proto._format_plu_data({
            'number': 168,
            'plu_code': '168',
            'price': 1390.0,
        })
        self.assertEqual(data[64:69], '00168')
        self.assertEqual(data[77:83], '139000')

    def test_equip_id_override(self):
        proto05 = type(self.proto)('192.168.50.120', 1001, equip_id=5)
        frame = proto05._build_command('0001')
        self.assertIn(b'C05', frame)
        self.assertEqual(proto05.equip_id, '05')

    def test_vendor_format(self):
        data = self.proto._format_vendor_data({
            'code': 5,
            'name': 'Juan Perez',
        })
        self.assertIn('05', data)
        self.assertIn('Juan Perez', data)
        self.assertEqual(len(data), 22)

    def test_response_codes(self):
        cls = type(self.proto)
        self.assertEqual(
            cls.RESPONSES['01'],
            'Comando ejecutado correctamente'
        )

    def test_constants(self):
        cls = type(self.proto)
        self.assertEqual(cls.STX, 0x02)
        self.assertEqual(cls.ETX, 0x04)
        self.assertEqual(cls.EQUIP_TYPE, 'C')
        self.assertEqual(cls.EQUIP_ID, '01')


class FakeKretzScale:
    """Balanza simulada con la semántica real del comando 5005.

    El dato del 5005 es la POSICIÓN del registro en la tabla (0-based), y la
    relación posición→número es no decreciente (varias posiciones pueden
    apuntar al mismo registro). Es lo que se observó en una Report Nx real.
    """

    def __init__(self, slot_numbers, count=None):
        self.slot_numbers = list(slot_numbers)
        self.count = count if count is not None else len(self.slot_numbers)
        self.reads = 0

    def record_for(self, number):
        return (
            f'{number:06d}'
            '001001'
            + f'{"PLU " + str(number):26s}'[:26]
            + ' ' * 26
            + f'{number:05d}'
            + 'N' + '0000000'
            + f'{number * 100:06d}'
            + '0' * 52
        )

    def send_command(self, command, data=''):
        if command == '5001':
            return '05', '01', '05' + f'{self.count:06d}'
        if command == '5005':
            self.reads += 1
            slot = int(data)
            if slot >= len(self.slot_numbers) or self.slot_numbers[slot] is None:
                return '05', '20', ''
            return '05', '01', self.record_for(self.slot_numbers[slot])
        raise AssertionError(f'comando inesperado {command}')


class TestKretzPluAddressing(unittest.TestCase):
    """Regresión: el 5005 direcciona por posición, no por número de PLU."""

    def setUp(self):
        KretzProtocol = _load_kretz_protocol()
        self.KretzProtocol = KretzProtocol

    def make(self, slot_numbers):
        proto = self.KretzProtocol.__new__(self.KretzProtocol)
        fake = FakeKretzScale(slot_numbers)
        proto.send_command = fake.send_command
        proto.plu_count = lambda: fake.count
        return proto, fake

    def test_positional_semantics_reproduce_off_by_one(self):
        """Un 5005 crudo con el número devuelve el registro siguiente."""
        proto, fake = self.make([1, 2, 3, 4])
        ok, code, data = proto.read_plu_slot(1)
        self.assertTrue(ok)
        self.assertEqual(data[:6], '000002')

    def test_find_plu_slot_dense(self):
        proto, _fake = self.make([1, 2, 3, 4])
        self.assertEqual(proto.find_plu_slot(1), 0)
        self.assertEqual(proto.find_plu_slot(4), 3)

    def test_find_plu_slot_with_gaps_and_duplicates(self):
        # posiciones: 0→2, 1→3, 2..4→4, 5→7, 6→9
        proto, _fake = self.make([2, 3, 4, 4, 4, 7, 9])
        self.assertEqual(proto.find_plu_slot(2), 0)
        self.assertEqual(proto.find_plu_slot(4), 2)
        self.assertEqual(proto.find_plu_slot(7), 5)
        self.assertEqual(proto.find_plu_slot(9), 6)

    def test_find_plu_slot_missing(self):
        proto, _fake = self.make([2, 3, 4, 4, 4, 7, 9])
        self.assertIsNone(proto.find_plu_slot(5))
        self.assertIsNone(proto.find_plu_slot(1))
        self.assertIsNone(proto.find_plu_slot(10))

    def test_binary_search_cost_is_logarithmic(self):
        slots = list(range(1, 1001))
        proto, fake = self.make(slots)
        self.assertEqual(proto.find_plu_slot(777), 776)
        self.assertLessEqual(fake.reads, 15, 'la búsqueda debe ser logarítmica')

    def test_read_plu_returns_requested_number(self):
        proto, _fake = self.make([2, 3, 4, 4, 4, 7, 9])
        ok, _code, data = proto.read_plu(4)
        self.assertTrue(ok)
        self.assertEqual(proto.plu_number_from_record(data), 4)
        ok, _code, data = proto.read_plu(9)
        self.assertTrue(ok)
        self.assertEqual(proto.plu_number_from_record(data), 9)

    def test_read_plu_missing_returns_20(self):
        proto, _fake = self.make([2, 3, 4, 4, 4, 7, 9])
        ok, code, data = proto.read_plu(5)
        self.assertFalse(ok)
        self.assertEqual(code, '20')
        self.assertEqual(data, '')

    def test_read_plu_rejects_wrong_number(self):
        """Si la balanza devuelve otro PLU hay que abortar, no escribir."""
        proto, _fake = self.make([2, 3, 4])
        # La búsqueda resuelve la posición 0, pero ahí está el PLU 2: si se
        # pide el 3 la lectura tiene que rechazarse en vez de devolver datos
        # de otro artículo.
        proto.find_plu_slot = lambda number, max_slot=None: 0
        ok, code, _data = proto.read_plu(3)
        self.assertFalse(ok)
        self.assertEqual(code, self.KretzProtocol.CODE_WRONG_PLU)

    def test_scan_table_dedupes(self):
        proto, fake = self.make([2, 3, 4, 4, 4, 7, 9])
        table = proto.scan_table(max_slot=7)
        self.assertEqual(sorted(table), [2, 3, 4, 7, 9])
        self.assertEqual(table[4][0], 2)   # primera posición del 4
        self.assertEqual(fake.reads, 7)    # una lectura por posición

    def test_scan_table_reports_progress(self):
        proto, _fake = self.make([1, 2, 3])
        seen = []
        proto.scan_table(max_slot=3,
                         progress=lambda slot, total, found: seen.append(found))
        self.assertEqual(len(seen), 3)
        self.assertEqual(seen[-1], 3)

    def test_price_offset_constant(self):
        self.assertEqual(self.KretzProtocol.PLU_PRICE_OFFSET, 77)
        self.assertEqual(self.KretzProtocol.PLU_PRICE_SIZE, 6)


if __name__ == '__main__':
    unittest.main()
