import asyncio

from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.widgets import Button, Header, Footer, Label
from textual import on
import time

from radio import Radio

class RadioApp(App):
    DEBUG = True

    CSS = """
    Screen {
        layout: grid;
        grid-size: 3;
        grid-gutter: 2;
        padding: 2;
    }
    Label {
        width: 100%;
        height: 100%;
        content-align: center middle;
        text-style: bold;
    }
    Button {
        width: 100%;
    }
    """

    TITLE = "Ma Radio Web"
    SUB_TITLE = "Mes stations web préférées"

    BINDINGS = [
        ("up", "volume_up()", "Increase volume"),
        ("down", "volume_down()", "Decrease volume"),
        ("right", "next_radio()", "Next channel"),
        ("left", "previous_radio()", "Previous channel"),
        ("m", "mute()", "Mute"),
        ("s", "toggle_on_off()", "Toggle On/Off")
    ]

    radio = Radio()
    __display_refresh_rate: int = 2 # in seconds
    __last_display_refresh: float = 0.0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("", id="display")
        yield Label("", id="display2")
        yield Label("", id="display3")
        yield Button("Previous", id="previous", variant="default")
        yield Button("On / Off", id="power", variant="default")
        yield Button("Next", id="next", variant="default")
        yield Button("Volume DOWN", id="volumeDown", variant="default")
        yield Button("Mute", id="mute", variant="default")
        yield Button("Volume UP", id="volumeUp", variant="default")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self.display_update_loop())

    #
    # Start worker to periodically update display
    #
    async def display_update_loop(self) -> None:
        while True:
            if time.time() > self.__last_display_refresh + self.__display_refresh_rate:
                self.refresh_display()
            await asyncio.sleep(self.__display_refresh_rate)

    #
    # Button events
    #
    @on(Button.Pressed, "#power")
    def toggle_on_off(self) -> None:
        if self.radio.toggle_on_off():
            self.show_text("Power On")
        else:
            self.show_text("Shut Off")

    @on(Button.Pressed, "#next")
    def next_radio(self) -> None:
        if self.radio.next_channel():
            self.show_text("Next")

    @on(Button.Pressed, "#previous")
    def previous_radio(self) -> None:
        if self.radio.previous_channel():
            self.show_text("Previous")

    @on(Button.Pressed, "#volumeUp")
    def volume_up(self) -> None:
        new_volume = self.radio.volume_up()
        if new_volume != -1:
            self.show_text(f"Volume Up : {new_volume}")

    @on(Button.Pressed, "#volumeDown")
    def volume_down(self) -> None:
        new_volume = self.radio.volume_down()
        if new_volume != -1:
            self.show_text(f"Volume Down : {new_volume}")

    @on(Button.Pressed, "#mute")
    def mute(self) -> None:
        new_volume = self.radio.mute()
        if new_volume != -1:
            if new_volume == 0:
                self.show_text("Mute")
            else:
                self.show_text("Unmute")

    #
    # Key bindings actions
    #
    def action_volume_up(self) -> None:
        self.volume_up()
    def action_volume_down(self) -> None:
        self.volume_down()
    def action_next_radio(self) -> None:
        self.next_radio()
    def action_previous_radio(self) -> None:
        self.previous_radio()
    def action_mute(self) -> None:
        self.mute()
    def action_toggle_on_off(self) -> None:
        self.toggle_on_off()

    # Sync display with radio media title
    def refresh_display(self) -> None:
        try:
            self.screen.query_one('#display').update(self.radio.get_channel_name())
            self.screen.query_one('#display2').update(self.radio.get_display())
            self.__last_display_refresh = time.time()
            if self.DEBUG:
                self.screen.query_one('#display3').update(self.radio.get_debug())
            else:
                self.screen.query_one('#display3').update("")
            self.__last_display_refresh = time.time()
        except NoMatches:
            pass # If display text is momentarily off-screen, just pass.

    # Temporary set additional display text
    def show_text(self, text) -> None:
        try:
            self.screen.query_one('#display').update(f"{self.radio.get_channel_name()}\n-\n{text}")
        except NoMatches:
            pass # If display text is momentarily off-screen, just pass.

#
# Main loop
#
if __name__ == "__main__":
    app = RadioApp()
    app.run()
