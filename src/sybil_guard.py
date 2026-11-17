from collections import Counter
from ipaddress import ip_address


class SybilEclipseGuard:
    """
    Базовая контрмера против Sybil/Eclipse:

    1. Ограничивает количество контактов с одного IP.
    2. Ограничивает количество контактов из одной подсети.
    3. Не позволяет повторно принимать один и тот же NodeID.
    4. Позволяет использовать разные лимиты для IPv4 и IPv6.

    Это не абсолютная защита от Sybil-атаки.
    Механизм ограничивает влияние большого количества
    идентичностей, находящихся в одном underlay-сегменте.
    """

    def __init__(
        self,
        max_contacts_per_host: int = 1,
        max_contacts_per_subnet: int = 2,
    ):
        if max_contacts_per_host <= 0:
            raise ValueError(
                "max_contacts_per_host must be greater than 0"
            )

        if max_contacts_per_subnet <= 0:
            raise ValueError(
                "max_contacts_per_subnet must be greater than 0"
            )

        self.max_contacts_per_host = (
            max_contacts_per_host
        )

        self.max_contacts_per_subnet = (
            max_contacts_per_subnet
        )

    @staticmethod
    def _parse_ip(host: str):
        try:
            return ip_address(host)
        except ValueError:
            return None

    @staticmethod
    def _subnet_key(host: str) -> str | None:
        ip = SybilEclipseGuard._parse_ip(host)

        if ip is None:
            return None

        if ip.version == 4:
            network = (
                ipaddress_network_v4(host)
            )
        else:
            network = (
                ipaddress_network_v6(host)
            )

        return str(network)

    def check_contact(
        self,
        contact,
        existing_contacts,
    ) -> tuple[bool, str]:
        """
        Проверяет, можно ли добавить контакт.

        Возвращает:

            (True, "accepted")

        либо:

            (False, причина)
        """

        existing_ids = {
            existing.node_id
            for existing in existing_contacts
        }

        if contact.node_id in existing_ids:
            return (
                False,
                "duplicate_node_id",
            )

        ip = self._parse_ip(
            contact.host
        )

        # Если host не является IP-адресом,
        # diversity-контроль применить невозможно.
        # Сам по себе такой контакт не блокируется.
        if ip is None:
            return (
                True,
                "accepted_non_ip_host",
            )

        same_host = sum(
            1
            for existing in existing_contacts
            if existing.host == contact.host
        )

        if (
            same_host
            >= self.max_contacts_per_host
        ):
            return (
                False,
                "host_limit_exceeded",
            )

        subnet = self._subnet_key(
            contact.host
        )

        if subnet is not None:

            same_subnet = 0

            for existing in existing_contacts:

                existing_subnet = (
                    self._subnet_key(
                        existing.host
                    )
                )

                if existing_subnet == subnet:
                    same_subnet += 1

            if (
                same_subnet
                >= self.max_contacts_per_subnet
            ):
                return (
                    False,
                    "subnet_limit_exceeded",
                )

        return (
            True,
            "accepted",
        )


def ipaddress_network_v4(host: str):
    import ipaddress

    ip = ipaddress.ip_address(host)

    return ipaddress.ip_network(
        f"{ip}/24",
        strict=False,
    )


def ipaddress_network_v6(host: str):
    import ipaddress

    ip = ipaddress.ip_address(host)

    return ipaddress.ip_network(
        f"{ip}/64",
        strict=False,
    )