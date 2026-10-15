"""Stream ROM-requested tones through Qt's audio output without blocking the UI."""
import math
from collections import deque
import numpy as np
from PySide6.QtCore import QIODevice, QObject, Signal
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices


class ToneStream(QIODevice):
    def __init__(self,parent=None):
        super().__init__(parent);self.tones=deque();self.pcm=deque();self.phase=0.0;self.rate=44100
        self.open(QIODevice.OpenModeFlag.ReadOnly)
    def isSequential(self):return True
    def bytesAvailable(self):return 8192+super().bytesAvailable()
    def add(self,frequency,duration):
        if not math.isfinite(frequency) or not math.isfinite(duration):return
        if not 0<frequency<=20000 or not 0<duration<=3600:return
        if len(self.tones)<128:self.tones.append([frequency,round(duration*self.rate)])
    def add_pcm(self,data):
        if len(data)%2 or len(data)>16384:return
        if len(self.pcm)<64:self.pcm.append(np.frombuffer(data,dtype='<i2').copy())
    def readData(self,maxlen):
        count=min(maxlen//2,8192);output=np.zeros(count,dtype='<i2');offset=0
        while offset<count and self.pcm:
            part=self.pcm[0];n=min(len(part),count-offset);output[offset:offset+n]=part[:n];offset+=n
            if n==len(part):self.pcm.popleft()
            else:self.pcm[0]=part[n:]
        while offset<count and self.tones:
            frequency,remaining=self.tones[0];n=min(remaining,count-offset)
            phase=self.phase+np.arange(n)*frequency/self.rate
            output[offset:offset+n]=(np.sin(2*np.pi*phase)*14000).astype('<i2')
            self.phase=(self.phase+n*frequency/self.rate)%1
            self.tones[0][1]-=n;offset+=n
            if not self.tones[0][1]:self.tones.popleft()
        return output.tobytes()
    def writeData(self,data):return -1


class RomAudio(QObject):
    unavailable=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.stream=ToneStream(self);self.sink=None;self.enabled=True;self.volume=.35;self.warned=False
    def play(self,event):
        if not self.enabled:return
        if self.sink is None:
            device=QMediaDevices.defaultAudioOutput()
            if device.isNull():
                if not self.warned:self.unavailable.emit('No audio output device is available');self.warned=True
                return
            fmt=QAudioFormat();fmt.setSampleRate(self.stream.rate);fmt.setChannelCount(1);fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not device.isFormatSupported(fmt):
                if not self.warned:self.unavailable.emit('Audio device does not support 44.1 kHz mono playback');self.warned=True
                return
            self.sink=QAudioSink(device,fmt,self);self.sink.setVolume(self.volume);self.sink.start(self.stream)
        if self.sink.state()==QAudio.State.StoppedState:self.sink.start(self.stream)
        if 'pcm' in event:
            try:self.stream.add_pcm(bytes.fromhex(event['pcm']))
            except (TypeError,ValueError):pass
        else:self.stream.add(float(event['frequency']),float(event['duration']))
    def set_enabled(self,enabled):
        self.enabled=enabled
        if not enabled:self.stop()
    def set_volume(self,value):
        self.volume=max(0,min(1,value))
        if self.sink:self.sink.setVolume(self.volume)
    def stop(self):
        self.stream.tones.clear();self.stream.pcm.clear()
        if self.sink:self.sink.stop()
