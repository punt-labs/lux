.PHONY: help test test-integration test-e2e test-slow snapshot-parity snapshot-record lint type check check-oo update-oo check-suppressions update-suppressions check-coupling update-coupling report format build install clean depot fuzz prob prfaq clean-tex font-test restart reload

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

test: ## Run tests — tier 1 unit only (excludes slow, integration, e2e)
	uv run --extra display pytest

test-integration: ## Run integration tests (tier 2, requires no display)
	uv run --extra display pytest -m integration

test-e2e: ## Run end-to-end tests (tier 3, requires display process running)
	uv run --extra display pytest -m e2e

test-slow: ## Run the isolated slow / timing-sensitive tests (excluded from the default gate)
	uv run --extra display pytest -m slow

snapshot-parity: ## Replay the characterization corpus — every snapshot must match
	uv run --extra display pytest tests/characterization/ -v

snapshot-record: ## Rebuild the characterization corpus (overwrites snapshots/)
	uv run --extra display python -m tests.characterization.build_corpus

lint: ## Lint and format check
	uv run --extra display ruff check .
	uv run --extra display ruff format --check .
	npx markdownlint-cli2 "**/*.md" "#node_modules"
	bash scripts/check-skill-permissions.sh

type: ## Type check with mypy and pyright
	uv run --extra display mypy src/ tests/
	npx pyright src/ tests/

check: check-oo check-suppressions lint type test ## Run all quality gates

check-oo: ## OO ratchet — must improve over baseline, never regress
	uv run --extra display python tools/oo_score.py src/punt_lux/ --check

update-oo: ## Update OO baseline after improvements (stage .oo-baseline.json and .oo-audit.jsonl)
	uv run --extra display python tools/oo_score.py src/punt_lux/ --update

check-suppressions: ## Suppression ratchet — count must not increase
	uv run --extra display python tools/suppression_ratchet.py src/punt_lux/ --check

update-suppressions: ## Update suppression baseline
	uv run --extra display python tools/suppression_ratchet.py src/punt_lux/ --update

check-coupling: ## Coupling metrics (informational, not in check chain)
	uv run --extra display python tools/oo_coupling.py src/punt_lux/ --check

update-coupling: ## Update coupling baseline
	uv run --extra display python tools/oo_coupling.py src/punt_lux/ --update

report: ## Full diagnostics (OO score + all checks, no fail-fast)
	-uv run --extra display python tools/oo_score.py src/punt_lux/ --threshold
	-uv run --extra display mypy src/ tests/
	-uv run --extra display ruff format --check .
	-uv run --extra display ruff check --preview --select PLR6301,PLR0913,UP035,UP040,UP007,N,I,SIM,S101 .
	-npx pyright src/ tests/
	-uv run --extra display pytest
	@echo "Report complete."

format: ## Auto-format code
	uv run ruff format .
	uv run ruff check --fix .

build: ## Build wheel and sdist
	rm -rf dist/
	uv build
	uvx twine check dist/*

install: build ## Build and install locally (with display extras)
	uv tool install --force "$$(ls dist/punt_lux-*.whl)[display]"

LUX_LAUNCHD_LABEL := com.punt-labs.lux

restart: install ## Install + restart luxd (via launchd) and display
	@# Restart luxd — launchd manages the daemon (KeepAlive: true)
	@launchctl kickstart -k "gui/$$(id -u)/$(LUX_LAUNCHD_LABEL)" 2>/dev/null || \
		echo "warning: launchctl kickstart failed — luxd may not be a launchd service"
	@sleep 1
	@# Reap the running display, then ensure exactly one — via the LOCKED, idempotent
	@# path, never a bare unlocked `lux display &`. reap() holds the spawn lock to
	@# terminate the owner (by its socket peer credential); ensure() re-acquires the
	@# lock, checks is_running() UNDER it, and REUSES any display a concurrent ensure()
	@# (e.g. the beads hook) raced into the reap->ensure gap — else spawns one. So a
	@# concurrent spawn can never stack a second window. ensure() waits for the READY
	@# handshake, so a display that cannot start (no monitor) fails LOUDLY here instead
	@# of backgrounding a dead process and printing success. LUX_LOG_LEVEL propagates:
	@# ensure()'s _spawn inherits this process's environment.
	@LUX_LOG_LEVEL=$${LUX_LOG_LEVEL:-DEBUG} uv run --extra display python -c "from punt_lux.paths import DisplayPaths; dp = DisplayPaths(); dp.reap(); dp.ensure()" || \
		{ echo "error: could not reap and restart the display — aborting restart (see log above)" >&2; exit 1; }
	@echo "luxd restarted via launchd; display reaped and exactly one live display ensured"

reload: install ## Install + restart luxd only (display keeps running)
	@launchctl kickstart -k "gui/$$(id -u)/$(LUX_LAUNCHD_LABEL)" 2>/dev/null || \
		echo "warning: launchctl kickstart failed — luxd may not be a launchd service"
	@sleep 1
	@echo "luxd restarted via launchd"

clean: ## Remove build artifacts
	rm -rf dist/ .tmp/

DEPOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))../.depot

depot: build ## Build and copy wheel to local depot
	@mkdir -p $(DEPOT)
	@cp dist/*.whl $(DEPOT)/
	@echo "depot: $$(ls dist/*.whl | xargs -n1 basename) -> $(DEPOT)/"

metrics: ## Run ABC complexity metrics on src/
	uv run --extra display python tools/run_metrics.py

coverage: ## Run tests with coverage report
	uv run --extra display python tools/run_coverage.py

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
LATEX_ARTIFACTS = *.aux *.log *.out *.bbl *.bcf *.blg *.run.xml *.fls \
                  *.fdb_latexmk *.synctex.gz *.toc \
                  docs/*.aux docs/*.log docs/*.out docs/*.bbl docs/*.bcf docs/*.blg \
                  docs/*.run.xml docs/*.fls docs/*.fdb_latexmk docs/*.synctex.gz \
                  docs/*.toc docs/*.fuzz docs/*.mf docs/fuzz.sty

TEX_FILES = prfaq.tex docs/architecture/system.tex

prfaq: ## Compile .tex files to .pdf and clean intermediate artifacts
	@for f in $(TEX_FILES); do \
	  echo "Compiling $$f ..."; \
	  dir=$$(dirname "$$f"); base=$$(basename "$$f" .tex); \
	  pdflatex -interaction=nonstopmode -output-directory="$$dir" "$$f" > /dev/null 2>&1; \
	  if [ -f "$$dir/$$base.bib" ] && command -v biber > /dev/null 2>&1; then \
	    (cd "$$dir" && biber "$$base") > /dev/null 2>&1 || true; \
	    pdflatex -interaction=nonstopmode -output-directory="$$dir" "$$f" > /dev/null 2>&1; \
	  fi; \
	  pdflatex -interaction=nonstopmode -output-directory="$$dir" "$$f" > /dev/null 2>&1; \
	  if [ -f "$$dir/$$base.pdf" ]; then \
	    echo "  $$dir/$$base.pdf"; \
	  else \
	    echo "Error: $$f failed to compile" >&2; exit 1; \
	  fi; \
	done
	@rm -f $(LATEX_ARTIFACTS)

font-test: ## Visual font coverage test (SMP + BMP double-struck letters)
	uv run python tools/font-test.py

clean-tex: ## Remove LaTeX intermediate files
	@rm -f $(LATEX_ARTIFACTS)
