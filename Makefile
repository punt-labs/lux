LUX_SOURCES = --namespace punt_lux src/punt_lux packages/punt-lux-client/src/punt_lux
SERVICE_ROOT = packages/punt-service/src/punt_service
SERVICE_SOURCES = --namespace punt_service $(SERVICE_ROOT)
PYTHON_SOURCES = src packages

.PHONY: sync-workspace-version

.PHONY: help test test-integration test-e2e test-e2e-gui test-slow snapshot-parity snapshot-record lint type check check-oo update-oo check-suppressions update-suppressions check-coupling update-coupling check-plugin-surface report format build install clean depot fuzz prob prfaq clean-tex font-test restart reload prove-reaping

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

sync-workspace-version: ## Synchronize member versions and exact pins after the release root bump
	uv run --no-sync python -m tools.workspace_version $(VERSION)
	uv lock

test: ## Run tests — tier 1 unit only (excludes slow, integration, e2e)
	uv run --extra display pytest

test-integration: ## Run integration tests (tier 2, requires no display)
	uv run --extra display pytest -m integration

test-e2e: ## Run end-to-end tests that need no GUI window (tier 3, CI-safe)
	uv run --extra display pytest -m 'e2e and not gui'

test-e2e-gui: ## Run end-to-end tests that spawn a real ImGui window (tier 3, local only)
	uv run --extra display pytest -m 'e2e and gui'

test-slow: ## Run the isolated slow / timing-sensitive tests (excluded from the default gate)
	uv run --extra display pytest -m slow

snapshot-parity: ## Replay the characterization corpus — every snapshot must match
	uv run --extra display pytest tests/characterization/ -v

snapshot-record: ## Rebuild the characterization corpus (overwrites snapshots/)
	uv run --extra display python -m tests.characterization.build_corpus

.PHONY: check-comments check-docstrings build-api-docs

lint: check-comments check-docstrings ## Lint and format check
	uv run --extra display ruff check .
	uv run --extra display ruff format --check .
	npx markdownlint-cli2 "**/*.md" "#node_modules"
	bash scripts/check-plugin-surface.sh

check-comments: ## Reject commented-out code and tracker references in Python prose
	uv run --locked ruff check --select ERA001 .
	uv run --locked python tools/check_python_docs.py comments $(PYTHON_SOURCES) tests tools scripts plugin typings

check-docstrings: ## Check public Python docstrings and documented argument names
	# Griffe checks exported class and member presence; Ruff checks their style.
	uv run --locked ruff check --select D,D401 --ignore D101,D102,D105,D106,D107,D417 $(PYTHON_SOURCES)
	for source in $(PYTHON_SOURCES); do uv run --locked python tools/check_python_docs.py docstrings "$$source" || exit $$?; done
	uv run --locked python tools/check_python_docs.py public src/

build-api-docs: ## Build and verify the generated Python API reference
	UV_NO_SYNC=false UV_PROJECT_ENVIRONMENT=.tmp/docs-venv uv run --locked --only-group docs mkdocs build --strict
	uv run --locked python tools/check_python_docs.py api .tmp/api-site/objects.inv

type: ## Type check with mypy and pyright
	uv run --extra display mypy $(PYTHON_SOURCES) tests/
	npx pyright $(PYTHON_SOURCES) tests/

DESIGN_BASE ?= origin/main

.PHONY: design-shadow

design-shadow: ## Report advisory design changes; never part of check
	uv run --extra display oo-ratchet design $(LUX_SOURCES) --shadow-check "$(DESIGN_BASE)"

check: check-oo check-coupling check-suppressions check-layers check-models lint type test ## Run all quality gates

.PHONY: check-models
check-models: ## Type-check and model-check Display readiness and every fidelity mutant
	PROBCLI="$(PROBCLI)" bash scripts/verify_readiness_model.sh

# CI compares PRs with their merge base and pushes to main with the pre-push
# tip (github.event.before). Without BASE_REF, the package resolves the merge
# base of origin/main and HEAD. Keep the explicit push base: comparing the
# freshly fetched main tip to itself would silently check an empty range.
check-oo: ## OO ratchet — must improve over baseline, never regress
	uv run --extra display oo-ratchet oo $(LUX_SOURCES) --check $(if $(BASE_REF),--base-ref $(BASE_REF) --require-base,)
	uv run --extra display oo-ratchet oo $(SERVICE_SOURCES) --check --allow-no-improvement $(if $(BASE_REF),--base-ref $(BASE_REF) --require-base,)

update-oo: ## Update OO baseline after improvements (stage .oo-baseline.json and .oo-audit.jsonl)
	uv run --extra display oo-ratchet oo $(LUX_SOURCES) --update
	uv run --extra display oo-ratchet oo $(SERVICE_SOURCES) --update

check-suppressions: ## Suppression ratchet — count must not increase
	uv run --extra display oo-ratchet suppressions $(LUX_SOURCES) --check
	uv run --extra display oo-ratchet suppressions $(SERVICE_SOURCES) --check

update-suppressions: ## Update suppression baseline
	uv run --extra display oo-ratchet suppressions $(LUX_SOURCES) --update
	uv run --extra display oo-ratchet suppressions $(SERVICE_SOURCES) --check

check-plugin-surface: ## Verify the plugin/ surface resolves entirely inside itself
	bash scripts/check-plugin-surface.sh

check-layers: ## Layer ratchet — reject new violations and stale baseline entries
	uv run --extra display python -m tools.layer_contract $(if $(BASE_REF),--base-ref $(BASE_REF),)

update-layers: ## Shrink the layer baseline after removing violating import edges
	uv run --extra display python -m tools.layer_contract --update $(if $(BASE_REF),--base-ref $(BASE_REF),)

.PHONY: check-layers update-layers

demo-class: ## Classify this branch's committed changes for the demo gate (interactive / rendering / exempt)
	uv run --extra display python -m tools.demo_class $(if $(BASE_REF),--base-ref $(BASE_REF),)

.PHONY: demo-class

check-coupling: ## Coupling ratchet — must not regress against .oo-coupling-baseline.json
	uv run --extra display oo-ratchet coupling $(LUX_SOURCES) --check $(if $(BASE_REF),--base-ref $(BASE_REF),)
	uv run --extra display oo-ratchet coupling $(SERVICE_SOURCES) --check $(if $(BASE_REF),--base-ref $(BASE_REF),)

update-coupling: ## Update coupling baseline
	uv run --extra display oo-ratchet coupling $(LUX_SOURCES) --update
	uv run --extra display oo-ratchet coupling $(SERVICE_SOURCES) --update

export FILES REASON
bless-coupling: override FILES := $(value FILES)
bless-coupling: override REASON := $(value REASON)
bless-coupling: ## Bounded coupling bless (FILES=src/punt_lux/a.py,src/punt_lux/b.py REASON="explanation")
	@test -n "$$FILES" || { echo "FILES is required" >&2; exit 1; }; \
	set -f; status=0; IFS=,; for file in $$FILES; do \
		case "/$$file" in \
			*/$(SERVICE_ROOT)/*) set -- $(SERVICE_SOURCES) ;; \
			*) set -- $(LUX_SOURCES) ;; \
		esac; \
		uv run --extra display oo-ratchet coupling "$$@" --rebaseline-files "$$file" --reason "$$REASON" || status=1; \
	done; exit $$status

.PHONY: bless-coupling

report: ## Full diagnostics (OO score + all checks, no fail-fast)
	-uv run --extra display oo-ratchet oo $(LUX_SOURCES) --threshold
	-uv run --extra display oo-ratchet design $(LUX_SOURCES)
	-uv run --extra display python tools/layer_contract.py
	-uv run --extra display mypy $(PYTHON_SOURCES) tests/
	-uv run --extra display ruff format --check .
	-uv run --extra display ruff check --preview --select PLR6301,PLR0913,UP035,UP040,UP007,N,I,SIM,S101 .
	-npx pyright $(PYTHON_SOURCES) tests/
	-uv run --extra display pytest
	@echo "Report complete."

format: ## Auto-format code
	uv run ruff format .
	uv run ruff check --fix .

build: ## Build wheel and sdist
	rm -rf dist/
	uv build --all-packages
	uvx twine check dist/*

install: build ## Build and install locally (with display extras)
	uv tool install --force --find-links dist/ "$$(ls dist/punt_lux-*.whl)[display]"

restart: install ## Install + restart Hub, Display, and a running luxd-pty (ends its terminal sessions)
	@lux hub restart || { echo "error: 'lux hub restart' failed — see output above" >&2; exit 1; }
	@lux display restart || { echo "error: 'lux display restart' failed — see output above" >&2; exit 1; }
	@uv run --locked --extra display python scripts/restart_terminal.py || { echo "error: luxd-pty restart step failed — see output above" >&2; exit 1; }

reload: install ## Install + restart luxd only (display keeps running)
	@lux hub restart || { echo "error: 'lux hub restart' failed — see output above" >&2; exit 1; }
	@echo "luxd restarted through the service supervisor"

prove-reaping: ## Manual regression demo for dead-connection reaping (lux-d84d) — needs a running luxd on branch code (`lux hub restart`); takes ~2 minutes
	@echo "prove-reaping: requires luxd already running the branch's code — run 'lux hub restart' first if unsure"
	@uv run --extra display python scripts/prove_reaping.py & \
	victim=$$!; \
	echo "victim pid=$$victim -- waiting 105s (90s cli-kind lease + 15s poll cycle) for the reap sweep"; \
	sleep 105; \
	echo; \
	echo "--- lux session ls --json (victim connection should be gone) ---"; \
	lux session ls --json; \
	echo; \
	echo "--- lux scene ls --json (reap-proof-victim scene should show owners: []) ---"; \
	lux scene ls --json; \
	echo; \
	kill "$$victim" 2>/dev/null || true; \
	echo "prove-reaping: victim process cleaned up"

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
                  docs/*.toc docs/*.fuzz docs/*.mf docs/fuzz.sty \
                  docs/architecture/*.aux docs/architecture/*.log \
                  docs/architecture/*.out docs/architecture/*.toc \
                  docs/architecture/*.fls docs/architecture/*.fdb_latexmk \
                  docs/architecture/*.synctex.gz

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
