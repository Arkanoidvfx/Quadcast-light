"""Protocol test: stream solid red to QuadCast S lighting controller (03F0:028C)."""
import time
import unittest
import hid

VID, PID = 0x03F0, 0x028C
REPORT_LEN = 65  # report id 0x00 + 64 bytes


def make(*vals):
    buf = bytearray(REPORT_LEN)
    buf[:len(vals)] = bytes(vals)
    return bytes(buf)


HEADER = make(0x00, 0x04, 0xF2, 0, 0, 0, 0, 0, 0, 0x01)
COLOR = make(0x00, 0x81, 0xFF, 0x00, 0x00, 0x81, 0xFF, 0x00, 0x00)


class ProtocolPacketTests(unittest.TestCase):
    def test_direct_packets_are_complete_feature_reports(self):
        self.assertEqual(len(HEADER), REPORT_LEN)
        self.assertEqual(len(COLOR), REPORT_LEN)
        self.assertEqual(HEADER[:3], bytes([0x00, 0x04, 0xF2]))
        self.assertEqual(COLOR[:9], bytes([0x00, 0x81, 0xFF, 0, 0, 0x81, 0xFF, 0, 0]))


def main(duration=6):
    """Run the opt-in hardware smoke test when this file is executed directly."""
    path = next(d["path"] for d in hid.enumerate(VID, PID) if d["usage_page"] == 0xFF90)
    dev = hid.device()
    dev.open_path(path)
    print("opened:", dev.get_product_string())

    ok = fail = 0
    t_end = time.time() + duration
    while time.time() < t_end:
        r1 = dev.send_feature_report(HEADER)
        r2 = dev.send_feature_report(COLOR)
        if r1 > 0 and r2 > 0:
            ok += 1
        else:
            fail += 1
            print("ret:", r1, r2, dev.error())
            break
        time.sleep(0.05)

    print(f"ok={ok} fail={fail}")
    dev.close()


if __name__ == "__main__":
    main()
