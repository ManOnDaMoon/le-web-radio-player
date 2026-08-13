
import os
import time, signal
from gpiozero import Button, RotaryEncoder
from math import ceil
import requests
import threading
from flask import Flask, request, abort
from waitress import serve

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from luma.core.virtual import viewport

from INA219 import INA219

from PIL import Image, ImageFont

from radio import Radio

class PiWebRadioApp():

    __debug = False
    __data_refresh_rate: int = 2  # Time between two metadata API calls, in seconds
    __display_refresh_rate: float = 0.20 # Time between two OLED screen refresh, in seconds
    __off_time_limit: int = 15*60 # Time limit after which the OS shuts down to save battery life, in seconds. Currently Unused.
    __off_time: float = 0 # Time since the radio has been toggled off

    def __init__(self):
        # IO INIT
        # Initialisation DISPLAY
        self.serial = i2c(port=1, address=0x3C)
        self.oled = ssd1306(self.serial)
        self.oled.contrast(40) #TODO Setup a contrast control

        # INIT UPS HAT
        self.ina219 = INA219(addr=0x43)
        self.__battery_alert_limit = 10.0 # Raise power alert if below 10%
        self.battery_percentage_history = []
        self.battery_percentage = 0.0 # Battery charge level
        self.battery_current = 0.0 # Used to detect charging
        self.battery_alert_time = 0.0
        self.update_battery_status()

        self.__script_dir_name = os.path.dirname(__file__)
        # Display splash screen
        self.display_splash(os.path.join(self.__script_dir_name, "radiodiane-splash.bmp"))

        # CLASS VARIABLES
        self.main_text = "" # Main display text, usually the station name
        self.secondary_text = "" # Secondary display text, usually the track and artist names
        self.volume = 0 # Initial volume
        self.scroll_r_count = 0 # Rotary buttons scroll counts
        self.scroll_l_count = 0
        self.is_mute = False # Mute indicator
        self.power = False # Power indicator
        self.doing_shutdown = False # OS Shutdown in progress indicator
        self.power_alert = 0 # Power alert indicator
        self.clock = True # Clock mode indicator
        self.radio = Radio(self.__debug) # The actual radio object
        self.redraw_volume = True
        self.redraw_battery = True
        self.redraw_main_text = True
        self.redraw_secondary_text = True
        self.menu_mode = False
        # OLED display fonts, loaded just once:
        self.icons_font = ImageFont.truetype(os.path.join(self.__script_dir_name, "radiocontrols.ttf"), 16)
        self.title_font = ImageFont.truetype(os.path.join(self.__script_dir_name, "Louis George Cafe.ttf"), 26)
        self.text_font = ImageFont.truetype(os.path.join(self.__script_dir_name, "Louis George Cafe.ttf"), 16)
        # OLED display default positions
        self.icons_y_position = 0
        self.title_y_position = 16
        self.text_y_position = 42

        # Adding a hold indicator to the Button class
        Button.was_held = False

        # Initialisation bouton VOLUME
        self.volume_knob = RotaryEncoder(17, 27, max_steps=10)  # GPIO17 = CLK, GPIO27 = DT
        self.mute_switch = Button(22, bounce_time=0.1)  # GPIO22 = SW - Note that Mute switch has no Hold event

        # Initialisation bouton CHANNEL
        self.channel_knob = RotaryEncoder(23, 24, max_steps=10)  # GPIO23 = CLK, GPIO24 = DT
        self.on_off_switch = Button(10, hold_time=2, bounce_time=0.1)  # GPIO10 = SW

        # Sélecteur Volume
        self.mute_switch.when_released = self.mute_switch_released
        #self.mute_switch.when_pressed = self.button_mute
        self.mute_switch.when_held = self.menu_toggle
        self.volume_knob.when_rotated_clockwise = self.button_volume_up
        self.volume_knob.when_rotated_counter_clockwise = self.button_volume_down

        # Sélecteur station
        self.on_off_switch.when_released = self.on_off_released
        self.on_off_switch.when_held = self.total_shutdown
        self.channel_knob.when_rotated_clockwise = self.button_next_radio
        self.channel_knob.when_rotated_counter_clockwise = self.button_previous_radio

        # Gestion de l'arrêt forcé
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGHUP, self.signal_handler)

        self.daemons = []
        self.threads = []

        # TODO : Display a specific information or replace with an Offline mode detection
        self.wait_for_internet_connection()

        # Initialisation API
        self.api = Flask(__name__)

        # Scroll the splashcreen to indicate the end of loading sequence
        self.scroll_right(self.splash_virtual, (0,0))

        # Start the radio in Off mode
        self.__off_time = time.time()

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

    def display_splash(self, image_path, wait_time = 0):
        splash = Image.open(image_path).convert('RGBA')
        splash = splash.convert(self.oled.mode)
        w, h = splash.size
        self.splash_virtual = viewport(self.oled, width=w, height=h)
        self.splash_virtual.display(splash)
        time.sleep(wait_time) # Does not lock splash in place if not called from display thread

    def on_off_released(self, button):
        if not button.was_held:
            self.toggle_on_off()
        button.was_held = False

    def mute_switch_released(self, button):
        if not button.was_held:
            self.button_mute()
        button.was_held = False

    def toggle_on_off(self):
        self.main_text = ""
        self.secondary_text = ""
        # TODO : Test self.radio.power instead
        if self.radio.toggle_on_off():
            self.power = True
            self.clock = False
            self.volume = self.radio.volume
        else:
            self.power = False
            self.clock = True
            self.__off_time = time.time()

    def shutdown_tasks(self):
        self.radio.stop()
        self.power = False
        self.clock = False
        self.doing_shutdown = True
        self.display_splash(os.path.join(self.__script_dir_name, "aurevoir.bmp"), 2)
        #self.oled.hide()

        for thread in self.threads:
            thread.join()

    # Catches SIGINT, SIGTERM, SIGHUP and terminates all threads properly
    def signal_handler(self, signal, frame):
        if not self.doing_shutdown: # Only if unexpected shutdown only
            self.shutdown_tasks()
            exit(0)

    def total_shutdown(self, button):
        button.was_held = True
        self.shutdown_tasks()
        print(f"{time.ctime(time.time())} : Extinction totale par bouton physique")
        os.system("sudo systemctl poweroff --force --message=\"RADIODIANE POWEROFF\"")
        exit(0)

    def menu_toggle(self, button):
        button.was_held = True
        self.menu_mode = True

    def button_volume_up(self, rotary_encoder: RotaryEncoder):
        self.volume = self.radio.volume_up()
        self.redraw_volume = True

    def button_volume_down(self, rotary_encoder: RotaryEncoder):
        self.volume = self.radio.volume_down()
        self.redraw_volume = True

    def button_next_radio(self, rotary_encoder: RotaryEncoder):
        self.scroll_r_count+=1
        self.scroll_l_count=0
        if self.scroll_r_count >= 1:
            self.scroll_r_count = 0
            if self.radio.next_channel():
                self.show_text(">>", "Chargement")

    def button_previous_radio(self, rotary_encoder: RotaryEncoder):
        self.scroll_l_count += 1
        self.scroll_r_count = 0
        if self.scroll_l_count >= 1:
            self.scroll_l_count = 0
            if self.radio.previous_channel():
                self.show_text("<<", "Chargement")

    def button_mute(self):
        new_volume = self.radio.mute()
        if new_volume != -1:
            if new_volume == 0:
                self.is_mute = True
            else:
                self.is_mute = False
            self.redraw_volume = True

    # Forces a custom text to be displayed immediately in front of the metadata text
    def show_text(self, text, secondary_text = "") -> None:
        self.main_text = f"{text} {self.radio.get_channel_name()}"
        self.secondary_text = secondary_text
        self.redraw_main_text = True
        self.redraw_secondary_text = True

    # THREAD
    # While currently running, regularly check if track info has changed and set flag to redraw display accordingly.
    # API metadata refresh happens in its own thread to avoid hanging during the HTTP request.
    def refresh_display_data(self) -> None:
        while not self.doing_shutdown:
            if self.power:
                old_main_text = self.main_text
                old_secondary_text = self.secondary_text
                self.main_text = self.radio.get_channel_name()
                self.secondary_text = self.radio.get_display()
                if (old_main_text != self.main_text):
                    self.redraw_main_text = True
                if (old_secondary_text != self.secondary_text):
                    self.redraw_secondary_text = True
                time.sleep(self.__data_refresh_rate)
            else:
                time.sleep(1)

    # THREAD
    # While currently running, regularly poll metadata API.
    # The radio object sets itself the correct refresh rate to avoid flooding the API provider.
    # So a __data_refresh_rate of 1s or 2s is not too long here.
    def refresh_metadata(self):
        while not self.doing_shutdown:
            if self.power:
                self.radio.current_channel.fetch_metadata()
                time.sleep(self.__data_refresh_rate)
            else:
                time.sleep(1)

    # Draws the volume icons according to volume
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

    # THREAD
    # This thread handles the OLED drawing procedures
    def main_display(self):
        self.oled.show()
        scroll1 = False
        scroll2 = False
        x3=0
        y3=0
        x3increment=4
        y3increment=4

        while not self.doing_shutdown:

            # DISPLAY PROCEDURE ON POWER ON
            if self.power:
                with canvas(self.oled) as draw:

                    # BATTERY STATUS
                    if self.redraw_battery:
                        if self.power_alert > 0:
                            old_volume = self.radio.volume
                            self.radio.set_volume(0)
                            self.display_splash(os.path.join(self.__script_dir_name, "lowpower.bmp"), 3)
                            self.power_alert = 0
                            self.radio.set_volume(old_volume)
                            continue
                        if self.battery_current > 0:
                            battery_text = "LOP"
                        else:
                            num_bars = ceil(self.battery_percentage / 25)
                            battery_text = f"L{'M' * (num_bars)} {'N' * (4 - num_bars)}P"
                        xbatt = 128 - draw.textlength(battery_text, font=self.icons_font)
                        self.redraw_battery = False
                    draw.text((xbatt, self.icons_y_position), battery_text, font=self.icons_font, fill="white")

                    # TOP ICONS
                    if self.redraw_volume:
                        icontext = self.get_volume_text()
                        self.redraw_volume = False
                    draw.text((0, self.icons_y_position), icontext, font=self.icons_font, fill="white")

                    # REDRAW TEXT
                    if self.redraw_main_text:
                        length1 = draw.textlength(self.main_text, font=self.title_font)
                        scroll1 = (length1 > 128)
                        pause1 = 5  # Pause (5*0,2 = ~1s) avant de démarrer le scroll
                        x1 = 0
                        self.redraw_main_text = False

                    if self.redraw_secondary_text:
                        length2 = draw.textlength(self.secondary_text, font=self.text_font)
                        scroll2 = (length2 > 128)
                        pause2 = 5  # Pause (5*0,2 = ~1s) avant de démarrer le scroll
                        x2 = 0
                        self.redraw_secondary_text = False

                    # SCROLLING
                    # TITLES
                    if scroll1:
                        line1 = self.main_text + "      "
                        if length1 + x1 < 64:
                            x1=0
                            pause1 = 20
                        draw.text((x1,self.title_y_position), line1, font=self.title_font, fill="white")
                        if (pause1 < 0):
                            x1-=3
                        else:
                            pause1-=1
                    else:
                        draw.text((0,self.title_y_position), self.main_text, font=self.title_font, fill="white")

                    if scroll2:
                        line2 = self.secondary_text + "      "
                        if length2 + x2 < 64:
                            x2=0
                            pause2 = 20
                        draw.text((x2, self.text_y_position), line2, font=self.text_font, fill="white")
                        if (pause2 < 0):
                            x2-=6 # Vitesse de scroll double pour les titres
                        else:
                            pause2-=1
                    else:
                        draw.text((0,self.text_y_position), self.secondary_text, font=self.text_font, fill="white")

                # Power mode refresh rate
                time.sleep(self.__display_refresh_rate)

            # DISPLAY PROCEDURE IN CLOCK MODE
            # Display time bouncing on the screen
            if self.clock:
                time_text = time.strftime("%H:%M")
                with canvas(self.oled) as draw:
                    time_text_length = draw.textlength(time_text, font_size=16)
                    draw.text((x3, y3), time_text, font_size=15, fill="white")
                    if self.battery_current > 0:
                        battery_text = "L O P"
                    else:
                        num_bars = ceil(self.battery_percentage / 25)
                        battery_text = f"L {'M' * (num_bars)} {'N' * (4 - num_bars)} P"
                    xbatt = 128 - draw.textlength(battery_text, font=self.icons_font)
                    draw.text((xbatt, self.icons_y_position), battery_text, font=self.icons_font, fill="white")

                x3+=x3increment
                y3+=y3increment
                if x3 <= 0 or x3 + time_text_length > 127:
                    x3increment=-x3increment
                if y3 <= 0 or y3 + 16 > 63:
                    y3increment=-y3increment

                # Off mode refresh rate : one tick per second - longer means radio can turn on before the display changes.
                time.sleep(1)

    def update_battery_status(self):
        bus_voltage = self.ina219.getBusVoltage_V()  # voltage on V- (load side)
        current = self.ina219.getCurrent_mA()  # current in mA
        p = (bus_voltage - 3) / 1.2 * 100
        if p > 100: p = 100
        if p < 0: p = 0
        if len(self.battery_percentage_history) == 0:
            for x in range(10):
                self.battery_percentage_history.append(p)
        else:
            self.battery_percentage_history.pop(0)
            self.battery_percentage_history.append(p)
        self.battery_current = current
        self.battery_percentage = sum(self.battery_percentage_history) / len(self.battery_percentage_history)
        self.redraw_battery = True

    # THREAD
    # BATTERY MANAGEMENT
    #TODO : Add network signal monitor
    def power_monitor(self):
        while not self.doing_shutdown:
            self.update_battery_status()
            if self.__debug:
                print(f"Pourcentage : {self.battery_percentage} - Courant : {self.battery_current}")
            if (self.battery_current < 0 and self.battery_percentage <= self.__battery_alert_limit):
                self.power_alert = 1
                self.battery_alert_time = time.time()
                print(f"{time.ctime(self.battery_alert_time)} : Alerte batterie faible {self.battery_percentage}")
                if self.battery_percentage <= 7.0:
                    print(f"{time.ctime(self.battery_alert_time)} : Extinction batterie faible")
                    os.system("sudo systemctl poweroff --force --message=\"RADIODIANE POWEROFF\"")
            else:
                self.power_alert = 0
            time.sleep(5)


    # API ROUTES
    def api_next_radio(self):
        """
        API route that handles switching to the next radio in the radio list.
        :return: Returns JSON object with 'radio' and 'title' fields.
        """
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
        self.redraw_volume = True
        response = {
            "volume" : self.volume
        }
        return response

    def api_volume_down(self):
        self.volume = self.radio.volume_down()
        self.redraw_volume = True
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
            self.redraw_volume = True
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
        self.shutdown_tasks()
        print(f"{time.ctime(time.time())} : Extinction totale par API")
        os.system("sudo systemctl poweroff --force --message=\"RADIODIANE POWEROFF\"")
        exit(0)

    def api_reboot(self):
        self.shutdown_tasks()
        print(f"{time.ctime(time.time())} : Reboot par API")
        os.system("sudo systemctl reboot --force --message=\"RADIODIANE REBOOT\"")
        exit(0)

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
            self.redraw_volume = True
            return response
        else:
            abort(400)

    def api_get_title(self):
        titles = {
            "radio" : self.radio.get_channel_name(),
            "title" : self.radio.get_display()
        }
        return titles

    def api_get_battery(self):
        self.update_battery_status()
        battery_status = {
            "current" : self.battery_current,
            "percentage" : self.battery_percentage
        }
        return battery_status

    def run_api(self):
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
        self.api.add_url_rule("/battery", view_func=self.api_get_battery)
        serve(self.api, host="0.0.0.0", port=80)
        #self.api.run(host="0.0.0.0", port=80, debug=self.__debug, use_reloader=False)

    def run_threads(self):
        self.threads.append(threading.Thread(target=self.refresh_display_data, args=()))
        self.threads.append(threading.Thread(target=self.refresh_metadata, args=()))
        self.threads.append(threading.Thread(target=self.main_display, args=()))
        self.threads.append(threading.Thread(target=self.power_monitor, args=()))
        self.daemons.append(threading.Thread(target=self.run_api, args=(), daemon=True))
        for thread in self.threads:
            thread.start()
        for daemon in self.daemons:
            daemon.start()

#
# Main loop
#
if __name__ == "__main__":
    try:
        app = PiWebRadioApp()
        app.run_threads()
    except (SystemExit, KeyboardInterrupt):
        exit(0)
