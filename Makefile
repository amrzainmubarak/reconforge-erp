.PHONY: install test lint typecheck format security demo clean

install:
	python -m pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

typecheck:
	mypy reconforge

format:
	ruff format .

security:
	bandit -q -r reconforge
	pip-audit

demo:
	reconforge doctor
	reconforge validate examples/sample_data
	reconforge reconcile stock-gl --input examples/sample_data --config config/reconforge.yml --output output
	reconforge reconcile workorders --input examples/sample_data --config config/reconforge.yml --output output
	reconforge report wip-aging --input examples/sample_data --config config/reconforge.yml --output output
	reconforge rules validate --pack control-packs/audit-basic
	reconforge rules list --pack control-packs/audit-basic
	reconforge rules run --input examples/sample_data --pack control-packs/audit-basic --output output/rules
	reconforge report evidence-binder --input output --output output/evidence
	reconforge anonymize --input examples/sample_data --output examples/anonymized_data
	reconforge generate synthetic --rows 1000 --output benchmarks/small_1k
	reconforge benchmark --input benchmarks/small_1k --engine pandas --output output/benchmark
	reconforge report management-pack --input examples/sample_data --config config/reconforge.yml --output output

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info output demo_workspace benchmarks/small_1k examples/anonymized_data
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
