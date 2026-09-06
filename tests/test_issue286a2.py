from PyQt6.QtWidgets import QApplication

from automap.target import MemoryTarget
from tests.test_automap import captured, make_window


def string_to_screen_codes(text):
    out = bytearray()
    for c in text:
        if 'A' <= c <= 'Z':
            out.append(ord(c) - ord('A') + 1)
        else:
            out.append(ord(c))
    return out

def test_a2_enumerate_wish_tick(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    save0, save1 = captured()
    
    screen = bytearray(b' ' * 1024)
    status_text = "E 16:48  5,2".ljust(40)
    screen[560:560+40] = string_to_screen_codes(status_text)
    
    memory = {
        0xD011: b'\x1B',
        0xD018: b'\x15',
        0xDD00: b'\x97',
        0x0400: bytes(screen),
        0x4900: save0,
        0x8300: save1,
        0x6E11: b'\x00',
    }
    
    machine = MemoryTarget(memory)
    window = make_window(app, tmp_path, monkeypatch, machine)
    
    for i in range(1, 11):
        machine.reads.clear()
        window.tick()
        reads = machine.reads
        
        # Verify read counts match the table for #286
        if i % 5 == 0:
            assert len(reads) == 12, f"Expected 12 reads on tick {i}, got {len(reads)}"
        else:
            assert len(reads) == 4, f"Expected 4 reads on tick {i}, got {len(reads)}"
