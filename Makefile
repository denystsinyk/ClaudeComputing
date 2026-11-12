.DEFAULT_GOAL := help

.PHONY: help status

help: ## Show available development commands
	@printf 'SudoSolver development commands\n\n'
	@printf '  make help     Show available development commands\n'
	@printf '  make status   Show the Git working tree status\n'

status: ## Show the Git working tree status
	git status --short
