#!/bin/bash
cd /opt/
git clone https://github.com/devegoo/SamplerBox.git
cd SamplerBox
apt-get update ; apt-get -y install git python3-dev python3-pip python3-numpy cython3 python3-smbus portaudio19-dev libportaudio2 libffi-dev ; pip3 install rtmidi-python pyaudio cffi sounddevice future
python3 setup.py build_ext --inplace
#services / control
cd /tools/
cp samplerbox.service /etc/systemd/system/samplerbox.service
cp start_samplerbox /usr/bin/
cp stop_samplerbox /usr/bin/
# sample renamer
cp nametonote /usr/bin/
chmod +x /usr/bin/start_samplerbox
chmod +x /usr/bin/stop_samplerbox
chmod +x /usr/bin/nametonote

