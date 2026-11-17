from pathlib import Path
import sys
import asyncio

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from contact import Contact
from lookup import IterativeLookup


def make_node_id(value: int) -> str:
    return f"{value:064x}"


def test_alpha_limits_parallel_queries():

    target_node_id = make_node_id(100)

    contacts = [
        Contact(
            node_id=make_node_id(index),
            host="127.0.0.1",
            port=10000 + index,
        )
        for index in range(1, 8)
    ]

    lookup = IterativeLookup(
        target_node_id=target_node_id,
        contacts=contacts,
        alpha=3,
    )

    assert lookup.alpha == 3

    batch = lookup.next_batch()

    assert len(batch) == 3

    assert all(
        candidate.queried
        for candidate in batch
    )

    second_batch = lookup.next_batch()

    assert len(second_batch) == 3

    assert all(
        candidate.queried
        for candidate in second_batch
    )

    third_batch = lookup.next_batch()

    assert len(third_batch) == 1

    assert third_batch[0].queried

    fourth_batch = lookup.next_batch()

    assert fourth_batch == []


def test_alpha_never_exceeds_three():

    async def fake_query(contact):

        await asyncio.sleep(0.01)

        return []

    async def run():

        contacts = [
            Contact(
                node_id=make_node_id(index),
                host="127.0.0.1",
                port=10000 + index,
            )
            for index in range(1, 10)
        ]

        lookup = IterativeLookup(
            target_node_id=make_node_id(100),
            contacts=contacts,
            alpha=3,
        )

        active = 0
        maximum_active = 0

        while True:

            batch = lookup.next_batch()

            if not batch:
                break

            async def tracked_query(
                candidate
            ):
                nonlocal active
                nonlocal maximum_active

                active += 1

                maximum_active = max(
                    maximum_active,
                    active,
                )

                try:
                    return await fake_query(
                        candidate.contact
                    )
                finally:
                    active -= 1

            results = await asyncio.gather(
                *[
                    tracked_query(candidate)
                    for candidate in batch
                ]
            )

            for candidate, result in zip(
                batch,
                results,
            ):
                lookup.mark_responded(
                    candidate.contact.node_id
                )

                lookup.add_contacts(
                    result
                )

        assert maximum_active <= 3

    asyncio.run(run())