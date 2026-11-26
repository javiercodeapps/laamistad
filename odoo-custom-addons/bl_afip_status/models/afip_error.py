import re

SERVICE_UNAVAILABLE = "service_unavailable"
SOAP_PARSE = "soap_parse"
TIMEOUT = "timeout"
NETWORK = "network"
TLS = "tls"
AUTH = "auth"
SOAP_FAULT = "soap_fault"
CONFIG = "config"
UNKNOWN = "unknown"

SERVICE_DOWN_TYPES = (SERVICE_UNAVAILABLE, SOAP_PARSE, TIMEOUT, NETWORK)

MESSAGES = {
    SERVICE_UNAVAILABLE: "ARCA no esta disponible en este momento: el servicio respondio una pagina de error en lugar de una respuesta valida. Reintenta en unos minutos.",
    SOAP_PARSE: "ARCA devolvio una respuesta que no se pudo interpretar. Suele indicar una caida o un mantenimiento del servicio. Reintenta en unos minutos.",
    TIMEOUT: "ARCA no respondio a tiempo. El servicio esta lento o saturado. Reintenta en unos minutos.",
    NETWORK: "No se pudo establecer la conexion de red con ARCA. Verifica la conectividad del servidor o reintenta en unos minutos.",
    TLS: "Fallo la negociacion segura (TLS) con ARCA. Si el problema persiste, avisa a soporte tecnico.",
    AUTH: "Fallo la autenticacion con ARCA (WSAA). Revisa el certificado, la clave privada y la delegacion del servicio en el portal de ARCA.",
    SOAP_FAULT: "ARCA rechazo la operacion e informo un error del servicio.",
    CONFIG: "Hay un problema de configuracion en la integracion con ARCA. Revisa el diario, el punto de venta y el webservice asignado.",
    UNKNOWN: "Ocurrio un error inesperado al comunicarse con ARCA. Se registro el incidente tecnico para soporte.",
}


def _to_text(value):
    if value is None:
        return ""
    if isinstance(value, Exception):
        return str(value)
    return str(value)


def _clip(value, max_size):
    value = _to_text(value)
    return value[:max_size] if len(value) > max_size else value


# Mensajes por codigo HTTP, mas precisos que el generico del tipo de error.
HTTP_MESSAGES = {
    500: "ARCA respondio con un error interno de su servidor (HTTP 500). Reintenta en unos minutos.",
    502: "El servidor de ARCA no esta disponible (HTTP 502, Bad Gateway). Reintenta en unos minutos.",
    503: "ARCA esta fuera de servicio o en mantenimiento (HTTP 503). Reintenta en unos minutos.",
    504: "ARCA no respondio a tiempo a traves de su gateway (HTTP 504). El servicio esta saturado.",
}


def classify_afip_error(error, response_excerpt=None, http_status=None):
    message = _to_text(error)
    lower_message = message.lower()
    excerpt = _clip(response_excerpt or message, 2000)
    lower_excerpt = excerpt.lower()

    normalized_status = None
    if http_status not in (None, ""):
        try:
            normalized_status = int(http_status)
        except Exception:
            normalized_status = None

    error_type = UNKNOWN

    if normalized_status is not None and normalized_status >= 500:
        error_type = SERVICE_UNAVAILABLE
    elif any(token in lower_excerpt for token in ["service unavailable", "<html", "<h1", "<!doctype", "bad gateway"]):
        error_type = SERVICE_UNAVAILABLE
    elif any(token in lower_message for token in ["timed out", "timeout", "read operation timed out"]):
        error_type = TIMEOUT
    elif any(
        token in lower_message
        for token in [
            "connection reset",
            "name or service not known",
            "temporary failure in name resolution",
            "failed to establish a new connection",
            "max retries exceeded",
            "connection refused",
            "network is unreachable",
            "newconnectionerror",
            "connectionerror",
        ]
    ):
        error_type = NETWORK
    elif any(
        token in lower_message
        for token in [
            "dh_key_too_small",
            "sslerror",
            "handshake",
            "certificate verify failed",
            "tls",
            "sslv3",
        ]
    ):
        error_type = TLS
    elif any(
        token in lower_message
        for token in [
            "no afip ws selected",
            "not implemented",
            "could not connect",
            "point of sale",
            "webservice",
            "config",
            "attributeerror: 'bool' object",
        ]
    ):
        error_type = CONFIG
    elif any(
        token in lower_message
        for token in ["wsaa", "logincms", "ns:cms.bad", "certificado", "certificate", "private key", "token", "sign"]
    ):
        error_type = AUTH
    elif any(token in lower_message for token in ["tag not found", "no elements found", "expaterror", "mismatched tag"]):
        error_type = SOAP_PARSE
    elif any(token in lower_message for token in ["soapfault", "soap fault", "faultcode", "faultstring"]):
        error_type = SOAP_FAULT

    summary_source = message or excerpt or "Error sin detalle"
    summary = re.sub(r"\s+", " ", summary_source).strip()[:255]
    user_message = HTTP_MESSAGES.get(normalized_status) or MESSAGES[error_type]

    return {
        "error_type": error_type,
        "message": user_message,
        "summary": summary,
        "excerpt": excerpt,
        "http_status": str(normalized_status) if normalized_status is not None else (str(http_status) if http_status else False),
    }
