from pathlib import Path
import sys
import tempfile

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from identity import Identity


def test_identity():
    # -----------------------------------
    # 1. Создаём временный каталог состояния
    # -----------------------------------

    with tempfile.TemporaryDirectory() as temp_dir:

        state_dir = Path(temp_dir)

        # -----------------------------------
        # 2. Первый запуск Identity
        # -----------------------------------

        identity1 = Identity(state_dir)

        print("Первый запуск:")
        print("NodeID:", identity1.node_id)
        print(
            "Файл ключа существует:",
            identity1.key_file.exists()
        )

        assert identity1.key_file.exists()
        assert len(identity1.node_id) == 64

        # Сохраняем данные для сравнения
        node_id_1 = identity1.node_id
        public_key_1 = identity1.public_key.public_bytes_raw()

        # -----------------------------------
        # 3. Второй запуск Identity
        # -----------------------------------

        identity2 = Identity(state_dir)

        print("\nВторой запуск:")
        print("NodeID:", identity2.node_id)

        node_id_2 = identity2.node_id
        public_key_2 = identity2.public_key.public_bytes_raw()

        # -----------------------------------
        # 4. Проверяем постоянство ключа
        # -----------------------------------

        assert public_key_1 == public_key_2

        print("Открытый ключ совпадает: YES")

        # -----------------------------------
        # 5. Проверяем постоянство NodeID
        # -----------------------------------

        assert node_id_1 == node_id_2

        print("NodeID совпадает: YES")

        # -----------------------------------
        # 6. Проверяем вычисление NodeID
        # -----------------------------------

        expected_node_id = identity1._calculate_node_id()

        assert identity1.node_id == expected_node_id

        print("NodeID вычисляется детерминированно: YES")

        # -----------------------------------
        # 7. Проверяем проверку чужого NodeID
        # -----------------------------------

        result = identity1.verify_node_id(
            public_key_1,
            node_id_1,
        )

        assert result is True

        print("Проверка правильного NodeID: PASS")

        result = identity1.verify_node_id(
            public_key_1,
            "0" * 64,
        )

        assert result is False

        print("Проверка неправильного NodeID: PASS")

    print("\nIDENTITY TEST PASSED")


if __name__ == "__main__":
    test_identity()