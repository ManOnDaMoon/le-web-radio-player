from abc import ABC, abstractmethod

class RadioChannel(ABC):

    @abstractmethod
    def get_channel_name(self) -> str:
        pass

    @abstractmethod
    def get_channel_url(self) -> str:
        pass

    @abstractmethod
    def get_current_track_info(self) -> dict[str, str]:
        pass