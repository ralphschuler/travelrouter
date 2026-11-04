"""Authenticated, password-encrypted backups with a small restoration schema."""

import base64
import json
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .filtering import validate_settings
from .policy import render_unbound
from .privacy import proxy_config, wireguard_config
from .security import DEFAULT_ADMIN_PASSWORD, validate_setup, validate_text, verify_password

CONTEXT = b'TravelRouter encrypted settings v1'


def _derive(password, salt):
    validate_text(password, 'Backup password', 12, 128)
    return Scrypt(salt=salt, length=32, n=32768, r=8, p=1).derive(password.encode())


def seal(payload, password):
    salt, nonce = os.urandom(16), os.urandom(12)
    ciphertext = AESGCM(_derive(password, salt)).encrypt(nonce, json.dumps(payload).encode(), CONTEXT)
    return {'format': 'travelrouter-backup-v1', 'salt': base64.b64encode(salt).decode(),
            'nonce': base64.b64encode(nonce).decode(), 'ciphertext': base64.b64encode(ciphertext).decode()}


def unseal(envelope, password):
    try:
        if not isinstance(envelope, dict) or envelope.get('format') != 'travelrouter-backup-v1':
            raise ValueError('Unsupported backup format')
        salt, nonce, ciphertext = (base64.b64decode(envelope[key], validate=True)
                                   for key in ('salt', 'nonce', 'ciphertext'))
        if len(salt) != 16 or len(nonce) != 12 or len(ciphertext) > 512000:
            raise ValueError('Invalid backup size')
        plaintext = AESGCM(_derive(password, salt)).decrypt(nonce, ciphertext, CONTEXT)
        return json.loads(plaintext)
    except (InvalidTag, ValueError, KeyError, TypeError) as error:
        raise ValueError('Cannot decrypt backup: invalid file or incorrect password') from error


def validate_payload(payload):
    if not isinstance(payload, dict) or payload.get('version') != 1 or set(payload) - {
            'version', 'config', 'networks', 'wireguard', 'proxy'}:
        raise ValueError('Invalid settings backup')
    config = payload.get('config')
    allowed = {'schema', 'setup_complete', 'ssid', 'ap_password', 'country', 'admin_hash',
               'dns_mode', 'privacy_mode', 'filtering', 'auto_updates'}
    if not isinstance(config, dict) or set(config) - allowed or config.get('setup_complete') is not True:
        raise ValueError('Backup must contain a completed setup')
    try:
        validate_setup('backup validation placeholder', config['ap_password'], config['ssid'], config['country'])
        if not re.fullmatch(r'scrypt\$[0-9a-f]{32}\$[0-9a-f]{128}', config['admin_hash']):
            raise ValueError('Invalid administrator hash')
        if verify_password(DEFAULT_ADMIN_PASSWORD, config['admin_hash']):
            raise ValueError('Factory credentials cannot be restored')
        render_unbound(config.get('dns_mode', 'dot'))
        if config.get('privacy_mode', 'direct') not in {'direct', 'wireguard', 'proxy'}:
            raise ValueError('Invalid privacy mode')
        if 'filtering' in config:
            config['filtering'] = validate_settings(config['filtering'])
        if type(config.get('auto_updates', False)) is not bool:
            raise ValueError('Invalid update preference')
        networks = payload.get('networks', [])
        if not isinstance(networks, list) or len(networks) > 50:
            raise ValueError('Too many saved networks')
        for network in networks:
            if not isinstance(network, dict) or set(network) - {'ssid', 'password', 'allow_open', 'priority'}:
                raise ValueError('Invalid network profile')
            validate_text(network['ssid'], 'SSID', 1, 32)
            password = network.get('password', '')
            if password:
                validate_text(password, 'Upstream password', 8, 63)
                if not password.isascii():
                    raise ValueError('Invalid upstream passphrase')
            elif network.get('allow_open') is not True:
                raise ValueError('Open network consent is missing')
            priority = network.get('priority', 10)
            if type(priority) is not int or not -100 <= priority <= 100:
                raise ValueError('Invalid network priority')
        if payload.get('wireguard'):
            payload['wireguard'] = wireguard_config(payload['wireguard'])
        if config.get('privacy_mode') == 'wireguard' and not payload.get('wireguard'):
            raise ValueError('WireGuard configuration is missing')
        if payload.get('proxy'):
            proxy_config(payload['proxy'], '192.0.2.9', 'wlan1')
        if config.get('privacy_mode') == 'proxy' and not payload.get('proxy'):
            raise ValueError('Proxy settings are missing')
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Backup settings are incomplete') from error
    return payload
