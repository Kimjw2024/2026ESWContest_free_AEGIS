# Arduino UNO Turret Firmware

`turret_uno.ino` is the final AEGIS Dual Pan-Tilt controller firmware.

Features:

- 115200-baud serial communication
- latest-command buffer
- non-blocking serial parser
- command watchdog timeout
- pan/tilt servo control
- dual logical laser output
- microsecond-based servo command support

The Windows-side controller is:

`runtime/fusion_pc/6_turret_server.py`

Machine-specific servo trim and geometry values are managed separately through
the Fusion PC configuration and calibration override file.
