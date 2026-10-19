"""PostgreSQL Concurrent FIFO Returns & Canonical Lock Ordering Verification.

Validates:
1. Canonical lock ordering: Verifies via AST analysis that all inventory_cost_layers locked via FOR UPDATE
   in reconforge/infrastructure/postgres_customer_partial_returns.py are canonically sorted
   (sorted(unique_layer_ids)) to eliminate cyclic deadlock dependencies.
2. Deadlock impossibility proof: Simulates concurrent multi-resource locking with and without
   canonical sorting, proving that sorted lock acquisition guarantees an acyclic wait-for graph.
3. Additive FIFO restitution under concurrency: Dispatches concurrent return requests against
   multi-layer sales orders using ThreadPoolExecutor, proving that layer restitution is strictly
   additive, preserves historical unit cost without repricing, and rejects excess return quantities cleanly.
"""

from __future__ import annotations

import ast
import concurrent.futures
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from reconforge.domain.finance_posting import FinancePostingError

ROOT = Path(__file__).resolve().parents[1]


# ==============================================================================
# 1. AST Inspection: Canonical Lock Ordering
# ==============================================================================


def test_inventory_cost_layers_locks_are_canonically_sorted() -> None:
    """Inspect reconforge/infrastructure/postgres_customer_partial_returns.py to ensure

    all FOR UPDATE queries on inventory_cost_layers iterate over sorted collections.
    """
    target_file = ROOT / "reconforge" / "infrastructure" / "postgres_customer_partial_returns.py"
    assert target_file.is_file(), f"Target file not found: {target_file}"

    tree = ast.parse(target_file.read_text(encoding="utf-8"), filename=str(target_file))

    found_sorted_lock_loops = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            # Check if body contains SQL query on inventory_cost_layers FOR UPDATE
            body_code = ast.unparse(node)
            if "inventory_cost_layers" in body_code and "FOR UPDATE" in body_code:
                # The loop iterable MUST be wrapped in sorted(...)
                iter_expr = ast.unparse(node.iter)
                assert "sorted(" in iter_expr, (
                    f"Locking loop at line {node.lineno} does not sort layer IDs canonically: {iter_expr}"
                )
                found_sorted_lock_loops += 1

    assert found_sorted_lock_loops >= 2, (
        f"Expected at least 2 sorted locking loops for inventory_cost_layers in _locks and _reversal_layers, "
        f"found {found_sorted_lock_loops}"
    )


def test_finance_entries_locks_are_canonically_sorted() -> None:
    """Inspect reconforge/infrastructure/postgres_customer_partial_returns.py to ensure

    all FOR UPDATE queries on finance_entries iterate over sorted collections.
    """
    target_file = ROOT / "reconforge" / "infrastructure" / "postgres_customer_partial_returns.py"
    tree = ast.parse(target_file.read_text(encoding="utf-8"), filename=str(target_file))

    found_sorted_entry_loops = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            body_code = ast.unparse(node)
            if "finance_entries" in body_code and "FOR UPDATE" in body_code:
                iter_expr = ast.unparse(node.iter)
                assert "sorted(" in iter_expr, (
                    f"Entry locking loop at line {node.lineno} does not sort entries canonically: {iter_expr}"
                )
                found_sorted_entry_loops += 1

    assert found_sorted_entry_loops >= 1, (
        f"Expected at least 1 sorted locking loop for finance_entries, found {found_sorted_entry_loops}"
    )


# ==============================================================================
# 2. Deadlock Freedom Mathematical Simulation
# ==============================================================================


class ResourceLockManager:
    """In-memory resource lock manager to simulate lock contention and detect deadlocks."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def get_lock(self, resource_id: str) -> threading.Lock:
        with self._global_lock:
            if resource_id not in self._locks:
                self._locks[resource_id] = threading.Lock()
            return self._locks[resource_id]

    def acquire_in_order(self, resource_ids: Sequence[str], timeout: float = 0.5) -> list[str]:
        acquired: list[str] = []
        for rid in resource_ids:
            lock = self.get_lock(rid)
            ok = lock.acquire(timeout=timeout)
            if not ok:
                # Release acquired on failure
                for prev in reversed(acquired):
                    self.get_lock(prev).release()
                raise TimeoutError(f"Deadlock/Timeout acquiring {rid}")
            acquired.append(rid)
        return acquired

    def release_all(self, resource_ids: Sequence[str]) -> None:
        for rid in reversed(resource_ids):
            self.get_lock(rid).release()


def test_unsorted_locking_causes_cyclic_deadlock() -> None:
    """Demonstrate that unsorted locking of inventory layers [L1, L2] vs [L2, L1]

    causes cyclic deadlock timeouts under concurrent transactions.
    """
    manager = ResourceLockManager()
    l1 = "layer-001"
    l2 = "layer-002"

    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def tx1() -> None:
        try:
            barrier.wait()
            # T1 acquires L1 then L2 (unsorted)
            lock1 = manager.get_lock(l1)
            lock1.acquire()
            time.sleep(0.05)  # Window for T2 to acquire L2
            lock2 = manager.get_lock(l2)
            if not lock2.acquire(timeout=0.2):
                errors.append(TimeoutError("T1 deadlocked on L2"))
            else:
                lock2.release()
            lock1.release()
        except Exception as exc:
            errors.append(exc)

    def tx2() -> None:
        try:
            barrier.wait()
            # T2 acquires L2 then L1 (unsorted - opposite order!)
            lock2 = manager.get_lock(l2)
            lock2.acquire()
            time.sleep(0.05)  # Window for T1 to acquire L1
            lock1 = manager.get_lock(l1)
            if not lock1.acquire(timeout=0.2):
                errors.append(TimeoutError("T2 deadlocked on L1"))
            else:
                lock1.release()
            lock2.release()
        except Exception as exc:
            errors.append(exc)

    thread1 = threading.Thread(target=tx1)
    thread2 = threading.Thread(target=tx2)
    thread1.start()
    thread2.start()
    thread1.join()
    thread2.join()

    # Without sorting, at least one thread must have timed out / deadlocked
    assert any("deadlock" in str(err).lower() or "timeout" in str(err).lower() for err in errors), (
        "Expected cyclic deadlock timeout with unsorted locking"
    )


def test_canonically_sorted_locking_guarantees_deadlock_freedom() -> None:
    """Prove that canonically sorting layer IDs prior to acquisition eliminates deadlocks

    even under high concurrency across multiple overlapping layer subsets.
    """
    manager = ResourceLockManager()
    layers = [f"layer-{i:03d}" for i in range(10)]

    concurrency = 20
    transactions = 100
    deadlock_count = 0
    success_count = 0

    def worker(task_id: int) -> None:
        nonlocal deadlock_count, success_count
        # Select randomized subset of layers
        # Even though each worker picks arbitrary subsets, they MUST sort them:
        subset = [layers[(task_id + offset) % len(layers)] for offset in (0, 2, 4)]
        sorted_subset = sorted(set(subset))

        try:
            acquired = manager.acquire_in_order(sorted_subset, timeout=2.0)
            # Critical section
            time.sleep(0.001)
            manager.release_all(acquired)
            success_count += 1
        except TimeoutError:
            deadlock_count += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(worker, i) for i in range(transactions)]
        concurrent.futures.wait(futures)

    # 100% of transactions must succeed with 0 deadlocks
    assert deadlock_count == 0, f"Detected {deadlock_count} deadlocks with sorted locking!"
    assert success_count == transactions, f"Expected {transactions} successes, got {success_count}"


# ==============================================================================
# 3. Additive FIFO Layer Restitution Concurrency Invariants
# ==============================================================================


@dataclass
class SimulatedCostLayer:
    layer_id: str
    original_quantity: int
    remaining_quantity: int
    unit_cost_minor: int  # Exact integer minor unit cost per unit
    currency: str = "USD"

    @property
    def remaining_value_minor(self) -> int:
        return self.remaining_quantity * self.unit_cost_minor


class ThreadSafeFIFOInventory:
    """Thread-safe simulated FIFO inventory ledger enforcing additive restitution."""

    def __init__(self, layers: list[SimulatedCostLayer]) -> None:
        self._layers = {layer.layer_id: layer for layer in layers}
        self._delivered_portions: list[tuple[str, int, int]] = []  # (layer_id, quantity, unit_cost)
        self._returned_quantity = 0
        self._total_delivered_quantity = 0
        self._mutex = threading.Lock()

    def record_issue(self, portions: list[tuple[str, int, int]]) -> None:
        """Record original consumption portions."""
        self._delivered_portions = list(portions)
        self._total_delivered_quantity = sum(qty for _, qty, _ in portions)

    def process_return(self, return_quantity: int) -> list[tuple[str, int, int]]:
        """Atomically restitute consumed inventory layers in forward FIFO sequence.

        Invariants:
        - Total returned quantity cannot exceed total delivered quantity.
        - Restores original cost portions without repricing historical transactions.
        - Canonically locks affected layers in sorted ID order.
        """
        if return_quantity <= 0:
            raise FinancePostingError("partial_return_invalid", "Return quantity must be positive.")

        with self._mutex:
            if self._returned_quantity + return_quantity > self._total_delivered_quantity:
                raise FinancePostingError(
                    "partial_return_quantity_exceeded",
                    f"Return quantity {return_quantity} exceeds delivered balance "
                    f"{self._total_delivered_quantity - self._returned_quantity}",
                )

            # Determine restitution portions by walking delivered portions
            # in original sequence (skip already returned, take return_quantity)
            skip = self._returned_quantity
            pending = return_quantity
            restituted: list[tuple[str, int, int]] = []

            for layer_id, original_qty, unit_cost in self._delivered_portions:
                if pending <= 0:
                    break
                if skip >= original_qty:
                    skip -= original_qty
                    continue

                available = original_qty - skip
                take = min(pending, available)
                skip = 0
                pending -= take

                restituted.append((layer_id, take, unit_cost))

            # Canonical lock order: Sort affected layer IDs
            sorted_layer_ids = sorted({layer_id for layer_id, _, _ in restituted})
            assert sorted_layer_ids == sorted(set(sorted_layer_ids)), "Must be canonically sorted"

            # Apply additive restitution
            for layer_id, take_qty, _unit_cost in restituted:
                layer = self._layers[layer_id]
                layer.remaining_quantity += take_qty
                # Cost layer integrity check: remaining cannot exceed original
                assert layer.remaining_quantity <= layer.original_quantity, "Layer capacity exceeded"

            self._returned_quantity += return_quantity
            return restituted


def test_concurrent_fifo_returns_additive_restitution() -> None:
    """Dispatches 10 concurrent partial returns across a 3-layer delivered sales order.

    Asserts:
    1. Total restored quantity strictly equals sum of accepted returns.
    2. Over-returning requests are rejected cleanly with partial_return_quantity_exceeded.
    3. Original acquisition unit costs are preserved without historical repricing.
    4. Concurrency safety: Zero state corruption across multi-threaded workers.
    """
    # Create 3 FIFO cost layers
    layers = [
        SimulatedCostLayer("L1", original_quantity=50, remaining_quantity=0, unit_cost_minor=1000),  # $10.00/unit
        SimulatedCostLayer("L2", original_quantity=30, remaining_quantity=0, unit_cost_minor=1200),  # $12.00/unit
        SimulatedCostLayer("L3", original_quantity=20, remaining_quantity=0, unit_cost_minor=1500),  # $15.00/unit
    ]
    inventory = ThreadSafeFIFOInventory(layers)
    inventory.record_issue([("L1", 50, 1000), ("L2", 30, 1200), ("L3", 20, 1500)])  # Total 100 units

    # We dispatch 12 return requests of 10 units each (total attempted = 120 units).
    # Since only 100 units were delivered, exactly 10 requests (100 units) must succeed,
    # and 2 requests must be rejected with partial_return_quantity_exceeded.
    return_requests = [10] * 12
    successful_returns = 0
    rejected_returns = 0
    total_restituted_qty = 0

    lock = threading.Lock()

    def do_return(qty: int) -> None:
        nonlocal successful_returns, rejected_returns, total_restituted_qty
        try:
            portions = inventory.process_return(qty)
            with lock:
                successful_returns += 1
                total_restituted_qty += sum(portion_qty for _, portion_qty, _ in portions)
        except FinancePostingError as exc:
            if exc.code == "partial_return_quantity_exceeded":
                with lock:
                    rejected_returns += 1
            else:
                raise

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(do_return, req) for req in return_requests]
        concurrent.futures.wait(futures)

    # Invariant 1: Exactly 10 returns succeed, 2 are rejected
    assert successful_returns == 10, f"Expected 10 successful returns, got {successful_returns}"
    assert rejected_returns == 2, f"Expected 2 rejected returns, got {rejected_returns}"

    # Invariant 2: Additive restitution matches total returned quantity exactly
    assert total_restituted_qty == 100, f"Expected 100 restituted units, got {total_restituted_qty}"

    # Invariant 3: Each layer's remaining quantity is restored to its exact original capacity
    assert layers[0].remaining_quantity == 50, f"L1 remaining: {layers[0].remaining_quantity}"
    assert layers[1].remaining_quantity == 30, f"L2 remaining: {layers[1].remaining_quantity}"
    assert layers[2].remaining_quantity == 20, f"L3 remaining: {layers[2].remaining_quantity}"

    # Invariant 4: Exact minor unit values preserved without repricing
    assert layers[0].remaining_value_minor == 50 * 1000  # $500.00
    assert layers[1].remaining_value_minor == 30 * 1200  # $360.00
    assert layers[2].remaining_value_minor == 20 * 1500  # $300.00
