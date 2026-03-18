.PHONY: help test lint type check format build clean depot fuzz prob clean-tex font-test

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

test: ## Run tests (excludes slow integration tests)
	uv run pytest

lint: ## Lint and format check
	uv run ruff check .
	uv run ruff format --check .
	npx markdownlint-cli2 "**/*.md" "#node_modules"

type: ## Type check with mypy and pyright
	uv run mypy src/ tests/
	npx pyright src/ tests/

check: lint type test ## Run all quality gates

format: ## Auto-format code
	uv run ruff check --fix .
	uv run ruff format .

build: ## Build wheel and sdist
	rm -rf dist/
	uv build
	uvx twine check dist/*

clean: ## Remove build artifacts
	rm -rf dist/ .tmp/

DEPOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))../.depot

depot: build ## Build and copy wheel to local depot
	@mkdir -p $(DEPOT)
	@cp dist/*.whl $(DEPOT)/
	@echo "depot: $$(ls dist/*.whl | xargs -n1 basename) -> $(DEPOT)/"

PROBCLI ?= $(HOME)/Applications/ProB/probcli
PROB_SETSIZE ?= 2
PROB_MAXINT ?= 4
PROB_TIMEOUT ?= 60000
PROB_FLAGS = -p DEFAULT_SETSIZE $(PROB_SETSIZE) -p MAXINT $(PROB_MAXINT) -p TIME_OUT $(PROB_TIMEOUT)
Z_SPECS = $(wildcard docs/*.tex)

fuzz: ## Type-check a Z spec with fuzz (usage: make fuzz SPEC=docs/foo.tex)
	@fuzz -t "$(SPEC)" > /dev/null
	@echo "fuzz: $(SPEC) OK"

prob: ## Animate and model-check a Z spec with ProB (usage: make prob SPEC=docs/foo.tex)
	@echo "--- init ---"
	@$(PROBCLI) "$(SPEC)" -init $(PROB_FLAGS) 2>&1 | grep -v "^Promoting\|^Z op\|^% given\|fuzz AST\|^Writing"
	@echo "--- animate ---"
	@$(PROBCLI) "$(SPEC)" -animate 20 $(PROB_FLAGS) 2>&1 | grep -E "COVERED|not_covered|Runtime"
	@echo "--- cbc assertions ---"
	@$(PROBCLI) "$(SPEC)" -cbc_assertions $(PROB_FLAGS) 2>&1 | grep -E "counter|ASSERTION"
	@echo "--- cbc deadlock ---"
	@$(PROBCLI) "$(SPEC)" -cbc_deadlock $(PROB_FLAGS) 2>&1 | grep -E "deadlock|DEADLOCK"
	@echo "--- model check ---"
	@$(PROBCLI) "$(SPEC)" -model_check $(PROB_FLAGS) \
		-p MAX_INITIALISATIONS 100 -p MAX_OPERATIONS 5000 2>&1 | \
		grep -E "states|COUNTER|No counter|COVERED|all open|not all"
	@echo "prob: $(SPEC) OK"

# LaTeX intermediate files to remove after compilation
LATEX_ARTIFACTS = docs/*.aux docs/*.log docs/*.out docs/*.bbl docs/*.bcf docs/*.blg \
                  docs/*.run.xml docs/*.fls docs/*.fdb_latexmk docs/*.synctex.gz \
                  docs/*.toc docs/*.fuzz docs/*.mf docs/fuzz.sty

font-test: ## Visual font coverage test (SMP + BMP double-struck letters)
	uv run python scripts/font-test.py

clean-tex: ## Remove LaTeX intermediate files
	@rm -f $(LATEX_ARTIFACTS)
