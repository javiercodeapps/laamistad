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


if __name__ == '__main__':
    unittest.main()
