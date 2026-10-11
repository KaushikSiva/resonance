"""
Hardware check for ThermoScene. Run before a demo:

  .venv/bin/python doctor.py            # detect only
  .venv/bin/python doctor.py --test     # also pulse each dot: LED, click, 3 s heat, 3 s cool
  .venv/bin/python doctor.py --radar    # stream breathing for 30 s
"""
import argparse
import subprocess
import time

import serial.tools.list_ports


def ok(msg):
    print(f"  \033[32m✔\033[0m {msg}")


def bad(msg, fix):
    print(f"  \033[31m✘\033[0m {msg}\n      → {fix}")


def check_datafeel(test):
    print("DataFeel")
    usb = subprocess.run(["ioreg", "-p", "IOUSB", "-w0"], capture_output=True, text=True).stdout
    if "CP2102N" not in usb:
        bad("El Jefe controller not on USB", "plug it in with a data cable, directly into the Mac")
        return
    ok("El Jefe controller on USB")
    ports = [p for p in serial.tools.list_ports.comports() if p.vid == 0x10C4 and p.pid == 0xEA60]
    if not ports:
        bad("no serial port for it",
            "unplug/replug and click Allow; or System Settings → Privacy & Security → Allow accessories to connect")
        return
    ok(f"serial port {ports[0].device}")

    from datafeel.device import VibrationWaveforms, discover_devices
    dots = discover_devices(4)
    if not dots:
        bad("no dots answered", "check the dots are seated on El Jefe and it is powered on")
        return
    ok(f"{len(dots)} dot(s) answering")
    for i, d in enumerate(dots, 1):
        try:
            print(f"      dot {i}: skin {d.registers.get_skin_temperature():.1f} °C, "
                  f"sink {d.registers.get_sink_temperature():.1f} °C")
        except Exception as e:
            print(f"      dot {i}: read failed ({e})")
    if not test:
        return

    for i, d in enumerate(dots, 1):
        print(f"  testing dot {i}…")
        d.set_led(0, 255, 0)
        d.play_vibration_sequence([VibrationWaveforms.DOUBLE_CLICK_P100])
        for name, rgb, power in (("heat", (255, 80, 0), 0.8), ("cool", (0, 80, 255), -0.8)):
            d.set_led(*rgb)
            before = d.registers.get_skin_temperature()
            d.activate_thermal_intensity_control(power)
            time.sleep(4)
            after = d.registers.get_skin_temperature()
            good = after > before + 1 if power > 0 else after < before - 1
            print(f"      {name}: skin {before:.1f} → {after:.1f} °C  {'✔' if good else '✘ no change'}")
        d.disable_all_thermal()
        d.set_led_off()
    ok("dot test done")


def check_radar(stream):
    print("Infineon radar")
    from ifxradarsdk.fmcw import DeviceFmcw
    found = DeviceFmcw.get_list()
    if not found:
        bad("no XENSIV FMCW radar found",
            "plug the kit directly into the Mac (not the hub) with a data cable; LED on the board should be on")
        return
    ok(f"radar found: {found}")
    if not stream:
        return

    from thermoscene import RadarBreath
    rb = RadarBreath()
    print("  sit 0.3–1.5 m in front of the radar and breathe normally (30 s)…")
    for _ in range(60):
        bar = "#" * int((rb.wave + 1) * 15)
        print(f"\r  {rb.status:32s} {rb.bpm:5.1f} bpm  {bar:30s}", end="", flush=True)
        time.sleep(0.5)
    print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="pulse each dot (LED, click, heat, cool)")
    ap.add_argument("--radar", action="store_true", help="stream breathing for 30 s")
    a = ap.parse_args()
    check_datafeel(a.test)
    check_radar(a.radar)
