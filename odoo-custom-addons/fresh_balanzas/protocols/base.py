from abc import ABC, abstractmethod


class BaseProtocol(ABC):
    """Clase abstracta para protocolos de comunicación con balanzas.

    Cada marca de balanza debe implementar esta interfaz.
    """

    @abstractmethod
    def connect(self):
        """Establece conexión con la balanza."""

    @abstractmethod
    def disconnect(self):
        """Cierra la conexión con la balanza."""

    @abstractmethod
    def test_communication(self, beep=True):
        """Prueba la comunicación con la balanza.

        Args:
            beep: Si True, emite un sonido de prueba.

        Returns:
            bool: True si la comunicación es exitosa.
        """

    @abstractmethod
    def upsert_plu(self, plu_data):
        """Alta o modificación de un PLU (producto).

        Args:
            plu_data: Diccionario con los datos del PLU.

        Returns:
            tuple: (ok: bool, code: str, message: str)
        """

    @abstractmethod
    def delete_plu(self, plu_number):
        """Baja de un PLU.

        Args:
            plu_number: Número de PLU a eliminar.

        Returns:
            tuple: (ok: bool, code: str, message: str)
        """

    @abstractmethod
    def delete_all_plus(self):
        """Baja de todos los PLUs.

        Returns:
            tuple: (ok: bool, code: str, message: str)
        """

    @abstractmethod
    def upsert_vendor(self, vendor_data):
        """Alta o modificación de un vendedor.

        Args:
            vendor_data: Diccionario con los datos del vendedor.

        Returns:
            tuple: (ok: bool, code: str, message: str)
        """

    @abstractmethod
    def delete_vendor(self, vendor_code):
        """Baja de un vendedor.

        Args:
            vendor_code: Código del vendedor.

        Returns:
            tuple: (ok: bool, code: str, message: str)
        """

    @abstractmethod
    def delete_all_vendors(self):
        """Baja de todos los vendedores.

        Returns:
            tuple: (ok: bool, code: str, message: str)
        """

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
