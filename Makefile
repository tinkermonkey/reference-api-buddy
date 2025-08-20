.PHONY: help install lint format test clean setup-dev
.DEFAULT_GOAL := help

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install dependencies
	pip install -r requirements.txt
	pip install -e .

setup-dev: ## Set up development environment
	pip install pre-commit
	pre-commit install
	@echo "Development environment set up successfully!"

lint: ## Run linting tools
	@echo "Running black..."
	black reference_api_buddy/ tests/ smoke_tests/ --line-length=120
	@echo "Running isort..."
	isort reference_api_buddy/ tests/ smoke_tests/ --profile=black --line-length=120
	@echo "Running flake8..."
	flake8 reference_api_buddy/
	@echo "Running mypy..."
	mypy reference_api_buddy/ --ignore-missing-imports --no-strict-optional

format: ## Format code with black and isort
	black reference_api_buddy/ tests/ smoke_tests/ --line-length=120
	isort reference_api_buddy/ tests/ smoke_tests/ --profile=black --line-length=120

test: ## Run tests
	pytest tests/ -v --cov=reference_api_buddy --cov-report=html --cov-report=term

test-unit: ## Run unit tests only
	pytest tests/unit_tests/ -v

test-integration: ## Run integration tests only
	pytest tests/integration_tests/ -v

test-performance: ## Run performance tests only
	pytest tests/performance_tests/ -v

clean: ## Clean up build artifacts and cache files
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

pre-commit: ## Run pre-commit on all files
	pre-commit run --all-files

ci-check: ## Run all CI checks locally
	@echo "Running CI checks..."
	make format
	make lint
	make test
	@echo "All CI checks passed!"
