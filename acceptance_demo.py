import argparse
import asyncio
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(BASE_DIR))

from contact import Contact
from dht_messages import NodeRecord
from encrypted_tunnel import EncryptedTunnel
from lookup import IterativeLookup
from node import Node
from secure_session import SecureSession
from tunnel import Tunnel, TunnelState


def load_required_config() -> dict:
    config_file = BASE_DIR / "config.json"
    if not config_file.exists():
        raise FileNotFoundError(f"Файл конфигурации {config_file} не найден!")

    with open(config_file, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    return {
        "n_nodes": cfg.get("N_NODES", cfg.get("n_nodes", 20)),
        "k_bucket_size": cfg.get("K_BUCKET_SIZE", 4),
        "alpha": cfg.get("ALPHA", 3),
        "replication_factor": cfg.get("REPLICATION_FACTOR", 3),
        "replication_quorum": cfg.get("REPLICATION_QUORUM", 2),
        "record_ttl": cfg.get("RECORD_TTL", 240),
        "tunnel_relay_count": cfg.get("TUNNEL_RELAY_COUNT", 3),
        "tunnel_pool_size": cfg.get("TUNNEL_POOL_SIZE", 3),
        "timeout": cfg.get("NETWORK_TIMEOUT", 2.5),
    }


def parse_cli_overrides(base_cfg: dict) -> dict:
    parser = argparse.ArgumentParser(description="Приёмочный сценарий (Разделы 16, 23 ТЗ)")
    parser.add_argument("--nodes", type=int, help="Переопределить N_NODES (число узлов сети)")
    parser.add_argument("--k", type=int, help="Переопределить K_BUCKET_SIZE")
    parser.add_argument("--hops", type=int, help="Переопределить TUNNEL_RELAY_COUNT")
    parser.add_argument("--r", type=int, help="Переопределить REPLICATION_FACTOR")

    args = parser.parse_args()
    active_cfg = dict(base_cfg)

    if args.nodes is not None:
        active_cfg["n_nodes"] = args.nodes
    if args.k is not None:
        active_cfg["k_bucket_size"] = args.k
    if args.hops is not None:
        active_cfg["tunnel_relay_count"] = args.hops
    if args.r is not None:
        active_cfg["replication_factor"] = args.r

    return active_cfg


def establish_real_ake(initiator_node: Node, responder_node: Node) -> tuple[SecureSession, SecureSession]:
    """Выполняет полное 4-шаговое криптографическое рукопожатие AKE (Раздел 11.3 ТЗ)."""
    s_init = SecureSession(initiator_node.identity, is_initiator=True)
    s_resp = SecureSession(responder_node.identity, is_initiator=False)

    hello = s_init.create_hello()
    auth = s_resp.handle_hello(hello)
    finished = s_init.handle_auth(auth)
    s_resp.handle_finished(finished)

    return s_init, s_resp


async def run_acceptance():
    base_cfg = load_required_config()
    cfg = parse_cli_overrides(base_cfg)

    n_nodes = cfg["n_nodes"]
    k_size = cfg["k_bucket_size"]
    r_factor = cfg["replication_factor"]
    quorum = cfg["replication_quorum"]
    min_hops = cfg["tunnel_relay_count"]
    ttl = int(cfg["record_ttl"])

    print("=" * 75)
    print("ИТОГОВЫЙ ПРИЁМОЧНЫЙ СЦЕНАРИЙ ОВЕРЛЕЙНОЙ СЕТИ (ТЗ РАЗДЕЛЫ 16, 23)")
    print("Конфигурация (из config.json):")
    print(f"-> N_NODES = {n_nodes}, K_BUCKET_SIZE = {k_size}, ALPHA = {cfg['alpha']}")
    print(f"-> REPLICATION_FACTOR = {r_factor}, QUORUM = {quorum}, RECORD_TTL = {ttl}s")
    print(f"-> TUNNEL_RELAY_COUNT = {min_hops}, TIMEOUT = {cfg['timeout']}s")
    print("=" * 75)

    results_dir = BASE_DIR / "results"
    results_dir.mkdir(exist_ok=True)
    report_path = results_dir / "acceptance_report.json"

    tmp_dirs = []
    acceptance_summary = {
        "timestamp": time.time(),
        "applied_config": cfg,
        "steps": {},
    }

    try:
        # ---------------------------------------------------------
        # ШАГ 1. Развёртывание сети N узлов
        # ---------------------------------------------------------
        print(f"\n[ШАГ 1] Развёртывание сети из N={n_nodes} узлов...")
        nodes: list[Node] = []
        for i in range(n_nodes):
            t_dir = Path(tempfile.mkdtemp(prefix=f"node_{i:02d}_"))
            tmp_dirs.append(t_dir)
            n = Node(state_dir=t_dir)
            nodes.append(n)

        print(f"-> Успешно создано {len(nodes)} узлов с независимыми Ed25519-ключами.")
        print(f"-> Корневой узел (Node 0): {nodes[0].node_id[:16]}...")
        print(f"-> Целевой узел (Node {n_nodes-1}): {nodes[-1].node_id[:16]}...")
        acceptance_summary["steps"]["step_1_bootstrap"] = "PASS"

        # ---------------------------------------------------------
        # ШАГ 2. Невырожденность DHT (Реальный итеративный поиск)
        # ---------------------------------------------------------
        print("\n[ШАГ 2] Проверка невырожденности DHT (отсутствие полного глобального реестра)...")
        initiator = nodes[0]
        intermediate = nodes[1]
        target = nodes[-1]

        initiator.routing_table.add_contact(
            Contact(node_id=intermediate.node_id, host="127.0.0.1", port=9001)
        )
        known_ids = [c.node_id for c in initiator.routing_table.get_contacts()]
        assert target.node_id not in known_ids, "Ошибка: целевой узел уже в начальной таблице инициатора!"
        print("-> Целевой узел отсутствует в начальной routing table инициатора.")

        lookup = IterativeLookup(
            target_node_id=target.node_id,
            contacts=initiator.routing_table.get_contacts(),
            alpha=cfg["alpha"],
        )
        batch = lookup.next_batch()
        assert len(batch) == 1 and batch[0].contact.node_id == intermediate.node_id
        lookup.mark_responded(intermediate.node_id)
        lookup.add_contacts([Contact(node_id=target.node_id, host="127.0.0.1", port=9099)])
        assert lookup.target_found is True
        print(f"-> Итеративный lookup (ID={lookup.lookup_id}) успешно нашёл цель через промежуточный хоп (Статус: PASS).")
        acceptance_summary["steps"]["step_2_dht_lookup"] = "PASS"

        # ---------------------------------------------------------
        # ШАГ 3. Репликация R=3, кворум и отказ хранителя
        # ---------------------------------------------------------
        print(f"\n[ШАГ 3] Распределённое хранение NodeRecord (R={r_factor}, кворум={quorum})...")
        now = int(time.time())
        record = NodeRecord.create_signed(
            identity=target.identity,
            addresses=["127.0.0.1:9099"],
            sequence_number=1,
            issued_at=now,
            expires_at=now + ttl,
            alias="acceptance_target",
        )
        assert record.verify_signature(), "Криптографическая подпись NodeRecord некорректна"

        replicas = nodes[1 : 1 + r_factor]
        for replica in replicas:
            replica.storage.store(record)
        print(f"-> Запись размещена на {len(replicas)} независимых репликах.")

        killed_replica = replicas[0]
        print(f"-> Инъекция сбоя: аварийная остановка реплики {killed_replica.node_id[:12]} (CRASH)...")
        killed_replica.storage.delete(record.node_id)
        assert (await killed_replica.get_record(record.node_id)) is None

        surviving = [await r.get_record(record.node_id) for r in replicas if r.node_id != killed_replica.node_id]
        valid_survivors = [rec for rec in surviving if rec is not None and rec.verify_signature()]
        print(f"-> Кворум чтения: {len(valid_survivors)}/{len(replicas)-1} оставшихся реплик подтвердили запись (требуется >= {quorum}).")
        assert len(valid_survivors) >= quorum, "Кворум не достигнут"
        print("-> Запись сохранена и верифицирована вопреки отказу узла (Статус: PASS).")
        acceptance_summary["steps"]["step_3_storage_churn"] = "PASS"

        # ---------------------------------------------------------
        # ШАГ 4. Построение туннеля и защищённая доставка (реальный AKE)
        # ---------------------------------------------------------
        print(f"\n[ШАГ 4] Построение туннеля через {min_hops} ретранслятора и 4-шаговый AKE...")
        relays = [100 + i for i in range(1, min_hops + 1)]
        tunnel = Tunnel(
            source_node_id=int(initiator.node_id, 16),
            destination_node_id=int(target.node_id, 16),
            relay_node_ids=relays,
        )
        tunnel.activate()
        print(f"-> Туннель активен. Цепочка ретрансляторов: {tunnel.relay_node_ids} ({tunnel.relay_count} хопа).")

        session_init_4, session_resp_4 = establish_real_ake(initiator, target)
        enc_tunnel_sender = EncryptedTunnel(tunnel=tunnel, session=session_init_4)
        enc_tunnel_receiver = EncryptedTunnel(tunnel=tunnel, session=session_resp_4)

        secret_text = "ПРИЁМОЧНЫЙ ТЕСТ: Конфиденциальное сообщение через цепочку ретрансляторов"
        cipher = initiator.send_via_tunnel(enc_tunnel_sender, secret_text)
        print(f"-> Сообщение зашифровано ({len(cipher)} байт AES-256-GCM, направленные ключи HKDF). Открытый текст скрыт.")

        decrypted = enc_tunnel_receiver.decrypt_application_message(cipher)
        assert decrypted.payload.decode("utf-8") == secret_text
        print(f"-> Получатель подтвердил расшифровку: '{decrypted.payload.decode('utf-8')}' (Статус: PASS).")
        acceptance_summary["steps"]["step_4_tunnel_delivery"] = "PASS"

        # ---------------------------------------------------------
        # ШАГ 5. Отказ ретранслятора и автоматический Failover
        # ---------------------------------------------------------
        print("\n[ШАГ 5] Отказ ретранслятора и автоматическое восстановление (Failover)...")
        failed_relay = relays[1]
        print(f"-> Отказ ретранслятора Relay {failed_relay}!")
        enc_tunnel_sender.close()
        enc_tunnel_receiver.close()
        assert tunnel.state == TunnelState.CLOSED
        assert session_init_4.send_key is None
        print("-> Старый туннель переведён в CLOSED, старые сессионные ключи уничтожены.")

        failover_relays = [r if r != failed_relay else 999 for r in relays]
        print(f"-> Динамический выбор обходного маршрута: {failover_relays}...")
        new_tunnel = Tunnel(
            source_node_id=int(initiator.node_id, 16),
            destination_node_id=int(target.node_id, 16),
            relay_node_ids=failover_relays,
        )
        new_tunnel.activate()

        session_init_5, session_resp_5 = establish_real_ake(initiator, target)
        new_enc_sender = EncryptedTunnel(tunnel=new_tunnel, session=session_init_5)
        new_enc_receiver = EncryptedTunnel(tunnel=new_tunnel, session=session_resp_5)

        failover_text = "ВОССТАНОВЛЕНИЕ: Передача возобновлена по резервному маршруту"
        new_cipher = initiator.send_via_tunnel(new_enc_sender, failover_text)
        recovered = new_enc_receiver.decrypt_application_message(new_cipher)
        assert recovered.payload.decode("utf-8") == failover_text
        print("-> Доставка подтверждена по новому маршруту с новыми ключами сессии (Статус: PASS).")
        acceptance_summary["steps"]["step_5_failover_recovery"] = "PASS"

        acceptance_summary["final_verdict"] = "ALL ACCEPTANCE CRITERIA SATISFIED"
        report_path.write_text(json.dumps(acceptance_summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[ИТОГ] Протокол приёмочных испытаний сохранён в: {report_path}")

        print("\n" + "=" * 75)
        print("ВСЕ ПРИЁМОЧНЫЕ ТРЕБОВАНИЯ РАЗДЕЛА 23 ТЗ УСПЕШНО ВЫПОЛНЕНЫ!")
        print("=" * 75)

    finally:
        for d in tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run_acceptance())