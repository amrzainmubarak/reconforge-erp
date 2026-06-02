from __future__ import annotations

from setuptools import find_packages, setup

INSTALL_REQUIRES = [
    "fastapi>=0.111",
    "openpyxl>=3.1",
    "pandas>=2.2",
    "pydantic>=2.7",
    "pyyaml>=6.0",
    "rich>=13.7",
    "typer>=0.12",
    "uvicorn>=0.30",
]

DEV_REQUIRES = [
    "bandit>=1.7",
    "build>=1.2",
    "httpx>=0.27",
    "mypy>=1.10",
    "pandas-stubs>=2.2",
    "pip-audit>=2.7",
    "pre-commit>=3.7",
    "pytest>=8.2",
    "ruff>=0.5",
    "types-PyYAML>=6.0",
]

with open("README.md", encoding="utf-8") as readme:
    LONG_DESCRIPTION = readme.read()


setup(
    name="reconforge-erp",
    version="0.3.0",
    description="Open-source reconciliation intelligence for ERP, inventory, GL, WIP, spare-parts, and workshop operations.",
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    packages=find_packages(include=["reconforge", "reconforge.*"]),
    python_requires=">=3.11",
    install_requires=INSTALL_REQUIRES,
    extras_require={"dev": DEV_REQUIRES, "docs": ["mkdocs>=1.6"], "duckdb": ["duckdb>=1.0"]},
    entry_points={"console_scripts": ["reconforge=reconforge.cli:app"]},
    license="MIT",
)
