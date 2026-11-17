from contact import Contact
from config import K_BUCKET_SIZE


class KBucket:
    def __init__(self, size: int = K_BUCKET_SIZE):
        self.size = size
        self.contacts: list[Contact] = []

    def add(self, contact: Contact):
        """
        Добавляет контакт без сетевой проверки.

        Если bucket заполнен, возвращает старый контакт,
        которого необходимо проверить через PING.
        """

        # Контакт уже существует.
        for existing in self.contacts:
            if existing.node_id == contact.node_id:
                self.contacts.remove(existing)
                self.contacts.append(contact)

                return None

        # Есть свободное место.
        if len(self.contacts) < self.size:
            self.contacts.append(contact)

            return None

        # Bucket заполнен.
        # Возвращаем самого старого контакта.
        return self.contacts[0]

    def remove(self, node_id: str):
        self.contacts = [
            contact
            for contact in self.contacts
            if contact.node_id != node_id
        ]

    def replace(
        self,
        old_node_id: str,
        new_contact: Contact,
    ):
        """
        Заменяет конкретный старый контакт новым.
        """

        for index, contact in enumerate(self.contacts):

            if contact.node_id == old_node_id:
                self.contacts[index] = new_contact
                return

        # Старого контакта уже нет — просто добавляем.
        if len(self.contacts) < self.size:
            self.contacts.append(new_contact)

    def __len__(self):
        return len(self.contacts)

    def get_contacts(self) -> list[Contact]:
        return list(self.contacts)