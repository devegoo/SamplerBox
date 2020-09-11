# SamplerBox
SamplerBox is a simple sampler

EASY INSTALL:

to /opt/

wget https://raw.githubusercontent.com/devegoo/SamplerBox/master/setup_over_web.sh

sudo su

chmod +x setup.sh

./setup.sh

RUNNING :

  command to start: "start_samplerbox"

  command to stop: "stop_samplerbox"

  command to rename samples : 

cd /to/samples/dir/

nametonote

full howto : https://github.com/devegoo/midi-note-name-to-number

EXTRA SAMPLE FOR SAMPLERBOX on this link:

https://github.com/devegoo/SamplerBoxSample



Updated for python3 ... https://github.com/J-Rios

tested on Ubuntu 20.10

Follow this installation procedure:

su

cd /opt

git clone https://github.com/devegoo/SamplerBox.git

cd SamplerBox

chmod +x install_requeriments

./install_requeriments

pip3 install -r requirements.txt

python3 setup.py build_ext --inplace

cp tools/samplerbox.service  /etc/systemd/system/samplerbox.service

systemctl enable samplerbox

systemctl start samplerbox

systemctl status samplerbox


Download samples to /opt/SamplerBox/

or change in samplerbox.py line:

SAMPLES_DIR = "."  to

SAMPLES_DIR = "/path/to/your/samples/dir/"
