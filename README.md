# Защищенная оверлейная сеть передачи данных на основе пиринговых протоколов

**Уровень выполнения:** Продвинутый (N=20, k=4, alpha=3, R=3, собственный 4-шаговый AKE на базе `Ed25519`/`X25519`/`HKDF-SHA256`, сквозное шифрование `AES-256-GCM` с разделением ключей направлений, туннели из 3 ретрансляторов, пул из 3 маршрутов, передача файлов с автоматической докачкой, 4 схемы bootstrap, изолированный underlay-стенд с `tc/netem`, защита от Sybil/Eclipse атак).

---

## 1. Системные требования и окружение

- **ОС:** Windows 10/11, Linux (Ubuntu 20.04+), macOS.
- **Интерпретатор:** стандартный CPython 3.10 или выше.
- **Зависимости:** перечислены в `requirements.txt` (`cryptography`, `pytest`, `pytest-asyncio`, `matplotlib`).

---

## 2. Основная последовательность команд для полного воспроизведения (Разделы 16 и 19 ТЗ)

### Вариант А. Запуск одной командой на Windows
```cmd
run.bat
```
Скрипт автоматически находит установленный CPython, создаёт виртуальное окружение `.venv`, устанавливает зависимости из `requirements.txt` и запускает единый оркестратор испытаний `run_all.py`.

### Вариант Б. Кроссплатформенная последовательность команд (PowerShell / Bash)
Следующая последовательность команд разворачивает чистую среду, поднимает сеть выбранного размера (N=20), выполняет полный набор модульных, интеграционных и негативных тестов (73 тестовых файла), проводит все приёмочные сценарии и сохраняет машинно-читаемые отчёты и графики в каталог `results/`:

```powershell
# 1. Создание и активация виртуального окружения
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # На Linux/macOS: source .venv/bin/activate

# 2. Установка зависимостей
pip install --upgrade pip
pip install -r requirements.txt

# 3. Полный прогон всех тестов, экспериментов, генерация графиков и pcap-дампа
python run_all.py

# 4. Комплексный приёмочный сценарий (Раздел 23 ТЗ) с сохранением отчёта в results/acceptance_report.json
python acceptance_demo.py --nodes 20 --k 4 --hops 3 --r 3

# 5. Альтернативный сценарий живой демонстрации
.\.venv\Scripts\python.exe interactive_cli.py / python interactive_cli.py
```

---

## 3. Архитектура узла и спецификация протокола (Разделы 7 и 8 ТЗ)

### 3.1. Логически разделённые подсистемы
Архитектура узла разделена на 7 изолированных подсистем, объединённых через единый фасад `Node` (`src/node.py`):
1. **Transport (`src/protocol.py`, `src/transport.py`, `src/message_types.py`)** — асинхронный TCP-транспорт, потоковое кадрирование, контроль лимита `MAX_FRAME_PAYLOAD` до аллокации буфера, обработка тайм-аутов и обрывов.
2. **Identity and Security (`src/identity.py`, `src/secure_session.py`, `src/secure_channel.py`)** — долговременные ключи `Ed25519`, детерминированный `NodeID = SHA-256(public_key)`, 4-шаговый AKE с подписью канонического транскрипта, `HKDF-SHA256`, `AES-256-GCM` и защита от внутрисессионного и межсессионного replay.
3. **DHT and Discovery (`src/kbucket.py`, `src/routing_table.py`, `src/lookup.py`, `src/dht_storage.py`, `src/replication.py`, `src/refresh.py`, `src/republisher.py`)** — Kademlia DHT с XOR-метрикой, `k-bucket` с LRU и проверкой старейшего контакта через TCP `PING`, итеративный поиск (alpha=3), хранение подписанных `NodeRecord` с поддержкой псевдонимов (`alias`), репликация (R=3,кворум = 3), контроль TTL и защита от отката `sequence_number`.
4. **Tunnel Management (`src/tunnel.py`, `src/tunnel_builder.py`, `src/tunnel_pool.py`, `src/tunnel_recovery.py`, `src/relay_profile.py`, `src/relay_selector.py`)** — каскадное построение 3-хоповых маршрутов, пул туннелей, профилирование ретрансляторов по EMA успешности и задержки (`random` vs `ranked`), автоматическое переключение на резервный маршрут при отказе.
5. **Application Services (`src/application_message.py`, `src/file_transfer.py`, `src/encrypted_tunnel.py`)** — сквозная доставка текстовых сообщений с уникальным `message_id` и передача файлов блоками по 32 КиБ с контролем `SHA-256` и автоматической докачкой (`FileTransferResume`).
6. **Metrics and Experimentation (`src/bootstrap_experiment.py`, `src/dht_absent_target_experiment.py`, `src/relay_experiment.py`, `run_performance_experiment.py`, `plot_results.py`)** — сбор сырых экспериментальных метрик в JSON и автоматическое построение графиков.
7. **User Interface (`demo_user.py`, `acceptance_demo.py`)** — консольный интерфейс демонстрации и параметризуемый CLI-стенд приёмочных испытаний.

### 3.2. Формат заголовка кадра (24 байта, `!BBH16sI`)
Каждый кадр передаётся поверх TCP и предваряется фиксированным 24-байтовым заголовком в сетевом порядке байтов (big-endian):

| Поле | Размер | Тип (`struct`) | Назначение |
|---|---:|---|---|
| `version` | 1 байт | `B` (`uint8`) | Версия протокола (`PROTOCOL_VERSION = 1`) |
| `type` | 1 байт | `B` (`uint8`) | Код типа сообщения (`MessageType`, значения `1..17`) |
| `flags` | 2 байта | `H` (`uint16`) | Флаги ответа, ошибки и фрагментации |
| `request_id` | 16 байт | `16s` (`UUID`) | Идентификатор запроса для сопоставления ответов и дедупликации |
| `payload_length` | 4 байта | `I` (`uint32`) | Длина полезной нагрузки (проверяется на $\le 65\,536$ байт до чтения) |
| `payload` | переменный | `bytes` | Сериализованные данные сообщения или шифротекст `AES-256-GCM` |

Поддерживаются все 17 обязательных типов сообщений: `PING (1)`, `PONG (2)`, `FIND_NODE_REQUEST (3)`, `FIND_NODE_RESPONSE (4)`, `STORE_REQUEST (5)`, `STORE_RESPONSE (6)`, `FIND_VALUE_REQUEST (7)`, `FIND_VALUE_RESPONSE (8)`, `TUNNEL_BUILD (9)`, `TUNNEL_OK (10)`, `TUNNEL_FAIL (11)`, `TUNNEL_DATA (12)`, `TUNNEL_ACK (13)`, `TUNNEL_CLOSE (14)`, `APP_MESSAGE (15)`, `APP_ACK (16)`, `ERROR (17)`.

---

## 4. Раздельный запуск тестов и экспериментов

1. **Полный набор модульных, интеграционных и негативных тестов (73 файла, 246 тестов):**
   ```powershell
   python -m pytest tests/ -v
   ```
2. **Обязательные негативные тесты безопасности (Раздел 11.4 ТЗ, 8 векторов атак):**
   ```powershell
   python -m pytest tests/test_negative_security.py -v -s или .\.venv\Scripts\python.exe -m pytest tests/test_negative_security.py -v -s
   ```
3. **Эксперимент холодной сходимости и сравнение 4 схем Bootstrap (Разделы 6, 14, 15.1 ТЗ):**
   ```powershell
   python run_bootstrap_experiment.py
   ```
   *Выходной артефакт:* `results/bootstrap_experiment_results.json`
4. **Эксперимент невырожденности DHT — 30 поисков отсутствующей цели на схему (Раздел 6 ТЗ):**
   ```powershell
   python src/dht_absent_target_experiment.py
   ```
   *Выходной артефакт:* `results/dht_absent_target_strict_results.json`
5. **Эксперимент сравнения стратегий выбора ретрансляторов `random` vs `ranked` (Раздел 12 ТЗ):**
   ```powershell
   python run_relay_experiment.py
   ```
   *Выходной артефакт:* `results/relay_experiment_results.json`
6. **Замер задержек сессий, отказоустойчивости при Churn и файлового Goodput (Раздел 15.2 ТЗ):**
   ```powershell
   python run_performance_experiment.py
   ```
   *Выходной артефакт:* `results/performance_experiment_results.json`
7. **Построение графиков из сырых JSON-данных (Разделы 15.3 и 19 ТЗ):**
   ```powershell
   python plot_results.py
   ```
   *Выходные графики:* `results/convergence_time.png`, `results/dht_absent_target_metrics.png`, `results/relay_strategy_latency.png`
8. **Генерация контрольного дампа трафика `.pcap` (Разделы 16 и 19 ТЗ):**
   ```powershell
   python make_pcap.py
   ```
   *Выходной артефакт:* `traffic_capture.pcap`
9. **Пользовательская и приёмочная демонстрации:**
   ```powershell
   python demo_user.py
   python acceptance_demo.py
   ```

---

## 5. Реализация обязательных сценариев испытаний (Раздел 15.1 ТЗ)

| № | Сценарий ТЗ | Что проверяется | Скрипты и тесты | Фиксируемый артефакт |
|---|---|---|---|---|
| **1** | **Холодный запуск и операционная сходимость** | Инициализация сети из N=20 узлов, достижение < 95 успешных lookup в 2 последовательных раундах при изменении числа контактов < = 10. | `run_bootstrap_experiment.py`, `src/bootstrap_experiment.py` | `results/bootstrap_experiment_results.json` |
| **2** | **`FIND_NODE` для отсутствующей цели** | По 30 итеративных поисков на каждую схему, где цель отсутствует в начальной таблице инициатора и находится через промежуточные DHT-узлы. | `src/dht_absent_target_experiment.py`, `tests/test_iterative_lookup_tcp.py` | `results/dht_absent_target_strict_results.json` |
| **3** | **`STORE / FIND_VALUE` с тремя репликами (R=3)** | Публикация подписанной `Ed25519` записи `NodeRecord` на 3 ближайших по XOR узла с подтверждением кворума 2/3. | `tests/test_dht_replication_tcp.py`, `acceptance_demo.py` | `results/acceptance_report.json` |
| **4** | **Отключение одного хранителя и повторный `FIND_VALUE`** | Остановка одного из трёх узлов-хранителей и успешное чтение записи с оставшихся реплик. | `tests/test_dht_replication_failure_tcp.py`, `acceptance_demo.py` | `results/acceptance_report.json` |
| **5** | **Отключение промежуточного кандидата во время lookup** | Устойчивость итеративного поиска (alpha=3) при внезапном отказе до 40% промежуточных узлов (30 прогонов). | `run_performance_experiment.py`, `src/lookup.py` | `results/performance_experiment_results.json` |
| **6** | **Построение туннеля и передача сообщения** | Сквозное 4-шаговое согласование сессии, построение маршрута из 3 ретрансляторов и E2E-передача шифротекста `AES-256-GCM`. | `tests/test_encrypted_application_relay_tcp.py`, `make_pcap.py` | `traffic_capture.pcap` |
| **7** | **Отключение активного ретранслятора и восстановление** | Аварийная остановка ретранслятора во время передачи, переключение на резервный маршрут и докачка оставшихся чанков файла. | `tests/test_encrypted_file_relay_resume_tcp.py`, `acceptance_demo.py` | `results/performance_experiment_results.json` |
| **8** | **Негативные криптографические и replay-тесты** | Автоматическая проверка 8 векторов атак: подмена ключа, несовпадение `NodeID`, искажение handshake, модификация ciphertext, replay внутри и между сессиями, подделка подписи DHT и откат `sequence_number`. | `tests/test_negative_security.py` | Отчёт `pytest` |
| **9** | **Сравнение bootstrap-схем** | Сравнение 4 схем начального присоединения (`star`, `ring`, `tree`, `multi_seed`) при неизменных остальных параметрах. | `run_bootstrap_experiment.py`, `plot_results.py` | `results/convergence_time.png` |
| **10** | **Ограниченный underlay и деградация `tc/netem`** | Маршрутизация между двумя изолированными IP-подсетями Docker (`172.28.1.0/24` и `172.28.2.0/24`) через пограничный ретранслятор с инжекцией задержек и потерь пакетов. | `docker-compose.underlay.yml`, `run_underlay_experiment.py` | `results/underlay_experiment_report.json` |

---

## 6. Воспроизводимость в Docker и изолированный Underlay-стенд (Раздел 14 ТЗ)

### 6.1. Автономный запуск всех проверок в контейнере
```bash
docker build -f Dockerfile -t overlay-network .
docker run --rm overlay-network
```

### 6.2. Стенд с ограниченной IP-достижимостью и `tc/netem` (Сценарий 10)
Файл `docker-compose.underlay.yml` создаёт две изолированные подсети Docker: `net_left` (`172.28.1.0/24`, где находится `node_a`) и `net_right` (`172.28.2.0/24`, где находится `node_b`). Прямая IP-связность между `node_a` и `node_b` отсутствует. Связь осуществляется исключительно через пограничный ретранслятор `relay_node` с привилегиями `NET_ADMIN`, на сетевом интерфейсе которого применяются правила `tc qdisc netem` (задержка +50 мс, джиттер 10 мс, потери 2%).

```bash
docker compose -f docker-compose.underlay.yml up --build --abort-on-container-exit
docker compose -f docker-compose.underlay.yml down
```
Очистка контейнеров и вируальных сетей(последняя команда)
---

## 7. Конфигурация и состав репозитория (Разделы 14 и 19 ТЗ)

Все параметры протокола вынесены в `config.json` и изменяются без модификации исходного кода (`N_NODES = 20`, `NODE_ID_BITS = 256`, `K_BUCKET_SIZE = 4`, `ALPHA = 3`, `REPLICATION_FACTOR = 3`, `REPLICATION_QUORUM = 2`, `RECORD_TTL = 240`, `TUNNEL_RELAY_COUNT = 3`, `TUNNEL_POOL_SIZE = 3`, `MAX_FRAME_PAYLOAD = 65536`, `FILE_CHUNK_SIZE = 32768`).

### Структура репозитория:
- `src/` — исходный код 7 подсистем узла оверлейной сети (39 модулей).
- `tests/` — полный набор модульных, интеграционных и негативных автотестов (73 файла).
- `results/` — сырые экспериментальные данные (`.json`) и построенные графики (`.png`).
- `run_all.py`, `run.bat` — единый оркестратор сборки, тестирования и экспериментов.
- `acceptance_demo.py`, `demo_user.py` — приёмочная и пользовательская демонстрации.
- `plot_results.py`, `make_pcap.py` — генераторы графиков и дампа сетевого трафика `traffic_capture.pcap`.
- `Dockerfile`, `docker-compose.underlay.yml` — конфигурация контейнерного развёртывания и изолированного underlay-стенда.
- `config.json`, `requirements.txt`, `USERGUIDE.md` — конфигурация сети, зависимости и руководство пользователя.