UV_PYTHON ?= 3.12
UV_RUN = uv run --python $(UV_PYTHON)

ANSIBLE_LINT_CMD = $(UV_RUN) --group lint ansible-lint -c .ansible-lint-tests.yml
PRE_COMMIT_CMD = $(UV_RUN) --group lint pre-commit run --all-files
MOLECULE_ANSIBLE_HOME ?= $(CURDIR)/.ansible
MOLECULE_CALLBACK_PLUGINS ?= $(CURDIR)/molecule/common/callback_plugins
MOLECULE_COVERAGE_CONFIG ?= molecule/$(MOLECULE_SCENARIO)/coverage.yml
MOLECULE_COVERAGE_FILE ?= $(MOLECULE_ANSIBLE_HOME)/molecule/common-task-coverage.jsonl
MOLECULE_COVERAGE_PLATFORM ?=
MOLECULE_COVERAGE_CMD = $(UV_RUN) --group molecule python molecule/common/scripts/verify_task_coverage.py
MOLECULE_COVERAGE_PLATFORM_ARGS = $(if $(MOLECULE_COVERAGE_PLATFORM),--platform $(MOLECULE_COVERAGE_PLATFORM),)
MOLECULE_COLLECTIONS_PATH ?= $(MOLECULE_ANSIBLE_HOME)/collections
MOLECULE_EPHEMERAL_DIRECTORY ?=
MOLECULE_PLATFORM_NAME ?= instance
MOLECULE_CMD = MOLECULE_ANSIBLE_HOME=$(MOLECULE_ANSIBLE_HOME) MOLECULE_CALLBACK_PLUGINS=$(MOLECULE_CALLBACK_PLUGINS) MOLECULE_COLLECTIONS_PATH=$(MOLECULE_COLLECTIONS_PATH) MOLECULE_COVERAGE_CONFIG=$(MOLECULE_COVERAGE_CONFIG) MOLECULE_COVERAGE_FILE=$(MOLECULE_COVERAGE_FILE) MOLECULE_EPHEMERAL_DIRECTORY=$(MOLECULE_EPHEMERAL_DIRECTORY) MOLECULE_PLATFORM_NAME=$(MOLECULE_PLATFORM_NAME) ANSIBLE_HOME=$(MOLECULE_ANSIBLE_HOME) ANSIBLE_COLLECTIONS_PATH=$(MOLECULE_COLLECTIONS_PATH):/usr/share/ansible/collections ANSIBLE_COLLECTIONS_SCAN_SYS_PATH=false $(UV_RUN) --group molecule molecule
MOLECULE_PHASE_COVERAGE_CONFIG ?= molecule/phase-coverage.yml
MOLECULE_PHASE_ENFORCE_COVERAGE ?= true
MOLECULE_PHASE_PLATFORM ?= ubuntu2404
MOLECULE_PHASE_SCENARIOS ?= phase-lifecycle-mysql phase-lifecycle-sqlite phase-resume-checkpoints phase-restore-success phase-guardrails-negative elasticsearch-readiness-cutover-negative elasticsearch-runtime-negative elasticsearch-reindex-negative elasticsearch-restore-validate-cleanup-negative elasticsearch-search-total-cap
MOLECULE_PHASE_COVERAGE_ARGS = $(foreach scenario,$(MOLECULE_PHASE_SCENARIOS),--coverage-file $(MOLECULE_ANSIBLE_HOME)/molecule/$(MOLECULE_PHASE_PLATFORM)-$(scenario)-task-coverage.jsonl)
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
	molecule-phase-coverage-rockylinux9 \
	molecule-phase-coverage-ubuntu2204 \
	molecule-phase-coverage-ubuntu2404 \
	molecule-test-phases \
	molecule-test-phases-platform \
	molecule-test-phases-rockylinux9 \
	molecule-test-phases-ubuntu2204 \
	molecule-test-phases-ubuntu2404 \
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
	@$(MOLECULE_COVERAGE_CMD) \
		--project-root . \
		--coverage-file $(MOLECULE_COVERAGE_FILE) \
		$(MOLECULE_COVERAGE_PLATFORM_ARGS) \
		--config $(MOLECULE_COVERAGE_CONFIG)

molecule-phase-coverage: ## Verify aggregate Molecule coverage for phase and migration scenarios
	@$(MOLECULE_COVERAGE_CMD) \
		--project-root . \
		$(MOLECULE_PHASE_COVERAGE_ARGS) \
		--platform $(MOLECULE_PHASE_PLATFORM) \
		--config $(MOLECULE_PHASE_COVERAGE_CONFIG)

molecule-phase-coverage-rockylinux9: ## Verify phase and migration coverage for Rocky Linux 9
	@$(MAKE) --no-print-directory molecule-phase-coverage MOLECULE_PHASE_PLATFORM=rockylinux9

molecule-phase-coverage-ubuntu2204: ## Verify phase and migration coverage for Ubuntu 22.04
	@$(MAKE) --no-print-directory molecule-phase-coverage MOLECULE_PHASE_PLATFORM=ubuntu2204

molecule-phase-coverage-ubuntu2404: ## Verify phase and migration coverage for Ubuntu 24.04
	@$(MAKE) --no-print-directory molecule-phase-coverage MOLECULE_PHASE_PLATFORM=ubuntu2404

molecule-test: molecule-test-ubuntu2404 ## Run Molecule tests on the default Ubuntu 24.04 platform

molecule-test-phases: molecule-test-phases-ubuntu2404 ## Run phase and migration Molecule scenarios and enforce coverage on Ubuntu 24.04

molecule-test-phases-rockylinux9: ## Run phase and migration Molecule scenarios and enforce coverage on Rocky Linux 9
	$(MAKE) molecule-test-phases-platform \
		MOLECULE_PHASE_PLATFORM=rockylinux9 \
		MOLECULE_PHASE_TEST_TARGET=molecule-test-rockylinux9

molecule-test-phases-ubuntu2204: ## Run phase and migration Molecule scenarios and enforce coverage on Ubuntu 22.04
	$(MAKE) molecule-test-phases-platform \
		MOLECULE_PHASE_PLATFORM=ubuntu2204 \
		MOLECULE_PHASE_TEST_TARGET=molecule-test-ubuntu2204

molecule-test-phases-ubuntu2404: ## Run phase and migration Molecule scenarios and enforce coverage on Ubuntu 24.04
	$(MAKE) molecule-test-phases-platform \
		MOLECULE_PHASE_PLATFORM=ubuntu2404 \
		MOLECULE_PHASE_TEST_TARGET=molecule-test-ubuntu2404

molecule-test-phases-platform:
	@set -eu; \
	for scenario in $(MOLECULE_PHASE_SCENARIOS); do \
		$(MAKE) $(MOLECULE_PHASE_TEST_TARGET) \
			MOLECULE_SCENARIO=$$scenario \
			MOLECULE_COVERAGE_CONFIG=$(MOLECULE_PHASE_COVERAGE_CONFIG) \
			MOLECULE_COVERAGE_FILE=$(MOLECULE_ANSIBLE_HOME)/molecule/$(MOLECULE_PHASE_PLATFORM)-$$scenario-task-coverage.jsonl \
			MOLECULE_EPHEMERAL_DIRECTORY=$(MOLECULE_ANSIBLE_HOME)/molecule/ephemeral/$(MOLECULE_PHASE_PLATFORM)-$$scenario \
			MOLECULE_PLATFORM_NAME=$(MOLECULE_PHASE_PLATFORM)-instance; \
	done; \
	if [ "$(MOLECULE_PHASE_ENFORCE_COVERAGE)" = "true" ]; then \
		$(MAKE) molecule-phase-coverage MOLECULE_PHASE_PLATFORM=$(MOLECULE_PHASE_PLATFORM); \
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
