import os, math, wave, struct

def tone(path, frequency=700, duration=0.10, volume=0.22):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rate = 44100
    frames = int(rate * duration)
    with wave.open(path, "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        for i in range(frames):
            t = i / rate
            envelope = min(1, i/(rate*0.01), (frames-i)/(rate*0.02))
            value = int(32767 * volume * envelope * math.sin(2*math.pi*frequency*t))
            wav.writeframes(struct.pack("<h", value))

def make_sound_pack(directory="sounds"):
    os.makedirs(directory, exist_ok=True)
    tone(os.path.join(directory, "activate.wav"), 900, .08)
    tone(os.path.join(directory, "success.wav"), 1200, .10)
    tone(os.path.join(directory, "error.wav"), 260, .14)
    tone(os.path.join(directory, "thinking.wav"), 500, .06)
