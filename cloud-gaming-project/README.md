# TCP vs QUIC - Cloud Gaming

Comparison of TCP and QUIC protocols for cloud gaming applications.

## Quick Start

```bash
make test-hol        # Head-of-Line blocking test
make test-connection # Connection time test
make demo-all        # Run both tests
```

## Project Structure

```
├── src/              # Protocol implementations
│   ├── quic_protocol.py
│   ├── quic_sender.py
│   ├── quic_receiver.py
│   └── rquic_protocol.py   # TODO: Reliable QUIC with FEC
├── tests/            # Test scripts
│   ├── hol_blocking_test.py
│   └── connection_time_test.py
├── results/
│   └── graphs/       # Generated graphs (PNG)
└── archive/          # Old files
```

## Results

Graphs are generated in `results/graphs/`:
- `HOL_BLOCKING_RESULTS.png` - HoL blocking comparison
- `CONNECTION_TIME_RESULTS.png` - Connection time vs RTT

## TODO: Real Improvements

1. **RQUIC (Reliable QUIC with FEC)**
   - Forward Error Correction for packet loss recovery
   - Adaptive redundancy based on network conditions

2. **BBR Congestion Control**
   - Replace Cubic with BBR algorithm
   - Better bandwidth estimation

3. **0-RTT Connection**
   - Implement session resumption
   - Faster reconnection after network switch
