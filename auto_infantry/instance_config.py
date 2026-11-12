"""Scope a background process to one explicitly selected emulator."""
import os
from pathlib import Path
import re

PRIMARY_DEVICE = 'emulator-5554'
DEVICE = os.environ.get('REA_HELPER_DEVICE', PRIMARY_DEVICE)
if not re.fullmatch(r'emulator-[0-9]{4,5}', DEVICE):
    raise ValueError('雷电设备编号无效')
SECONDARY = DEVICE != PRIMARY_DEVICE
DEVICE_ID = os.environ.get('REA_HELPER_DEVICE_ID', '')
DATA_HOME = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'REA_YXS'


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
