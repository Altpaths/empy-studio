.PHONY: install test lint typecheck check build package-check release-assets

install:
	python -m pip install ".[dev]"

test:
	pytest

lint:
	ruff check .

typecheck:
	mypy src

check: lint typecheck test

build:
	python -m build --no-isolation

package-check:
	python -m build --no-isolation --wheel --sdist --outdir build/packages
	python scripts/build_release_assets.py --output build/release-assets
	python scripts/verify_release_assets.py build/release-assets/release-assets.json

release-assets:
	python scripts/build_release_assets.py --output build/release-assets
