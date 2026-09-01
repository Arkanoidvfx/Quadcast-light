"""HyperX QuadCast S lighting controller: HID transport and packet layout.

The mic is two USB devices. Lighting lives on the controller 03F0:028C, in the
vendor HID collection with usage page 0xFF90 - not on 03F0:0294, where Windows
filters the feature reports. See docs for the full protocol notes.

Packets are 65-byte HID feature reports: [0x00 report id][64 bytes payload].
Direct display has to be refreshed a few times a second or the mic falls back to
the color saved in its flash.
"""
import time

import hid

from . import effects

VID, PID = 0x03F0, 0x028C
USAGE_PAGE = 0xFF90
REPORT_LEN = 65  # report id 0x00 + 64 data bytes
FRAME_DELAY = 0.05  # seconds between streamed frames


class DeviceNotFound(RuntimeError):
    """The lighting controller is not enumerable (unplugged, or claimed)."""


class DeviceWriteError(RuntimeError):
    """A feature report failed; the device usually vanished mid-write."""


def available():
    """True when the lighting collection is present, without opening it."""
    return any(entry["usage_page"] == USAGE_PAGE for entry in hid.enumerate(VID, PID))


def open_dev():
    for entry in hid.enumerate(VID, PID):
        if entry["usage_page"] == USAGE_PAGE:
            device = hid.device()
            device.open_path(entry["path"])
            return device
    raise DeviceNotFound(
        "HyperX QuadCast S lighting controller (03F0:028C) not found. Mic connected?"
    )


def report(*values):
    buffer = bytearray(REPORT_LEN)
    buffer[: len(values)] = bytes(values)
    return bytes(buffer)


def send(device, buffer):
    if device.send_feature_report(buffer) <= 0:
        raise DeviceWriteError(f"HID send failed: {device.error()}")


def reg_packet(register, p1=0, p2=0):
    # payload[0]=0x04, payload[1]=reg, payload[7]=p1, payload[8]=p2
    # (indices below are +1 because of the leading report id)
    buffer = bytearray(REPORT_LEN)
    buffer[1], buffer[2], buffer[8], buffer[9] = 0x04, register, p1, p2
    return bytes(buffer)


def color_packet(upper, lower):
    return report(0x00, 0x81, *upper, 0x81, *lower)


def apply_packet():
    """Register write that makes the next color packet show immediately."""
    return reg_packet(0xF2, 0, 1)


def save_to_device(upper, lower):
    """Write one held colour into mic flash. Persists across replug and reboot.

    One colour is all the flash holds. The save sequence carries a frame count,
    and the packet layout has room for eight frames each, which reads like a
    stored animation, but nothing plays it back: there is no speed or delay
    field anywhere in the protocol, OpenRGB's own controller only ever passes a
    frame count of 1, and writing 48 frames to the device leaves it sitting on
    a still colour. See docs/PROTOCOL.md.
    """
    device = open_dev()
    delay = 0.02
    try:
        send(device, reg_packet(0x53, 1, 0))            # start save, 1 packet
        time.sleep(delay)
        buffer = bytearray(REPORT_LEN)
        buffer[1:9] = bytes([0x81, *upper, 0x81, *lower])
        send(device, bytes(buffer))
        time.sleep(delay)
        send(device, reg_packet(0x02))                  # post-save
        time.sleep(delay)
        send(device, reg_packet(0x23, 1, 0))            # commit
        time.sleep(delay)
        eot = bytearray(REPORT_LEN)
        eot[1] = 0x08
        eot[0x3C] = 0x28
        eot[0x3D] = 1                                   # frame count
        eot[0x3F] = 0xAA
        eot[0x40] = 0x55
        send(device, bytes(eot))
        time.sleep(delay)
        send(device, reg_packet(0x02))
        time.sleep(delay)
        # The device wants one direct frame after a save, and it makes the
        # change visible without waiting.
        send(device, color_packet(upper, lower))
        send(device, apply_packet())
    finally:
        device.close()


def frame_packets(frames):
    """Pre-render (upper, lower) frames into wire packets."""
    return [color_packet(*frame) for frame in frames]


__all__ = [
    "VID",
    "PID",
    "USAGE_PAGE",
    "REPORT_LEN",
    "FRAME_DELAY",
    "DeviceNotFound",
    "DeviceWriteError",
    "available",
    "open_dev",
    "report",
    "send",
    "reg_packet",
    "color_packet",
    "apply_packet",
    "save_to_device",
    "frame_packets",
    "effects",
]
