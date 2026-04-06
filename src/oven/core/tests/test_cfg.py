"""Test control flow graph functionality."""

from __future__ import annotations

import pytest
from oven.core.ast import Node
from oven.core.cfg import CFG, CFGNode


def test_cfg_basic() -> None:
    cfg = CFG()
    assert len(cfg.nodes) == 0

    node = cfg.add_node(label="start")
    assert isinstance(node, CFGNode)
    assert cfg.find_node("start") is node
    assert len(cfg.nodes) == 1


def test_cfg_node_creation() -> None:
    cfg = CFG()
    insns = [Node("get_local", [1]), Node("push_int", [42]), Node("add")]

    node = cfg.add_node(label=10, insns=insns)
    assert node.label == 10
    assert len(node.instructions) == 3
    assert node.instructions[0].type == "get_local"


def test_cfg_edge_creation() -> None:
    cfg = CFG()
    n1 = cfg.add_node("A")
    n2 = cfg.add_node("B")
    n3 = cfg.add_node("C")

    n1.add_target(n2)
    n1.add_target(n3)

    assert n2 in n1.targets
    assert n3 in n1.targets

    assert n1 in cfg.sources_for(n2)
    assert n1 in cfg.sources_for(n3)


def test_cfg_rpo_traversal() -> None:
    cfg = CFG()

    a = cfg.add_node("A")
    b = cfg.add_node("B")
    c = cfg.add_node("C")
    d = cfg.add_node("D")

    a.add_target(b)
    a.add_target(c)
    b.add_target(d)
    c.add_target(d)
    cfg.entry = a
    cfg.exit = d

    rpo = cfg.get_reverse_post_order()
    assert rpo[0] == a
    assert rpo[-1] == d
    assert set[CFGNode](rpo) == {a, b, c, d}


def test_cfg_dominance_analysis() -> None:
    cfg = CFG()
    # A -> B -> C
    #      B -> D
    a = cfg.add_node("A")
    b = cfg.add_node("B")
    c = cfg.add_node("C")
    d = cfg.add_node("D")

    a.add_target(b)
    b.add_target(c)
    b.add_target(d)
    cfg.entry = a

    doms = cfg.dominators

    assert doms[a] == {a}
    assert doms[b] == {a, b}
    assert doms[c] == {a, b, c}
    assert doms[d] == {a, b, d}


def test_cfg_merge_redundant() -> None:
    cfg = CFG()
    a = cfg.add_node("A", insns=[Node("push_int", [1])])
    b = cfg.add_node("B", insns=[Node("push_int", [2])])
    c = cfg.add_node("C", insns=[Node("return_void")])

    a.add_target(b)
    b.add_target(c)

    cfg.merge_redundant()

    assert len(cfg.nodes) < 3

    start_node = cfg.find_node("A")
    assert any(
        i.children[0] == 2 for i in start_node.instructions if i.type == "push_int"
    )


def test_cfg_unreachable_elimination() -> None:
    cfg = CFG()
    entry = cfg.add_node("entry")
    dead = cfg.add_node("dead")
    cfg.entry = entry

    cfg.eliminate_unreachable()

    with pytest.raises(KeyError):
        cfg.find_node("dead")
    assert len(cfg.nodes) == 1


def test_cfg_irreducible_flow() -> None:
    """
    Entry -> B, Entry -> C, B -> C, C -> B
    """
    cfg = CFG()
    entry = cfg.add_node("Entry")
    b = cfg.add_node("B")
    c = cfg.add_node("C")

    entry.add_target(b)
    entry.add_target(c)
    b.add_target(c)
    c.add_target(b)
    cfg.entry = entry

    doms = cfg.dominators
    assert doms[b] == {entry, b}
    assert doms[c] == {entry, c}

    loops = cfg.identify_loops()
    assert b not in loops


def test_cfg_nested_loops_shared_header() -> None:
    cfg = CFG()
    h = cfg.add_node("Header")
    b = cfg.add_node("Body")

    h.add_target(b)
    b.add_target(h)
    cfg.entry = h

    loops = cfg.identify_loops()
    assert h in loops

    assert b in loops[h]


def test_cfg_exception_implicit_edges() -> None:
    cfg = CFG()
    try_block = cfg.add_node("Try", insns=[Node("call_property", ["trace"])])
    normal_exit = cfg.add_node("NormalExit")
    handler = cfg.add_node("CatchHandler")

    try_block.add_target(normal_exit)
    try_block.exception_label = handler.label

    sources = cfg.sources_for(handler, exceptions=True)
    assert try_block in sources


def test_cfg_deep_diamond_post_dominance() -> None:
    r"""
         A
       /   \
      B     C
     / \   / \
    D   E F   G
     \ /   \ /
      H     I
       \   /
         J
    """
    cfg = CFG()
    nodes = {name: cfg.add_node(name) for name in "ABCDEFGHIJ"}

    nodes["A"].add_target(nodes["B"])
    nodes["A"].add_target(nodes["C"])

    nodes["B"].add_target(nodes["D"])
    nodes["B"].add_target(nodes["E"])

    nodes["C"].add_target(nodes["F"])
    nodes["C"].add_target(nodes["G"])

    nodes["D"].add_target(nodes["H"])
    nodes["E"].add_target(nodes["H"])

    nodes["F"].add_target(nodes["I"])
    nodes["G"].add_target(nodes["I"])

    nodes["H"].add_target(nodes["J"])
    nodes["I"].add_target(nodes["J"])
    cfg.entry = nodes["A"]
    cfg.exit = nodes["J"]

    pdoms = cfg.postdominators
    assert nodes["J"] in pdoms[nodes["A"]]
    assert nodes["J"] in pdoms[nodes["H"]]

    assert nodes["H"] not in pdoms[nodes["A"]]


def test_cfg_infinite_loop_no_exit() -> None:
    # Entry -> LoopHead <-> LoopBody

    cfg = CFG()
    entry = cfg.add_node("Entry")
    h = cfg.add_node("Head")
    b = cfg.add_node("Body")

    entry.add_target(h)
    h.add_target(b)
    b.add_target(h)
    cfg.entry = entry

    rpo = cfg.get_reverse_post_order()
    assert len(rpo) == 3

    doms = cfg.dominators
    assert doms[b] == {entry, h, b}


def build_linear_chain(n: int) -> CFG:
    cfg = CFG()
    prev_node = None
    nodes = []
    for i in range(n):
        node = cfg.add_node(label=i)
        nodes.append(node)
        if prev_node:
            prev_node.add_target(node)
        prev_node = node
    cfg.entry = nodes[0]
    cfg.exit = nodes[-1]
    return cfg


def build_worst_case_diamond(n: int) -> CFG:
    cfg = CFG()
    entry = cfg.add_node(label="entry")
    exit_node = cfg.add_node(label="exit")
    cfg.entry = entry
    cfg.exit = exit_node

    # A -> B, A -> C, B -> D, C -> D ...
    curr = entry
    for i in range(n // 2):
        left = cfg.add_node(label=f"l_{i}")
        right = cfg.add_node(label=f"r_{i}")
        merge = cfg.add_node(label=f"m_{i}")

        curr.add_target(left)
        curr.add_target(right)
        left.add_target(merge)
        right.add_target(merge)
        curr = merge

    curr.add_target(exit_node)
    return cfg


def build_deeply_nested_loops(n: int) -> CFG:
    cfg = CFG()
    nodes = [cfg.add_node(label=i) for i in range(n)]
    cfg.entry = nodes[0]
    cfg.exit = nodes[-1]

    # 0 -> 1 -> 2 ... -> N-1
    for i in range(n - 1):
        nodes[i].add_target(nodes[i + 1])

    # N-2 -> 1, N-3 -> 2 ...
    for i in range(1, n // 2):
        nodes[n - 1 - i].add_target(nodes[i])

    return cfg


@pytest.mark.parametrize("size", [100, 500, 1000])
def test_cfg_dominance_performance_scaling(size: int) -> None:
    import time

    # O(N log N)) ?
    cfg = build_worst_case_diamond(size)

    start_time = time.perf_counter()
    _ = cfg.dominators
    end_time = time.perf_counter()

    duration = end_time - start_time
    print(f"\nSize {size} Dominance: {duration:.4f}s")

    assert duration < 1.0


def test_cfg_identify_loops_stress() -> None:
    import time

    size = 2000
    cfg = build_deeply_nested_loops(size)

    start_time = time.perf_counter()
    loops = cfg.identify_loops()
    end_time = time.perf_counter()

    duration = end_time - start_time
    print(f"\nNested Loops {size}: {duration:.4f}s, found {len(loops)} headers")
    assert duration < 6.0


def test_merge_redundant_chain_performance() -> None:
    # O(N)) ?
    import time

    size = 2000
    cfg = build_linear_chain(size)

    for node in cfg.nodes:
        node.instructions = []

    start_time = time.perf_counter()
    cfg.merge_redundant()
    end_time = time.perf_counter()

    duration = end_time - start_time
    print(f"\nMerge Redundant {size}: {duration:.4f}s")

    assert len(cfg.nodes) <= 2
    assert duration < 0.3


def test_cfg_random_graph_robustness() -> None:
    import time, random

    # Irreducible Graph
    n = 300
    cfg = CFG()
    nodes = [cfg.add_node(label=i) for i in range(n)]
    cfg.entry = nodes[0]

    for i in range(n):
        targets = random.sample(nodes, random.randint(1, 2))
        for t in targets:
            nodes[i].add_target(t)

    start_time = time.perf_counter()
    _ = cfg.get_reverse_post_order()
    _ = cfg.dominators
    _ = cfg.identify_loops()
    end_time = time.perf_counter()

    print(f"\nRandom Graph {n}: {end_time - start_time:.4f}s")


def create_block(cfg: CFG, label: str | int) -> CFGNode:
    """Utility to add a node with a single dummy instruction."""
    return cfg.add_node(label=label, insns=[Node("nop")])


class TestCFGRobustness:
    def test_cfg_irreducible_flow_stability(self) -> None:
        """
        Scenario: Irreducible Control Flow (Multi-entry loop).
        Topology: Entry -> A, Entry -> B, A -> B, B -> A.
        Neither A nor B dominates each other, making this a non-natural loop.
        Ensures dominance and loop algorithms don't crash or hang.
        """
        cfg = CFG()
        entry = create_block(cfg, "entry")
        a = create_block(cfg, "A")
        b = create_block(cfg, "B")
        cfg.entry = entry

        entry.add_target(a)
        entry.add_target(b)
        a.add_target(b)
        b.add_target(a)

        # 1. RPO should still function
        rpo = cfg.get_reverse_post_order()
        assert len(rpo) == 3

        # 2. CHK Dominance should converge
        doms = cfg.dominators
        assert doms[a] == {entry, a}
        assert doms[b] == {entry, b}

        # 3. Identify loops should not identify B as a natural loop header for A
        loops = cfg.identify_loops()
        assert a not in loops and b not in loops

    def test_cfg_infinite_loop_no_exit_path(self) -> None:
        """
        Scenario: Black Hole / Infinite loop with no path to Exit.
        Topology: Entry -> LoopHeader <-> LoopBody. (No targets point to Exit).
        Ensures RPO and Post-Dominance handle graphs where Exit is unreachable.
        """
        import time

        cfg = CFG()
        entry = create_block(cfg, "entry")
        h = create_block(cfg, "header")
        b = create_block(cfg, "body")
        ext = create_block(cfg, "exit")
        cfg.entry = entry
        cfg.exit = ext  # Note: ext is physically present but logically unreachable

        entry.add_target(h)
        h.add_target(b)
        b.add_target(h)

        # RPO from entry should only find 3 nodes
        rpo = cfg.get_reverse_post_order()
        assert len(rpo) == 3
        assert ext not in rpo

        # Post-dominators from exit should return empty or limited set
        pdoms = cfg.postdominators
        assert h not in pdoms or pdoms[h] == {h}

    def test_cfg_control_flow_flattening_stress(self) -> None:
        """
        Scenario: Control Flow Flattening (Mega Dispatcher).
        Topology: Dispatcher -> {N Branch Blocks} -> Dispatcher.
        Commonly used in obfuscated ActionScript.
        Tests the 'Fan-out' performance of the Dominance algorithm.
        """
        import time

        N = 500
        cfg = CFG()
        dispatcher = create_block(cfg, "dispatcher")
        cfg.entry = dispatcher

        blocks = []
        for i in range(N):
            blk = create_block(cfg, i)
            dispatcher.add_target(blk)
            blk.add_target(dispatcher)
            blocks.append(blk)

        start = time.perf_counter()
        doms = cfg.dominators
        end = time.perf_counter()

        # In flattening, every block is dominated only by Entry/Dispatcher and itself
        assert len(doms[blocks[0]]) == 2
        print(f"\nFlattening ({N} blocks) Dominance Time: {end - start:.4f}s")
        assert (end - start) < 0.5

    def test_cfg_deeply_nested_stack_stability(self) -> None:
        """
        Scenario: Deeply Nested Linear Chain.
        Topology: 0 -> 1 -> 2 -> ... -> 10000.
        Ensures algorithms (RPO, Unreachable, SourceMaps) use explicit stacks
        instead of recursion to avoid RecursionError.
        """
        import time

        N = 10000
        cfg = CFG()
        nodes = [create_block(cfg, i) for i in range(N)]
        cfg.entry = nodes[0]

        for i in range(N - 1):
            nodes[i].add_target(nodes[i + 1])

        # Test RPO (Forward)
        start = time.process_time()
        rpo = cfg.get_reverse_post_order()
        assert len(rpo) == N

        # Test Source Map generation
        _ = cfg.sources_for(nodes[-1])

        # Test Dominators
        _ = cfg.dominators
        end = time.process_time()

        print(f"\nDeep Chain ({N} nodes) Processing Time: {end - start:.4f}s")
        assert (end - start) < 5

    def test_cfg_exception_label_fragmentation(self) -> None:
        """
        Scenario: Malicious Exception ranges.
        Topology: N nodes, each having a DIFFERENT exception handler node.
        This prevents 'merge_redundant' and stresses the source map cache.
        """
        import time

        N = 1000
        cfg = CFG()
        entry = create_block(cfg, "entry")
        cfg.entry = entry

        current = entry
        for i in range(N):
            handler = create_block(cfg, f"handler_{i}")
            nxt = create_block(cfg, f"code_{i}")

            current.add_target(nxt)
            current.exception_label = handler.label
            current = nxt

        # merge_redundant should be able to do nothing but finish quickly
        start = time.perf_counter()
        cfg.merge_redundant()
        end = time.perf_counter()

        print(f"\nFragmented Exceptions ({N} handlers) Merge Time: {end - start:.4f}s")
        assert (end - start) < 0.5

    # --- Performance Trend Analysis ---

    @pytest.mark.parametrize("scale", [1, 2, 4])
    def test_cfg_performance_scaling_trend(self, scale: int) -> None:
        """
        Analyzes performance trend of CHK Dominance.
        CHK should be near-linear in most cases. O(N log N) or better.
        """
        import time, random

        base_n = 250
        N = base_n * scale
        cfg = CFG()
        entry = create_block(cfg, "entry")
        cfg.entry = entry

        # Create a complex "Spider Web" graph
        nodes = [create_block(cfg, i) for i in range(N)]
        entry.add_target(nodes[0])
        for i in range(N):
            # Jump to next and a random previous/future node
            nodes[i].add_target(nodes[(i + 1) % N])
            nodes[i].add_target(nodes[random.randint(0, N - 1)])

        start = time.perf_counter()
        _ = cfg.dominators
        duration = time.perf_counter() - start

        print(f"\nScale {N} nodes: {duration:.4f}s")
        # No strict assertion on O(x) here, but ensures no exponential explosion
        assert duration < 2.0
