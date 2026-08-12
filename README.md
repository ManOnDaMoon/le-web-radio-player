# Notes d'installation du LeWebRadioPlayer

## Hardware

### Bill of materials

- 1x Raspberry Pi Zero 2W
- 1x Waveshare Audio Hat WM8960
- 1x Waveshare UPS Hat C pour Raspberry Pi Zero
- 2x AZDelivery KY-040 Rotary Encoder Module
- 1x écran OLED I2C 0,96" 128x64px

### Branchements

GPIO :
```
1 : 3.3V - ROTARY1+
2 : 5V
3 : GPIO2 : I2C AUDIO HAT - I2C OLED SDA
4 : 5V - OLED VCC
5 : GPIO3 : I2C AUDIO HAT - I2C OLED SCL
7 : GPIO4
8 : GPIO14
9 : GND - ROTARY1 GND
10 : GPIO15
11 : GPIO17 - AUDIO HAT Custom Button
12 : GPIO18 - I2S AUDIO HAT
13 : GPIO27 - ROTARY1 DT
14 : GND - ROTARY2 GND
15 : GPIO22 - ROTARY1 SW
16 : GPIO23 - ROTARY2 CLK
17 : 3.3V - ROTARY2+
18 : GPIO24 - ROTARY2 DT
19 : GPIO10 - ROTARY2 SW
[...]
35 : GPIO19 - I2S AUDIO HAT
36 : GPIO16
37 : GPIO26
38 : GPIO20 - I2S AUDIO HAT
39 : GND
40 : GPIO21 - I2S AUDIO HAT
```

## Software

1. Utiliser une image [Comitup Lite](https://davesteele.github.io/comitup/)
2. Se connecter au RPi en AP et configurer l’accès Wifi
3. Se connecter au RPi en SSH et configurer le nom de l’appareil :

`sudo nano /etc/comitup.conf`

Modifier le nom local dans comitup, raspi-config et /etc/hosts. Ou utiliser `comitup-cli`

Commandes d’installation et de configuration :
```
sudo apt-get update && sudo apt-get upgrade -y
sudo apt install git -y
sudo raspi-config
```
Activer I2C dans Interface Options

### Installation du Audio Hat :

```
git clone https://github.com/waveshare/WM8960-Audio-HAT
cd WM8960-Audio-HAT
# sudo chmod +x install.sh # Si nécessaire
sudo ./install.sh 
sudo reboot
```

Installer le Hat avec les speakers.

Puis test avec :
```
sudo dkms status
sudo alsamixer # Vérifier la présence de la carte son

sudo apt install vlc -y
cvlc https://stream.radiofrance.fr/monpetitfranceinter/monpetitfranceinter.m3u8?id=radiofranceBose
```

### Installer les packages Python :
```
# Uniquement pour l'interface console Textual
sudo apt install python3-textual -y

# Bibliothèques VLC Python
sudo apt install python3-vlc -y

Installation library OLED :
sudo apt install python3-luma.oled -y

# Augmenter la vitesse de rafraichissement I2C :
sudo echo "dtparam=i2c_baudrate=400000" >> /boot/firmware/config.txt 
```

Télécharger le-web-radio-player (ce repo !) :
```
git clone https://github.com/ManOnDaMoon/le-web-radio-player.git
cd le-web-radio-player/
python main.py
```
La radio fonctionne !

### Modifier le Volume par défaut :
`sudo nano /etc/wm8960-soundcard/wm8960_asound.state`
Et modifier la valeur value.0 et value.1 :
```
control.13 {
                iface MIXER
                name 'Speaker Playback Volume'
                value.0 121
                value.1 121
                comment {
                        access 'read write'
                        type INTEGER
                        count 2
                        range '0 - 127'
                        dbmin -9999999
                        dbmax 600
                        dbvalue.0 -1200
                        dbvalue.1 -1200
                }
        }
```

Installer la dernière version de Pillow pour la manipulation d’image - dirty, mais fonctionne :
```
sudo apt install pip -y
sudo pip3 install --user --upgrade --break-system-packages pillow
pip3 install --user --upgrade --break-system-packages pillow
```

Installer Flask pour l'API web (potentiellement déjà installé)
```
sudo apt install python3-flask
```

Installer Waitress comme serveur pour Flask
```
sudo apt install python3-waitress
```

Pour interroger le pourcentage de batterie
```
 sudo apt install python3-smbus
 ```

### Lancement du script au démarrage via systemd

```
sudo nano /etc/systemd/system/myradio.service
```

Renseigner le fichier suivant, en modifiant le chemin vers le script `main-luma.py` :
```
[Unit]
Description=Le Web Radio Player
After=sound.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/user/le-web-radio-player/main-luma.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Puis exécuter :
```
sudo systemctl daemon-reload
sudo systemctl enable myradio
```

Rebooter pour vérifier le fonctionnement.

Pour débugger :
```
sudo systemctl status myradio
journalctl -u myradio.service -e
```

# Web API

L'API est appelable en utilisant l'adresse IP de la radio ou son nom local, sur le port 80. 

Ex: `myradio.local/route`

## Routes

### Next et Previous
`myradio.local/next`
`myradio.local/previous`

Naviguer dans les stations

### Volumeup et Volumedown

`myradio.local/volumeup`
`myradio.local/volumedown`

Augmenter/Réduire le volume

### Setvolume
`myradio.local/setvolume?volume=x`

Mettre à jour le volume à la valeur `x` (entre 0 et 100)

### Mute
`myradio.local/mute`

Couper le son

### Onoff
`myradio.local/onoff`

Eteindre le player, en laissant la radio allumée en mode horloge.

### List
`myradio.local/list`

Obtenir la liste des radios au format JSON.
Utile pour utilisation avec la route `/switch` par exemple.
```
[
      {
        "name": "Mon petit France Inter",
        "num": 0
      },
      {
        "name": "FIP",
        "num": 1
      },
      {
        "name": "FIP Rock",
        "num": 2
      },
  
  ...
  
  ]
 ```

### Switch  
`myradio.local/switch?radio=x`

Sélectionner la radio `x` (où `x` est la valeur `num` retournée par la route `/list`)


### Totalshutdown

`myradio.local/totalshutdown`

Lancer un `sudo shutdown -h now` pour éteindre le RPi.

### Reboot

`myradio.local/reboot`

Lancer un `sudo reboot` pour redémarrer le RPi.

### Battery

`myradio.local/battery`

Obtenir l'état de la batterie en %