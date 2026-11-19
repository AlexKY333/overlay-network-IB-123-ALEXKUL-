# Руководство пользователя оверлейной сети (USERGUIDE)

Настоящее руководство описывает консольные команды запуска, параметры приёмочного стенда и программный интерфейс (API) класса-фасада `Node` (`src/node.py`) для работы с защищённой пиринговой оверлейной сетью.

---

## 1. Консольные команды запуска и демонстрации

### 1.1. Демонстрация пользовательского API (`demo_user.py`)
Показывает полный жизненный цикл работы одного узла с оверлейной сетью (генерация ключей `Ed25519`, подпись и публикация `NodeRecord` с псевдонимом `alias`, построение 3-хопового туннеля по стратегии `ranked`, согласование сессии 4-шаговым AKE, передача текстового сообщения и файла с проверкой `SHA-256`):

```powershell
python demo_user.py
```

### 1.2. Полный приёмочный сценарий (`acceptance_demo.py`)
Запускает живую TCP-сеть из `N` узлов и последовательно выполняет все приёмочные испытания раздела 23 ТЗ (проверка невырожденности DHT, репликация записи на `R = 3` узла, чтение после отказа хранителя, передача сообщения через 3 ретранслятора, инъекция отказа ретранслятора и автоматическое восстановление доставки):

```powershell
# Запуск с параметрами по умолчанию из config.json (N = 20, k = 4, hops = 3, R = 3)
python acceptance_demo.py

# Запуск с пользовательскими параметрами через флаги командной строки
python acceptance_demo.py --nodes 20 --k 4 --hops 3 --r 3
```

Поддерживаемые аргументы командной строки `acceptance_demo.py`:
- `--nodes` — количество одновременно работающих логических узлов сети (по умолчанию `20`);
- `--k` — ёмкость одного `k-bucket` таблицы маршрутизации (по умолчанию `4`, можно указать `3` для сравнительного анализа);
- `--hops` — количество промежуточных ретрансляторов в туннеле (по умолчанию `3`);
- `--r` — фактор репликации записей в Kademlia DHT (по умолчанию `3`).

### 1.3. Интерактивный пульт управления (`interactive_cli.py`)
Позволяет вручную пошагово проверять любой пункт программы приёмочных испытаний (Раздел 23 ТЗ) в живой консоли:

```powershell
python interactive_cli.py
```

Поддерживаемые команды в `overlay-cli>`:
- `1` или `init [N] [k] [scheme]` — создание живой TCP-сети (например, `init 20 4 multi_seed` или `init 15 3 ring`);
- `2` или `lookup` — итеративный поиск отсутствующего в таблице узла через DHT;
- `3` или `store [alias]` — подпись и репликация `NodeRecord` на `R = 3` узла;
- `4` или `kill_keeper` — отказ одного хранителя и чтение записи через `FIND_VALUE` с живой реплики;
- `5` или `send [текст]` — построение 3-хопового туннеля (`AKE + AES-256-GCM`) и сквозная отправка сообщения;
- `6` или `kill_relay` — отказ активного ретранслятора и автоматическое восстановление доставки;
- `7` или `all` — автоматический прогон всех шагов 1–6 подряд;
- `0` или `exit` — корректная остановка узлов и выход.

---

## 2. Архитектура фасада `Node` (Раздел 7 ТЗ)

Прикладной слой взаимодействует с сетью исключительно через публичные методы класса-фасада `Node`, не обращаясь напрямую к внутренним структурам `k-bucket` или хранилища:

```text
+--------------------------------------------------------------------------+
|                                NODE FACADE                               |
|                                                                          |
|  +----------------+  +--------------------+  +------------------------+  |
|  |    Identity    |  |    RoutingTable    |  |       DHTStorage       |  |
|  | (Ed25519 / ID) |  | (k-bucket, α = 3)  |  | (R=3, Quorum, Rollback)|  |
|  +----------------+  +--------------------+  +------------------------+  |
|                                                                          |
|  +--------------------+  +--------------------+  +--------------------+  |
|  |     TunnelPool     |  |   TunnelBuilder    |  |    FileTransfer    |  |
|  |  (Active/Prepared) |  |   (Ranked/Random)  |  | (Chunks, AES, SHA) |  |
|  +--------------------+  +--------------------+  +--------------------+  |
+--------------------------------------------------------------------------+
```

### Сводная таблица методов фасада `Node`:

| Метод фасада | Назначение |
|---|---|
| `await node.join(bootstrap_peers, timeout)` | Подключение к сети через список начальных контактов с валидацией по TCP `PING` и наполнением `k-bucket`. |
| `await node.lookup_node(target_node_id, timeout)` | Итеративный поиск ближайших узлов к цели (`α = 3`) по сети TCP. |
| `await node.put_record(record)` | Локальное сохранение и сетевая репликация подписанной `NodeRecord` на `R = 3` узла (кворум `2/3`). |
| `await node.get_record(key)` | Поиск адресной записи в локальном хранилище и через итеративный `FIND_VALUE` в DHT. |
| `await node.resolve_alias(alias)` | Разрешение человекочитаемого псевдонима по ключу `SHA-256("alias:" \|\| normalize(alias))`. |
| `node.build_tunnel(destination_node_id, relay_count, strategy)` | Построение многопереходного туннеля (`ranked` или `random`) и регистрация в `TunnelPool`. |
| `node.send_via_tunnel(encrypted_tunnel, message)` | Упаковка сообщения в `ApplicationMessage` и сквозное шифрование `AES-256-GCM`. |
| `node.send_file_via_tunnel(encrypted_tunnel, file_path)` | Нарезка файла на чанки по 32 КиБ и сквозное шифрование каждого блока для передачи. |
| `node.process_incoming_file_chunk(encrypted_tunnel, data)` | Расшифровка чанка, сборка файла в `downloads/` и финальная сверка хэша `SHA-256`. |
| `node.close_tunnel(tunnel_id)` | Штатное закрытие туннеля и удаление его из активного пула. |
| `node.get_network_state()` | Получение телеметрии узла (число контактов, записей DHT, активных и резервных туннелей). |

---

## 3. Примеры использования программного интерфейса

### Сценарий 1. Инициализация узла и подключение к сети (`join` и `lookup_node`)
При первом запуске узел генерирует ключевую пару `Ed25519` и сохраняет закрытый ключ в `state_dir/identity.key`. Идентификатор `node_id` вычисляется детерминированно как `SHA-256(public_key)`:

```python
from pathlib import Path
from node import Node
from contact import Contact

# 1. Инициализация узла (можно также передать k_bucket_size=4 или k_bucket_size=3)
node = Node(state_dir=Path("./node_storage"))
print(f"Локальный NodeID: {node.node_id}")

# 2. Подключение к известным bootstrap-узлам
bootstrap_peers = [
    Contact(node_id="1" * 64, host="127.0.0.1", port=9001),
    Contact(node_id="2" * 64, host="127.0.0.1", port=9002),
]
discovered = await node.join(bootstrap_peers, timeout=2.5)
print(f"Обнаружено и добавлено контактов: {discovered}")

# 3. Итеративный поиск целевого узла в DHT (α = 3)
target_id = "f" * 64
closest_contacts = await node.lookup_node(target_id, timeout=2.5)
print(f"Найдено ближайших контактов: {len(closest_contacts)}")
```

### Сценарий 2. Публикация, поиск записей и разрешение псевдонимов (`put_record`, `get_record`, `resolve_alias`)
Каждая запись `NodeRecord` подписывается закрытым ключом владельца и защищена от подмены и отката версии (`sequence_number`):

```python
import time
from dht_messages import NodeRecord

# 1. Создание и публикация подписанной записи с псевдонимом (alias)
now = int(time.time())
record = NodeRecord.create_signed(
    identity=node.identity,
    addresses=["127.0.0.1:9050"],
    sequence_number=1,
    issued_at=now,
    expires_at=now + 240,
    alias="alice_workstation",
)

replicas_ack = await node.put_record(record)
print(f"Запись подтверждена {replicas_ack} репликами (кворум ≥ 2)")

# 2. Поиск записи по 64-символьному NodeID
found_by_id = await node.get_record(node.node_id)
if found_by_id and found_by_id.verify_signature():
    print(f"Адреса узла: {found_by_id.addresses}")

# 3. Разрешение псевдонима (без учёта регистра и пробелов)
found_by_alias = await node.resolve_alias("Alice_Workstation")
if found_by_alias:
    print(f"Псевдоним разрешён в NodeID: {found_by_alias.node_id}")
```

### Сценарий 3. Установление защищённой сессии (4-шаговый AKE) и туннельная передача сообщений
Для защиты прикладных данных от промежуточных ретрансляторов между отправителем и получателем устанавливается сквозная сессия `SecureSession`:

```python
from relay_profile import RelayProfile
from relay_selector import RelaySelector
from secure_session import SecureSession
from encrypted_tunnel import EncryptedTunnel

# 1. Конфигурация профилей кандидатов и выбор по рейтингу (EMA)
profiles = [
    RelayProfile(node_id=101, ema_latency=0.04, ema_success=1.00, subnet="10.0.1.0/24"),
    RelayProfile(node_id=102, ema_latency=0.07, ema_success=0.98, subnet="10.0.2.0/24"),
    RelayProfile(node_id=103, ema_latency=0.11, ema_success=0.96, subnet="10.0.3.0/24"),
]
selector = RelaySelector(profiles)
node.relay_selector = selector
node.tunnel_builder.relay_selector = selector

# 2. Построение туннеля из 3 ретрансляторов через фасад
tunnel = node.build_tunnel(
    destination_node_id=recipient_node.node_id,
    relay_count=3,
    strategy="ranked",
)
print(f"Маршрут туннеля {tunnel.tunnel_id}: {tunnel.path}")

# 3. 4-шаговое аутентифицированное рукопожатие (X25519 + Ed25519 + HKDF-SHA256)
session_a = SecureSession(node.identity, is_initiator=True)
session_b = SecureSession(recipient_node.identity, is_initiator=False)

hello_msg = session_a.create_hello()
auth_msg = session_b.handle_hello(hello_msg)
fin_msg = session_a.handle_auth(auth_msg)
session_b.handle_finished(fin_msg)

enc_tunnel_a = EncryptedTunnel(tunnel=tunnel, session=session_a)
enc_tunnel_b = EncryptedTunnel(tunnel=tunnel, session=session_b)

# 4. Сквозное шифрование и отправка прикладного сообщения
ciphertext = node.send_via_tunnel(enc_tunnel_a, "Секретный пакет данных")
received_msg = enc_tunnel_b.decrypt_text_message(ciphertext)
print(f"Расшифровано на получателе: {received_msg.payload.decode('utf-8')}")

# 5. Закрытие туннеля и уничтожение сессионных ключей
node.close_tunnel(str(tunnel.tunnel_id))
session_a.close()
session_b.close()
```

### Сценарий 4. Передача файлов с проверкой `SHA-256` и докачкой (`FileTransferResume`)
Файлы разбиваются на блоки по 32 КиБ (гарантированно меньше `MAX_FRAME_PAYLOAD = 65 536` байт после AEAD), шифруются `AES-256-GCM` и собираются строго в изолированном каталоге `downloads/`:

```python
# 1. Нарезка и шифрование всех блоков файла на отправителе
encrypted_chunks = node.send_file_via_tunnel(
    encrypted_tunnel=enc_tunnel_a,
    file_path="./sample_document.bin",
)

# 2. Поочерёдная обработка входящих зашифрованных блоков на получателе
for chunk_cipher in encrypted_chunks:
    saved_file_path = recipient_node.process_incoming_file_chunk(
        encrypted_tunnel=enc_tunnel_b,
        encrypted_chunk_data=chunk_cipher,
    )
    if saved_file_path is not None:
        print(f"Файл собран и проверен по SHA-256: {saved_file_path}")
```

### Сценарий 5. Получение состояния и метрик узла (`get_network_state`)
```python
state = node.get_network_state()
print(f"Узел: {state['node_id'][:16]}...")
print(f"Контактов в k-bucket: {state['routing_contacts']}")
print(f"Записей в DHTStorage: {state['stored_records']}")
print(f"Туннелей (активных / всего): {state['tunnels_active']} / {state['tunnels_total']}")
```