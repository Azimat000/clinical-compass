PYTHON ?= python3
VENV ?= .venv
RUN = $(VENV)/bin/python

.PHONY: setup migrate seed run worker test check smoke
setup:
	$(PYTHON) -m venv $(VENV)
	$(RUN) -m pip install -r apps/requirements.lock
migrate:
	$(RUN) -m apps.compass migrate
seed:
	$(RUN) -m apps.compass seed-demo
run:
	$(RUN) -m apps.compass serve
worker:
	$(RUN) -m apps.compass worker
test:
	$(RUN) -m unittest discover -s apps/tests -v
smoke:
	$(RUN) apps/tests/smoke_restart.py
check: test smoke
	$(RUN) -m pip check
	$(PYTHON) tools/validate_synthetic.py
	$(PYTHON) -m unittest discover -s tools -p 'test_*.py' -v
