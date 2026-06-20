"""Circle board configurations and audio-device helpers."""

from dataclasses import dataclass

_AUDIO_DEVICE_INFO: dict[str, tuple[str, str, str]] = {
    "i2s": (
        "<circle/sound/i2ssoundbasedevice.h>",
        "CI2SSoundBaseDevice",
        "I2S",
    ),
    "pwm": (
        "<circle/sound/pwmsoundbasedevice.h>",
        "CPWMSoundBaseDevice",
        "PWM",
    ),
    "hdmi": (
        "<circle/sound/hdmisoundbasedevice.h>",
        "CHDMISoundBaseDevice",
        "HDMI",
    ),
    "usb": (
        "<circle/sound/usbsoundbasedevice.h>",
        "CUSBSoundBaseDevice",
        "USB",
    ),
}


def _get_audio_include(audio_device: str) -> str:
    """Return the #include line for a sound device type."""
    header, _, _ = _AUDIO_DEVICE_INFO[audio_device]
    return f"#include {header}"


def _get_audio_base_class(audio_device: str) -> str:
    """Return the Circle sound base class name."""
    _, cls, _ = _AUDIO_DEVICE_INFO[audio_device]
    return cls


def _get_audio_label(audio_device: str) -> str:
    """Return a human-readable label for the audio device."""
    _, _, label = _AUDIO_DEVICE_INFO[audio_device]
    return label


def _get_extra_libs(audio_device: str) -> str:
    """Return additional LIBS entries needed for the audio device."""
    if audio_device == "usb":
        return "$(CIRCLEHOME)/lib/usb/libusb.a"
    return ""


def _get_boot_config(audio_device: str) -> str:
    """Return config.txt content specific to the audio device."""
    if audio_device == "i2s":
        return (
            "# For I2S DAC setup (PCM5102A, PCM5122, UDA1334A, etc.):\n"
            "#   Connect DAC to Pi GPIO header:\n"
            "#     BCK  -> GPIO 18 (pin 12)\n"
            "#     LRCK -> GPIO 19 (pin 35)\n"
            "#     DIN  -> GPIO 21 (pin 40)\n"
            "#     VIN  -> 3.3V (pin 1)\n"
            "#     GND  -> GND (pin 6)\n"
            "\n"
            "# Enable I2S audio overlay\n"
            "dtparam=i2s=on"
        )
    elif audio_device == "pwm":
        return (
            "# PWM audio output through 3.5mm headphone jack\n"
            "# No additional hardware required\n"
            "# Default GPIOs: 12 (left) and 13 (right)"
        )
    elif audio_device == "hdmi":
        return (
            "# HDMI audio output (48kHz stereo)\n"
            "# Connect HDMI to a monitor or audio receiver"
        )
    elif audio_device == "usb":
        return (
            "# USB audio output (Pi 4/5 only)\n# Connect a USB DAC or audio interface"
        )
    return ""


# ---------------------------------------------------------------------------
# Board configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CircleBoardConfig:
    """Hardware configuration for a specific Circle board variant."""

    key: str  # "pi3-i2s", "pi4-pwm", etc.
    rasppi: int  # RASPPI value: 1, 3, 4, or 5
    aarch: int  # 32 or 64 (bit width)
    prefix: str  # Compiler prefix
    kernel_img: str  # Output kernel image filename
    audio_device: str  # "i2s", "pwm", "hdmi", or "usb"


CIRCLE_BOARDS: dict[str, CircleBoardConfig] = {
    # --- Pi Zero (original / W) - 32-bit, single core ---
    "pi0-pwm": CircleBoardConfig(
        key="pi0-pwm",
        rasppi=1,
        aarch=32,
        prefix="arm-none-eabi-",
        kernel_img="kernel.img",
        audio_device="pwm",
    ),
    "pi0-i2s": CircleBoardConfig(
        key="pi0-i2s",
        rasppi=1,
        aarch=32,
        prefix="arm-none-eabi-",
        kernel_img="kernel.img",
        audio_device="i2s",
    ),
    # --- Pi Zero 2 W - same SoC as Pi 3 ---
    "pi0w2-i2s": CircleBoardConfig(
        key="pi0w2-i2s",
        rasppi=3,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8.img",
        audio_device="i2s",
    ),
    "pi0w2-pwm": CircleBoardConfig(
        key="pi0w2-pwm",
        rasppi=3,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8.img",
        audio_device="pwm",
    ),
    # --- Pi 3 / 3B+ ---
    "pi3-i2s": CircleBoardConfig(
        key="pi3-i2s",
        rasppi=3,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8.img",
        audio_device="i2s",
    ),
    "pi3-pwm": CircleBoardConfig(
        key="pi3-pwm",
        rasppi=3,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8.img",
        audio_device="pwm",
    ),
    "pi3-hdmi": CircleBoardConfig(
        key="pi3-hdmi",
        rasppi=3,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8.img",
        audio_device="hdmi",
    ),
    # --- Pi 4 / 400 ---
    "pi4-i2s": CircleBoardConfig(
        key="pi4-i2s",
        rasppi=4,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8-rpi4.img",
        audio_device="i2s",
    ),
    "pi4-pwm": CircleBoardConfig(
        key="pi4-pwm",
        rasppi=4,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8-rpi4.img",
        audio_device="pwm",
    ),
    "pi4-usb": CircleBoardConfig(
        key="pi4-usb",
        rasppi=4,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8-rpi4.img",
        audio_device="usb",
    ),
    "pi4-hdmi": CircleBoardConfig(
        key="pi4-hdmi",
        rasppi=4,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8-rpi4.img",
        audio_device="hdmi",
    ),
    # --- Pi 5 (64-bit only) ---
    "pi5-i2s": CircleBoardConfig(
        key="pi5-i2s",
        rasppi=5,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel_2712.img",
        audio_device="i2s",
    ),
    "pi5-usb": CircleBoardConfig(
        key="pi5-usb",
        rasppi=5,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel_2712.img",
        audio_device="usb",
    ),
    "pi5-hdmi": CircleBoardConfig(
        key="pi5-hdmi",
        rasppi=5,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel_2712.img",
        audio_device="hdmi",
    ),
}
