PYTHON = sudo venv/bin/python3

.PHONY: help setup test-hol test-hol-rquic test-connection test-connection-3proto test-multichannel demo-all clean

help:
	@echo "=== TCP vs QUIC vs rQUIC Demo ==="
	@echo "  make test-hol             - HoL blocking (TCP vs QUIC)"
	@echo "  make test-hol-rquic       - HoL blocking (TCP vs QUIC vs rQUIC)"
	@echo "  make test-connection      - Connection time (TCP+TLS vs QUIC)"
	@echo "  make test-connection-3proto - Connection time (TCP vs QUIC vs rQUIC)"
	@echo "  make test-multichannel    - 4-channel test (VIDEO/AUDIO/CONTROL)"
	@echo "  make demo-all             - Run all tests"

setup:
	venv/bin/python3 -m pip install aioquic matplotlib numpy

test-hol:
	@sudo service openvswitch-switch start 2>/dev/null || true
	$(PYTHON) tests/hol_blocking_test.py
	@mv HOL_BLOCKING_RESULTS.* results/graphs/ 2>/dev/null || true

test-hol-rquic:
	@sudo service openvswitch-switch start 2>/dev/null || true
	$(PYTHON) tests/hol_blocking_test_with_rquic.py
	@mv HOL_BLOCKING_RESULTS.* results/graphs/ 2>/dev/null || true

test-connection:
	@sudo service openvswitch-switch start 2>/dev/null || true
	$(PYTHON) tests/connection_time_test.py
	@mv CONNECTION_TIME_RESULTS.* results/graphs/ 2>/dev/null || true

test-connection-3proto:
	@sudo service openvswitch-switch start 2>/dev/null || true
	$(PYTHON) tests/connection_3proto_test.py
	@mv CONNECTION_3PROTO_RESULTS.* results/graphs/ 2>/dev/null || true

test-multichannel:
	@sudo service openvswitch-switch start 2>/dev/null || true
	$(PYTHON) tests/multi_channel_test.py
	@mv MULTI_CHANNEL_RESULTS.* results/graphs/ 2>/dev/null || true

demo-all: test-hol-rquic test-connection-3proto test-multichannel
	@echo "=== DONE ==="
	@ls results/graphs/*.png 2>/dev/null

clean:
	rm -rf __pycache__ results/graphs/*.png
