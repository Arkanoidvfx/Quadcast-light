# HyperX QuadCast S lighting protocol

Notes from making the newer HP-era QuadCast S light up without NGENUITY.
Cross-checked against OpenRGB's `Controllers/HyperXMicrophoneController/` and
Ors1mer/QuadcastRGB (GPL). No code was taken from either; only the protocol.

## The mic is two USB devices

| VID:PID   | What it is                                     | Lighting |
|-----------|------------------------------------------------|----------|
| 03F0:0294 | audio plus consumer HID (MI_03, usage page 0x000C) | No. Windows filters feature reports on this collection. |
| 03F0:028C | the lighting controller                        | Yes, on the vendor HID collection with **usage page 0xFF90** (MI_00). |

Open the 028C path whose `usage_page == 0xFF90`. Anything else looks like it
works and then silently does nothing. See `open_dev()` in
[`quadcastlight/device.py`](../quadcastlight/device.py).

## Packets

Everything is a 65-byte HID **feature** report: `[0x00 report id][64 bytes]`.
Underneath that is a SET_REPORT (bmRequestType 0x21, bRequest 0x09, wValue 0x0300).

**Register packet** (`reg_packet`): `payload[0]=0x04`, `payload[1]=register`,
`payload[7]=p1`, `payload[8]=p2`. Indices in the code are one higher because of
the leading report id.

**Color packet** (`color_packet`): up to 8 frames of 8 bytes,
`0x81 R G B  0x81 R G B` - upper zone, then lower zone.

## Operations

| Operation | Sequence |
|---|---|
| Show one frame directly | `reg 0xF2 p2=1`, then a color packet. Repeat every ~50 ms or the mic reverts to the color in its flash after about a second. |
| Write to flash | `reg 0x53 p1=N` (N color packets), then N color packets at least 15 ms apart, then `reg 0x02`, `reg 0x23 p1=1`, the EOT packet, then `reg 0x02`. |
| EOT packet | `payload[0]=0x08`, `payload[0x3B]=0x28`, `payload[0x3C]=frame count`, `payload[0x3E]=0xAA`, `payload[0x3F]=0x55`. |

### The flash holds a colour, not an effect

The save sequence looks like it stores an animation. It announces a packet
count, each packet has room for eight frames, and the EOT packet carries a
frame count. It is tempting to conclude the microphone cycles them by itself.

It does not, and this was tested: writing 48 frames and then releasing the
device leaves the mic sitting on a still colour. Three things agree with that
result.

- There is no speed or delay field anywhere in the protocol. A stored animation
  would need one, and the byte next to the frame count is a fixed `0x28` in
  every implementation, this one included.
- OpenRGB, where this sequence comes from, only ever calls its save with a
  frame count of 1, and logs it as "Saving current direct colors to device".
- Its newer controller for the same family carries the comment "I believe
  currently this is setting a 'static' frame".
- QuadcastRGB, the other reference, lists a save option under things yet to be
  done and has no persistence at all.

So an effect exists only while something is streaming frames. QuadcastLight
streams while it runs, and Save to mic writes the single colour that is showing
at that moment, which is what the microphone falls back to when the app is
closed.

## Zones and brightness

There are exactly two addressable zones, upper and lower. Individual LEDs inside
a zone are not reachable over this protocol.

There is no brightness register. Brightness is the host multiplying RGB before
sending, `rgb * level / 100`, which is what NGENUITY does too. It is safe: no
current or thermal setting is being touched, only the color values in a frame.

## One writer at a time

The device takes whatever arrives last. NGENUITY, a second copy of this app, or
any other lighting tool will fight for it and the result flickers. QuadcastLight
keeps a single writer thread with the handle open for exactly this reason, and
records who owns the LEDs in `.tmp/miclight.pid`.
