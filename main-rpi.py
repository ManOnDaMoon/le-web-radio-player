
import os
import sys, time, signal
import asyncio
from gpiozero import Button, RotaryEncoder

from RaspiOled import oled,ScrollText
from PIL import Image, ImageDraw, ImageFont

from radio import Radio

class PiWebRadioApp():

    __debug = False
    __display_refresh_rate: int = 2  # in seconds
    __last_display_refresh: float = 0.0

    def __init__(self):
        # IO INIT
        # Initialisation DISPLAY
        oled.begin()
        im = Image.new('1', oled.size)
        im2 = Image.open("radiodiane.bmp")
        im.paste(im2)
        oled.image(im, sync=1)

        # Initialisation bouton VOLUME
        self.volume_knob = RotaryEncoder(17, 27, max_steps=10)  # GPIO17 = CLK, GPIO27 = DT
        self.mute_switch = Button(22, bounce_time=0.2)  # GPIO22 = SW

        # Initialisation bout CHANNEL
        self.channel_knob = RotaryEncoder(23, 24, max_steps=10)  # GPIO23 = CLK, GPIO24 = DT
        self.on_off_switch = Button(10, hold_time=3, bounce_time=0.2)  # GPIO10 = SW

        # # Sélecteur Volume
        self.mute_switch.when_pressed = self.mute
        self.volume_knob.when_rotated_clockwise = self.volume_up
        self.volume_knob.when_rotated_counter_clockwise = self.volume_down
        #self.volume_knob.when_rotated = self.change

        # # Sélecteur channel
        self.on_off_switch.when_pressed = self.toggle_on_off
        self.on_off_switch.when_held = self.total_shutdown
        self.channel_knob.when_rotated_clockwise = self.next_radio
        self.channel_knob.when_rotated_counter_clockwise = self.previous_radio
        #self.channel_knob.when_rotated = self.change

        # Registering signal
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGHUP, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

        self.radio = Radio(self.__debug)

        sc = ScrollText.new(
            font='/usr/share/fonts/truetype/freefont/FreeMono.ttf',
            speed=64)
        sc.scrollOut()
        while sc.update():
            time.sleep(0.005)


    def toggle_on_off(self):
        if self.radio.toggle_on_off():
            self.show_text("Power On") #TODO : Hande soft Wake
        else:
            self.show_text("Shut Off") #TODO : Handle soft Shutdown

    def total_shutdown(self):
        os.system("sudo shutdown -h now")

    def volume_up(self, rotary_encoder: RotaryEncoder):
        new_volume = self.radio.volume_up()
        if new_volume != -1:
            self.show_text(f"Volume Up : {new_volume}")

    def volume_down(self, rotary_encoder: RotaryEncoder):
        new_volume = self.radio.volume_down()
        if new_volume != -1:
            self.show_text(f"Volume Down : {new_volume}")

    def next_radio(self, rotary_encoder: RotaryEncoder):
        if self.radio.next_channel():
            self.show_text("Next")

    def previous_radio(self, rotary_encoder: RotaryEncoder):
        if self.radio.previous_channel():
            self.show_text("Previous")

    def mute(self):
        new_volume = self.radio.mute()
        if new_volume != -1:
            if new_volume == 0:
                self.show_text("Mute")
            else:
                self.show_text("Unmute")

    # def change(self, rotary_encoder: RotaryEncoder):
    #     print(f"{rotary_encoder.value}")

    def signal_handler(self, signal, frame):
        oled.clear()
        im = Image.new('1', oled.size)
        im2 = Image.open("zzz.bmp")
        im.paste(im2)
        oled.image(im, sync=1)
        time.sleep(2)
        oled.clear()
        oled.end()
        sys.exit(0)

    def show_text(self, text) -> None:
        #Affichage des commandes
        image = Image.new('1', (128,16))  # make 128x64 bitmap image
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(
            font='/usr/share/fonts/truetype/freefont/FreeMono.ttf')
        draw.text((0, 0), text, font=font, fill=255)
        oled.image(image)

    async def display_update_loop(self) -> None:
        while True:
            if time.time() > self.__last_display_refresh + self.__display_refresh_rate:
                self.refresh_display()
            await asyncio.sleep(self.__display_refresh_rate)

    def run(self):
        while True:
            # Affichage de la station
            # oled.clear(area=(0,(16+1),128,(64-17))) # Line 1 = 16. Line 3 = 16
            # self.current_channel = self.radio.get_channel_name()
            # sc1 = ScrollText.new(
            #     font='/usr/share/fonts/truetype/freefont/FreeMono.ttf',
            #     speed=16,
            #     area=((0, 17), (128, 64-17)),
            #     size=32)
            # sc1.add_text("Mon petit France Inter")
            # sc1.scrollOut()

            # Affichage des titres
            oled.clear(area=(0,48,128,64))
            self.current_title = self.radio.get_display()
            sc2 = ScrollText.new(
                font='/usr/share/fonts/truetype/freefont/FreeMono.ttf',
                speed=16,
                area=((0,48),(128,64)),
                size=16)
            sc2.add_text(self.radio.get_display())
            sc2.scrollOut()
            while self.current_title == self.radio.get_display():
                #sc1.update()
                sc2.update()
                #time.sleep(0.005))



#
# Main loop
#
if __name__ == "__main__":
    app = PiWebRadioApp()
    app.run()




