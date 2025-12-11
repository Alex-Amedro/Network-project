# Cloud Gaming Network Protocol Comparison - Demo Guide

## Quick Start Commands

All tests are automated via Makefile. Simply run:

```bash
make help           # Show all available commands
make demo-all       # Run all main demo tests
make clean          # Clean up generated files
```

---

## Available Test Commands

### 1. Head-of-Line Blocking Test (TCP vs QUIC)
```bash
make test-hol
```
**What it demonstrates:**
- TCP suffers from HoL blocking when packets are lost
- QUIC's independent streams avoid HoL blocking
- Shows jitter comparison under 5% packet loss

**Graph output:** `HOL_BLOCKING_COMPARISON.png`

---

### 2. Head-of-Line Blocking Test (3 Protocols)
```bash
make test-hol-rquic
```
**What it demonstrates:**
- Compares TCP, QUIC, and rQUIC under packet loss (5%)
- Shows how rQUIC (custom protocol) handles HoL blocking
- Tests HIGH and LOW priority streams

**Graph output:** `HOL_BLOCKING_3PROTO.png`

**Expected results:**
- TCP: ~17ms jitter (HoL blocking impact)
- QUIC: ~0.35ms jitter (no HoL blocking)
- rQUIC: ~0.53ms jitter (no HoL blocking)

---

### 3. Connection Time Test (TCP+TLS vs QUIC)
```bash
make test-connection
```
**What it demonstrates:**
- TCP requires 3-way handshake + TLS handshake (2 RTTs minimum)
- QUIC combines connection + encryption in 1-RTT
- Measures connection establishment time

**Graph output:** `CONNECTION_TIME_COMPARISON.png`

---

### 4. Connection Time Test (3 Protocols)
```bash
make test-connection-3proto
```
**What it demonstrates:**
- Compares TCP+TLS, QUIC, and rQUIC connection times
- Shows rQUIC's simplified handshake

**Graph output:** `CONNECTION_TIME_3PROTO.png`

---

### 5. Multi-Channel Test
```bash
make test-multichannel
```
**What it demonstrates:**
- Simulates real cloud gaming scenario with 4 channels:
  - **VIDEO**: High-bandwidth (1 MB frames)
  - **AUDIO**: Medium-bandwidth (10 KB frames)
  - **INPUT**: Low-latency commands (100 bytes)
  - **CHAT**: Text messages (200 bytes)
- Tests under network stress (10% loss, 20ms delay)

**Graph output:** `MULTICHANNEL_PERFORMANCE.png`

**Expected results:**
- INPUT channel maintains low latency even under loss
- VIDEO/AUDIO channels show higher latency but still functional
- QUIC's stream multiplexing keeps channels independent

---

### 6. Latency Under Packet Loss Test
```bash
make test-latency
```
**What it demonstrates:**
- Measures round-trip latency under increasing packet loss
- Tests 5 scenarios: 0%, 1%, 3%, 5%, 10% loss
- Shows how TCP latency explodes under loss vs QUIC/rQUIC

**Graph output:** `LATENCY_3PROTO_RESULTS.png`

**Expected results:**
- **0% loss**: All protocols ~80ms RTT
- **5% loss**: TCP ~151ms, QUIC ~81ms, rQUIC ~83ms
- **10% loss**: TCP ~367ms (!), QUIC ~103ms, rQUIC ~108ms

---

## Complete Demo Sequence

Run all main tests in one command:
```bash
make demo-all
```

This runs:
1. `test-hol-rquic` - HoL blocking comparison (3 protocols)
2. `test-connection-3proto` - Connection time comparison
3. `test-multichannel` - Real cloud gaming simulation
4. `test-latency` - Latency under packet loss

**Total runtime:** ~2-3 minutes

---

## Graph Locations

All graphs are saved in: `results/graphs/`

Individual graphs are also saved in the project root for quick access:
- `HOL_BLOCKING_COMPARISON.png`
- `HOL_BLOCKING_3PROTO.png`
- `CONNECTION_TIME_COMPARISON.png`
- `CONNECTION_TIME_3PROTO.png`
- `MULTICHANNEL_PERFORMANCE.png`
- `LATENCY_3PROTO_RESULTS.png`

---

## Presentation Talking Points

### Why QUIC for Cloud Gaming?

1. **No Head-of-Line Blocking**
   - TCP blocks all data if one packet is lost
   - QUIC's independent streams keep video/audio/input separate
   - Demo: `test-hol-rquic` shows 50x less jitter

2. **Faster Connection Setup**
   - TCP+TLS: 2 RTTs minimum
   - QUIC: 1-RTT (or 0-RTT on reconnection)
   - Demo: `test-connection-3proto` shows connection time difference

3. **Better Loss Recovery**
   - TCP retransmits sequentially (causes cascading delays)
   - QUIC retransmits per-stream (isolated impact)
   - Demo: `test-latency` shows TCP latency explodes under loss

4. **Stream Prioritization**
   - Critical data (user input) gets priority
   - Less critical data (chat) doesn't block important streams
   - Demo: `test-multichannel` shows 4-channel multiplexing

### rQUIC: Educational Implementation

- Custom UDP-based protocol demonstrating QUIC concepts
- Implements: selective retransmission, ACK/NACK, independent streams
- **70-75% realistic** compared to real QUIC
- Purpose: Show core principles without full complexity
- See `RQUIC_EXPLAINED.md` for detailed explanation

---

## Network Conditions Simulated

All tests use **Mininet** network emulation with:
- **Bandwidth:** 10 Mbps
- **Delay:** 10-100ms (varies by test)
- **Packet Loss:** 0-10% (varies by test)
- **Queue:** 1000 packets

These simulate realistic internet conditions for cloud gaming.

---

## Troubleshooting

**Test hangs or doesn't finish:**
```bash
make clean-all
```

**Need to restart network:**
```bash
make clean
sudo mn -c
```

**Permission issues:**
- Tests require `sudo` (Mininet needs root)
- Password prompt is normal

---

## File Structure

```
cloud-gaming-project/
├── src/
│   ├── quic_protocol.py      # QUIC implementation
│   ├── quic_sender.py
│   ├── quic_receiver.py
│   └── rquic_protocol.py     # Custom rQUIC implementation
├── tests/
│   ├── hol_blocking_test.py
│   ├── hol_blocking_test_with_rquic.py
│   ├── connection_time_test.py
│   ├── connection_3proto_test.py
│   ├── multi_channel_test.py
│   └── latency_test_3proto.py
├── results/graphs/            # All generated graphs
├── Makefile                   # All test commands
├── PRESENTATION.md            # This file
├── IMPLEMENTATION_DETAILLEE.md # Detailed technical docs (FR)
└── RQUIC_EXPLAINED.md         # rQUIC architecture explanation
```

---

## Key Metrics to Highlight

| Protocol | HoL Blocking | Connection Time | Latency @ 10% Loss |
|----------|--------------|-----------------|---------------------|
| **TCP**  | ❌ Yes       | ~2 RTTs         | ~367ms             |
| **QUIC** | ✅ No        | ~1 RTT          | ~103ms             |
| **rQUIC**| ✅ No        | ~1 RTT          | ~108ms             |

---

## Demo Recommendations

**For 5-minute presentation:**
1. Run `make demo-all` before presenting
2. Show graphs in order: HoL → Connection → Latency → Multichannel
3. Emphasize the 367ms vs 103ms latency difference (10% loss scenario)

**For 10-minute presentation:**
1. Live demo: `make test-latency` (takes ~30 seconds)
2. Show code: `src/rquic_protocol.py` (explain selective retransmission)
3. Show all 6 graphs with detailed explanations

**For technical deep-dive:**
- Refer to `IMPLEMENTATION_DETAILLEE.md` for complete technical details
- Show packet flow diagrams
- Explain rQUIC vs real QUIC differences

---

## Contact & Resources

- Project repository: Network-project
- Implementation details: `IMPLEMENTATION_DETAILLEE.md`
- rQUIC architecture: `RQUIC_EXPLAINED.md`
- Quick guide: `GUIDE.md`
