#
#  SamplerBox
#
#  author:    Joseph Ernest (twitter: @JosephErnest, mail: contact@samplerbox.org)
#  url:       http://www.samplerbox.org/
#  license:   Creative Commons ShareAlike 3.0 (http://creativecommons.org/licenses/by-sa/3.0/)
#
#  samplerbox.py: Main file
#


#########################################
# LOCAL
# CONFIG
#########################################

AUDIO_DEVICE_ID = "0"       # change this number to use another soundcard
SAMPLES_DIR = "."         # The root directory containing the sample-sets. Example: "/media/" to look for samples on a USB stick / SD card
USE_SERIALPORT_MIDI = False       # Set to True to enable MIDI IN via SerialPort (e.g. RaspberryPi's GPIO UART pins)
USE_I2C_7SEGMENTDISPLAY = False   # Set to True to use a 7-segment display via I2C
USE_BUTTONS = False               # Set to True to use momentary buttons (connected to RaspberryPi's GPIO pins) to change preset
USE_KEYBOARD = True               # Set to true to use keyboard '+' and '-' to increase/decrease presets
MAX_POLYPHONY = 80                # This can be set higher, but 80 is a safe value
DEBUG = False

#########################################
# IMPORT
# MODULES
#########################################

#import pyximport
#pyximport.install()

import wave
import time
import numpy
import os
import re
import sounddevice
import threading
from chunk import Chunk
import struct
import rtmidi2 as rtmidi
import samplerbox_audio
from sys import argv as sys_argv
from signal import signal, SIGTERM, SIGINT
from traceback import format_exc as traceback_format_exc
import time
import os
import glob
import re
import threading
import psutil
from modules import globalvars as gv
import sound
from modules import definitionparser as dp
from sfzparser import SFZParser
import sys
import gc  # garbage collector
# from sf2utils.sf2parse import Sf2File
# from mingus.midi import fluidsynth
# from mingus.containers import Note
from mingus.midi import pyfluidsynth



####################################################################################################

### Termination Signals Handler For Program Process ###

def signal_handler(signal,  frame):
    '''Termination signals (SIGINT, SIGTERM) handler for program process'''
    print("Exit")
    exit(0)


### Signals attachment ###
signal(SIGTERM, signal_handler) # SIGTERM (kill pid) to signal_handler
signal(SIGINT, signal_handler)  # SIGINT (Ctrl+C) to signal_handler

####################################################################################################

### Check for input arguments ###

argv = sys_argv[1:]
argc = len(sys_argv)-1
for arg in argv:
    if arg == "debug":
        DEBUG = True
    elif arg == "devices":
        print(sounddevice.query_devices())
        exit(0)
    else:
        try:
            AUDIO_DEVICE_ID = int(arg)
        except ValueError:
            print(sounddevice.query_devices())
            exit(0)

####################################################################################################

### Debug Function ###

def _debug(text):
    if DEBUG:
        print(text)

####################################################################################################

### Preset Change Functions ###

def set_preset(num):
    global preset
    if num < 0:
        num = 0
    preset = num
    print("\nPreset: {}".format(preset))
    LoadSamples()


def preset_reduce():
    global preset
    preset = preset - 1
    set_preset(preset)


def preset_increase():
    global preset
    preset = preset + 1
    set_preset(preset)

####################################################################################################

#########################################
# SLIGHT MODIFICATION OF PYTHON'S WAVE MODULE
# TO READ CUE MARKERS & LOOP MARKERS
#########################################

class waveread(wave.Wave_read):

    def initfp(self, file):
        self._convert = None
        self._soundpos = 0
        self._cue = []
        self._loops = []
        self._ieee = False
        self._file = Chunk(file, bigendian=0)
        if self._file.getname() != b'RIFF':
            raise Exception("Error: file does not start with RIFF id")
        if self._file.read(4) != b'WAVE':
            raise Exception("Error: Not a WAV file")
        self._fmt_chunk_read = 0
        self._data_chunk = None
        while 1:
            self._data_seek_needed = 1
            try:
                chunk = Chunk(self._file, bigendian=0)
            except EOFError:
                break
            chunkname = chunk.getname()
            if chunkname == b'fmt ':
                self._read_fmt_chunk(chunk)
                self._fmt_chunk_read = 1
            elif chunkname == b'data':
                if not self._fmt_chunk_read:
                    raise Exception("Error: data chunk before fmt chunk")
                self._data_chunk = chunk
                self._nframes = chunk.chunksize // self._framesize
                self._data_seek_needed = 0
            elif chunkname == b'cue ':
                numcue = struct.unpack('<i', chunk.read(4))[0]
                for i in range(numcue):
                    id, position, datachunkid, chunkstart, blockstart, sampleoffset = struct.unpack('<iiiiii', chunk.read(24))
                    self._cue.append(sampleoffset)
            elif chunkname == b'smpl':
                manuf, prod, sampleperiod, midiunitynote, midipitchfraction, smptefmt, smpteoffs, numsampleloops, samplerdata = struct.unpack(
                    '<iiiiiiiii', chunk.read(36))
                for i in range(numsampleloops):
                    cuepointid, type, start, end, fraction, playcount = struct.unpack('<iiiiii', chunk.read(24))
                    self._loops.append([start, end])
            chunk.skip()
        if not self._fmt_chunk_read or not self._data_chunk:
            raise Exception("Error: fmt chunk and/or data chunk missing")

    def getmarkers(self):
        return self._cue

    def getloops(self):
        return self._loops


#########################################
# MIXER CLASSES
#
#########################################

class PlayingSound:

    def __init__(self, sound, note):
        self.sound = sound
        self.pos = 0
        self.fadeoutpos = 0
        self.isfadeout = False
        self.note = note

    def fadeout(self, i):
        self.isfadeout = True

    def stop(self):
        try:
            playingsounds.remove(self)
        except:
            pass


class Sound:

    def __init__(self, filename, midinote, velocity):
        wf = waveread(filename)
        self.fname = filename
        self.midinote = midinote
        self.velocity = velocity
        if wf.getloops():
            self.loop = wf.getloops()[0][0]
            self.nframes = wf.getloops()[0][1] + 2
        else:
            self.loop = -1
            self.nframes = wf.getnframes()

        self.data = self.frames2array(wf.readframes(self.nframes), wf.getsampwidth(), wf.getnchannels())

        wf.close()

    def play(self, note):
        snd = PlayingSound(self, note)
        playingsounds.append(snd)
        return snd

    def frames2array(self, data, sampwidth, numchan):
        if sampwidth == 2:
            npdata = numpy.frombuffer(data, dtype=numpy.int16)
        elif sampwidth == 3:
            npdata = samplerbox_audio.binary24_to_int16(data, len(data)/3)
        if numchan == 1:
            npdata = numpy.repeat(npdata, 2)
        return npdata

FADEOUTLENGTH = 30000
FADEOUT = numpy.linspace(1., 0., FADEOUTLENGTH)            # by default, float64
FADEOUT = numpy.power(FADEOUT, 6)
FADEOUT = numpy.append(FADEOUT, numpy.zeros(FADEOUTLENGTH, numpy.float32)).astype(numpy.float32)
SPEED = numpy.power(2, numpy.arange(0.0, 84.0)/12).astype(numpy.float32)

samples = {}
playingnotes = {}
sustainplayingnotes = []
sustain = False
playingsounds = []
globalvolume = 10 ** (-12.0/20)  # -12dB default global volume
globaltranspose = 0


#########################################
# AUDIO AND MIDI CALLBACKS
#
#########################################

def AudioCallback(outdata, frame_count, time_info, status):
    global playingsounds
    rmlist = []
    playingsounds = playingsounds[-MAX_POLYPHONY:]
    b = samplerbox_audio.mixaudiobuffers(playingsounds, rmlist, frame_count, FADEOUT, FADEOUTLENGTH, SPEED)
    for e in rmlist:
        try:
            playingsounds.remove(e)
        except:
            pass
    b *= globalvolume
    outdata[:] = b.reshape(outdata.shape)

def MidiCallback(message, time_stamp):
    global playingnotes, sustain, sustainplayingnotes
    global preset
    _debug("{} - {}\n".format(time_stamp, message))
    messagetype = message[0] >> 4
    #messagechannel = (message[0] & 15) + 1
    note = message[1] if len(message) > 1 else None
    midinote = note
    velocity = message[2] if len(message) > 2 else None

    # Control Preset
    if messagetype == 14:
        if velocity == 0:
            preset_reduce()
        elif velocity == 126:
            preset_increase()

    if messagetype == 9 and velocity == 0:
        messagetype = 8

    if messagetype == 9:    # Note on
        midinote += globaltranspose
        try:
            playingnotes.setdefault(midinote, []).append(samples[midinote, velocity].play(midinote))
        except:
            pass

    elif messagetype == 8:  # Note off
        midinote += globaltranspose
        if midinote in playingnotes:
            for n in playingnotes[midinote]:
                if sustain:
                    sustainplayingnotes.append(n)
                else:
                    n.fadeout(50)
            playingnotes[midinote] = []

    elif messagetype == 12:  # Program change
        print("Program change {}".format(str(note)))
        preset = note
        LoadSamples()

    elif (messagetype == 11) and (note == 64) and (velocity < 64):  # sustain pedal off
        for n in sustainplayingnotes:
            n.fadeout(50)
        sustainplayingnotes = []
        sustain = False

    elif (messagetype == 11) and (note == 64) and (velocity >= 64):  # sustain pedal on
        sustain = True


#########################################
# LOAD SAMPLES
#
#########################################

class LoadingSamples:
    def __init__(self):

        self.LoadingThread = None
        self.LoadingInterrupt = False
        self.preset_current_is_loaded = False
        self.preset_current_loading = gv.samples_indices[gv.preset]
        self.preset_change_triggered = False
        self.all_presets_loaded = False
        self.memory_limit_reached = False
        self.midi_detected = False
        self.pause_sleep = 0.5
        self.last_memory_reading = 0
        # gv.setlist.update()

        # Create empty dicts for every sample-set. This is necessary for setlist rearrangement
        for i in xrange(len(gv.SETLIST_LIST)):
            self.init_sampleset_dict(i)

    #################################
    # Init a single sample-set dict #
    #################################

    def init_sampleset_dict(self, i):
        if gv.samples.has_key(i): gv.samples.pop(i)
        gv.samples[i] = {}
        gv.samples[i]['keywords'] = {}
        gv.samples[i]['fillnotes'] = {}
        gv.samples[i]['keywords']['voices'] = {}

    ###########################
    # Initiate sample loading #
    ###########################

    def load_samples(self):

        self.preset_current_is_loaded = False
        self.preset_current_loading = gv.samples_indices[gv.preset]
        self.preset_change_triggered = True

        if self.LoadingThread:
            self.LoadingInterrupt = True
            self.LoadingThread.join()
            self.LoadingThread = None

        self.LoadingInterrupt = False
        self.LoadingThread = threading.Thread(target=self.actually_load)
        self.LoadingThread.daemon = True
        self.LoadingThread.start()

    ############################
    # Pause loading script if  #
    # there are sounds playing #
    ############################

    def pause_if_playingsounds_or_midi(self):

        pause_time = 0.5 #secs

        if self.LoadingInterrupt:
            return

        if self.preset_current_is_loaded and self.preset_current_loading != gv.samples_indices[gv.preset]:
            # if gv.playingsounds or self.midi_detected or gv.displayer.menu_mode != gv.displayer.DISP_PRESET_MODE: # menu_mode breaks definition editor. TODO: find better way
            if gv.playingsounds or self.midi_detected:  # are there sounds or midi playing?
                print '####################################'
                print '# Initiate pause on sample loading #'
                while True:
                    if not gv.playingsounds or self.preset_change_triggered:

                        if self.midi_detected:
                            # desired wait secs / loop sleep = number of iterations
                            for k in xrange(int(pause_time / self.pause_sleep)):
                                time.sleep(self.pause_sleep)

                        print '#----------------------------------#'
                        print '#   No more playingsounds or MIDI  #'
                        print '#         Continue loading         #'
                        print '####################################'
                        self.preset_change_triggered = False
                        self.midi_detected = False
                        time.sleep(pause_time)  # wait a short while before loading samples again
                        return

                    sys.stdout.write('\r[!] LOADING PAUSED: sounds or MIDI is playing')
                    sys.stdout.flush()
                    time.sleep(self.pause_sleep)
            else:
                # print '++ Keep loading ++'
                return

    #####################
    # Memory management #
    #####################

    def check_memory_usage(self):
        RAM_usage_percentage = psutil.virtual_memory().percent
        self.last_memory_reading = RAM_usage_percentage
        if RAM_usage_percentage > gv.RAM_LIMIT_PERCENTAGE:

            print '    RAM usage = %d%%' % RAM_usage_percentage
            print '    RAM limit = %d%%' % gv.RAM_LIMIT_PERCENTAGE
            print 'x   RAM usage has reached limit (in config.ini)'
            print '    STOP LOADING PRESETS'
            self.memory_limit_reached = True
            return True
        else:

            print '    RAM usage = %d%%' % RAM_usage_percentage
            print '    RAM limit = %d%%' % gv.RAM_LIMIT_PERCENTAGE
            print '+   RAM usage is OK - can load next preset'
            self.memory_limit_reached = False
            return False

    def kill_preset(self, preset):

        if gv.samples.has_key(preset):
            print 'Killing samples in preset [%d: %s]' % (preset, gv.SETLIST_LIST[preset])  # debug
            self.init_sampleset_dict(preset)
            self.all_presets_loaded = False
            gc.collect()
            return True
        else:
            print 'No samples loaded in previous preset slot - do nothing'  # debug
            return False

    def kill_one_before(self):
        prev_preset = self.get_prev_preset(gv.samples_indices[gv.preset])

        # Kill previous preset (if it exists)
        if gv.samples.has_key(prev_preset):
            print 'Killing samples in previous preset [%d: %s]' % (prev_preset, gv.SETLIST_LIST[prev_preset])  # debug
            self.init_sampleset_dict(prev_preset)
            self.all_presets_loaded = False
            gc.collect()
            return True
        else:
            print 'No samples loaded in previous preset slot - do nothing'  # debug
            return False

    def kill_two_before(self):
        two_preset_prev = self.get_prev_preset(self.get_prev_preset(gv.samples_indices[gv.preset]))
        # Kill previous preset (if it exists)
        if gv.samples.has_key(two_preset_prev):
            print 'Killing two presets previous [%d: %s]' % (two_preset_prev, gv.SETLIST_LIST[two_preset_prev])  # debug
            self.init_sampleset_dict(two_preset_prev)
            self.all_presets_loaded = False
            gc.collect()
            return True
        else:
            print 'No samples loaded in two presets previous - do nothing'  # debug
            return False

    def is_all_presets_loaded(self):
        i = 0
        for s in gv.samples.keys():
            if gv.samples[s].has_key('loaded'):
                i += 1
        if len(gv.setlist.song_folders_list) == i:
            print '///// All presets are now loaded into memory /////'
            self.all_presets_loaded = True
        else:
            print '///// Not all presets have been loaded into memory /////'

    ####################################
    # Next and previous preset getters #
    ####################################

    def get_next_preset(self, current_preset):
        if current_preset < len(gv.samples_indices) - 1:
            preset_next_to_load = gv.samples_indices[current_preset + 1]
        else:
            preset_next_to_load = 0
        return preset_next_to_load

    def get_prev_preset(self, current_preset):
        if current_preset > 0:
            preset_prev_to_load = gv.samples_indices[current_preset - 1]
        else:
            preset_prev_to_load = gv.samples_indices[-1]
        return preset_prev_to_load

    ##########################################
    # Set globals from dict from definitions #
    ##########################################

    def set_globals_from_keywords(self):

        gv.voices = gv.samples[gv.samples_indices[gv.preset]]['keywords']['voices']

        if gv.samples[gv.samples_indices[gv.preset]].has_key('keywords'):
            preset_keywords_dict = gv.samples[gv.samples_indices[gv.preset]]['keywords']

            for global_var, keyword in dp.keywords_to_try:
                if preset_keywords_dict.has_key(keyword):
                    value = preset_keywords_dict.get(keyword)
                    print '>>>> Global keyword found in definition -> %%%%%s=%s' % (keyword, str(value))  # debug
                    exec (global_var + '=value')  # set the global variable

    def reset_global_defaults(self):

        # gv.global_volume = 10 ** (-6.0/20)  # -12dB default global volume
        gv.basename = gv.SETLIST_LIST[gv.preset]
        gv.globaltranspose = dp.get_default('%%transpose')
        gv.sample_mode = dp.get_default('%%mode')
        gv.velocity_mode = dp.get_default('%%velmode')
        gv.PRERELEASE = dp.get_default('%%release')
        gv.gain = dp.get_default('%%gain')
        gv.PITCHBEND = dp.get_default('%%pitchbend')
        gv.currvoice = 1
        #### prevbase = gv.basename  # disp_changed from currbase


    def load_next_preset(self):

        if len(gv.SETLIST_LIST) > 1:

            if self.preset_current_loading == gv.samples_indices[gv.preset]:

                if gv.displayer.menu_mode == 'preset': gv.displayer.disp_change('preset', timeout=0)
                self.preset_next_to_load = self.get_next_preset(gv.preset)
                self.preset_current_is_loaded = True

            else:

                self.preset_next_to_load = self.get_next_preset(self.preset_current_loading)

                if self.preset_next_to_load == gv.preset:
                    return True

            self.preset_current_loading = self.preset_next_to_load
            # time.sleep(0.05)  # allow a tiny pause before loading next preset for LCD

            # if gv.displayer.menu_mode == 'preset':
            #     gv.displayer.disp_change('preset') # force display to update

            self.actually_load()  # load next preset


    ###################
    # The mother load #
    ###################

    def actually_load(self):

        print 'RAM check at START of preset load'
        self.check_memory_usage()

        if self.preset_current_loading == gv.samples_indices[gv.preset]:
            self.reset_global_defaults()

        # Check if all presets are in memory.
        # This is possible if the total size of all sample-sets are smaller that the percentage of
        # RAM allocated to samples (RAM_LIMIT_PERCENTAGE in config.ini)
        if self.all_presets_loaded:
            print '\rLOADED NOTHING: all presets have been loaded into memory'
            self.set_globals_from_keywords()
            if gv.displayer.menu_mode == 'preset': gv.displayer.disp_change('preset')  # Force the display to update
            return  # all is loaded, no need to proceed further from here

        if self.preset_current_loading == gv.samples_indices[gv.preset]:

            print '\rCurrent preset: [%d: %s]' % (self.preset_current_loading, gv.SETLIST_LIST[self.preset_current_loading])  # debug

            self.preset_current_is_loaded = False
            self.preset_change_triggered = False

            if self.memory_limit_reached == True:
                if self.kill_two_before() == False:  # Free up RAM - kill 2 presets previous (if exists)
                    if self.kill_one_before() == False:  # Free up RAM - kill 1 preset previous (if exists)
                        pass
                self.reset_global_defaults()

        self.pause_if_playingsounds_or_midi()

        if gv.samples.has_key(self.preset_current_loading):  # If key exists, preset is fully or partially loaded
            # If 'loaded' key exists, preset is fully loaded.
            if gv.samples[self.preset_current_loading].has_key('loaded'):
                print '[%d: %s] has already been loaded. Skipping.' % (self.preset_current_loading, gv.SETLIST_LIST[self.preset_current_loading])
                self.set_globals_from_keywords()
                if gv.displayer.menu_mode == 'preset':
                    gv.displayer.disp_change('preset')  # Force the display to update

                if self.memory_limit_reached == False:
                    self.load_next_preset()
                    return
                else:
                    return
            else:
                # Preset seems to have been partially loaded at some point.
                # Stop all playing sounds to avoid pops and finish loading.
                # gv.playingsounds = []  # clear/stop all currently playing samples
                pass
        else:
            # Preset has never been loaded, or has been unloaded at some point. Initialize its dict and load samples.
            self.init_sampleset_dict([self.preset_current_loading])

        # Reset defaults
        current_basename = gv.SETLIST_LIST[self.preset_current_loading]
        voices_local = []
        channel = gv.MIDI_CHANNEL
        gv.pitchnotes = gv.PITCHRANGE_DEFAULT  # fallback to the samplerbox default
        gv.PRERELEASE = gv.BOXRELEASE  # fallback to the samplerbox default for the preset release time

        dirname = os.path.join(gv.SAMPLES_DIR, current_basename)

        definitionfname = os.path.join(dirname, "definition.txt")

        sfzfname = glob.glob(os.path.join(dirname, '*.sfz'))
        sfzfname = sfzfname[0].replace('\\', '/') if sfzfname else ''

        sf2fname = glob.glob(os.path.join(dirname, '*.sf2'))
        sf2fname = sf2fname[0].replace('\\', '/') if sf2fname else ''
        print sf2fname
        # with open(sf2fname, 'rb') as sf2_file:
        #     sf2 = Sf2File(sf2_file)
        #     print sf2.samples[0]

        pfs = pyfluidsynth.Synth()

        pfs.sfload(sf2fname)

        print pfs.get_samples()

        # fluidsynth.init(sf2fname)

        # fluidsynth.play_Note(40, 1, 127)

        exit()



        file_count = float(len(os.listdir(dirname)))
        file_current = 0.0

        gv.samples[self.preset_current_loading]['keywords']['fillnotes'] = 'Y'  # set fillnotes global default because it's needed in this iteration later

        if os.path.isfile(definitionfname):

            print 'START LOADING: [%d] %s' % (self.preset_current_loading, current_basename)  # debug

            file_count = file_count - 1  # One of the files is definition.txt

            definition_list = list(enumerate(open(definitionfname, 'r')))
            wav_definitions_list = [x for x in definition_list if "%%" not in x[1]]  # remove list entries containing %%
            wav_definitions_list = [x for x in wav_definitions_list if "\n" != x[1]]  # remove blank lines

            with open(definitionfname, 'r') as definitionfile:

                self.pause_if_playingsounds_or_midi()

                ############################
                # Global-level definitions #
                ############################

                for i, pattern in enumerate(definitionfile):  # iterate every line

                    self.pause_if_playingsounds_or_midi()

                    if r'%%' not in pattern:
                        continue

                    try:

                        # Add any found keywords to preset's samples dict without applying to globals

                        if r'%%gain' in pattern:
                            gv.samples[self.preset_current_loading]['keywords']['gain'] = abs(float(pattern.split('=')[1].strip()))
                            continue
                        if r'%%transpose' in pattern:
                            gv.samples[self.preset_current_loading]['keywords']['transpose'] = int(pattern.split('=')[1].strip())
                            continue
                        if r'%%release' in pattern:
                            release = (int(pattern.split('=')[1].strip()))
                            if release > 127:
                                print "Release of %d limited to %d" % (release, 127)
                                release = 127
                            gv.samples[self.preset_current_loading]['keywords']['release'] = release
                            continue
                        if r'%%fillnotes' in pattern:
                            m = pattern.split('=')[1].strip().title()
                            if m == 'Y' or m == 'N':
                                fillnotes = m
                                gv.samples[self.preset_current_loading]['keywords']['fillnotes'] = fillnotes
                                continue
                        if r'%%pitchbend' in pattern:
                            pitchnotes = abs(int(pattern.split('=')[1].strip()))
                            pitchnotes = sorted([0, pitchnotes, 24])[1]  # limit value to within the range 0-24
                            gv.samples[self.preset_current_loading]['keywords']['pitchbend'] = pitchnotes
                            continue
                        if r'%%mode' in pattern:
                            mode = pattern.split('=')[1].strip().title()
                            if mode == gv.PLAYLIVE \
                                    or mode == gv.PLAYONCE \
                                    or mode == gv.PLAYSTOP \
                                    or mode == gv.PLAYLOOP \
                                    or mode == gv.PLAYLO2X:
                                gv.samples[self.preset_current_loading]['keywords']['mode'] = mode
                                continue
                        if r'%%velmode' in pattern:
                            velmode = pattern.split('=')[1].strip().title()
                            if velmode == gv.VELSAMPLE or velmode == gv.VELACCURATE:
                                gv.samples[self.preset_current_loading]['keywords']['velmode'] = velmode
                                continue

                                # End of global definitions

                    except Exception as e:
                        if pattern != '':
                            print "Error in definition file, skipping line %s." % (i + 1)
                            print "Line %d contents: %s" % (i + 1, pattern)
                            # exc_info = sys.exc_info()
                            # print exc_info
                            print('Error on line {}'.format(sys.exc_info()[-1].tb_lineno), type(e), e)

                # Set global variables from definitions or defaults

                if self.preset_current_loading == gv.samples_indices[gv.preset]:
                    self.set_globals_from_keywords()
                    print '################################'

                    self.pause_if_playingsounds_or_midi()

            with open(definitionfname, 'r') as definitionfile:

                self.pause_if_playingsounds_or_midi()
                ############################
                # Sample-level definitions #
                ############################

                for i, pattern in enumerate(definitionfile):  # iterate every line (again)

                    self.pause_if_playingsounds_or_midi()

                    try:

                        defaultparams = {'midinote': '0', 'velocity': '127', 'notename': '',
                                         'voice': '1', 'seq': '1', 'channel': gv.MIDI_CHANNEL, 'release': '128',
                                         'fillnote': 'G', 'mode': 'Keyb', 'mutegroup': '0'}

                        if len(pattern.split(',')) > 1:
                            defaultparams.update(dict([item.split('=') for item in pattern.split(',', 1)[1].replace(' ', '').replace('%', '').split(',')]))
                        pattern = pattern.split(',')[0]
                        pattern = re.escape(pattern.strip())
                        pattern = pattern \
                            .replace(r"\%midinote", r"(?P<midinote>\d+)") \
                            .replace(r"\%channel", r"(?P<channel>\d+)") \
                            .replace(r"\%velocity", r"(?P<velocity>\d+)") \
                            .replace(r"\%voice", r"(?P<voice>\d+)") \
                            .replace(r"\%release", r"(?P<release>[a-zA-Z0-9_])") \
                            .replace(r"\%fillnote", r"(?P<fillnote>[YNGyng])") \
                            .replace(r"\%mode", r"(?P<mode>\w+)") \
                            .replace(r"\%seq", r"(?P<seq>\d+)") \
                            .replace(r"\%notename", r"(?P<notename>[A-Ga-g]#?[0-9])") \
                            .replace(r"\%mutegroup", r"(?P<mutegroup>\d+)") \
                            .replace(r"\*", r".*?").strip()  # .*? => non greedy

                        for fname in os.listdir(dirname):  # iterate over samples in the dir and ignore definition.txt

                            if 'definition.txt' not in fname:

                                self.pause_if_playingsounds_or_midi()
                                # print 'Processing ' + fname
                                if self.LoadingInterrupt:
                                    # print 'Loading % s interrupted...' % dirname
                                    return

                                ############################
                                # DISPLAY LOADING PROGRESS #
                                ############################
                                if self.preset_current_loading == gv.samples_indices[gv.preset]:
                                    percent_loaded = (file_current / (file_count * len(definition_list)) * 100.0)
                                    file_current += 1
                                    gv.percent_loaded = percent_loaded
                                    # Send percent loaded of sample-set to be displayed
                                    if gv.displayer.menu_mode == 'preset': gv.displayer.disp_change('loading', timeout=0.2)
                                ############################

                                if self.LoadingInterrupt:
                                    return
                                m = re.match(pattern, fname)
                                if m:
                                    info = m.groupdict()
                                    voice = int(info.get('voice', defaultparams['voice']))
                                    voices_local.append(voice)
                                    release = int(info.get('release', defaultparams['release']))
                                    fillnote = str(info.get('fillnote', defaultparams['fillnote'])).title().rstrip()
                                    if self.preset_current_loading == gv.samples_indices[gv.preset]:
                                        gv.voices = voices_local
                                    midinote = int(info.get('midinote', defaultparams['midinote']))
                                    channel = int(info.get('channel', defaultparams['channel']))
                                    velocity = int(info.get('velocity', defaultparams['velocity']))
                                    seq = int(info.get('seq', defaultparams['seq']))
                                    notename = info.get('notename', defaultparams['notename'])
                                    mode = info.get('mode', defaultparams['mode']).rstrip()
                                    mutegroup = int(info.get('mutegroup', defaultparams['mutegroup']))
                                    # next statement places note 60 on C3/C4/C5 with the +0/1/2. So now it is C4:
                                    if notename:
                                        midinote = gv.NOTES.index(notename[:-1].lower()) + (int(notename[-1]) + 2) * 12

                                    # Ignore loops at the sample level, overriding the global sample_mode
                                    mode_prop = None
                                    if mode.title() == 'Once' or gv.sample_mode.title() == 'Once':
                                        mode_prop = mode.title()

                                    if gv.samples[self.preset_current_loading].has_key((midinote, velocity, voice, channel)):
                                        """
                                        Sample Randomization by David Hilowitz
                                        """
                                        # Find samples marked for randomization (seq).
                                        # Check existing list of sound objects if s.seq == seq
                                        if any(s.seq == seq for s in gv.samples[self.preset_current_loading][midinote, velocity, voice, channel]):
                                            # print 'Sequence:%i, File:%s already loaded' % (seq, fname)
                                            continue
                                        else:
                                            if (midinote, velocity, voice, channel) in gv.samples[self.preset_current_loading]:
                                                gv.samples[self.preset_current_loading][midinote, velocity, voice, channel] \
                                                    .append(sound.Sound(os.path.join(dirname, fname), midinote, velocity, seq, channel, release, mode_prop, mutegroup))
                                                print 'Sample randomization: found seq:%i (%s) >> loading' % (seq, fname)
                                    else:

                                        gv.samples[self.preset_current_loading][midinote, velocity, voice, channel] = [
                                            sound.Sound(os.path.join(dirname, fname), midinote, velocity, seq, channel, release, mode_prop, mutegroup)]
                                        # gv.fillnotes[midinote, voice] = fillnote
                                        gv.samples[self.preset_current_loading]['fillnotes'][midinote, voice] = fillnote
                                        # print "sample: %s, note: %d, voice: %d, channel: %d" %(fname, midinote, voice, channel)

                                    # If this isn't the preset in focus, don't load samples so quickly - give the system more resources to do other things (eg navigate menu)
                                    if self.preset_current_loading != gv.samples_indices[gv.preset]:
                                        time.sleep(0.01)

                    except Exception as e:
                        if pattern != '':
                            print "Error in definition file, skipping line %s." % (i + 1)
                            print "Line %d contents: %s" % (i + 1, pattern)
                            # exc_info = sys.exc_info()
                            # print exc_info
                            print('Error on line {}'.format(sys.exc_info()[-1].tb_lineno), type(e), e)

        ###############
        # SFZ support #
        ###############

        elif os.path.isfile(sfzfname):

            # SFZParser by SpotlightKid. https://github.com/SpotlightKid/sfzparser
            # LICENCE: https://github.com/SpotlightKid/sfzparser/blob/master/LICENSE
            sfz = SFZParser(sfzfname)

            # Set globals
            release = int((float(sfz.sections[0][1].get('ampeg_release')) * 1000) / 17)
            release = sorted([0, release, 127])[1] # limit value to within the range 0-127
            gain = float(sfz.sections[0][1].get('volume')) + 1.0
            sustain = int(sfz.sections[0][1].get('ampeg_sustain')) # unused
            decay = float(sfz.sections[0][1].get('ampeg_decay')) # unused
            attack = float(sfz.sections[0][1].get('ampeg_attack')) # unused
            gv.samples[self.preset_current_loading]['keywords']['release'] = release
            gv.samples[self.preset_current_loading]['keywords']['gain'] = gain
            print '>>>> Global release:', release
            print '>>>> Global gain:', gain

            if self.LoadingInterrupt:
                return

            voices_local.append(1)
            if self.preset_current_loading == gv.samples_indices[gv.preset]:
                gv.voices = voices_local

            for section in sfz.sections:

                self.pause_if_playingsounds_or_midi()

                if type(section[0]) == unicode:
                    if section[0] == 'region':

                        sample_fname = section[1].get('sample')
                        sample_path = os.path.join(dirname, sample_fname)
                        hivel = int(section[1].get('hivel'))
                        lovel = int(section[1].get('lovel')) # unused
                        midinote = int(section[1].get('pitch_keycenter'))
                        hikey = int(section[1].get('hikey')) # unused
                        lokey = int(section[1].get('lokey')) # unused

                        gv.samples[self.preset_current_loading][midinote, hivel, 1, 1] = [sound.Sound(sample_path, midinote, hivel, 1, 1, release, None, 0)]
                        gv.samples[self.preset_current_loading]['fillnotes'][midinote, 1] = 'Y'

                        percent_loaded = (file_current * 100) / file_count  # more accurate loading progress
                        gv.percent_loaded = percent_loaded
                        if gv.displayer.menu_mode == 'preset':
                            gv.displayer.disp_change('loading')
                        file_current += 1

                    # If this isn't the preset in focus, don't load samples so quickly - give the system more resources to do other things (eg navigate menu)
                if self.preset_current_loading != gv.samples_indices[gv.preset]:
                    time.sleep(0.01)


        # If no definition.txt or *.sfz file found in folder, look for numbered files (64.wav, 65.wav etc) or notenamed files (C1.wav, D3.wav etc)
        else:

            for midinote in range(0, 127):
                self.pause_if_playingsounds_or_midi()
                if self.LoadingInterrupt:
                    return
                voices_local.append(1)
                if self.preset_current_loading == gv.samples_indices[gv.preset]: gv.voices = voices_local

                file_midinote = os.path.join(dirname, "%d.wav" % midinote)

                notename_index = midinote % 12
                octave = str((midinote / 12) )
                notename = gv.NOTES[notename_index] + octave
                file_notename = os.path.join(dirname, "%s.wav" % notename)

                if os.path.isfile(file_midinote):
                    # print "Processing " + file_midinote
                    gv.samples[self.preset_current_loading][midinote, 127, 1, channel] = [sound.Sound(file_midinote, midinote, 127, 1, channel, gv.BOXRELEASE, None, 0)]

                elif os.path.isfile(file_notename):
                    # print "Processing " + file_notename
                    gv.samples[self.preset_current_loading][midinote, 127, 1, channel] = [sound.Sound(file_notename, midinote, 127, 1, channel, gv.BOXRELEASE, None, 0)]

                gv.samples[self.preset_current_loading]['fillnotes'][midinote, 1] = 'Y'

                percent_loaded = (file_current * 100) / file_count  # more accurate loading progress
                gv.percent_loaded = percent_loaded
                if gv.displayer.menu_mode == 'preset':
                    gv.displayer.disp_change('loading')
                file_current += 1

            if self.preset_current_loading != gv.samples_indices[gv.preset]:
                time.sleep(0.01)

        ################
        # NOTE FILLING #
        ################
        """
        Fill unassigned notes with the closest sample
        """

        initial_keys = set(gv.samples[self.preset_current_loading].keys())

        # NOTE: Only gv.MIDI_CHANNEL notes will be filled across all keys.
        # eg. pad samples on channel 9 will not be filled across all notes in channel 9

        if len(initial_keys) > 0:
            voices_local = list(set(voices_local))  # Remove duplicates by converting to a set
            if self.preset_current_loading == gv.samples_indices[gv.preset]: gv.voices = voices_local
            fillnotes_global = gv.samples[self.preset_current_loading]['keywords']['fillnotes']
            fillnotes = gv.samples[self.preset_current_loading]['fillnotes']
            for voice in voices_local:
                for midinote in xrange(128):
                    last_velocity = None
                    for velocity in xrange(128):
                        if (midinote, velocity, voice, gv.MIDI_CHANNEL) in initial_keys:  # only process default channel
                            if not last_velocity:
                                for v in xrange(velocity):
                                    self.pause_if_playingsounds_or_midi()
                                    gv.samples[self.preset_current_loading][midinote, v, voice, gv.MIDI_CHANNEL] = gv.samples[self.preset_current_loading][midinote, velocity, voice, gv.MIDI_CHANNEL]
                            last_velocity = gv.samples[self.preset_current_loading][midinote, velocity, voice, gv.MIDI_CHANNEL]
                        else:
                            if last_velocity:
                                gv.samples[self.preset_current_loading][midinote, velocity, voice, gv.MIDI_CHANNEL] = last_velocity

                # we got more keys, but not enough yet
                initial_keys = set(gv.samples[self.preset_current_loading].keys())

                last_low = -130  # force lowest unfilled notes to be filled with the next_high
                next_high = None  # next_high not found yet
                for midinote in xrange(128):  # and start filling the missing notes
                    if (midinote, 1, voice, gv.MIDI_CHANNEL) in initial_keys:  # only process default midi channel
                        try:
                            if fillnotes.has_key((midinote, voice)):
                                # can we use this note for filling? Look for: sample-level = Y, or sample-level = D (default) AND global = Y
                                if fillnotes[midinote, voice] == 'Y' or (fillnotes[midinote, voice] == 'G' and fillnotes_global == 'Y'):
                                    next_high = None  # passed next_high
                                    last_low = midinote  # but we got fresh low info
                        except Exception as e:
                            print "fillnotes[%d, %d] doesn't exist." % (midinote, voice)
                            print('Error on line {}'.format(sys.exc_info()[-1].tb_lineno), type(e), e)
                    else:
                        if not next_high:
                            next_high = 260  # force highest unfilled notes to be filled with the last_low
                            for m in xrange(midinote + 1, 128):
                                if (m, 1, voice, gv.MIDI_CHANNEL) in initial_keys:
                                    # can we use this note for filling? Look for: sample-level = Y, or sample-level = D (default) AND global = Y
                                    if fillnotes[m, voice] == 'Y' or (fillnotes[m, voice] == 'G' and fillnotes_global == 'Y'):
                                        if m < next_high:
                                            next_high = m

                        if (next_high - last_low) > 260:  # did we find a note valid for filling?
                            continue  # no, stop trying
                        if float(midinote) <= 0.5 + (next_high + last_low) / 2:
                            m = last_low
                        else:
                            m = next_high
                        # print "Note %d will be generated from %d" % (midinote, m)
                        for velocity in xrange(128):
                            self.pause_if_playingsounds_or_midi()
                            gv.samples[self.preset_current_loading][midinote, velocity, voice, gv.MIDI_CHANNEL] = gv.samples[self.preset_current_loading][m, velocity, voice, gv.MIDI_CHANNEL]
        elif len(initial_keys) == 0:
            if gv.displayer.menu_mode == 'preset': gv.displayer.disp_change('preset')
            pass
        else:
            gv.displayer.disp_change('')  # Force the display to update
            pass

        # Record number of voices because if preset is loaded into mem, its voices don't get detected again
        gv.samples[self.preset_current_loading]['keywords']['voices'] = voices_local
        gv.samples[self.preset_current_loading]['loaded'] = True  # flag this preset's dict item as loaded

        print 'END LOADING: [%d] %s' % (self.preset_current_loading, current_basename)  # debug

        self.is_all_presets_loaded()

        if gv.displayer.menu_mode == 'preset':
            gv.displayer.disp_change('preset')  # Force the display to update

        print 'RAM check at END of preset load'
        self.check_memory_usage() # check memory again to see if we can load the next preset

        if self.memory_limit_reached == False:
            self.load_next_preset()



#########################################
# OPEN AUDIO DEVICE
#
#########################################

try:
    sd = sounddevice.OutputStream(device=AUDIO_DEVICE_ID, blocksize=512, 
            samplerate=44100, channels=2, dtype='int16', callback=AudioCallback)
    sd.start()
    print("Opened audio device #{}".format(AUDIO_DEVICE_ID))
except Exception:
    print("\n[ERROR] {}".format(traceback_format_exc()))
    print("Invalid audio device #{}".format(AUDIO_DEVICE_ID))
    exit(1)


#########################################
# KEYBOARD THREAD (NEEDS ROOT)
#
#########################################
if USE_KEYBOARD:
    from keyboard import read_key as keyboard_read_key

    def Keyboard():
        global preset
        try:
            while True:
                if keyboard_read_key() == '-':
                    preset_reduce()
                elif keyboard_read_key() == '+':
                    preset_increase()
                time.sleep(0.350)
        except ImportError:
            print("You need to be root to use keyboard")


    KeyboardThread = threading.Thread(target=Keyboard)
    KeyboardThread.daemon = True
    KeyboardThread.start()


#########################################
# BUTTONS THREAD (RASPBERRY PI GPIO)
#
#########################################

if USE_BUTTONS:
    import RPi.GPIO as GPIO

    lastbuttontime = 0

    def Buttons():
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(18, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        global preset, lastbuttontime
        while True:
            now = time.time()
            if not GPIO.input(18) and (now - lastbuttontime) > 0.2:
                lastbuttontime = now
                preset -= 1
                if preset < 0:
                    preset = 127
                LoadSamples()

            elif not GPIO.input(17) and (now - lastbuttontime) > 0.2:
                lastbuttontime = now
                preset += 1
                if preset > 127:
                    preset = 0
                LoadSamples()

            time.sleep(0.020)

    ButtonsThread = threading.Thread(target=Buttons)
    ButtonsThread.daemon = True
    ButtonsThread.start()


#########################################
# 7-SEGMENT DISPLAY
#
#########################################

if USE_I2C_7SEGMENTDISPLAY:
    import smbus

    bus = smbus.SMBus(1)     # using I2C

    def display(s):
        for k in '\x76\x79\x00' + s:     # position cursor at 0
            try:
                bus.write_byte(0x71, ord(k))
            except:
                try:
                    bus.write_byte(0x71, ord(k))
                except:
                    pass
            time.sleep(0.002)

    display('----')
    time.sleep(0.5)

else:

    def display(s):
        pass


#########################################
# MIDI IN via SERIAL PORT
#
#########################################

if USE_SERIALPORT_MIDI:
    import serial

    ser = serial.Serial('/dev/ttyAMA0', baudrate=38400)       # see hack in /boot/cmline.txt : 38400 is 31250 baud for MIDI!

    def MidiSerialCallback():
        message = [0, 0, 0]
        while True:
            i = 0
            while i < 3:
                data = ord(ser.read(1))  # read a byte
                if data >> 7 != 0:
                    i = 0      # status byte!   this is the beginning of a midi message: http://www.midi.org/techspecs/midimessages.php
                message[i] = data
                i += 1
                if i == 2 and message[0] >> 4 == 12:  # program change: don't wait for a third byte: it has only 2 bytes
                    message[2] = 0
                    i = 3
            MidiCallback(message, None)

    MidiThread = threading.Thread(target=MidiSerialCallback)
    MidiThread.daemon = True
    MidiThread.start()


#########################################
# LOAD FIRST SOUNDBANK
#
#########################################

preset = 0
LoadSamples()


#########################################
# MIDI DEVICES DETECTION
# MAIN LOOP
#########################################

midi_in = rtmidi.MidiInMulti()
curr_ports = []
prev_ports = []
first_loop = True
while True:
    curr_ports = rtmidi.get_in_ports()
    if (len(prev_ports) != len(curr_ports)):
        midi_in.close_ports()
        prev_ports = []
    for port in curr_ports:
        if port not in prev_ports and "Midi Through" not in port and (len(prev_ports) != len(curr_ports)):
            midi_in.open_ports(port)
            midi_in.callback = MidiCallback
            if first_loop:
                print("Opened MIDI port: {}".format(port))
                first_loop = False
            else:
                print("Reopening MIDI port: {}".format(port))
            prev_ports = curr_ports
    time.sleep(2)

