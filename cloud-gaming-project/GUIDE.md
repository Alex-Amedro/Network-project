# Test Guide - TCP vs QUIC vs rQUIC

## What the tests do

### Test 1: HoL Blocking (`make test-hol`)

**Setup:**
- Mininet creates 2 hosts connected via switch
- Sends 50 HIGH priority + 50 LOW priority messages
- Tests under 3 conditions: Ideal, 5% loss, 10% loss

**What happens:**
1. **TCP**: All data goes through ONE connection
   - When packet lost → TCP waits for retransmission
   - ALL streams blocked (HIGH and LOW)
   - Result: HIGH jitter on both streams

2. **QUIC**: Uses INDEPENDENT streams
   - When HIGH packet lost → only HIGH waits
   - LOW continues normally
   - Result: LOW jitter, especially on LOW stream

3. **rQUIC**: Custom UDP + selective ACK
   - Retransmits only lost packets
   - No connection setup overhead
   - Result: Similar to QUIC but simpler

**Graph interpretation:**
- Left graph: HIGH priority jitter
- Right graph: LOW priority jitter
- **Red bars (TCP)**: Should be HIGH under packet loss
- **Blue bars (QUIC)**: Should be LOW (independent streams)
- **Green bars (rQUIC)**: Should be LOW (selective retransmission)

---

### Test 2: Connection Time (`make test-connection`)

**Setup:**
- Tests connection establishment at different RTTs: 10ms, 50ms, 100ms, 200ms
- Compares TCP+TLS vs QUIC

**What happens:**
1. **TCP+TLS**: 
   - 3-way handshake (1.5 RTT)
   - TLS handshake (2 RTT)
   - Total: ~3.5 RTT

2. **QUIC**:
   - Crypto integrated in handshake
   - Total: ~1 RTT

**Graph interpretation:**
- Left graph: Absolute connection time (ms)
  - Red line (TCP+TLS): Steep slope
  - Blue line (QUIC): Gentle slope
  
- Right graph: Time/RTT ratio
  - Dashed red line: TCP theoretical (3.5x)
  - Dashed blue line: QUIC theoretical (1x)
  - Bars show actual measured ratios

---

## What to say during presentation

### HoL Blocking Test

> "TCP has a fundamental problem called Head-of-Line blocking. When one packet is lost, ALL data is blocked until retransmission."
>
> "QUIC solves this with independent streams. If HIGH priority packet is lost, LOW priority continues."
>
> "Look at the graph: TCP (red) has 60ms jitter under 5% loss. QUIC (blue) has only 1.3ms. That's 40x better."

### Connection Time Test

> "TCP+TLS needs 3.5 round-trips to establish a secure connection. QUIC does it in 1 round-trip."
>
> "At 200ms RTT (US server), TCP takes 1043ms to connect. QUIC takes 649ms. 40% faster."
>
> "For cloud gaming, this means faster game launch and quicker reconnection after network switch."

---

## Key numbers to remember

| Metric | TCP | QUIC | Improvement |
|--------|-----|------|-------------|
| Jitter (5% loss) | ~60ms | ~1.3ms | 40x better |
| Connection (200ms RTT) | 1043ms | 649ms | 40% faster |
| Theoretical RTT ratio | 3.5x | 1x | 3.5x faster |

---

## Commands

```bash
make test-hol        # Run HoL blocking test
make test-connection # Run connection time test
make demo-all        # Run both tests
```

Results in `results/graphs/`:
- `HOL_BLOCKING_RESULTS.png`
- `CONNECTION_TIME_RESULTS.png`
