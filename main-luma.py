
import os
import sys, time, signal
import asyncio
from gpiozero import Button, RotaryEncoder
import requests

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
import luma.core.legacy
from luma.core.virtual import viewport

from PIL import Image, ImageDraw, ImageFont

from radio import Radio

class PiWebRadioApp():

    __debug = False
    __display_refresh_rate: int = 2  # in seconds
    __last_display_refresh: float = 0.0

    def __init__(self):
        # IO INIT
        # Initialisation DISPLAY
        self.serial = i2c(port=1, address=0x3C)
        self.oled = ssd1306(self.serial)

        self.__script_dir_name = os.path.dirname(__file__)
        self.display_splash(os.path.join(self.__script_dir_name, "radiodiane-splash.bmp"))

        # CLASS VARIABLES
        self.main_text = ""
        self.secondary_text = ""
        self.volume = 0
        self.scroll_r_count = 0
        self.scroll_l_count = 0
        self.is_mute = False
        self.power = False
        self.power_alert = 0
        self.clock = True
        self.redraw = True
        self.radio = Radio(self.__debug)
        self.icons_font = ImageFont.truetype(os.path.join(self.__script_dir_name, "radiocontrols.ttf"), 16)
        self.title_font = ImageFont.truetype(os.path.join(self.__script_dir_name, "Louis George Cafe.ttf"), 26)
        self.text_font = ImageFont.truetype(os.path.join(self.__script_dir_name, "Louis George Cafe.ttf"), 16)
        self.icons_y_position = 0
        self.title_y_position = 18
        self.text_y_position = 46

        Button.was_held = False

        # Initialisation bouton VOLUME
        self.volume_knob = RotaryEncoder(17, 27, max_steps=10)  # GPIO17 = CLK, GPIO27 = DT
        self.mute_switch = Button(22, bounce_time=0.1)  # GPIO22 = SW

        # Initialisation bouton CHANNEL
        self.channel_knob = RotaryEncoder(23, 24, max_steps=10)  # GPIO23 = CLK, GPIO24 = DT
        self.on_off_switch = Button(10, hold_time=2, bounce_time=0.1)  # GPIO10 = SW

        # Sélecteur Volume
        self.mute_switch.when_pressed = self.mute
        self.volume_knob.when_rotated_clockwise = self.volume_up
        self.volume_knob.when_rotated_counter_clockwise = self.volume_down

        # Sélecteur station
        self.on_off_switch.when_released = self.on_off_released
        #self.on_off_switch.when_pressed = self.toggle_on_off
        self.on_off_switch.when_held = self.total_shutdown
        self.channel_knob.when_rotated_clockwise = self.next_radio
        self.channel_knob.when_rotated_counter_clockwise = self.previous_radio
        #self.channel_knob.when_rotated = self.change

        # Gestion de l'arrêt forcé
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGHUP, self.signal_handler)

        self.wait_for_internet_connection()

        self.scroll_right(self.splash_virtual, (0,0))

    def wait_for_internet_connection(self):
        while True:
            try:
                res = requests.get("https://www.radiofrance.fr")
                if res.status_code == 200:
                    return
                time.sleep(1)
            except:
                pass

    # VIRTUAL
    def scroll_left(self, virtual, pos):
        x, y = pos
        while x >= 0:
            virtual.set_position((x, y))
            x -= 1
        x = 0
        return (x, y)

    def scroll_right(self, virtual, pos):
        x, y = pos
        if virtual.width > self.oled.width:
            while x < virtual.width - self.oled.width:
                virtual.set_position((x, y))
                x += 2
            x -= 2
        return (x, y)

    def display_splash(self, image_path, wait_time = 1):
        self.splash = Image.open(image_path).convert('RGBA')
        self.splash = self.splash.convert(self.oled.mode)
        w, h = self.splash.size
        self.splash_virtual = viewport(self.oled, width=w, height=h)
        self.splash_virtual.display(self.splash)
        time.sleep(wait_time)

    def on_off_released(self, button):
        if not button.was_held:
            self.toggle_on_off()
        button.was_held = False

    def toggle_on_off(self):
        self.main_text = ""
        self.secondary_text = ""
        if self.radio.toggle_on_off():
            self.power = True
            self.clock = False
            self.volume = self.radio.volume
        else:
            self.power = False
            self.clock = True

    def total_shutdown(self, button):
        button.was_held = True
        self.radio.stop()
        self.power = False
        self.clock = False
        self.display_splash(os.path.join(self.__script_dir_name, "aurevoir.bmp"))
        self.oled.hide()
        os.system("sudo shutdown -h now")

    def volume_up(self, rotary_encoder: RotaryEncoder):
        self.volume = self.radio.volume_up()

    def volume_down(self, rotary_encoder: RotaryEncoder):
        self.volume = self.radio.volume_down()

    def next_radio(self, rotary_encoder: RotaryEncoder):
        self.scroll_r_count+=1
        self.scroll_l_count=0
        if self.scroll_r_count >= 3:
            self.scroll_r_count = 0
            if self.radio.next_channel():
                self.show_text(">>", "")

    def previous_radio(self, rotary_encoder: RotaryEncoder):
        self.scroll_l_count += 1
        self.scroll_r_count = 0
        if self.scroll_l_count >= 3:
            self.scroll_l_count = 0
            if self.radio.previous_channel():
                self.show_text("<<", "")

    def mute(self):
        new_volume = self.radio.mute()
        if new_volume != -1:
            if new_volume == 0:
                self.is_mute = True
            else:
                self.is_mute = False

    def signal_handler(self, signal, frame):
        loop = asyncio.get_event_loop()
        loop.stop()
        self.radio.stop()
        self.oled.show()
        self.display_splash(os.path.join(self.__script_dir_name, "zzz.bmp"))
        self.scroll_right(self.splash_virtual, (0,0))
        self.oled.hide()
        sys.exit(0)

    def show_text(self, text, secondary_text = "") -> None:
        self.main_text = f"{text} {self.radio.get_channel_name()}"
        self.secondary_text = secondary_text
        self.redraw = True

    async def refresh_display_data(self) -> None:
        while True:
            if self.power:
                if time.time() > self.__last_display_refresh + self.__display_refresh_rate:
                    old_main_text = self.main_text
                    old_secondary_text = self.secondary_text
                    self.main_text = self.radio.get_channel_name()
                    self.secondary_text = self.radio.get_display()
                    self.__last_display_refresh = time.time()
                    if (old_main_text != self.main_text) or (old_secondary_text != self.secondary_text):
                        self.redraw = True
            await asyncio.sleep(self.__display_refresh_rate)

    def get_volume_text(self) -> str:
        icontext = ""
        if not self.is_mute:
            icontext = "A" # Icone haut-parleur
        else:
            icontext = "B" # Icone haut-parleur barré
        if (self.volume >= 15): # Barres de volume
            icontext += "C"
            if (self.volume >= 20):
                icontext += "D"
                if (self.volume >= 30):
                    icontext += "E"
                    if (self.volume >= 40):
                        icontext += "F"
                        if (self.volume >= 50):
                            icontext += "G"
                            if (self.volume >= 60):
                                icontext += "H"
                                if (self.volume >= 75):
                                    icontext += "I"
                                    if (self.volume > 80):
                                        icontext += "J"
        return icontext

    async def main_display(self):
        self.redraw = True
        x3=128
        while True:
            if self.power:
                self.oled.show()
                if self.redraw:
                    with canvas(self.oled) as draw:
                        line1 = self.main_text
                        if draw.textlength(line1, font=self.title_font) > 128:
                            line1 = self.main_text + "    " + self.main_text + "    "
                        line2 = self.secondary_text
                        if draw.textlength(line2, font=self.text_font) > 128:
                            line2 = self.secondary_text + "       " + self.secondary_text + "       "
                    pause1 = 20 # Pause (20*0,05 = ~1s) avant de démarrer le scroll
                    pause2 = 20 # Pause (20*0,05 = ~1s) avant de démarrer le scroll
                    x1 = 0
                    x2 = 0
                    self.redraw = False
                icontext = self.get_volume_text()
                with canvas(self.oled) as draw:
                    # TOP ICONS
                    draw.text((0, self.icons_y_position), icontext, font=self.icons_font, fill="white")

                    # HEURE
                    time_text = time.strftime("%H:%M")
                    time_text_length = draw.textlength(time_text, font_size=15)
                    draw.text((128 - time_text_length, self.icons_y_position - 2), time_text,  font_size=15, fill="white")

                    # TITLES
                    l1_length = draw.textlength(line1, font=self.title_font) / 2
                    l2_length = draw.textlength(line2, font=self.text_font) / 2
                    if (l1_length <= 128) or (l1_length + x1 < 0):
                        x1=0
                        pause1 = 20
                    draw.text((x1,self.title_y_position), line1, font=self.title_font, fill="white")
                    if (l2_length <= 128) or (l2_length + x2 < 0):
                        x2=0
                        pause2 = 20
                    draw.text((x2, self.text_y_position), line2, font=self.text_font, fill="white")
                if (pause1 < 0):
                    x1-=1
                else:
                    pause1-=1
                if (pause2 < 0):
                    x2-=2 # Vitesse de scroll double pour les titres
                else:
                    pause2-=1

                # Power mode refresh rate
                await asyncio.sleep(0.05)
            if self.clock:
                self.oled.show()
                time_text = time.strftime("%H:%M")
                with canvas(self.oled) as draw:
                    # HEURE
                    time_text_length = draw.textlength(time_text, font_size=15)
                    draw.text((x3 - time_text_length, self.icons_y_position - 2), time_text, font_size=15, fill="white")
                x3-=5 # Vitesse de scroll de l'horloge
                if x3 - time_text_length < 0:
                    x3=128 #TODO : Défiler l'heure autour de l'écran
                # Off mode refresh rate
                await asyncio.sleep(1) # Si temps d'attente trop long, le display ne se met pas en marche avec la radio !

    async def power_monitor(self):
        self.power_alert = 0
        while True:
            # get cpu low voltage indicator
            #t = os.popen('/home/laurent/test_throttled.sh').readline() #TEST MODE
            t = os.popen('vcgencmd get_throttled').readline()
            b = int(t.split('=')[1], 0)
            if (b & 0x1) == 1:
                print(f"{time.ctime(time.time())} : LOW VOLTAGE ALERT")
                if self.power: #Sound only if currently running, else shut down silently
                    os.popen("espeak -v fr+f1 -s 120 \"Batterie faible\" --stdout | aplay")
                self.power_alert+=1
                self.display_splash(os.path.join(self.__script_dir_name, "lowpower.bmp"))
                if self.power_alert >= 3:
                    self.radio.stop()
                    self.power = False
                    self.clock = False
                    self.oled.hide()
                    os.system("sudo shutdown -h now")
            else:
                self.power_alert = 0
            await asyncio.sleep(60)

    async def run(self):
        await asyncio.gather(
            self.refresh_display_data(),
            self.main_display(),
            self.power_monitor()
        )

#
# Main loop
#
if __name__ == "__main__":
    try:
        app = PiWebRadioApp()
        asyncio.run(app.run())
    except KeyboardInterrupt:
        pass




