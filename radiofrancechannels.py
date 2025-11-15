import requests
from radiochannel import RadioChannel
import time

__default_channels = [
        ['Mon Petit France Inter', 'https://stream.radiofrance.fr/monpetitfranceinter/monpetitfranceinter.m3u8?id=radiofranceBose', 1102],
        ['FIP', 'https://stream.radiofrance.fr/fip/fip.m3u8?id=radiofranceBose', 7],
        ['FIP Rock', 'https://stream.radiofrance.fr/fiprock/fiprock.m3u8?id=radiofranceBose', 64],
        ['FIP Jazz', 'https://stream.radiofrance.fr/fipjazz/fipjazz.m3u8?id=radiofranceBose', 65],
        ['FIP Groove', 'https://stream.radiofrance.fr/fipgroove/fipgroove.m3u8?id=radiofranceBose', 66],
        ['FIP Monde', 'https://stream.radiofrance.fr/fipworld/fipworld.m3u8?id=radiofranceBose', 69],
        ['FIP Nouveautés', 'https://stream.radiofrance.fr/fipnouveautes/fipnouveautes.m3u8?id=radiofranceBose', 70],
        ['FIP Reggae', 'https://stream.radiofrance.fr/fipreggae/fipreggae.m3u8?id=radiofranceBose', 71],
        ['FIP Electro', 'https://stream.radiofrance.fr/fipelectro/fipelectro.m3u8?id=radiofranceBose', 74],
        ['FIP Metal', 'https://stream.radiofrance.fr/fipmetal/fipmetal.m3u8?id=radiofranceBose', 77],
        ['FIP Pop', 'https://stream.radiofrance.fr/fippop/fippop.m3u8?id=radiofranceBose', 78],
        ['FIP Hip Hop', 'https://stream.radiofrance.fr/fiphiphop/fiphiphop.m3u8?id=radiofranceBose', 95],
        ['FIP Sacré Français', 'https://stream.radiofrance.fr/fipsacrefrancais/fipsacrefrancais.m3u8?id=radiofranceBose', 96],
        ['France Inter', 'https://stream.radiofrance.fr/franceinter/franceinter.m3u8?id=radiofranceBose', 1],
        ['Musique d\'Inter', 'https://stream.radiofrance.fr/franceinterlamusiqueinter/franceinterlamusiqueinter.m3u8?id=radiofranceBose', 1101]
    ]

class RadioFranceChannel(RadioChannel):

    __api_url = "https://api.radiofrance.fr/livemeta/live/{}/fip_player" # FIP Player structure may be the most convenient
    """
    Other player structures are usable - but may differ in content:
        apprf_bleu_display --- apprf = appli radio france
        apprf_bleu_player
        apprf_culture_display
        apprf_culture_player
        apprf_fip_display
        apprf_fip_player
        apprf_info_display
        apprf_info_player
        apprf_inter_display
        apprf_inter_player
        apprf_mouv_display
        apprf_mouv_player
        apprf_musique_display
        apprf_musique_player
        apprf_webradio_common_display -- ONLY SONG TITLE
        apprf_webradio_common_player -- ONLY SONG TITLE AND ARTIST
        apprf_webradio_musique_display -- ONLY COVER ART
        bleu_player -- xxxx_player = différents players des sites radio france
        bleu_player_web_only
        bleu_rds
        culture_player
        culture_rds
        fip_extended -- NO STATION INFO, BUT TITLE, INTERPRETER, ALBUM, LABEL, STYLE, and ART
        fip_player -- SIMPLE STATION INFO, TITLE, ARTIST and ART
        fip_rds
        francebleu_player
        francebleu_webradio_player
        info_player
        info_rds
        inter_player
        inter_rds
        mouv_player
        mouv_rds
        music_player
        musique_player
        musique_rds
        new_apprf_bleu
        new_apprf_culture
        new_apprf_fip
        new_apprf_info
        new_apprf_inter
        new_apprf_monpetitfranceinter
        new_apprf_mouv
        new_apprf_musique
        new_apprf_musique_new_layout
        new_apprf_webradio_common
        new_apprf_webradio_common_layout
        radio_visuel ------------------------------ MAYBE THE MOST COMPLETE (AND COMPLEX)
        spoken_station
        spoken_station_exemple
        spoken_station_with_composition
        spoken_station_with_max_next
        spoken_station_with_next_level1
        transistor_bleu_direct_player
        transistor_bleu_player
        transistor_culture_player
        transistor_info_player
        transistor_inter_player
        transistor_monpetitfranceinter_player
        transistor_mouv_player
        transistor_musical_player
        transistor_musique_player
        webrf_bleu_player
        webrf_culture_player
        webrf_fip_player
        webrf_info_player
        webrf_inter_player
        webrf_monpetitfranceinter_player
        webrf_mouv_player
        webrf_musique_inter_webradio_player
        webrf_musique_player
        webrf_webradio_player
    """

    def __init__(self, channel_info: list):
        self.name = channel_info[0] # Temporary name awaiting update from API
        self.url = channel_info[1] # Stream URL
        self.__RF_channel_id = channel_info[2] # RadioFrance specific channel id
        self.global_program = None
        self.program_name = None
        self.track_name = None
        self.artist_name = None
        self.last_metadata_refresh = 0 # In epoch time
        self.time_to_refresh = 0 # In seconds

    def get_channel_name(self):
        return self.name

    def get_channel_url(self):
        return self.url

    def get_current_track_info(self) -> dict[str, str]:
        infos = {
            "name": self.name,
            "global_program": self.global_program,
            "program_name": self.program_name,
            "track_name": self.track_name,
            "artist_name": self.artist_name
        }
        return infos

    def get_display_text(self) -> str:
        self.fetch_metadata()
        infos = self.get_current_track_info()
        if infos['name'] == infos['program_name']:
            infos.pop('program_name')
        infos.pop('name')
        infos = {k: v for k, v in infos.items() if v is not None}
        return "\n".join(infos.values())

    def fetch_metadata(self, force: bool = False):
        if ((time.time() > self.last_metadata_refresh + 60) # Account for 1 minute max from last refresh
                or (time.time() > self.time_to_refresh + 5)
                or force): # Account for 5s of streaming delay
            api_url = self.__api_url.format(self.__RF_channel_id)

            try:
                response = requests.get(api_url, timeout=1.0) # 1s timeout
            except Exception as e:
                print(e)

            if response:
                if not response.ok:
                    print(f"{time.ctime(time.time())} : Error fetching metadata: {response.reason}")
                else:
                    metadata = response.json()
                    self.last_metadata_refresh = time.time()
                    self.time_to_refresh = metadata['now']['endTime']
                    if not self.time_to_refresh: # Set next refresh at track end time
                        self.time_to_refresh = time.time()
                    self.name = metadata['prev'][0]['firstLine'] # metadata['prev'] is a list! # Station name
                    self.global_program = metadata['prev'][0]['secondLine']  # metadata['prev'] is a list! # Global program name
                    self.program_name = metadata['now']['firstLine'] # metadata['now'] is a dict!! # Program name
                    self.track_name = metadata['now']['secondLine'] # Music name or Podcast Title
                    self.artist_name = metadata['now']['thirdLine'] # Artist name or None
            else:
                print(f"{time.ctime(time.time())} : Exception getting metadata")

    def get_debug(self) -> str:
        return ("Last refresh : " + time.ctime(self.last_metadata_refresh) +
                "\nNext refresh : " + time.ctime(self.last_metadata_refresh + 60) +
                "\nNext program : " + time.ctime(self.time_to_refresh))

#
# Generate an array of RadioFrance channels
#
def get_radiofrance_channels() -> list[RadioFranceChannel]:
    radiofrance_channels = []
    for channel in __default_channels:
        radiofrance_channels.append(RadioFranceChannel(channel))
    return radiofrance_channels
