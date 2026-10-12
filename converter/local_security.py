# -*- coding: utf-8 -*-
"""Política de mismo origen y acceso local para la interfaz de conversión."""
from urllib.parse import urlsplit
import ipaddress

_ALLOWED_HOSTS = {'localhost', '127.0.0.1', '::1'}


def _authority(value: str):
    if not value or '@' in value or '\\' in value:
        return None
    try:
        parsed = urlsplit('//' + value)
        if parsed.path or parsed.query or parsed.fragment:
            return None
        host = (parsed.hostname or '').lower().rstrip('.')
        port = parsed.port
        if host not in _ALLOWED_HOSTS:
            return None
        return host, port
    except ValueError:
        return None


def is_allowed_request(host, remote_addr, origin=None, referer=None,
                       method='GET', fetch_site=None, requested_with=None):
    """Prohíbe DNS rebinding, peticiones remotas y POST cross-site/HTML forms."""
    target = _authority(host or '')
    if not target:
        return False
    try:
        if not ipaddress.ip_address(remote_addr or '').is_loopback:
            return False
    except ValueError:
        return False
    if fetch_site == 'cross-site':
        return False
    if method.upper() not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        return True
    # El encabezado personalizado fuerza preflight en formularios enviados desde
    # otros sitios. No se habilita CORS en la aplicación.
    if requested_with != 'XMLHttpRequest':
        return False
    if origin or referer:
        try:
            candidate = urlsplit(origin or referer)
            if candidate.scheme not in {'http', 'https'}:
                return False
            return _authority(candidate.netloc) == target
        except ValueError:
            return False
    return True
