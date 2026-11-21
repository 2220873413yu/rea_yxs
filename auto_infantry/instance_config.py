"""Scope a background process to one explicitly selected emulator."""
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

DATA_HOME = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'REA_YXS'
EMULATOR_SETTINGS = DATA_HOME / 'emulator.json'


def load_emulator_settings():
    """Read machine-local connection settings, falling back after a missing or invalid file."""
    try:
        settings = json.loads(EMULATOR_SETTINGS.read_text(encoding='utf-8'))
        if (isinstance(settings, dict) and isinstance(settings.get('adb'), str)
                and Path(settings['adb']).is_absolute() and Path(settings['adb']).name.lower() == 'adb.exe'
                and isinstance(settings.get('device'), str)
                and re.fullmatch(r'emulator-[0-9]{4,5}', settings['device'])):
            return settings
    except (OSError, ValueError):
        pass
    return {}


def save_emulator_settings(adb_path, device):
    """Replace the local settings only after the new file has been written."""
    EMULATOR_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=EMULATOR_SETTINGS.parent,
                                delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'adb': adb_path, 'device': device}, stream, ensure_ascii=False)
        temporary.replace(EMULATOR_SETTINGS)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


EMULATOR_CONFIG = load_emulator_settings()
PRIMARY_DEVICE = EMULATOR_CONFIG.get('device', 'emulator-5554')
DEVICE = os.environ.get('REA_HELPER_DEVICE', PRIMARY_DEVICE)
if not re.fullmatch(r'emulator-[0-9]{4,5}', DEVICE):
    raise ValueError('雷电设备编号无效')
SECONDARY = DEVICE != PRIMARY_DEVICE
DEVICE_ID = os.environ.get('REA_HELPER_DEVICE_ID', '')


def instance_directory(device, device_id):
    """Use the emulator serial and Android identity to isolate accounts and files from a replaced instance."""
    if not re.fullmatch(r'emulator-[0-9]{4,5}', device) or not re.fullmatch(r'[0-9a-f]{16}', device_id):
        raise ValueError('雷电设备身份尚未确认')
    return DATA_HOME / 'instances' / device / device_id


INSTANCE_DIRECTORY = instance_directory(DEVICE, DEVICE_ID) if SECONDARY else None


def role_preferences(directory, role, zone, map_id):
    """Keep hero and beacon choices per role and resource coordinates per role and map."""
    if (not re.fullmatch(r'[0-9a-f]{64}', role) or type(zone) is not int or zone < 0 or
            type(map_id) is not int or map_id <= 0):
        raise ValueError('角色或地图身份尚未确认')
    role_dir = directory / 'roles' / role
    map_dir = role_dir / f'{zone}-{map_id}'
    return dict(heroes=role_dir / 'hero_preferences.json', beacon=role_dir / 'beacon_preferences.json',
                resources=map_dir / 'resource_preferences.json')
