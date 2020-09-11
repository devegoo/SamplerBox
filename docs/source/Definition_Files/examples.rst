.. _definition-examples:

1. Velocity
===========

The original `GrandPiano <http://www.samplerbox.org/instruments>`_ set uses multiple lines specifying the wav's to be
selected and the corresponding fixed velocity value. Remember that default velocity is 127.


**File names:**

.. code-block:: text

    D#5v16.wav
    D#6v4.wav
    D#6v7.wav
    D#6v11.wav
    D#6v14.wav
    D#6v16.wav
    D#7v4.wav

**definition.txt:**

.. code-block:: text

    %%mode=Keyb
    %%velmode=Sample
    %notenamev4.wav,%velocity=40
    %notenamev7.wav,%velocity=60
    %notenamev11.wav,%velocity=80
    %notenamev14.wav,%velocity=100
    %notenamev16.wav

Alternatively, you can set the global velocity mode (``%%velmode``) to either ``Accurate`` (default) or ``Sample``.

``Accurate`` will scale the volume of a sample based on the velocity of the note played.

``Sample`` will look for velocity values in the ``definition.txt`` (as in the example above).

.. code-block:: text

    %%mode=Keyb
    %%velmode=Accurate
    %notenamev14.wav
    %notenamev16.wav


2. Naming and looping
=====================

I often use this definition set, which makes it possible to give the loops and fills a self explaining name.
Directory on the left is interpreted correctly.

**File names:**

.. code-block:: text

    03 Alesis-Fusion-Bass-Loop.wav
    4 takkeherrie.wav
    6.wav
    11 Carol.wav
    20 130-bpm-electro-synth-loop.wav
    21 Aggressive-saw-synth-bass-loop.wav

**definition.txt:**

.. code-block:: text

    %%mode=Loop
    %%velmode=Accurate
    %midinote*.wav

3. Voices
=========

This is set 3 on the SDcard with voices. It uses actually one velocity range of the GrandPiano combined with
Saw. The saw WAV's are renamed with midinumber prefixed with notename plus an "m".

**File names:**

.. code-block:: text

    A5v12.wav
    A6v12.wav
    A7v12.wav
    C1v12.wav
    c2m36.wav
    C2v12.wav
    c3m48.wav
    C3v12.wav

**definition.txt:**

.. code-block:: text

    %%mode=Keyb
    %%release=3
    %%velmode=Accurate
    %notenamev*.wav
    %notenamem*.wav,%voice=2

.. hint::

    You can also define the voice in the file name. eg ``c3_voice2.wav`` will be found with ``%notename_voice%voice*.wav`` in the definition.txt

4. Randomization
================

You might have a sample-set with a variation of samples of the same instrument note. In this example there are 4
samples/recordings of a kick drum and a snare drum. The ``%seq`` keyword tells SamplerBox to play back a
different version of the kick or snare for every hit, thus giving a more realistic performance.

**File names:**

.. code-block:: text

    bonham-kick-1.wav
    bonham-kick-2.wav
    bonham-kick-3.wav
    bonham-kick-4.wav
    bonham-snare-1.wav
    bonham-snare-2.wav
    bonham-snare-3.wav
    bonham-snare-4.wav

**definition.txt:**

.. code-block:: text

    %%mode=Once
    %%velmode=Accurate
    bonham-kick-%seq.wav
    bonham-snare-%seq.wav

.. note::

    SamplerBox may randomize samples in an order like this: 3-6-2-1-8-7-2. Notice how there are no consecutive repeats.

5. Playback mode
================

In this example the global ``%%mode`` is ``Keyb`` (normal playback), but 1 sample plays back from start to end ignoring the standard note-off.

**File names:**

.. code-block:: text

    mellotron C1.wav
    mellotron E1.wav
    mellotron G1.wav
    aeroplane-sample.wav

**definition.txt:**

.. code-block:: text

    %%mode=Keyb
    %%velmode=Accurate
    mellotron %notename.wav
    aeroplane-sample.wav, %mode=Once