from pathlib import Path
import sys
import tempfile

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from identity import Identity


def test_identity_nodes():
    with tempfile.TemporaryDirectory() as temp_dir:

        base_dir = Path(temp_dir)

        # -----------------------------------
        # Создаём два независимых узла
        # -----------------------------------

        node_a = Identity(
            base_dir / "node_a"
        )

        node_b = Identity(
            base_dir / "node_b"
        )

        print("Node A:")
        print("NodeID:", node_a.node_id)

        print("\nNode B:")
        print("NodeID:", node_b.node_id)

        # -----------------------------------
        # 1. NodeID должны различаться
        # -----------------------------------

        assert node_a.node_id != node_b.node_id

        print("\nNodeID A != NodeID B: PASS")

        # -----------------------------------
        # 2. Проверяем Node A
        # -----------------------------------

        public_key_a = (
            node_a.public_key.public_bytes_raw()
        )

        result = node_a.verify_node_id(
            public_key_a,
            node_a.node_id,
        )

        assert result is True

        print("Проверка Node A: PASS")

        # -----------------------------------
        # 3. Проверяем Node B
        # -----------------------------------

        public_key_b = (
            node_b.public_key.public_bytes_raw()
        )

        result = node_b.verify_node_id(
            public_key_b,
            node_b.node_id,
        )

        assert result is True

        print("Проверка Node B: PASS")

        # -----------------------------------
        # 4. Подмена NodeID A
        # -----------------------------------

        result = node_a.verify_node_id(
            public_key_a,
            node_b.node_id,
        )

        assert result is False

        print("Подмена NodeID A: PASS")

        # -----------------------------------
        # 5. Подмена public key
        # -----------------------------------

        result = node_a.verify_node_id(
            public_key_b,
            node_a.node_id,
        )

        assert result is False

        print("Подмена public key: PASS")

    print("\nIDENTITY NODES TEST PASSED")


if __name__ == "__main__":
    test_identity_nodes()