# Makefile — for Unix/CI graders and anyone with `make` available.
# On Windows without `make` (this project was built on such a machine —
# see LIMITATIONS.md), run the command on the right of each target directly,
# or use WSL/Git Bash where this file works as-is.

.PHONY: setup test eval scenarios demo clean

setup:
	python -m venv .venv
	. .venv/bin/activate; pip install -r requirements.txt

test:
	python -m pytest -q

eval:
	python -m data.generate --seed 42 --count 800
	python -m eval.run_eval
	python -m eval.scenarios

demo:
	python -m src.cli list --limit 10
	@echo ""
	@echo "Try: python -m src.cli explain <mandate_id>"
	@echo "Try: python -m src.cli compare <mandate_id>"

clean:
	rm -rf .venv __pycache__ .pytest_cache results/*.json EVALUATION.md
	find . -name "__pycache__" -type d -exec rm -rf {} +
