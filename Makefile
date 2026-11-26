.DEFAULT_GOAL := help

.PHONY: help status runner-build runner-example

help: ## Show available development commands
	@printf 'SudoSolver development commands\n\n'
	@printf '  make help     Show available development commands\n'
	@printf '  make status   Show the Git working tree status\n'
	@printf '  make runner-build                         Build the local runner image\n'
	@printf '  make runner-example MODE=run SOLUTION=starter   Run the example in Docker\n'

status: ## Show the Git working tree status
	git status --short

runner-build: ## Build the local runner image
	docker build -t sudosolver-runner:local services/runner

runner-example: runner-build ## Run the task-store example in the local runner
	mkdir -p services/runner/.local/input services/runner/.local/output
	python3 services/runner/build_example_job.py --mode $(or $(MODE),run) --solution $(or $(SOLUTION),starter) --output services/runner/.local/input/job.zip
	docker run --rm --read-only --network none --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m --cpus 1 --tmpfs /tmp:rw,nosuid,size=32m --user "$(shell id -u):$(shell id -g)" --mount type=bind,src="$(CURDIR)/services/runner/.local/input",dst=/input,readonly --mount type=bind,src="$(CURDIR)/services/runner/.local/output",dst=/output -e RUNNER_INPUT=/input/job.zip -e RUNNER_OUTPUT=/output/result.json sudosolver-runner:local
	python3 -m json.tool services/runner/.local/output/result.json
