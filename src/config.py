import json
from pathlib import Path

# Поиск config.json: корень проекта, текущая папка или рабочая директория
_CURRENT_DIR = Path(__file__).resolve().parent
_CANDIDATE_PATHS = [
    _CURRENT_DIR.parent / "config.json",
    _CURRENT_DIR / "config.json",
    Path("config.json"),
]

DEFAULTS = {
    "N_NODES": 20,
    "NODE_ID_BITS": 256,
    "K_BUCKET_SIZE": 4,
    "ALPHA": 3,
    "REPLICATION_FACTOR": 3,
    "REPLICATION_QUORUM": 2,
    "RECORD_TTL": 240,
    "REFRESH_INTERVAL": 30.0,
    "REPUBLISH_INTERVAL": 60.0,
    "NETWORK_TIMEOUT": 2.5,
    "TUNNEL_RELAY_COUNT": 3,
    "TUNNEL_POOL_SIZE": 3,
    "DEGRADATION_CONSECUTIVE_FAILURES": 3,
    "MAX_FRAME_PAYLOAD": 65536,
    "FILE_CHUNK_SIZE": 32768,
}

def load_config() -> dict:
    for path in _CANDIDATE_PATHS:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return {**DEFAULTS, **json.load(f)}
            except Exception:
                pass
    return dict(DEFAULTS)

CONFIG = load_config()

# Экспорт отдельных констант для прямого импорта в модули
NODE_ID_BITS: int = int(CONFIG["NODE_ID_BITS"])
K_BUCKET_SIZE: int = int(CONFIG["K_BUCKET_SIZE"])
ALPHA: int = int(CONFIG["ALPHA"])
REPLICATION_FACTOR: int = int(CONFIG["REPLICATION_FACTOR"])
REPLICATION_QUORUM: int = int(CONFIG["REPLICATION_QUORUM"])
RECORD_TTL: int = int(CONFIG["RECORD_TTL"])
REFRESH_INTERVAL: float = float(CONFIG["REFRESH_INTERVAL"])
REPUBLISH_INTERVAL: float = float(CONFIG["REPUBLISH_INTERVAL"])
NETWORK_TIMEOUT: float = float(CONFIG["NETWORK_TIMEOUT"])
TUNNEL_RELAY_COUNT: int = int(CONFIG["TUNNEL_RELAY_COUNT"])
TUNNEL_POOL_SIZE: int = int(CONFIG["TUNNEL_POOL_SIZE"])
DEGRADATION_CONSECUTIVE_FAILURES: int = int(CONFIG["DEGRADATION_CONSECUTIVE_FAILURES"])
N_NODES: int = int(CONFIG["N_NODES"])
MAX_FRAME_PAYLOAD: int = int(CONFIG["MAX_FRAME_PAYLOAD"])
FILE_CHUNK_SIZE: int = int(CONFIG["FILE_CHUNK_SIZE"])