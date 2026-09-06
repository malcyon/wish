import time

from tools.instance import claim
from tools.session import Session


def run():
    with claim(game="por", note="issue286 A") as slot:
        sess = Session(slot=slot)
        sess.launch()
        # Give the game time to start the fastloader or whatever
        time.sleep(3.0)
        
        with sess.mon() as mon:
            # Setup for the crash
            mon.write(0x0314, b'\x00\x00')
            mon.write(0xD018, b'\x35')
            dd00 = mon.read(0xDD00, 1)[0]
            mon.write(0xDD00, bytes([dd00 & 0xFC]))
            mon.write(0x0288, b'\xCC')
            mon.write(0xC000, b'\x00')
            
            # Set PC to 0xC000
            mon.set_registers({3: 0xC000})
            
        # The monitor exit resumes the emulator, so it will execute the BRK at 0xC000
        time.sleep(2.0)
        
        with sess.mon() as mon:
            v0314 = mon.read(0x0314, 2)
            d018 = mon.read(0xD018, 1)[0]
            dd00_new = mon.read(0xDD00, 1)[0]
            v0288 = mon.read(0x0288, 1)[0]
            cc00_bytes = mon.read(0xCC00, 160)
            
        print(f"$0314/$0315: {v0314.hex()}")
        print(f"$D018: {hex(d018)}")
        print(f"$DD00: {hex(dd00_new)}")
        print(f"$0288: {hex(v0288)}")
        
        chars = []
        for b in cc00_bytes:
            if 1 <= b <= 26: 
                chars.append(chr(b + 64))
            elif b == 46: 
                chars.append('.')
            elif b == 32: 
                chars.append(' ')
            else: 
                chars.append(f'[{hex(b)}]')
        print(f"$CC00: {''.join(chars)}")

if __name__ == '__main__':
    run()
