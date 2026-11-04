"""Password validation and bounded, in-memory administrator sessions."""

import hashlib
import hmac
import re
import secrets
import time

DEFAULT_ADMIN_PASSWORD = 'ChangeMe-TravelRouter!'
DEFAULT_AP_PASSWORD = 'TravelRouter-Setup!'


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f'scrypt${salt.hex()}${digest.hex()}'


def verify_password(password, encoded):
    try:
        scheme, salt, expected = encoded.split('$')
        if scheme != 'scrypt' or len(salt) != 32 or len(expected) != 128:
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError, AttributeError):
        return False


def validate_text(value, label, minimum, maximum):
    if not isinstance(value, str) or not minimum <= len(value.encode('utf-8')) <= maximum:
        raise ValueError(f'{label} must be {minimum} to {maximum} UTF-8 bytes')
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f'{label} cannot contain control characters')
    return value


def validate_setup(admin_password, ap_password, ssid, country):
    validate_text(admin_password, 'Administrator password', 12, 128)
    validate_text(ap_password, 'Wi-Fi passphrase', 12, 63)
    if not ap_password.isascii():
        raise ValueError('Wi-Fi passphrase must use ASCII characters')
    validate_text(ssid, 'SSID', 1, 32)
    if admin_password == DEFAULT_ADMIN_PASSWORD or ap_password == DEFAULT_AP_PASSWORD:
        raise ValueError('Replace both factory passwords')
    if hmac.compare_digest(admin_password, ap_password):
        raise ValueError('Use different administrator and Wi-Fi passwords')
    if not isinstance(country, str) or not re.fullmatch('[A-Z]{2}', country):
        raise ValueError('Select your two-letter Wi-Fi country code')


class Sessions:
    def __init__(self):
        self.sessions = {}
        self.attempts = {}

    def allow_login(self, peer):
        now = time.monotonic()
        self.attempts = {key: value for key, value in self.attempts.items()
                         if value[0] > now - 60}
        started, count = self.attempts.get(peer, (now, 0))
        if count >= 5 or len(self.attempts) >= 1024:
            return False
        self.attempts[peer] = (started, count + 1)
        return True

    def create(self):
        now = time.monotonic()
        self.sessions = {key: val for key, val in self.sessions.items() if val['expires'] > now}
        if len(self.sessions) >= 32:
            self.sessions.pop(next(iter(self.sessions)))
        token = secrets.token_urlsafe(32)
        session = {'csrf': secrets.token_urlsafe(32), 'expires': now + 1800}
        self.sessions[token] = session
        return token, session

    def get(self, token):
        session = self.sessions.get(token)
        return session if session and session['expires'] > time.monotonic() else None

    def clear(self):
        self.sessions.clear()
