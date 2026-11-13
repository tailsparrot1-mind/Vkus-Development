import json
import logging
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
LOGS = ROOT / 'logs'
CONFIG = DATA / 'settings.json'
DATA.mkdir(exist_ok=True)
LOGS.mkdir(exist_ok=True)


def hv(v):
    return hashlib.sha256(v.encode('utf-8')).hexdigest()

DEFAULTS = {
    'search_query': 'ремонт',
    'community_url': 'https://vk.com/club1',
    'post_url': 'https://vk.com/wall-1_1',
    'password_hash': hv('vkus'),
    'pin_hash': hv('2580'),
    'pattern_hash': hv('1-4-7-8-9'),
    'touch_hash': hv('1-2-5-4-3'),
    'last_check_at': '',
    'last_results_json': '{}',
    'message_contacts_json': '[]',
    'chat_history_json': '{}',
    'search_results_json': '[]',
    'search_region': 'Москва и область',
    'search_city': 'Москва',
    'search_source': 'Стены сообществ',
    'search_mode': 'posts',
    'search_state': 'Новые сообщения',
    'search_scroll_timeout': '90',
    'search_scroll_rounds': '120',
}


def load_settings():
    if not CONFIG.exists():
        save_settings(DEFAULTS)
        return DEFAULTS.copy()
    try:
        data = json.loads(CONFIG.read_text(encoding='utf-8'))
        result = DEFAULTS.copy()
        result.update({k: str(v) for k, v in data.items() if k in DEFAULTS})
        return result
    except Exception:
        return DEFAULTS.copy()


def save_settings(data):
    CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def setup_logging():
    logger = logging.getLogger('vkus')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(LOGS / 'vkus.log', encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
        logger.addHandler(handler)
    return logger
