#!/usr/bin/env python3

import socket
import struct
import threading
import time
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Set, Optional
import argparse
from enum import IntEnum


PACKET_DATA = 0x01
PACKET_ACK = 0x02
PACKET_NACK = 0x03

#hhhhhhhhhhhh
class FramePriority(IntEnum):
    CRITICAL = 0  # 500ms
    HIGH = 1      # 100ms
    MEDIUM = 2    # 50ms 
    LOW = 3       # 20ms


@dataclass
class rQUICStats:
    frames_sent: int = 0
    frames_received: int = 0
    total_bytes_sent: int = 0
    total_bytes_received: int = 0
    retransmissions: int = 0
    acks_sent: int = 0
    acks_received: int = 0
    nacks_sent: int = 0
    
    # HHHHHHHHHHHHHH
    frames_dropped_ttl: int = 0
    
    
    frame_times: list = field(default_factory=list)
    frame_sizes: list = field(default_factory=list)
    rtt_samples: list = field(default_factory=list)
    start_time: float = 0
    end_time: float = 0


class rQUICServer:
    
    def __init__(self, host: str = '0.0.0.0', port: int = 5000):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.settimeout(1.0)
        
        self.stats = rQUICStats()
        self.received_frames: Set[int] = set()
        self.expected_frame = 0
        self.running = False
        self.client_addr = None
        
    def start(self, duration: int = 30):
        self.sock.bind((self.host, self.port))
        self.running = True
        self.stats.start_time = time.time()
        
        print(f"[rQUIC Server] Écoute sur {self.host}:{self.port}")
        
        end_time = time.time() + duration + 5
        
        while self.running and time.time() < end_time:
            try:
                data, addr = self.sock.recvfrom(65535)
                self.client_addr = addr
                self.handle_packet(data, addr)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Erreur: {e}")
                break
        
        self.stats.end_time = time.time()
        self.sock.close()
        
        return self.get_results()
    
    def handle_packet(self, data: bytes, addr):
        if len(data) < 9:
            return
        
        packet_type = data[0]
        
        #format
        if packet_type == PACKET_DATA:
            #hhhhhhhhhhhh
            if len(data) >= 10:
                frame_id, frame_size, priority = struct.unpack('!IIB', data[1:10])
                frame_data = data[10:10+frame_size]
            else:
                frame_id, frame_size = struct.unpack('!II', data[1:9])
                frame_data = data[9:9+frame_size]
                priority = FramePriority.MEDIUM  
            
            recv_time = time.time()
            
            if frame_id not in self.received_frames:
                self.received_frames.add(frame_id)
                self.stats.frames_received += 1
                self.stats.total_bytes_received += len(frame_data)
                self.stats.frame_times.append(recv_time)
                self.stats.frame_sizes.append(len(frame_data))
                
                if self.stats.frames_received % 60 == 0:
                    print(f"[rQUIC] Frames reçues: {self.stats.frames_received}, "
                          f"Retransmissions demandées: {self.stats.nacks_sent}")
            
            self.send_ack(frame_id, addr)
            self.check_missing_frames(frame_id, addr)
    
    def send_ack(self, frame_id: int, addr):
        ack_packet = struct.pack('!BI', PACKET_ACK, frame_id)
        self.sock.sendto(ack_packet, addr)
        self.stats.acks_sent += 1
    
    def send_nack(self, frame_id: int, addr):
        nack_packet = struct.pack('!BI', PACKET_NACK, frame_id)
        self.sock.sendto(nack_packet, addr)
        self.stats.nacks_sent += 1
    
    def check_missing_frames(self, latest_frame: int, addr):
        window_start = max(0, latest_frame - 100)
        
        for frame_id in range(window_start, latest_frame):
            if frame_id not in self.received_frames:
                self.send_nack(frame_id, addr)
    
    def get_results(self) -> dict:
        duration = self.stats.end_time - self.stats.start_time
        
        delays = []
        for i in range(1, len(self.stats.frame_times)):
            delay = (self.stats.frame_times[i] - self.stats.frame_times[i-1]) * 1000
            delays.append(delay)
        
        avg_delay = sum(delays) / len(delays) if delays else 0
        
        jitter = 0
        if len(delays) > 1:
            jitter = sum(abs(delays[i] - delays[i-1]) for i in range(1, len(delays))) / (len(delays) - 1)
        
        return {
            'protocol': 'rQUIC',
            'port': self.port,
            'frames_received': self.stats.frames_received,
            'total_bytes': self.stats.total_bytes_received,
            'start_time': self.stats.start_time,
            'end_time': self.stats.end_time,
            'duration_sec': duration,
            'avg_fps': self.stats.frames_received / duration if duration > 0 else 0,
            'throughput_mbps': (self.stats.total_bytes_received * 8) / (duration * 1_000_000) if duration > 0 else 0,
            'avg_inter_frame_delay_ms': avg_delay,
            'jitter_ms': jitter,
            'acks_sent': self.stats.acks_sent,
            'nacks_sent': self.stats.nacks_sent,
            'retransmission_requests': self.stats.nacks_sent,
        }


class rQUICClient:
    
    def __init__(self, server_host: str, server_port: int = 5000):
        self.server_host = server_host
        self.server_port = server_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.001)
        
        self.stats = rQUICStats()
        
        self.pending_acks: Dict[int, tuple] = {}
        self.acked_frames: Set[int] = set()
        self.max_retries = 3
        self.rto = 0.1
        self.srtt = 0.1
         # HHHHHHHHHHHHHH
        self.frame_ttl = 0.050  # 50ms
        
        #temp de drop en fonction de la criticité
        self.frame_ttl_by_priority = {
            FramePriority.CRITICAL: 0.5,    # 500ms
            FramePriority.HIGH: 0.1,        # 100ms
            FramePriority.MEDIUM: 0.050,    # 50ms 
            FramePriority.LOW: 0.020        # 20ms
        }
        
        self.fps = 60
        self.avg_frame_size = 50000
        self.max_frame_size = 60000
        
    def generate_frame_size(self) -> int:
        is_i_frame = random.random() < 0.1
        if is_i_frame:
            size = int(random.gauss(self.avg_frame_size * 2.5, self.avg_frame_size * 0.5))
        else:
            size = int(random.gauss(self.avg_frame_size * 0.7, self.avg_frame_size * 0.2))
        return max(1000, min(size, self.max_frame_size))
    
    #
    def detect_frame_priority(self, frame_size: int) -> FramePriority:
        if frame_size > 80000:
            return FramePriority.HIGH
        elif frame_size > 20000:
            return FramePriority.MEDIUM
        else:
            return FramePriority.LOW
    
    def send_frame(self, frame_id: int, priority: Optional[FramePriority] = None) -> int:
        size = self.generate_frame_size()
        data = bytes(random.getrandbits(8) for _ in range(size))
        
        #pas de priorité envoyer avec une priorité au talent
        if priority is None:
            priority = self.detect_frame_priority(size)
        
        packet = struct.pack('!BIIB', PACKET_DATA, frame_id, size, priority) + data
        
        self.sock.sendto(packet, (self.server_host, self.server_port))
        
        self.pending_acks[frame_id] = (packet, time.time(), 0, priority)
        
        self.stats.frames_sent += 1
        self.stats.total_bytes_sent += len(packet)
        self.stats.frame_sizes.append(size)
        
        return size
    
    def process_acks(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(1024)
                if len(data) < 5:
                    continue
                
                packet_type = data[0]
                frame_id = struct.unpack('!I', data[1:5])[0]
                
                #hhhh adaptation
                if packet_type == PACKET_ACK:
                    if frame_id in self.pending_acks:
                        
                        send_time = self.pending_acks[frame_id][1]
                        rtt = time.time() - send_time
                        self.stats.rtt_samples.append(rtt * 1000)
                        
                        self.srtt = 0.875 * self.srtt + 0.125 * rtt
                        self.rto = max(0.05, min(1.0, self.srtt * 2))
                        
                        del self.pending_acks[frame_id]
                        self.acked_frames.add(frame_id)
                        self.stats.acks_received += 1
                
                elif packet_type == PACKET_NACK:
                    self.retransmit_frame(frame_id)
                    
            except socket.timeout:
                break
            except BlockingIOError:
                break
    
    def retransmit_frame(self, frame_id: int):
        if frame_id not in self.pending_acks:
            return
        
        #recup la prio
        packet, send_time, retries, priority = self.pending_acks[frame_id]
        
        # HHHHHHHHHHHHHH
        frame_age = time.time() - send_time
        # recup le temp
        ttl_for_this_frame = self.frame_ttl_by_priority[priority]
        
        if frame_age > ttl_for_this_frame:
            
            del self.pending_acks[frame_id]
            self.stats.frames_dropped_ttl += 1
            
            # Log 
            if self.stats.frames_dropped_ttl % 10 == 0:
                
                priority_name = FramePriority(priority).name
                print(f"[rQUIC TTL] {self.stats.frames_dropped_ttl} frames droppées "
                      f"(obsolètes > {ttl_for_this_frame*1000:.0f}ms, dernière: {priority_name})")
            return
        
        # Frame ok
        if retries < self.max_retries:
            self.sock.sendto(packet, (self.server_host, self.server_port))
            self.pending_acks[frame_id] = (packet, time.time(), retries + 1, priority)
            self.stats.retransmissions += 1
    
    def check_timeouts(self):
        current_time = time.time()
        frames_to_drop = []
        frames_to_retransmit = []
         # HHHHHHHHHHHHHH
        for frame_id, (packet, send_time, retries, priority) in list(self.pending_acks.items()):
            frame_age = current_time - send_time
            
            ttl_for_this_frame = self.frame_ttl_by_priority[priority]
        
            if frame_age > ttl_for_this_frame:
                # Frame morte
                frames_to_drop.append(frame_id)
                
            elif current_time - send_time > self.rto:
                # Frame ok
                if retries < self.max_retries:
                    frames_to_retransmit.append(frame_id)
                else:
                    del self.pending_acks[frame_id]
        
         # HHHHHHHHHHHHHH
        for frame_id in frames_to_drop:
            del self.pending_acks[frame_id]
            self.stats.frames_dropped_ttl += 1
        
         # HHHHHHHHHHHHHH on reconstruit avec la prio
        for frame_id in frames_to_retransmit:
            packet, send_time, retries, priority = self.pending_acks[frame_id]
            self.sock.sendto(packet, (self.server_host, self.server_port))
            self.pending_acks[frame_id] = (packet, current_time, retries + 1, priority)
            self.stats.retransmissions += 1
    
    def run(self, duration: int = 30) -> dict:
        print(f"[rQUIC Client] Connexion à {self.server_host}:{self.server_port}")
        print(f"[rQUIC Client] Durée: {duration}s, FPS: {self.fps}")
        
        self.stats.start_time = time.time()
        start_time = self.stats.start_time
        frame_id = 0
        frame_interval = 1.0 / self.fps
        last_report = start_time
        
        while time.time() - start_time < duration:
            frame_start = time.time()
            
            self.send_frame(frame_id)
            frame_id += 1
            
            self.process_acks()
            self.check_timeouts()
            
            if time.time() - last_report >= 1.0:
                elapsed = time.time() - start_time
                print(f"[{elapsed:.1f}s] Envoyées: {self.stats.frames_sent}, "
                      f"ACKs: {self.stats.acks_received}, "
                      f"Retrans: {self.stats.retransmissions}")
                last_report = time.time()
            
            elapsed_frame = time.time() - frame_start
            sleep_time = frame_interval - elapsed_frame
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        time.sleep(0.5)
        self.process_acks()
        
        self.stats.end_time = time.time()
        self.sock.close()
        
        return self.get_results()
    
    def get_results(self) -> dict:
        avg_rtt = sum(self.stats.rtt_samples) / len(self.stats.rtt_samples) if self.stats.rtt_samples else 0
        
        return {
            'frames_sent': self.stats.frames_sent,
            'total_bytes': self.stats.total_bytes_sent,
            'start_time': time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.stats.start_time)),
            'protocol': 'rQUIC',
            'fps': self.fps,
            'frame_sizes': self.stats.frame_sizes,
            'retransmissions': self.stats.retransmissions,
            'acks_received': self.stats.acks_received,
            
            # HHHHHHHHHHHHHH
            'frames_dropped_ttl': self.stats.frames_dropped_ttl,
            
            'avg_rtt_ms': avg_rtt,
            'delivery_rate': (self.stats.acks_received / self.stats.frames_sent * 100) if self.stats.frames_sent > 0 else 0,
        }

def run_server(host: str, port: int, duration: int, output_file: str):
    """Lance le serveur rQUIC"""
    server = rQUICServer(host, port)
    results = server.start(duration)
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"[rQUIC Server] Résultats sauvegardés: {output_file}")
    print(f"[rQUIC] Frames reçues: {results['frames_received']}")
    print(f"[rQUIC] Retransmissions demandées: {results['retransmission_requests']}")
    
    return results


def run_client(server_host: str, server_port: int, duration: int, output_file: str):
    """Lance le client rQUIC"""
    client = rQUICClient(server_host, server_port)
    results = client.run(duration)
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"[rQUIC Client] Résultats sauvegardés: {output_file}")
    print(f"[rQUIC] Frames envoyées: {results['frames_sent']}")
    print(f"[rQUIC] Retransmissions: {results['retransmissions']}")
    print(f"[rQUIC] Taux de livraison: {results['delivery_rate']:.1f}%")
    
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='rQUIC - Reliable QUIC-like Protocol')
    parser.add_argument('mode', choices=['server', 'client'], help='Mode: server ou client')
    parser.add_argument('--host', default='0.0.0.0', help='Adresse (serveur) ou destination (client)')
    parser.add_argument('--port', type=int, default=5000, help='Port')
    parser.add_argument('--duration', type=int, default=30, help='Durée en secondes')
    parser.add_argument('--output', default='rquic_results.json', help='Fichier de sortie')
    
    args = parser.parse_args()
    
    if args.mode == 'server':
        run_server(args.host, args.port, args.duration, args.output)
    else:
        run_client(args.host, args.port, args.duration, args.output)
