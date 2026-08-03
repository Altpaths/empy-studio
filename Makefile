.PHONY: install test lint typecheck check build

install:
	python -m pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

typecheck:
	mypy src

check: lint typecheck test

build:
	python -m build
