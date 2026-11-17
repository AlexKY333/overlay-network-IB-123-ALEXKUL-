from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class BootstrapEdge:
    """
    Начальная bootstrap-связь между двумя узлами.

    source -> target означает:
    source использует target как bootstrap-узел.
    """

    source: int
    target: int

    def __post_init__(self) -> None:
        if self.source == self.target:
            raise ValueError(
                "Bootstrap edge cannot connect node to itself"
            )


class BootstrapTopology:
    """
    Построение начальной bootstrap-топологии.

    Поддерживаемые схемы:
        - star
        - ring
        - tree
        - multi_seed

    Этот класс НЕ выполняет TCP и FIND_NODE.
    Он только определяет, к каким bootstrap-узлам
    должны обращаться узлы на начальном этапе.
    """

    SUPPORTED_SCHEMES = {
        "star",
        "ring",
        "tree",
        "multi_seed",
    }

    def __init__(
        self,
        nodes: Iterable[int],
    ):
        self.nodes = list(nodes)

        if len(self.nodes) < 2:
            raise ValueError(
                "At least two nodes are required"
            )

        if len(set(self.nodes)) != len(self.nodes):
            raise ValueError(
                "Node IDs must be unique"
            )

    def build(
        self,
        scheme: str,
        seeds: Iterable[int] | None = None,
    ) -> list[BootstrapEdge]:

        if scheme not in self.SUPPORTED_SCHEMES:
            raise ValueError(
                f"Unsupported bootstrap scheme: {scheme}"
            )

        if scheme == "star":
            return self._build_star()

        if scheme == "ring":
            return self._build_ring()

        if scheme == "tree":
            return self._build_tree()

        return self._build_multi_seed(
            seeds
        )

    def _build_star(self) -> list[BootstrapEdge]:
        """
        Star:

              seed
             / | \
            /  |  \
           N2 N3 N4

        Первый узел является bootstrap seed.
        """

        seed = self.nodes[0]

        return [
            BootstrapEdge(
                source=node,
                target=seed,
            )
            for node in self.nodes
            if node != seed
        ]

    def _build_ring(self) -> list[BootstrapEdge]:
        """
        Ring:

        N1 -> N2 -> N3 -> ... -> N1
        """

        edges: list[BootstrapEdge] = []

        for index, node in enumerate(self.nodes):
            target = self.nodes[
                (index + 1) % len(self.nodes)
            ]

            edges.append(
                BootstrapEdge(
                    source=node,
                    target=target,
                )
            )

        return edges

    def _build_tree(self) -> list[BootstrapEdge]:
        """
        Бинарное дерево.

        Для узла с индексом i:
            parent = (i - 1) // 2
        """

        edges: list[BootstrapEdge] = []

        for index in range(1, len(self.nodes)):
            parent_index = (index - 1) // 2

            edges.append(
                BootstrapEdge(
                    source=self.nodes[index],
                    target=self.nodes[parent_index],
                )
            )

        return edges

    def _build_multi_seed(
        self,
        seeds: Iterable[int] | None,
    ) -> list[BootstrapEdge]:
        """
        Multi-seed:

        Несколько независимых bootstrap seed.

        Обычные узлы распределяются между seed.
        """

        if seeds is None:
            raise ValueError(
                "seeds are required for multi_seed"
            )

        seeds = list(seeds)

        if not seeds:
            raise ValueError(
                "At least one seed is required"
            )

        if len(set(seeds)) != len(seeds):
            raise ValueError(
                "Seed IDs must be unique"
            )

        unknown_seeds = [
            seed
            for seed in seeds
            if seed not in self.nodes
        ]

        if unknown_seeds:
            raise ValueError(
                f"Unknown seed nodes: {unknown_seeds}"
            )

        edges: list[BootstrapEdge] = []

        ordinary_nodes = [
            node
            for node in self.nodes
            if node not in seeds
        ]

        for index, node in enumerate(
            ordinary_nodes
        ):
            seed = seeds[
                index % len(seeds)
            ]

            edges.append(
                BootstrapEdge(
                    source=node,
                    target=seed,
                )
            )

        return edges