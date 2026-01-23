
import os
import time, signal
from gpiozero import Button, RotaryEncoder
import requests
import threading
from flask import Flask, request, abort

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from luma.core.virtual import viewport

from PIL import Image, ImageFont

from radio import Radio

class PiWebRadioApp():

    __debug = False
    __data_refresh_rate: int = 2  # in seconds
    __display_refresh_rate: float = 0.2
    __last_display_refresh: float = 0.0
    __off_time_limit: int = 15*60 # in seconds
    __off_time: float = 0

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
        self.doing_shutdown = False
        self.power_alert = 0
        self.clock = True
        self.redraw = True
        self.radio = Radio(self.__debug)
        self.icons_font = ImageFont.truetype(os.path.join(self.__script_dir_name, "radiocontrols.ttf"), 16)
        self.title_font = ImageFont.truetype(os.path.join(self.__script_dir_name, "Louis George Cafe.ttf"), 26)
        self.text_font = ImageFont.truetype(os.path.join(self.__script_dir_name, "Louis George Cafe.ttf"), 16)
        self.icons_y_position = 0
        self.title_y_position = 16
        self.text_y_position = 42

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
        #TODO: Maintenir le bouton volume pour switcher de mode

        # Sélecteur station
        self.on_off_switch.when_released = self.on_off_released
        self.on_off_switch.when_held = self.total_shutdown
        self.channel_knob.when_rotated_clockwise = self.next_radio
        self.channel_knob.when_rotated_counter_clockwise = self.previous_radio

        # Gestion de l'arrêt forcé
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGHUP, self.signal_handler)

        self.wait_for_internet_connection() #TODO: Replace with an Offline Mode detection

        self.scroll_right(self.splash_virtual, (0,0))
        self.__off_time = time.time()

        # Initialisation API
        self.api = Flask(__name__)

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
    def scroll_right(self, virtual, pos):
        x, y = pos
        if virtual.width > self.oled.width:
            while x < virtual.width - self.oled.width:
                virtual.set_position((x, y))
                x += 2

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
            self.__off_time = time.time()

    def total_shutdown(self, button):
        button.was_held = True
        self.radio.stop()
        self.power = False
        self.clock = False
        self.display_splash(os.path.join(self.__script_dir_name, "aurevoir.bmp"))
        self.oled.hide()
        self.doing_shutdown = True
        self.metadataThread.join()
        self.displayThread.join()
        self.dataThread.join()
        print(f"{time.ctime(time.time())} : Extinction totale par bouton physique")
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
                self.show_text(">>", "Chargement")

    def previous_radio(self, rotary_encoder: RotaryEncoder):
        self.scroll_l_count += 1
        self.scroll_r_count = 0
        if self.scroll_l_count >= 3:
            self.scroll_l_count = 0
            if self.radio.previous_channel():
                self.show_text("<<", "Chargement")

    def mute(self):
        new_volume = self.radio.mute()
        if new_volume != -1:
            if new_volume == 0:
                self.is_mute = True
            else:
                self.is_mute = False

    def signal_handler(self, signal, frame):
        if not self.doing_shutdown: # Only if unexpected shutdown only
            self.radio.stop()
            self.power = False
            self.doing_shutdown = True
            self.metadataThread.join()
            self.displayThread.join()
            self.dataThread.join()
            self.oled.show()
            self.display_splash(os.path.join(self.__script_dir_name, "zzz.bmp"))
            self.scroll_right(self.splash_virtual, (0,0))
            self.oled.hide()

    def show_text(self, text, secondary_text = "") -> None:
        self.main_text = f"{text} {self.radio.get_channel_name()}"
        self.secondary_text = secondary_text
        self.redraw = True

    def refresh_display_data(self) -> None:
        while not self.doing_shutdown:
            if self.power:
                #if time.time() > self.__last_display_refresh + self.__data_refresh_rate: # Useless ?!
                old_main_text = self.main_text
                old_secondary_text = self.secondary_text
                self.main_text = self.radio.get_channel_name()
                self.secondary_text = self.radio.get_display() # Causes hang during metadata API call
                #self.__last_display_refresh = time.time()
                if (old_main_text != self.main_text) or (old_secondary_text != self.secondary_text):
                    self.redraw = True
            # Disabling inactivity shutdown as long as there is no RTC in the radio
            # This has been wrongly triggered on several cases when time was not already synced
            #else:
            #    if time.time() > self.__off_time + self.__off_time_limit:
            #        print(f"Time: {time.ctime(time.time())}")
            #        print(f"Off time limit: {time.ctime(self.__off_time + self.__off_time_limit)}")
            #        print(f"{time.ctime(time.time())} : Extinction totale par délai d'inactivité")
            #        os.system("sudo shutdown -h now")
            time.sleep(self.__data_refresh_rate)

    def refresh_metadata(self):
        while not self.doing_shutdown:
            if self.power:
                self.radio.current_channel.fetch_metadata()
            time.sleep(self.__data_refresh_rate)

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

    def main_display(self):
        #TODO: Introduire un self.mode pour différencier les fonctionnalités : offline, radio, réveil, bluetooth, podcasts...
        #TODO: Définir une arborescence de menu pour les différentes fonctionnalités
        self.redraw = True
        x3=128
        while not self.doing_shutdown:
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
                    pause1 = 5 # Pause (5*0,2 = ~1s) avant de démarrer le scroll
                    pause2 = 5 # Pause (5*0,2 = ~1s) avant de démarrer le scroll
                    x1 = 0
                    x2 = 0
                    self.redraw = False
                icontext = self.get_volume_text()
                with canvas(self.oled) as draw:
                    # TOP ICONS - TODO : Optimiser pour ne pas redessiner les icones si elles n'ont pas changé
                    draw.text((0, self.icons_y_position), icontext, font=self.icons_font, fill="white")

                    # HEURE - TODO : Optimiser pour ne pas recalculer ça toutes les microsecondes.
                    time_text = time.strftime("%H:%M")
                    time_text_length = draw.textlength(time_text, font_size=15)
                    draw.text((128 - time_text_length, self.icons_y_position - 2), time_text,  font_size=15, fill="white")

                    # TITLES - TODO : ne calculer les textlength qu'une fois
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
                time.sleep(self.__display_refresh_rate)

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

                # Off mode refresh rate : one tick per second
                time.sleep(1) # Si temps d'attente trop long, le display ne se met pas en marche avec la radio !

    def power_monitor(self):
        self.power_alert = 0
        while not self.doing_shutdown:
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
                    print(f"{time.ctime(time.time())} : Extinction totale par alerte voltage")
                    os.system("sudo shutdown -h now")
            else:
                self.power_alert = 0
            time.sleep(60)

    def api_next_radio(self):
        channel = self.radio.next_channel()
        if channel != "":
            self.show_text(">>", "Chargement (API)")
        response = {
            "radio" : self.radio.get_channel_name(),
            "title" : self.radio.get_display()
        }
        return response


    def api_previous_radio(self):
        channel = self.radio.previous_channel()
        if channel != "":
            self.show_text("<<", "Chargement (API)")
        response = {
            "radio" : self.radio.get_channel_name(),
            "title" : self.radio.get_display()
        }
        return response

    def api_volume_up(self):
        self.volume = self.radio.volume_up()
        response = {
            "volume" : self.volume
        }
        return response

    def api_volume_down(self):
        self.volume = self.radio.volume_down()
        response = {
            "volume" : self.volume
        }
        return response

    def api_mute(self):
        new_volume = self.radio.mute()
        if new_volume != -1:
            if new_volume == 0:
                self.is_mute = True
            else:
                self.is_mute = False
        response = {
            "volume" : new_volume
        }
        return response

    def api_toggle_on_off(self):
        self.toggle_on_off()
        response = {
            "radio" : self.radio.get_channel_name(),
            "title" : self.radio.get_display()
        }
        return response

    def api_total_shutdown(self):
        self.radio.stop()
        self.power = False
        self.clock = False
        self.display_splash(os.path.join(self.__script_dir_name, "aurevoir.bmp"))
        self.oled.hide()
        self.doing_shutdown = True
        self.metadataThread.join()
        self.displayThread.join()
        self.dataThread.join()
        print(f"{time.ctime(time.time())} : Extinction totale par API")
        os.system("sudo shutdown -h now")
        return "Extinction totale en cours"

    def api_reboot(self):
        self.radio.stop()
        self.power = False
        self.clock = False
        self.display_splash(os.path.join(self.__script_dir_name, "aurevoir.bmp"))
        self.oled.hide()
        self.doing_shutdown = True
        self.metadataThread.join()
        self.displayThread.join()
        self.dataThread.join()
        print(f"{time.ctime(time.time())} : Reboot par API")
        os.system("sudo reboot")
        return "Reboot en cours"

    def api_list_radio(self):
        channels = []
        for channel in self.radio.channels:
            channels.append({
                "num" : self.radio.channels.index(channel),
                "name" : channel.name
            })
        return channels

    def api_switch_radio(self):
        if request.args.get("radio") and request.args.get("radio").isdigit():
            self.radio.switch_channel(int(request.args.get("radio")) - self.radio.channel_num)
            response = {
                "radio": self.radio.get_channel_name(),
                "title": self.radio.get_display()
            }
            return response
        else:
            abort(400)

    def api_set_volume(self):
        if request.args.get("volume") and request.args.get("volume").isdigit():
            self.volume = self.radio.set_volume(int(request.args.get("volume")))
            response = {
                "volume" : self.volume
            }
            return response
        else:
            abort(400)

    def api_get_title(self):
        titles = {
            "radio" : self.radio.get_channel_name(),
            "title" : self.radio.get_display()
        }
        return titles

    def run_api(self):
        #TODO : Réponses API mieux structurées
        self.api.add_url_rule("/next", view_func=self.api_next_radio)
        self.api.add_url_rule("/previous", view_func=self.api_previous_radio)
        self.api.add_url_rule("/volumeup", view_func=self.api_volume_up)
        self.api.add_url_rule("/volumedown", view_func=self.api_volume_down)
        self.api.add_url_rule("/setvolume", view_func=self.api_set_volume)
        self.api.add_url_rule("/mute", view_func=self.api_mute)
        self.api.add_url_rule("/onoff", view_func=self.api_toggle_on_off)
        self.api.add_url_rule("/totalshutdown", view_func=self.api_total_shutdown)
        self.api.add_url_rule("/reboot", view_func=self.api_reboot)
        self.api.add_url_rule("/list", view_func=self.api_list_radio)
        self.api.add_url_rule("/switch", view_func=self.api_switch_radio)
        self.api.add_url_rule("/title", view_func=self.api_get_title)
        self.api.run(host="0.0.0.0", port=80, debug=self.__debug, use_reloader=False)

    def run_threads(self):
        #TODO : Réintégrer le dataThread dans le displayThread
        self.dataThread = threading.Thread(target=self.refresh_display_data, args=())
        self.dataThread.start()
        self.metadataThread = threading.Thread(target=self.refresh_metadata, args=())
        self.metadataThread.start()
        self.displayThread = threading.Thread(target=self.main_display, args=())
        self.displayThread.start()
        self.apiThread = threading.Thread(target=self.run_api, args=(), daemon=True)
        self.apiThread.start()

#
# Main loop
#
if __name__ == "__main__":
    try:
        app = PiWebRadioApp()
        app.run_threads()
    except (SystemExit, KeyboardInterrupt):
        exit(0)
