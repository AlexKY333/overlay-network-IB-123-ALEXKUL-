import sys
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

import pytest

from bootstrap_topology import BootstrapTopology


NODES = [1, 2, 3, 4, 5, 6, 7, 8]


def test_star_bootstrap():
    topology = BootstrapTopology(NODES)

    edges = topology.build("star")

    assert len(edges) == 7

    assert all(
        edge.target == 1
        for edge in edges
    )

    assert {
        edge.source
        for edge in edges
    } == {
        2, 3, 4, 5, 6, 7, 8
    }


def test_ring_bootstrap():
    topology = BootstrapTopology(NODES)

    edges = topology.build("ring")

    assert len(edges) == 8

    pairs = {
        (edge.source, edge.target)
        for edge in edges
    }

    assert (1, 2) in pairs
    assert (2, 3) in pairs
    assert (3, 4) in pairs
    assert (4, 5) in pairs
    assert (5, 6) in pairs
    assert (6, 7) in pairs
    assert (7, 8) in pairs
    assert (8, 1) in pairs


def test_tree_bootstrap():
    topology = BootstrapTopology(NODES)

    edges = topology.build("tree")

    assert len(edges) == 7

    pairs = {
        (edge.source, edge.target)
        for edge in edges
    }

    assert (2, 1) in pairs
    assert (3, 1) in pairs
    assert (4, 2) in pairs
    assert (5, 2) in pairs
    assert (6, 3) in pairs
    assert (7, 3) in pairs
    assert (8, 4) in pairs


def test_multi_seed_bootstrap():
    topology = BootstrapTopology(NODES)

    edges = topology.build(
        "multi_seed",
        seeds=[1, 5],
    )

    assert len(edges) == 6

    pairs = {
        (edge.source, edge.target)
        for edge in edges
    }

    assert (2, 1) in pairs
    assert (3, 5) in pairs
    assert (4, 1) in pairs
    assert (6, 5) in pairs
    assert (7, 1) in pairs
    assert (8, 5) in pairs


def test_multi_seed_requires_seeds():
    topology = BootstrapTopology(NODES)

    with pytest.raises(ValueError):
        topology.build("multi_seed")


def test_multi_seed_rejects_unknown_seed():
    topology = BootstrapTopology(NODES)

    with pytest.raises(ValueError):
        topology.build(
            "multi_seed",
            seeds=[1, 99],
        )


def test_multi_seed_rejects_duplicate_seeds():
    topology = BootstrapTopology(NODES)

    with pytest.raises(ValueError):
        topology.build(
            "multi_seed",
            seeds=[1, 1],
        )


def test_duplicate_nodes_are_rejected():
    with pytest.raises(ValueError):
        BootstrapTopology(
            [1, 2, 2, 3]
        )


def test_too_few_nodes_are_rejected():
    with pytest.raises(ValueError):
        BootstrapTopology([1])


def test_unknown_scheme_is_rejected():
    topology = BootstrapTopology(NODES)

    with pytest.raises(ValueError):
        topology.build("unknown")


def test_no_self_edges():
    topology = BootstrapTopology(NODES)

    for scheme in (
        "star",
        "ring",
        "tree",
    ):
        edges = topology.build(scheme)

        assert all(
            edge.source != edge.target
            for edge in edges
        )


def test_multi_seed_has_no_self_edges():
    topology = BootstrapTopology(NODES)

    edges = topology.build(
        "multi_seed",
        seeds=[1, 5],
    )

    assert all(
        edge.source != edge.target
        for edge in edges
    )