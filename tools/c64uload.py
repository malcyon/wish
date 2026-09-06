#!/usr/bin/env python3
"""
Sampler tool for C64 Ultimate (Issue #286).
"""
import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError

DEFAULT_PORT = 80

def get_machine_host():
    import os
    return os.environ.get("C64U_HOST") or "c64u"

def perform_request(host, port, route, params=None):
    url = f"http://{host}:{port}/v1{route}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    
    send_time = time.time()
    result = {
        "send_time": send_time,
        "route": route,
        "size": params.get("length", 0) if params else 0,
    }
    
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=30.0) as reply:
            reply_time = time.time()
            data = reply.read()
            result.update({
                "reply_time": reply_time,
                "status": reply.status,
                "elapsed": reply_time - send_time,
                "error": None
            })
            return result, data
    except HTTPError as e:
        reply_time = time.time()
        result.update({
            "reply_time": reply_time,
            "status": e.code,
            "elapsed": reply_time - send_time,
            "error": str(e)
        })
        return result, b""
    except Exception as e:
        reply_time = time.time()
        result.update({
            "reply_time": reply_time,
            "status": None,
            "elapsed": reply_time - send_time,
            "error": str(e)
        })
        return result, b""

def read_mem(host, port, address, length):
    res, data = perform_request(host, port, "/machine:readmem", {"address": f"{address:X}", "length": length})
    if res["status"] == 200:
        return data, res
    return b"", res

def get_sample(host, port):
    # D018, DD00
    d018_data, _ = read_mem(host, port, 0xD018, 1)
    dd00_data, _ = read_mem(host, port, 0xDD00, 1)
    
    if not d018_data or not dd00_data:
        return None
        
    d018 = d018_data[0]
    dd00 = dd00_data[0]
    
    screen_page = (d018 >> 4) & 0x0F
    vic_bank = (~dd00) & 0x03
    screen_addr = (vic_bank * 16384) + (screen_page * 1024)
    
    screen_data, _ = read_mem(host, port, screen_addr, 1000)
    screen_hash = hashlib.sha256(screen_data).hexdigest() if screen_data else None
    
    jiffy_data, _ = read_mem(host, port, 0x00A0, 3)
    jiffy = list(jiffy_data) if jiffy_data else None
    
    dc0d_data, _ = read_mem(host, port, 0xDC0D, 1)
    d01a_data, _ = read_mem(host, port, 0xD01A, 1)
    
    return {
        "time": time.time(),
        "sha256": screen_hash,
        "jiffy": jiffy,
        "DD00": dd00,
        "DC0D": dc0d_data[0] if dc0d_data else None,
        "D01A": d01a_data[0] if d01a_data else None,
    }

def codes_to_text(codes):
    out = []
    for byte in codes:
        b = byte & 0x7F
        if b == 0: 
            out.append('@')
        elif 1 <= b <= 26: 
            out.append(chr(ord('A') + b - 1))
        elif 27 <= b <= 31: 
            out.append("[£]^_"[b - 27])
        elif 32 <= b <= 63: 
            out.append(chr(b))
        else: 
            out.append('.')
    return "".join(out)

def teardown(host, port):
    print("\n--- Teardown (Crash Parameters) ---")
    data_0314, _ = read_mem(host, port, 0x0314, 2)
    if data_0314:
        print(f"$0314/$0315: {data_0314.hex()}")
        
    data_d018, _ = read_mem(host, port, 0xD018, 1)
    if data_d018:
        print(f"$D018: 0x{data_d018[0]:02x}")
        
    data_dd00, _ = read_mem(host, port, 0xDD00, 1)
    if data_dd00:
        print(f"$DD00: 0x{data_dd00[0]:02x}")
        
    data_0288, _ = read_mem(host, port, 0x0288, 1)
    if data_0288:
        print(f"$0288: 0x{data_0288[0]:02x}")
        
    data_0400, _ = read_mem(host, port, 0x0400, 24)
    if data_0400:
        print(f"$0400: {codes_to_text(data_0400)}")
        
    data_cc00, _ = read_mem(host, port, 0xCC00, 24)
    if data_cc00:
        print(f"$CC00: {codes_to_text(data_cc00)}")

def do_wish_tick(host, port, tick_num):
    # D011, D018, DD00, status row
    reqs = [
        {"route": "/machine:readmem", "params": {"address": f"{0xD011:X}", "length": 1}},
        {"route": "/machine:readmem", "params": {"address": f"{0xD018:X}", "length": 1}},
        {"route": "/machine:readmem", "params": {"address": f"{0xDD00:X}", "length": 1}},
        {"route": "/machine:readmem", "params": {"address": f"{0x0630:X}", "length": 40}},
    ]
    if tick_num % 5 == 0:
        reqs.extend([
            {"route": "/machine:readmem", "params": {"address": f"{0x6E11:X}", "length": 1}},
            {"route": "/machine:readmem", "params": {"address": f"{0x0600:X}", "length": 20}},
            {"route": "/machine:readmem", "params": {"address": f"{0x037E:X}", "length": 2}},
            {"route": "/machine:readmem", "params": {"address": f"{0x6E11:X}", "length": 1}},
            {"route": "/machine:readmem", "params": {"address": f"{0x6E11:X}", "length": 1}},
            {"route": "/machine:readmem", "params": {"address": f"{0x6E11:X}", "length": 1}},
            {"route": "/machine:readmem", "params": {"address": f"{0x4900:X}", "length": 7168}},
            {"route": "/machine:readmem", "params": {"address": f"{0x8300:X}", "length": 256}},
        ])
    
    for r in reqs:
        res, _ = perform_request(host, port, r["route"], r.get("params"))
        print(json.dumps(res))
        sys.stdout.flush()

def main():
    parser = argparse.ArgumentParser(description="Sampler tool for C64 Ultimate (Issue #286).")
    parser.add_argument("--host", default=get_machine_host())
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--route", choices=["readmem", "info", "version", "drives"], required=True)
    parser.add_argument("--interval", type=float)
    parser.add_argument("--size", type=int)
    parser.add_argument("--at", type=lambda x: int(x, 16) if x else None)
    parser.add_argument("--shape", choices=["wish"])
    parser.add_argument("--minutes", type=float, required=True)
    parser.add_argument("--sample", type=float, default=10.0)
    args = parser.parse_args()

    end_time = time.time() + args.minutes * 60
    last_sample_time = time.time() - args.sample # force immediate sample
    tick_num = 0
    
    try:
        while time.time() < end_time:
            now = time.time()
            if now - last_sample_time >= args.sample:
                if args.route != "info":
                    sample = get_sample(args.host, args.port)
                    if sample:
                        print(json.dumps(sample))
                        sys.stdout.flush()
                last_sample_time = time.time()
                
            if args.shape == "wish":
                tick_num += 1
                do_wish_tick(args.host, args.port, tick_num)
                # Wish interval is ~0.5s, so we sleep the remainder of interval if any
                elapsed = time.time() - now
                if args.interval and elapsed < args.interval:
                    time.sleep(args.interval - elapsed)
            else:
                params = {}
                route = f"/{args.route}"
                if args.route == "readmem" and args.size and args.at is not None:
                    route = "/machine:readmem"
                    params = {"address": f"{args.at:X}", "length": args.size}
                    
                res, _ = perform_request(args.host, args.port, route, params)
                print(json.dumps(res))
                sys.stdout.flush()
                
                if args.interval:
                    time.sleep(args.interval)
                    
    except KeyboardInterrupt:
        pass
    finally:
        teardown(args.host, args.port)

if __name__ == "__main__":
    main()
