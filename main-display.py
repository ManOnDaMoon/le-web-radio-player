from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
#from signal import pause
import time
import sys
from luma.core import cmdline, error

def display_settings(device, args):
    """
    Display a short summary of the settings.

    :rtype: str
    """
    iface = ''
    display_types = cmdline.get_display_types()
    if args.display not in display_types['emulator']:
        iface = f'Interface: {args.interface}\n'

    lib_name = cmdline.get_library_for_display_type(args.display)
    if lib_name is not None:
        lib_version = cmdline.get_library_version(lib_name)
    else:
        lib_name = lib_version = 'unknown'

    import luma.core
    version = f'luma.{lib_name} {lib_version} (luma.core {luma.core.__version__})'

    return f'Version: {version}\nDisplay: {args.display}\n{iface}Dimensions: {device.width} x {device.height}\n{"-" * 60}'

def get_device(actual_args=None):
    """
    Create device from command-line arguments and return it.
    """
    if actual_args is None:
        actual_args = sys.argv[1:]
    parser = cmdline.create_parser(description='luma.examples arguments')
    args = parser.parse_args(actual_args)

    if args.config:
        # load config from file
        config = cmdline.load_config(args.config)
        args = parser.parse_args(config + actual_args)

    # create device
    try:
        device = cmdline.create_device(args)
        print(display_settings(device, args))
        return device

    except error.Error as e:
        parser.error(e)
        return None

def do_nothing():
    pass

# rev.1 users set port=0
# substitute spi(device=0, port=0) below if using that interface
#serial = i2c(port=1, address=0x3C)

# substitute ssd1331(...) or sh1106(...) below if using that device
#device = ssd1306(serial) # Default 128x64, Options : rotate=1/2/3, height=32, width=64)
#device.contrast(1)
#device.cleanup() # Peut être override : = do_nothing
#device.hide() # Low power mode
#device.show() # Sortir du Low power mode
#device.display(PIL.Image)
device = get_device()
i = 0
while True:
        with canvas(device) as draw:
            # draw.rectangle(device.bounding_box, outline="white", fill="black")
            draw.text((i, 0), "Radio Diane", fill="white")
            i = (i + 1) % 32
            time.sleep(0.1)

