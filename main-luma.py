
import os, subprocess
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
    #TODO: Use __off_time and __off_time_limit or delete them. __off_time is not consistently updated at the time
    __off_time_limit: int = 15*60 # Time limit after which the OS shuts down to save battery life, in seconds. Currently Unused.
    __off_time: float = 0 # Time since the radio has been toggled off

    def __init__(self):
        # IO INIT
        # Initialisation DISPLAY
        self.serial = i2c(port=1, address=0x3C)
        self.oled = ssd1306(self.serial)
        self.oled.contrast(10)

        # INIT UPS HAT
        self.ina219 = INA219(addr=0x43)
        self.__battery_alert_limit = 10.0 # Raise power alert if below 10%
        self.__critical_battery_alert_limit = 5.0 # Critical alert below 5%
        self.__final_battery_alert_limit = 3.0 # Shut down when below 3%
        self.battery_percentage_history = []
        self.battery_percentage = 0.0 # Battery charge level
        self.battery_current = 0.0 # Used to detect charging
        self.battery_alert_time = 0.0
        self.update_battery_status()

        self.wifi_status = None # Wifi status dictionary
        self.wifi_quality = 0.0 # Wifi quality percentage (self.wifi_status['Quality'] rated up to 70)

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
        self.redraw_wifi = True
        self.redraw_main_text = True
        self.redraw_secondary_text = True
        self.sleep_mode = False
        self.sleep_time = 0.0
        self.bt_active = False

        # OLED display fonts, loaded just once:
        self.icons_font = ImageFont.truetype(os.path.join(self.__script_dir_name, "radiocontrols.ttf"), 16)
        self.title_font = ImageFont.truetype(os.path.join(self.__script_dir_name, "Louis George Cafe.ttf"), 26)
        self.text_font = ImageFont.truetype(os.path.join(self.__script_dir_name, "Louis George Cafe.ttf"), 16)
        self.menu_font = ImageFont.truetype(os.path.join(self.__script_dir_name, "Louis George Cafe.ttf"), 12)
        # OLED display default positions
        self.icons_y_position = 0
        self.title_y_position = 16
        self.text_y_position = 42

        # Menu structures
        self.redraw_menu = True
        self.menu_active = False
        self.menu_highlight_index = 1
        # Menu item structure : [ "Name", submenu or value , callback ]
        self.menu = [
            "Menu",
            [
                "Sleep",
                ["5 min.", 5, self.menu_set_sleep],
                ["10 min.", 10, self.menu_set_sleep],
                ["15 min.", 15, self.menu_set_sleep],
                ["30 min.", 30, self.menu_set_sleep],
                ["60 min.", 60, self.menu_set_sleep],
                ["Off", -1, self.menu_set_sleep],
                ["Retour", None, self.menu_reset]
            ],
            [
                "Wifi",
                ["SSID", None, None], # Info only, no callback
                ["Signal", None, None], # Info only, no callback
                ["Retour", None, self.menu_reset]
            ],
            [
                "Bluetooth",
                ["Statut :", None, None],
                ["Activer", True, self.menu_set_bluetooth],
                ["Désactiver", False, self.menu_set_bluetooth],
                ["Retour", None, self.menu_reset]
            ],
            [
                "Retour",
                None,
                self.menu_close # Callback to close menu?
            ]
        ]
        self.displayed_menu = self.menu

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

        # Wait for an active connection to conclude init
        self.wait_for_internet_connection()

        # Initialisation API
        self.api = Flask(__name__)

        # Scroll the splashcreen to indicate the end of loading sequence
        # Disabled for faster startup
        #self.scroll_right(self.splash_virtual, (0,0))

        # Start the radio in Off mode
        self.__off_time = time.time()

    def wait_for_internet_connection(self):
        while True:
            try:
                res = requests.get("https://www.radiofrance.fr")
                if res.status_code == 200:
                    self.update_wifi_status()
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
        if self.menu_active:
            # In menu mode : NAVIGATE MENU and LAUNCH ACTIONS
            # Check if last item of menu : go back to main menu
            #if self.menu_highlight_index == len(self.displayed_menu) - 1:
            #    #go back
            #    self.menu_highlight_index = 1
            #    self.displayed_menu = self.menu
            #    self.redraw_menu = True
            #    return
            # Check if last item or if self.displayed_menu[self.menu_highlight_index][1] is a list
            if type(self.displayed_menu[self.menu_highlight_index][1]) == list:
                self.displayed_menu = self.displayed_menu[self.menu_highlight_index]
                self.menu_highlight_index = 1
                return
            else: #No list, so use callback method
                if not self.displayed_menu[self.menu_highlight_index][2] is None:
                    if self.displayed_menu[self.menu_highlight_index][1] is None:
                        self.displayed_menu[self.menu_highlight_index][2]()
                    else:
                        self.displayed_menu[self.menu_highlight_index][2](self.displayed_menu[self.menu_highlight_index][1])

        else:
            # In standard mode : TOGGLE ON/OFF
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
        if self.power:
            self.redraw_menu = True
            self.displayed_menu = self.menu
            self.menu_highlight_index = 1
            self.menu_active = not self.menu_active

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
            if self.menu_active:
                self.redraw_menu = True
                self.menu_highlight_index = min(len(self.displayed_menu) - 1, self.menu_highlight_index + 1)
            else:
                if self.radio.next_channel():
                    self.show_text(">>", "Chargement")

    def button_previous_radio(self, rotary_encoder: RotaryEncoder):
        self.scroll_l_count += 1
        self.scroll_r_count = 0
        if self.scroll_l_count >= 1:
            self.scroll_l_count = 0
            if self.menu_active:
                self.redraw_menu = True
                self.menu_highlight_index = max(1, self.menu_highlight_index - 1)
            else:
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

    def menu_reset(self) -> None:
        self.menu_highlight_index = 1
        self.displayed_menu = self.menu
        self.redraw_menu = True

    def menu_close(self) -> None:
        self.menu_active = not self.menu_active

    def menu_set_sleep(self, minutes: int) -> None:
        if minutes > 0:
            self.sleep_mode = True
            self.sleep_time = time.time() + (minutes * 60)
            self.show_text("Sleep ON", f"{minutes} minutes")
        else:
            self.sleep_mode = False
            self.sleep_time = 0.0
            self.show_text("Sleep OFF")
            self.menu[1][0] = "Sleep"
        self.menu_close()

    def menu_set_bluetooth(self, active: bool) -> None:
        if active:
            os.system("sudo systemctl start bt-agent")
        else:
            os.system("sudo systemctl stop bt-agent")

    # THREAD
    # While currently running, regularly check if track info has changed and set flag to redraw display accordingly.
    # API metadata refresh happens in its own thread to avoid hanging during the HTTP request.
    def refresh_display_data(self) -> None:
        while not self.doing_shutdown:
            if self.power:
                # TODO: Add a 2s delay to display messages from show_text()
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
        icontext = (
            f"{'B' if self.is_mute else 'A'}" # Speaker icon
            f"{'C' if self.volume >= 10 else ''}"
            f"{'D' if self.volume >= 20 else ''}"
            f"{'E' if self.volume >= 30 else ''}"
            f"{'F' if self.volume >= 40 else ''}"
            f"{'G' if self.volume >= 50 else ''}"
            f"{'H' if self.volume >= 60 else ''}"
            f"{'I' if self.volume >= 70 else ''}"
            f"{'J' if self.volume >= 80 else ''}"
        )

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
                # HANDLE MENU DISPLAY
                if self.menu_active:
                    if self.redraw_menu:
                        with canvas(self.oled) as menu_draw:
                            for index, item in enumerate(self.displayed_menu):
                                if index == 0:
                                    title_text = item
                                    menu_draw.rectangle([(0, 0), (128, 12)], outline="white", fill="white")
                                    menu_draw.text((64, 6), title_text, font=self.menu_font, fill="black",
                                                   anchor="mm")
                                if index != 0:
                                    item_x = 0 if index < 5 else 64
                                    item_y = (index * 12) if index < 5 else (index - 4) * 12
                                    item_text = f"{'> ' if self.menu_highlight_index == index else ''}{item[0]}"
                                    menu_draw.text((item_x, item_y), item_text, font=self.menu_font, fill="white")

                else:
                    with canvas(self.oled) as draw:
                        # HANDLE REGULAR DISPLAY (Volume - Clock - Station - Song)
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
                                battery_text = "LONP"
                            else:
                                num_bars = ceil(self.battery_percentage / 25)
                                battery_text = f"L{'M' * (num_bars)} {'N' * (4 - num_bars)}P"
                            xbatt = 128 - draw.textlength(battery_text, font=self.icons_font)
                            self.redraw_battery = False
                        draw.text((xbatt, self.icons_y_position), battery_text, font=self.icons_font, fill="white")

                        if self.sleep_mode:
                            draw.text((50, self.icons_y_position), "Z", font=self.icons_font, fill="white")

                        if self.redraw_wifi:
                            wifitext = (
                                f"U{'V' if self.wifi_quality > 0 else ''}"
                                f"{'W' if self.wifi_quality > 25 else ''}"
                                f"{'X' if self.wifi_quality > 50 else ''}"
                                f"{'Y' if self.wifi_quality > 75 else ''}"
                            )
                        draw.text((68, self.icons_y_position), wifitext, font=self.icons_font, fill="white")

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
                        battery_text = "LOP" # Battery bottom segment + charge indicator + top segment
                    else:
                        num_bars = ceil(self.battery_percentage / 25)
                        battery_text = (
                            "L" # Battery bottom segment
                            f"{'M' * (num_bars)}" # battery capacity segments
                            f"{'N' * (4 - num_bars)}" # empty battery segments
                            "P" # Battery top segment
                        )
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

    def update_bt_status(self):
        btresult = subprocess.Popen(['sudo', 'systemctl', 'is-active', 'bt-agent', '--quiet'], stdout=subprocess.PIPE, universal_newlines=True)
        self.bt_active = (btresult.returncode == '0')
        self.menu[3][1] = [f"Statut : {'Actif' if self.bt_active else 'Inactif'}", None, None]

    def update_wifi_status(self):
        iwresult = subprocess.Popen(['iwconfig', 'wlan0'], stdout=subprocess.PIPE, universal_newlines=True)
        out, err = iwresult.communicate()
        resultdict = {}
        for iwresult in out.split(' '):
            if iwresult:
                if iwresult.find(':') > 0:
                    datumname = iwresult.strip().split(':')[0]
                    datum = iwresult.strip().split(':')[1].split(' ')[0].split('/')[0].replace('"', '')
                    resultdict[datumname] = datum
                elif iwresult.find('=') > 0:
                    datumname = iwresult.strip().split('=')[0]
                    datum = iwresult.strip().split('=')[1].split(' ')[0].split('/')[0].replace('"', '')
                    resultdict[datumname] = datum

        if len(resultdict) == 0:
            self.wifi_status = {'ESSID' : '', 'Quality' : '0'}
        else:
            self.wifi_status = resultdict

        self.menu[2][1] = [f"SSID : {self.wifi_status['ESSID']}", 1, None]
        self.menu[2][2] = [f"Qualité : {self.wifi_status['Quality']} / 70", 0, None]
        self.wifi_quality = int(self.wifi_status['Quality'])*100/70
        self.redraw_wifi = True

    def update_battery_status(self):
        bus_voltage = self.ina219.getBusVoltage_V()  # voltage on V- (load side)
        current = self.ina219.getCurrent_mA()  # current in mA
        p = (bus_voltage - 3) / 1.2 * 100
        if p > 100: p = 100
        if p < 0: p = 0
        if current > 0:
            self.battery_percentage_history = []
        else:
            self.battery_percentage_history.append(p)
            if len(self.battery_percentage_history) > 10:
                self.battery_percentage_history.pop(0)
            self.battery_percentage = sum(self.battery_percentage_history) / len(self.battery_percentage_history)
        self.battery_current = current
        self.redraw_battery = True

    # THREAD
    # BATTERY & NETWORK & SLEEP MANAGEMENT
    def power_monitor(self):
        while not self.doing_shutdown:
            self.update_battery_status()
            self.update_wifi_status()
            self.update_bt_status()

            # Power alert update
            if self.__debug:
                print(f"Pourcentage : {self.battery_percentage} - Courant : {self.battery_current}")

            # Show an alert
            if (self.battery_current < 0 and (
                    (self.battery_percentage <= self.__battery_alert_limit
                    and time.time() - self.battery_alert_time > 60)
                    or
                    (self.battery_percentage <= self.__critical_battery_alert_limit
                     and time.time() - self.battery_alert_time > 15)
                )
            ):
                self.power_alert = 1
                self.battery_alert_time = time.time()
                print(f"{time.ctime(self.battery_alert_time)} : Alerte batterie faible {self.battery_percentage}")
            else:
                self.power_alert = 0

            # Force shutdown if too low
            if self.battery_current < 0 and self.battery_percentage <= self.__final_battery_alert_limit:
                print(f"{time.ctime(self.battery_alert_time)} : Extinction batterie faible")
                os.system("sudo systemctl poweroff --force --message=\"RADIODIANE POWEROFF\"")

            if self.sleep_mode:
                if time.time() > self.sleep_time:
                    # Sleep is over. Turn off.
                    self.radio.power = False
                    self.radio.stop()
                    self.power = False
                    self.clock = True
                    self.__off_time = time.time()
                    self.sleep_mode = False
                    self.sleep_time = 0
                    self.menu[1][0] = "Sleep"
                # Update remaining sleep time
                self.menu[1][0] = f"Sleep ({(self.sleep_time - time.time())/60:2.0f} min.)"

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
