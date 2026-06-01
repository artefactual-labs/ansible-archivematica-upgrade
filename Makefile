ANSIBLE_LINT_CMD = uv run --python 3.12 --group lint ansible-lint -c .ansible-lint-tests.yml
PRE_COMMIT_CMD = uv run --python 3.12 --group lint pre-commit run --all-files
MOLECULE_ANSIBLE_HOME ?= $(CURDIR)/.ansible
MOLECULE_CALLBACK_PLUGINS ?= $(CURDIR)/molecule/common/callback_plugins
MOLECULE_COVERAGE_CONFIG ?= molecule/$(MOLECULE_SCENARIO)/coverage.yml
MOLECULE_COVERAGE_FILE ?= $(MOLECULE_ANSIBLE_HOME)/molecule/common-task-coverage.jsonl
MOLECULE_COVERAGE_CMD = uv run --python 3.12 --group molecule python molecule/common/scripts/verify_task_coverage.py
MOLECULE_COLLECTIONS_PATH ?= $(MOLECULE_ANSIBLE_HOME)/collections
MOLECULE_CMD = MOLECULE_ANSIBLE_HOME=$(MOLECULE_ANSIBLE_HOME) MOLECULE_CALLBACK_PLUGINS=$(MOLECULE_CALLBACK_PLUGINS) MOLECULE_COLLECTIONS_PATH=$(MOLECULE_COLLECTIONS_PATH) MOLECULE_COVERAGE_CONFIG=$(MOLECULE_COVERAGE_CONFIG) MOLECULE_COVERAGE_FILE=$(MOLECULE_COVERAGE_FILE) ANSIBLE_HOME=$(MOLECULE_ANSIBLE_HOME) ANSIBLE_COLLECTIONS_PATH=$(MOLECULE_COLLECTIONS_PATH):/usr/share/ansible/collections ANSIBLE_COLLECTIONS_SCAN_SYS_PATH=false uv run --python 3.12 --group molecule molecule
MOLECULE_PHASE_COVERAGE_CONFIG ?= molecule/phase-coverage.yml
MOLECULE_PHASE_ENFORCE_COVERAGE ?= true
MOLECULE_PHASE_SCENARIOS ?= phase-lifecycle-mysql phase-lifecycle-sqlite phase-resume-checkpoints phase-restore-success phase-guardrails-negative elasticsearch-readiness-cutover-negative elasticsearch-runtime-negative elasticsearch-reindex-negative elasticsearch-restore-validate-cleanup-negative
MOLECULE_PHASE_COVERAGE_ARGS = $(foreach scenario,$(MOLECULE_PHASE_SCENARIOS),--coverage-file $(MOLECULE_ANSIBLE_HOME)/molecule/$(scenario)-task-coverage.jsonl)
MOLECULE_SCENARIO ?= common
MOLECULE_UBUNTU_2404_IMAGE ?= geerlingguy/docker-ubuntu2404-ansible@sha256:68af87df907605679a3fd572d0eb8b13330b160a3aa89fe9d89e31a4d8ef6ca0
MOLECULE_UBUNTU_2204_IMAGE ?= geerlingguy/docker-ubuntu2204-ansible@sha256:12e0dce9f846b01ac40dc27a3fbab027644e08c5f252ef664677ba962051328f
MOLECULE_ROCKYLINUX_9_IMAGE ?= geerlingguy/docker-rockylinux9-ansible@sha256:967060db9f42dc650fddc74ea175f7aec0b0c852884645a10c95ddaea517eb10

.PHONY: \
	help \
	diff-check \
	lint-all \
	molecule-coverage \
	molecule-destroy \
	molecule-phase-coverage \
	molecule-test-phases \
	molecule-test \
	molecule-test-all \
	molecule-test-rockylinux9 \
	molecule-test-ubuntu2204 \
	molecule-test-ubuntu2404 \
	pre-commit \
	static-checks

diff-check: ## Check the working tree diff for whitespace errors
	git diff --check

lint-all: ## Run ansible-lint on the whole repository
	$(ANSIBLE_LINT_CMD) .

pre-commit: ## Run all pre-commit hooks
	$(PRE_COMMIT_CMD)

static-checks: pre-commit diff-check ## Run static checks used by CI

molecule-coverage: ## Verify Molecule task coverage from the latest common scenario run
	$(MOLECULE_COVERAGE_CMD) \
		--project-root . \
		--coverage-file $(MOLECULE_COVERAGE_FILE) \
		--config $(MOLECULE_COVERAGE_CONFIG)

molecule-phase-coverage: ## Verify aggregate Molecule coverage for phase and migration scenarios
	$(MOLECULE_COVERAGE_CMD) \
		--project-root . \
		$(MOLECULE_PHASE_COVERAGE_ARGS) \
		--config $(MOLECULE_PHASE_COVERAGE_CONFIG)

molecule-test: molecule-test-ubuntu2404 ## Run Molecule tests on the default Ubuntu 24.04 platform

molecule-test-phases: ## Run phase and migration Molecule scenarios and enforce coverage on Ubuntu 24.04
	@set -eu; \
	for scenario in $(MOLECULE_PHASE_SCENARIOS); do \
		$(MAKE) molecule-test-ubuntu2404 \
			MOLECULE_SCENARIO=$$scenario \
			MOLECULE_COVERAGE_CONFIG=$(MOLECULE_PHASE_COVERAGE_CONFIG) \
			MOLECULE_COVERAGE_FILE=$(MOLECULE_ANSIBLE_HOME)/molecule/$$scenario-task-coverage.jsonl; \
	done; \
	if [ "$(MOLECULE_PHASE_ENFORCE_COVERAGE)" = "true" ]; then \
		$(MAKE) molecule-phase-coverage; \
	else \
		printf '%s\n' "Skipping aggregate phase coverage because MOLECULE_PHASE_ENFORCE_COVERAGE=$(MOLECULE_PHASE_ENFORCE_COVERAGE)"; \
	fi

molecule-test-ubuntu2404: ## Run Molecule tests on Ubuntu 24.04
	MOLECULE_IMAGE=$(MOLECULE_UBUNTU_2404_IMAGE) $(MOLECULE_CMD) test -s $(MOLECULE_SCENARIO)

molecule-test-ubuntu2204: ## Run Molecule tests on Ubuntu 22.04
	MOLECULE_IMAGE=$(MOLECULE_UBUNTU_2204_IMAGE) $(MOLECULE_CMD) test -s $(MOLECULE_SCENARIO)

molecule-test-rockylinux9: ## Run Molecule tests on Rocky Linux 9
	MOLECULE_IMAGE=$(MOLECULE_ROCKYLINUX_9_IMAGE) $(MOLECULE_CMD) test -s $(MOLECULE_SCENARIO)

molecule-test-all: ## Run Molecule tests on every supported platform
	$(MAKE) molecule-test-ubuntu2404
	$(MAKE) molecule-test-ubuntu2204
	$(MAKE) molecule-test-rockylinux9

molecule-destroy: ## Destroy the active Molecule scenario
	$(MOLECULE_CMD) destroy -s $(MOLECULE_SCENARIO)

help: ## Show available Make targets and what they do
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_.-]+:.*## / {printf "%-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST) | sort
