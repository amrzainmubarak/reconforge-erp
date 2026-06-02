# Getting Started

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Create a Workspace

```bash
reconforge init demo_workspace
```

The command creates:

- `input/`
- `output/`
- `config/`
- `reports/`
- `logs/`

## Validate Sample Data

```bash
reconforge validate examples/sample_data
```

The sample data includes intentional warnings such as duplicate references, missing customer references, invalid product codes, and amount inconsistencies. Structural errors such as missing columns or invalid required dates cause validation to exit with an error.

## Required Files

| File | Purpose |
| --- | --- |
| `stock_moves.csv` | Inventory receipts, issues, direct fits, and consumption |
| `gl_entries.csv` | GL postings from inventory, expense, WIP, or manual journals |
| `work_orders.csv` | Workshop/service order master and cost status |
| `purchase_orders.csv` | Purchase order history and linked work orders |
| `products.csv` | Product master, category, standard cost, and account mapping |
| `customers.csv` | Customer reference data |
| `old_parts_returns.csv` | Evidence of returned old parts or cores |
| `invoices.csv` | Customer invoice status and value |

CSV and XLSX formats are supported. Column names are normalized to lowercase with underscores.

## Generate Reports

```bash
reconforge report management-pack --input examples/sample_data --config config/reconforge.yml --output output
```

The output folder includes Excel, JSON, CSV, Markdown, and HTML report artifacts.
