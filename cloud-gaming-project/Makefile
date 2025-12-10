PYTHON = sudo venv/bin/python3

.PHONY: help setup test-hol test-connection demo-all clean

help:
	@echo "=== TCP vs QUIC Demo ==="
	@echo "  make test-hol        - HoL blocking test"
	@echo "  make test-connection - Connection time test"
	@echo "  make demo-all        - Run all tests"

setup:
	venv/bin/python3 -m pip install aioquic matplotlib numpy

test-hol:
	@sudo service openvswitch-switch start 2>/dev/null || true
	$(PYTHON) tests/hol_blocking_test.py
	@mv HOL_BLOCKING_RESULTS.* results/graphs/ 2>/dev/null || true

test-connection:
	@sudo service openvswitch-switch start 2>/dev/null || true
	$(PYTHON) tests/connection_time_test.py
	@mv CONNECTION_TIME_RESULTS.* results/graphs/ 2>/dev/null || true

demo-all: test-hol test-connection
	@echo "=== DONE ==="
	@ls results/graphs/*.png 2>/dev/null

clean:
	rm -rf __pycache__ results/graphs/*.png
