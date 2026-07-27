"""Optional DuckDB reconciliation backend."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from reconforge.config import ReconForgeConfig
from reconforge.engines.base import EngineResult
from reconforge.engines.signature import (
    CURRENT_RECONCILIATION_SIGNATURE_VERSION,
    build_reconciliation_signature,
)
from reconforge.io.ingress import validate_tabular_input
from reconforge.io.readers import coerce_dataset_types, find_dataset_file, read_table
from reconforge.reconciliation.matching import SOURCE_POSITION_COLUMN
from reconforge.reconciliation.stock_gl import StockGLReconciliationResult, reconcile_stock_gl
from reconforge.schemas import REQUIRED_COLUMNS, DatasetName
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY


class DuckDBEngine:
    """DuckDB-backed local export reader with relation-aware reconciliation.

    CSV/XLSX inputs are loaded into DuckDB relations, where large workloads are
    partitioned by normalized work order keys before running the existing pure
    reconciliation decision logic. This keeps work-order isolation and reduces
    eager materialization for large datasets.
    """

    name = "duckdb"

    _FULL_SCAN_ROW_LIMIT = 100_000
    _WORK_ORDER_TARGET_PARTITION_ROWS = 500
    _MAX_PARTITION_BUCKETS = 100_000
    _STOCK_MOVES_RELATION = "stock_moves_input"
    _GL_ENTRIES_RELATION = "gl_entries_input"
    _STREAM_STOCK_MOVES_RELATION = "stream_stock_moves_input"
    _STREAM_GL_ENTRIES_RELATION = "stream_gl_entries_input"
    _PARTITION_WORK_ORDER_FILTER_RELATION = "_duckdb_work_order_filter"
    _RELATION_WORK_ORDER_VALUE = "_normalized_work_order"
    _FILTER_WORK_ORDER_VALUE = "_filtered_work_order"
    _RELATION_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    _SUMMARY_METRIC_ORDER = (
        "matched_transactions",
        "stock_without_gl",
        "gl_without_stock",
        "value_differences",
        "date_differences",
        "reference_mismatches",
    )

    def run(self, input_dir: Path, config: ReconForgeConfig) -> EngineResult:
        stock_registered = False
        gl_registered = False
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError(
                "DuckDB engine requires optional dependency. Install with pip install reconforge-erp[duckdb].",
            ) from exc
        catalog_exception = duckdb.CatalogException
        try:
            connection = duckdb.connect(database=":memory:")
            stock_relation, stock_registered = self._register_dataset(
                connection,
                input_dir,
                DatasetName.STOCK_MOVES,
                relation_name=self._STOCK_MOVES_RELATION,
            )
            gl_relation, gl_registered = self._register_dataset(
                connection,
                input_dir,
                DatasetName.GL_ENTRIES,
                relation_name=self._GL_ENTRIES_RELATION,
            )

            stock_count = self._relation_count(connection, stock_relation)
            gl_count = self._relation_count(connection, gl_relation)

            if stock_count + gl_count == 0:
                result = self._empty_local_result(config)
            elif stock_count + gl_count <= self._FULL_SCAN_ROW_LIMIT:
                result = self._full_scan_result(
                    connection,
                    stock_relation,
                    gl_relation,
                    config,
                )
            else:
                result = self._partitioned_result(
                    connection,
                    stock_relation=stock_relation,
                    gl_relation=gl_relation,
                    stock_rows=stock_count,
                    gl_rows=gl_count,
                    config=config,
                )
        except (duckdb.Error, OSError, ValueError) as exc:
            raise RuntimeError("DuckDB could not read the required local reconciliation exports.") from exc
        finally:
            if "connection" in locals():
                for relation, should_unregister in (
                    (self._STOCK_MOVES_RELATION, stock_registered),
                    (self._GL_ENTRIES_RELATION, gl_registered),
                ):
                    if should_unregister:
                        with contextlib.suppress(catalog_exception):
                            connection.unregister(relation)
                connection.close()

        return EngineResult(
            engine=self.name,
            matched_rows=len(result.matched_transactions),
            exception_rows=len(result.all_exceptions),
            stock_rows=int(result.invariants.get("stock_input_rows", 0)),
            gl_rows=int(result.invariants.get("gl_input_rows", 0)),
            summary=result.summary,
            reconciliation_signature=build_reconciliation_signature(
                matched_transactions=result.matched_transactions,
                all_exceptions=result.all_exceptions,
            ),
            reconciliation_signature_version=CURRENT_RECONCILIATION_SIGNATURE_VERSION,
            financial_input_policy=result.financial_input_policy,
            record_identity_policy=result.record_identity_policy,
            matching_ambiguity_policy=result.matching_ambiguity_policy,
        )

    def iter_dataset_batches(
        self,
        input_dir: Path,
        dataset: DatasetName,
        *,
        batch_size: int = 50_000,
    ) -> Iterator[pd.DataFrame]:
        """Stream canonicalized batches from a DuckDB relation.

        CSV input is scanned directly by DuckDB and fetched with a bounded cursor
        batch; non-CSV inputs remain SQL-registered before streaming.
        """

        if isinstance(batch_size, bool) or not 1 <= int(batch_size) <= 1_000_000:
            raise ValueError("batch_size must be between 1 and 1000000.")
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError(
                "DuckDB engine requires optional dependency. Install with pip install reconforge-erp[duckdb].",
            ) from exc
        catalog_exception = duckdb.CatalogException
        path = find_dataset_file(input_dir, dataset)
        if path is None:
            raise ValueError(f"Missing required local export: {dataset.value}")
        validate_tabular_input(path)
        relation_name = self._stream_relation_name(dataset)
        stream_registered = False
        connection = duckdb.connect(database=":memory:")
        try:
            if path.suffix.lower() == ".csv":
                cursor = connection.execute(
                    "SELECT * FROM read_csv_auto(?, header = true, all_varchar = true, sample_size = -1)",
                    [str(path.resolve())],
                )
                columns = [str(column[0]) for column in cursor.description or ()]
                while True:
                    rows = cursor.fetchmany(int(batch_size))
                    if not rows:
                        break
                    yield coerce_dataset_types(pd.DataFrame.from_records(rows, columns=columns), dataset)
            else:
                connection.register(relation_name, read_table(path))
                stream_registered = True
                relation = self._relation_by_name(connection, relation_name)
                sorted_relation = relation.order("*")
                offset = 0
                while True:
                    batch = sorted_relation.limit(int(batch_size), offset).to_df()
                    if batch.empty:
                        break
                    yield coerce_dataset_types(batch, dataset)
                    offset += int(batch_size)
        except (duckdb.Error, OSError, ValueError) as exc:
            raise RuntimeError("DuckDB could not stream the required local reconciliation export.") from exc
        finally:
            if "connection" in locals():
                with contextlib.suppress(catalog_exception):
                    if stream_registered:
                        connection.unregister(relation_name)
                connection.close()

    @staticmethod
    def _empty_local_result(config: ReconForgeConfig) -> StockGLReconciliationResult:
        return reconcile_stock_gl(
            coerce_dataset_types(
                pd.DataFrame(columns=list(REQUIRED_COLUMNS[DatasetName.STOCK_MOVES])),
                DatasetName.STOCK_MOVES,
            ),
            coerce_dataset_types(
                pd.DataFrame(columns=list(REQUIRED_COLUMNS[DatasetName.GL_ENTRIES])),
                DatasetName.GL_ENTRIES,
            ),
            config,
            input_policy=STRICT_FINANCIAL_INPUT_POLICY,
            _source_positions_trusted=True,
        )

    @classmethod
    def _register_dataset(
        cls,
        connection: Any,
        input_dir: Path,
        dataset: DatasetName,
        *,
        relation_name: str,
    ) -> tuple[str, bool]:
        path = find_dataset_file(input_dir, dataset)
        if path is None:
            raise ValueError(f"Missing required local export: {dataset.value}")
        validate_tabular_input(path)
        if path.suffix.lower() == ".csv":
            source = connection.from_csv_auto(
                str(path.resolve()),
                header=True,
                all_varchar=True,
                sample_size=-1,
            )
            if SOURCE_POSITION_COLUMN in source.columns:
                raise ValueError("Input uses a reserved ReconForge lineage column.")
            connection.register(
                relation_name,
                source.project(
                    f"row_number() OVER () AS {SOURCE_POSITION_COLUMN}, *",
                ),
            )
            return relation_name, True
        table = read_table(path)
        if SOURCE_POSITION_COLUMN in table.columns:
            raise ValueError("Input uses a reserved ReconForge lineage column.")
        table.insert(0, SOURCE_POSITION_COLUMN, range(1, len(table) + 1))
        connection.register(relation_name, table)
        return relation_name, True

    @staticmethod
    def _relation_count(connection: Any, relation: str) -> int:
        row = DuckDBEngine._relation_by_name(connection, relation).count("*").fetchone()
        if row is None:
            return 0
        return int(row[0])

    @staticmethod
    def _full_scan_result(
        connection: Any,
        stock_relation: str,
        gl_relation: str,
        config: ReconForgeConfig,
    ) -> StockGLReconciliationResult:
        stock = coerce_dataset_types(
            DuckDBEngine._relation_by_name(connection, stock_relation).to_df(),
            DatasetName.STOCK_MOVES,
        )
        gl = coerce_dataset_types(
            DuckDBEngine._relation_by_name(connection, gl_relation).to_df(),
            DatasetName.GL_ENTRIES,
        )
        return reconcile_stock_gl(
            stock,
            gl,
            config,
            input_policy=STRICT_FINANCIAL_INPUT_POLICY,
            _source_positions_trusted=True,
        )

    @classmethod
    def _work_order_partition_size(cls, total_records: int, work_order_count: int) -> int:
        if work_order_count <= 1:
            return 1
        if total_records <= work_order_count:
            estimated_buckets = cls._WORK_ORDER_TARGET_PARTITION_ROWS
        else:
            numerator = cls._WORK_ORDER_TARGET_PARTITION_ROWS * work_order_count
            estimated_buckets = (numerator + total_records - 1) // total_records
        return max(1, min(work_order_count, max(1, estimated_buckets)))

    @staticmethod
    def _read_work_order_buckets(
        connection: Any,
        stock_relation: str,
        gl_relation: str,
    ) -> list[str]:
        stock = (
            DuckDBEngine._relation_by_name(connection, stock_relation)
            .project("COALESCE(TRIM(CAST(work_order AS VARCHAR)), '') AS work_order")
            .distinct()
        )
        gl = (
            DuckDBEngine._relation_by_name(connection, gl_relation)
            .project("COALESCE(TRIM(CAST(work_order AS VARCHAR)), '') AS work_order")
            .distinct()
        )
        work_orders = stock.union(gl).distinct().order("work_order").to_df()["work_order"]
        return ["" if pd.isna(work_order) else str(work_order) for work_order in list(work_orders)]

    @staticmethod
    def _read_partition_records(
        connection: Any,
        relation: str,
        dataset: DatasetName,
        work_order_values: Sequence[str],
    ) -> pd.DataFrame:
        if not work_order_values:
            return coerce_dataset_types(
                pd.DataFrame(columns=list(REQUIRED_COLUMNS[dataset])),
                dataset,
            )
        normalized_values = []
        for value in work_order_values:
            if pd.isna(value):
                normalized_values.append("")
                continue
            normalized_values.append(str(value).strip())
        normalized_values = list(dict.fromkeys(normalized_values))

        with contextlib.suppress(Exception):
            connection.unregister(DuckDBEngine._PARTITION_WORK_ORDER_FILTER_RELATION)
        connection.register(
            DuckDBEngine._PARTITION_WORK_ORDER_FILTER_RELATION,
            pd.DataFrame({DuckDBEngine._FILTER_WORK_ORDER_VALUE: normalized_values}).drop_duplicates(),
        )
        try:
            source = (
                DuckDBEngine._relation_by_name(connection, relation).project(
                    f"COALESCE(TRIM(CAST(work_order AS VARCHAR)), '') AS {DuckDBEngine._RELATION_WORK_ORDER_VALUE}, *"
                )
            )
            filtered = (
                DuckDBEngine._relation_by_name(connection, DuckDBEngine._PARTITION_WORK_ORDER_FILTER_RELATION).project(
                    DuckDBEngine._FILTER_WORK_ORDER_VALUE,
                )
            )
            joined = source.join(
                filtered,
                f"{DuckDBEngine._RELATION_WORK_ORDER_VALUE} = {DuckDBEngine._FILTER_WORK_ORDER_VALUE}",
                how="inner",
            )
            rows = (
                joined.order(DuckDBEngine._RELATION_WORK_ORDER_VALUE)
                .to_df()
                .sort_values(DuckDBEngine._RELATION_WORK_ORDER_VALUE, kind="mergesort")
                .reset_index(drop=True)
            )
            rows = rows.drop(
                columns=[
                    DuckDBEngine._RELATION_WORK_ORDER_VALUE,
                    DuckDBEngine._FILTER_WORK_ORDER_VALUE,
                ],
                errors="ignore",
            )
        finally:
            with contextlib.suppress(Exception):
                connection.unregister(DuckDBEngine._PARTITION_WORK_ORDER_FILTER_RELATION)
        return coerce_dataset_types(rows, dataset)

    @staticmethod
    def _stream_relation_name(dataset: DatasetName) -> str:
        if dataset == DatasetName.STOCK_MOVES:
            return DuckDBEngine._STREAM_STOCK_MOVES_RELATION
        if dataset == DatasetName.GL_ENTRIES:
            return DuckDBEngine._STREAM_GL_ENTRIES_RELATION
        raise ValueError(f"Unsupported dataset for streaming in DuckDB engine: {dataset.value}")

    @staticmethod
    def _relation_by_name(connection: Any, relation: str) -> Any:
        if not DuckDBEngine._RELATION_NAME_PATTERN.fullmatch(relation):
            raise ValueError("Unexpected DuckDB relation name; must be an identifier from this process.")
        return connection.table(relation)

    @classmethod
    def _partitioned_result(
        cls,
        connection: Any,
        *,
        stock_relation: str,
        gl_relation: str,
        stock_rows: int,
        gl_rows: int,
        config: ReconForgeConfig,
    ) -> StockGLReconciliationResult:
        work_orders = cls._read_work_order_buckets(connection, stock_relation, gl_relation)
        if not work_orders:
            return cls._empty_local_result(config)

        total_records = stock_rows + gl_rows
        bucket_size = cls._work_order_partition_size(total_records, len(work_orders))
        if bucket_size > cls._MAX_PARTITION_BUCKETS:
            bucket_size = cls._MAX_PARTITION_BUCKETS
        partitions: list[StockGLReconciliationResult] = []

        for start in range(0, len(work_orders), bucket_size):
            window = work_orders[start : start + bucket_size]
            left = cls._read_partition_records(
                connection=connection,
                relation=stock_relation,
                dataset=DatasetName.STOCK_MOVES,
                work_order_values=window,
            )
            right = cls._read_partition_records(
                connection=connection,
                relation=gl_relation,
                dataset=DatasetName.GL_ENTRIES,
                work_order_values=window,
            )
            partitions.append(
                reconcile_stock_gl(
                    left,
                    right,
                    config,
                    input_policy=STRICT_FINANCIAL_INPUT_POLICY,
                    _source_positions_trusted=True,
                )
            )

        if not partitions:
            return cls._empty_local_result(config)

        return cls._merge_partitioned_results(partitions)

    @staticmethod
    def _merge_partitioned_results(parts: list[StockGLReconciliationResult]) -> StockGLReconciliationResult:
        input_policies = {part.financial_input_policy for part in parts}
        if len(input_policies) != 1:
            raise ValueError("DuckDB partitions used inconsistent financial input policies.")
        financial_input_policy = next(iter(input_policies))
        identity_policies = {part.record_identity_policy for part in parts}
        if len(identity_policies) != 1:
            raise ValueError("DuckDB partitions used inconsistent record identity policies.")
        record_identity_policy = next(iter(identity_policies))
        ambiguity_policies = {part.matching_ambiguity_policy for part in parts}
        if len(ambiguity_policies) != 1:
            raise ValueError("DuckDB partitions used inconsistent matching ambiguity policies.")
        matching_ambiguity_policy = next(iter(ambiguity_policies))
        matched = pd.concat([part.matched_transactions for part in parts], ignore_index=True)
        stock_without = pd.concat([part.stock_without_gl for part in parts], ignore_index=True)
        gl_without = pd.concat([part.gl_without_stock for part in parts], ignore_index=True)
        value_diff = pd.concat([part.value_differences for part in parts], ignore_index=True)
        date_diff = pd.concat([part.date_differences for part in parts], ignore_index=True)
        reference_mismatch = pd.concat([part.reference_mismatches for part in parts], ignore_index=True)
        data_quality = pd.concat([part.data_quality_exceptions for part in parts], ignore_index=True)

        all_exceptions = pd.concat([part.all_exceptions for part in parts], ignore_index=True)
        summary = pd.concat([part.summary for part in parts], ignore_index=True)
        if summary.empty:
            summary = pd.DataFrame(
                [
                    {"metric": "matched_transactions", "count": 0},
                    {"metric": "stock_without_gl", "count": 0},
                    {"metric": "gl_without_stock", "count": 0},
                    {"metric": "value_differences", "count": 0},
                    {"metric": "date_differences", "count": 0},
                    {"metric": "reference_mismatches", "count": 0},
                ],
            )
        else:
            summary = (
                summary.groupby("metric", as_index=False, sort=False)["count"]
                .sum()
                .set_index("metric")
                .reindex(DuckDBEngine._SUMMARY_METRIC_ORDER, fill_value=0)
                .rename_axis("metric")
                .reset_index()
            )

        stock_input_rows = sum(int(part.invariants.get("stock_input_rows", 0)) for part in parts)
        gl_input_rows = sum(int(part.invariants.get("gl_input_rows", 0)) for part in parts)
        invalid_stock_rows = sum(int(part.invariants.get("invalid_stock_rows", 0)) for part in parts)
        invalid_gl_rows = sum(int(part.invariants.get("invalid_gl_rows", 0)) for part in parts)
        accounted_stock_rows = sum(int(part.invariants.get("accounted_stock_rows", 0)) for part in parts)
        accounted_gl_rows = sum(int(part.invariants.get("accounted_gl_rows", 0)) for part in parts)

        return StockGLReconciliationResult(
            matched_transactions=matched,
            stock_without_gl=stock_without,
            gl_without_stock=gl_without,
            value_differences=value_diff,
            date_differences=date_diff,
            reference_mismatches=reference_mismatch,
            data_quality_exceptions=data_quality,
            all_exceptions=all_exceptions,
            summary=summary,
            financial_input_policy=financial_input_policy,
            record_identity_policy=record_identity_policy,
            matching_ambiguity_policy=matching_ambiguity_policy,
            invariants={
                "stock_input_rows": stock_input_rows,
                "gl_input_rows": gl_input_rows,
                "invalid_stock_rows": invalid_stock_rows,
                "invalid_gl_rows": invalid_gl_rows,
                "accounted_stock_rows": accounted_stock_rows,
                "accounted_gl_rows": accounted_gl_rows,
                "record_accounting_ok": (
                    accounted_stock_rows == stock_input_rows and accounted_gl_rows == gl_input_rows
                ),
            },
        )
