.PHONY: install setup dev-doctor dev-bootstrap docs-install doctor test test-all lint type typecheck format security demo studio-data showcase showcase-serve web-install web web-test web-build api docker docs screenshots release-check clean

install:
	python -m pip install -e ".[dev]"

setup: install docs-install web-install

dev-doctor:
	python .github/scripts/manage_developer_environment.py doctor --project-root . --python-version 3.12

dev-bootstrap:
	python .github/scripts/manage_developer_environment.py bootstrap --project-root . --python-version 3.12

docs-install:
	python -m pip install -e ".[docs]"

doctor:
	python -m reconforge.cli doctor

test:
	pytest

test-all: test web-test

lint:
	ruff check .

type: typecheck

typecheck:
	mypy reconforge

format:
	ruff format .

security:
	python -m bandit -q -r reconforge
	python .github/scripts/run_locked_python_audit.py --project-root .

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

studio-data:
	reconforge demo enterprise --output output/enterprise_demo
	reconforge demo studio-data --input output/enterprise_demo --output apps/web/public/demo/studio-overview.json

showcase:
	python -m reconforge.cli demo showcase --output output/showcase/enterprise_demo --studio-output apps/web/public/demo/studio-overview.json
	npm --prefix apps/web run build
	@echo "Showcase built. Run 'make showcase-serve' to open the local preview."

showcase-serve: showcase
	npm --prefix apps/web run preview -- --host 127.0.0.1 --port 4173

web-install:
	npm --prefix apps/web install

web:
	npm --prefix apps/web run dev

web-test:
	npm --prefix apps/web run typecheck
	npm --prefix apps/web run test:run

web-build:
	npm --prefix apps/web run build

api:
	reconforge api serve --db output/reconforge.db --host 127.0.0.1 --port 8765

docker:
	docker build -t reconforge-erp .

docs:
	python -m mkdocs build --strict

screenshots:
	npm --prefix apps/web run screenshots

release-check: lint typecheck test web-test web-build security

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info output demo_workspace benchmarks/small_1k examples/anonymized_data
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
